import datetime
import itertools
import json
import os
import random
import re
import socket
import string
import time
from urllib.parse import urlencode, urlparse

import pickledb
import redis
import requests
from starlette.config import Config

import rq

from .utilities import cleanup_path, get_common_paths, redis_connection

config = Config()
PLEX_TOKEN = config("PLEX_TOKEN", cast=str, default="")
DEVELOPMENT = config("DEVELOPMENT", cast=bool, default=False)
IGNORE_PLAYLIST = config("IGNORE_PLAYLIST", cast=str, default="")
REDIS_REFRESH_TTL = 3 * 60 * 60
REDIS_PATH_TTL = 24 * 60 * 60
IGNORE_EXTENSIONS = ["avi", None]
IGNORE_RESOLUTIONS = ["sd", None]
IGNORE_MOVIE_TEMPLATES = [r".*sample.*"]  # r"^\d{2}\s.*\.\w{3,4}$",
IGNORE_EPISODE_TEMPLATES = [r".*anime.*"]
MOVIE_MIN_SIZE = 500
EPISODE_MIN_SIZE = 80
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"
    " (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
}

r = redis.Redis(
    host=config("REDIS_HOST", default="localhost"),
    port=config("REDIS_PORT", cast=int, default=6379),
    db=11,
    decode_responses=True,
)
rq_queue = rq.Queue(name="default", connection=redis_connection)
rq_retries = rq.Retry(max=3, interval=[10, 30, 120])


def _get_pickledb(autodump: bool = True):
    return pickledb.load("/pr/pr.db", autodump)


def _get_max_files() -> int:
    date_start = config("DATE_START", cast=str, default=None)
    files_day = config("FILES_DAY", cast=int, default=25)

    if not date_start:
        return 100_000_000
    else:
        date_start = datetime.datetime.strptime(date_start, "%Y-%m-%d")
        date_now = datetime.datetime.now()
        return abs((date_now - date_start).days) * files_day


def _get_servers() -> list[dict]:
    query_params = {
        "includeHttps": 1,
        "includeRelay": 0,
        "includeIPv6": 0,
        "X-Plex-Client-Identifier": "".join(
            random.choices(string.ascii_uppercase + string.ascii_lowercase + string.digits, k=24)
        ),
        "X-Plex-Platform-Version": "16.6",
        "X-Plex-Token": PLEX_TOKEN,
    }

    req = requests.get(
        url=f"https://clients.plex.tv/api/v2/resources?{urlencode(query_params)}",
        headers=HEADERS,
    )

    servers = {}
    for server in [server for server in req.json() if server["provides"] == "server"]:
        for conn in server["connections"]:
            if not conn["relay"] and not conn["local"] and not conn["IPv6"]:
                custom_access = False
                if "plex.direct" not in conn["uri"]:
                    custom_access = True

                    s = [c for c in server["connections"] if "plex.direct" in c["uri"]]

                    url = urlparse(conn["uri"])
                    server_ip = socket.gethostbyname(url.netloc.split(":")[0])
                    conn["uri"] = (
                        f"{server_ip.replace('.', '-')}.{s[0]['uri'].split('.')[1]}.plex.direct:{conn['port']}"
                    )

                uri = conn["uri"].split("://")[-1]
                node = uri.split(".")[1]
                ip = uri.split(".")[0].replace("-", ".")
                port = conn["port"]
                token = server["accessToken"]
                owned = server["owned"]

                if not servers.get(server["clientIdentifier"]) or custom_access:
                    servers[server["clientIdentifier"]] = {
                        "node": node,
                        "uri": uri,
                        "ip": ip,
                        "port": port,
                        "token": token,
                        "owned": owned,
                    }

    return list(servers.values())


def get_plex_playlists(plex_servers: list = None) -> None:
    db = _get_pickledb(autodump=True)

    query_params = {
        "playlistType": "video",
        "includeCollections": 0,
        "includeExternalMedia": 1,
        "includeAdvanced": 1,
        "includeMeta": 1,
        "X-Plex-Client-Identifier": "".join(
            random.choices(string.ascii_uppercase + string.ascii_lowercase + string.digits, k=24)
        ),
        "X-Plex-Platform-Version": "16.6",
        "X-Plex-Token": PLEX_TOKEN,
    }

    query_params_items = {
        "X-Plex-Container-Start": 0,
        "X-Plex-Container-Size": 120,
        "X-Plex-Client-Identifier": "".join(
            random.choices(string.ascii_uppercase + string.ascii_lowercase + string.digits, k=24)
        ),
        "X-Plex-Platform-Version": "16.6",
        "X-Plex-Token": PLEX_TOKEN,
    }

    ignored_items = []

    for plex_server in [ps for ps in plex_servers if ps["owned"]]:
        playlists = requests.get(
            url=f"https://{plex_server['uri']}/playlists?{urlencode(query_params)}",
            timeout=15,
            headers=HEADERS,
        )

        for playlist in playlists.json()["MediaContainer"]["Metadata"]:
            if playlist["title"] == IGNORE_PLAYLIST:
                playlist_items = requests.get(
                    url=f"https://{plex_server['uri']}{playlist['key']}?{urlencode(query_params_items)}",
                    timeout=15,
                    headers=HEADERS,
                )

                for ignore_item in playlist_items.json()["MediaContainer"]["Metadata"]:
                    for media in ignore_item["Media"]:
                        for part in media["Part"]:
                            ignored_items.append(
                                part["file"]
                                .replace("/media/moviesextra/", "")
                                .replace("/media/showsextra/", "")
                                .strip("/")
                            )

                if db.exists("ignores"):
                    existing_ignore_items = db.get("ignores")
                    ignored_items = list(set(ignored_items + existing_ignore_items))

                db.set("ignores", ignored_items)


def get_plex_servers() -> None:
    db = _get_pickledb(autodump=True)
    rkey = "pr:servers"

    if not r.exists(rkey):
        time.sleep(random.randint(1, 20 if DEVELOPMENT else 60))

    if not r.exists(rkey):
        plex_servers = _get_servers()
        r.set(rkey, json.dumps(plex_servers))
        r.expire(rkey, int(REDIS_REFRESH_TTL / 3))
        rq_queue.enqueue_in(
            datetime.timedelta(seconds=int(REDIS_REFRESH_TTL / 3 + 60)), "tasks.get_plex_servers", retry=rq_retries
        )

        if IGNORE_PLAYLIST:
            rq_queue.enqueue("tasks.get_plex_playlists", at_front=True, retry=rq_retries, plex_servers=plex_servers)

        if not db.exists("ignores"):
            db.set("ignores", [])
    else:
        plex_servers = json.loads(r.get(rkey))

    for plex_server in [ps for ps in plex_servers if not ps["owned"]]:
        rkey_node_refresh = f"pr:node:{plex_server['node']}:refresh"
        rkey_node_ip = f"pr:node:{plex_server['node']}:ip"
        rkey_node_port = f"pr:node:{plex_server['node']}:port"
        rkey_node_token = f"pr:node:{plex_server['node']}:token"

        # no need to refresh
        if r.exists(rkey_node_refresh):
            continue

        r.set(rkey_node_refresh, str(datetime.datetime.now()))
        r.expire(
            rkey_node_refresh,
            random.randint(6, 12) * random.randint(50, 60) * 60,
        )

        r.set(rkey_node_ip, plex_server["ip"])
        r.set(rkey_node_port, str(plex_server["port"]))
        r.set(rkey_node_token, plex_server["token"])

        rq_queue.enqueue("tasks.get_plex_libraries", retry=rq_retries, kwargs={"plex_server": plex_server})


def get_plex_libraries(plex_server: dict = None) -> None:
    query_params = {"X-Plex-Token": plex_server["token"]}
    libraries = requests.get(
        url=f"https://{plex_server['uri']}/library/sections?{urlencode(query_params)}",
        timeout=15,
        headers=HEADERS,
    )

    for library in libraries.json()["MediaContainer"]["Directory"]:
        if library["type"] in ["movie", "show"]:
            rq_queue.enqueue(
                "tasks.get_plex_library",
                retry=rq_retries,
                kwargs={
                    "plex_server": plex_server,
                    "library": library,
                    "offset": 0,
                },
            )


def get_plex_library(
    plex_server: dict = None,
    library: dict = None,
    offset: int = None,
) -> None:
    query_params = {
        "X-Plex-Token": plex_server["token"],
        "X-Plex-Container-Start": offset,
        "X-Plex-Container-Size": 100,
    }

    library_res = requests.get(
        url=f"https://{plex_server['uri']}/library/sections/{library['key']}/all?{urlencode(query_params)}",
        headers=HEADERS,
    )

    media_container = library_res.json()["MediaContainer"]
    rq_queue.enqueue(
        f"tasks.get_{library['type']}s", kwargs={"media_container": media_container, "plex_server": plex_server}
    )

    if media_container["size"] + media_container["offset"] < media_container["totalSize"]:
        offset += 100
        rq_queue.enqueue_in(
            datetime.timedelta(seconds=offset / (10 if library["type"] == "show" else 50)),
            "tasks.get_plex_library",
            retry=rq_retries,
            at_front=True,
            kwargs={
                "plex_server": plex_server,
                "library": library,
                "offset": offset,
            },
        )


def get_movies(media_container: dict = None, plex_server: dict = None) -> None:
    movies_list = {}

    for movie in media_container["Metadata"]:
        for media in movie["Media"]:
            if media.get("videoResolution") in IGNORE_RESOLUTIONS:
                continue

            for part in media["Part"]:
                movie_key = part.get("key")
                movie_path = part.get("file")

                if (
                    not movie_key
                    or not movie_path
                    or part.get("container") in IGNORE_EXTENSIONS
                    or part.get("size", 1) / 1000000 < MOVIE_MIN_SIZE
                ):
                    continue

                movie_file = movie_path.split("/")[-1]

                # ignore file that match a specific name-template
                if any(re.match(imt, movie_file, flags=re.I) for imt in IGNORE_MOVIE_TEMPLATES):
                    continue

                movie_path = cleanup_path(path=movie_path)
                movies_list[movie_key] = f"{movie_path}###{movie['title']} ({movie.get('year')})".replace(
                    " (None)", ""
                )

    rkey_movies = f"pr:movies:{plex_server['node']}"
    if r.exists(rkey_movies):
        existing_movies_list = r.hgetall(rkey_movies)
        movies_list.update(existing_movies_list)

    if len(movies_list):
        r.hmset(rkey_movies, movies_list)
        r.expire(rkey_movies, 60 * 60)

    rq_queue.enqueue_in(
        datetime.timedelta(seconds=random.randint(10, 60)),
        "tasks.process_media",
        retry=rq_retries,
        kwargs={
            "plex_server": plex_server,
            "media_type": "movies",
        },
    )


def get_shows(media_container: dict = None, plex_server: dict = None) -> None:
    for sid, show in enumerate(media_container["Metadata"]):
        # rq_queue.enqueue_in(
        #     datetime.timedelta(seconds=sid * 5),
        rq_queue.enqueue(
            "tasks.get_seasons",
            retry=rq_retries,
            at_front=True,
            kwargs={
                "show": show,
                "plex_server": plex_server,
                "show_count": sid,
            },
        )


def get_seasons(show: dict = None, plex_server: dict = None, show_count: int = 0):
    time.sleep(0.2)
    query_params = {
        "X-Plex-Token": plex_server["token"],
        "X-Plex-Container-Start": 0,
        "X-Plex-Container-Size": 100,  # no more than 100 seasons
        "excludeAllLeaves": 1,
        "includeUserState": 0,
    }

    seasons = requests.get(
        url=f"https://{plex_server['uri']}{show['key']}?{urlencode(query_params)}",
        timeout=10,
        headers=HEADERS,
    )

    seasons_metadata = seasons.json()["MediaContainer"]["Metadata"]
    for sid, season in enumerate(seasons_metadata):
        # rq_queue.enqueue(
        rq_queue.enqueue_in(
            datetime.timedelta(seconds=sid * 10 + show_count),
            "tasks.get_episodes",
            retry=rq_retries,
            # at_front=True,
            kwargs={"season": season, "plex_server": plex_server, "last_season": sid + 1 == len(seasons_metadata)},
        )


def get_episodes(season: dict = None, plex_server: dict = None, offset: int = 0, last_season: bool = False) -> None:
    episodes_list = {}

    query_params = {
        "X-Plex-Token": plex_server["token"],
        "X-Plex-Container-Start": offset,
        "X-Plex-Container-Size": 100,
        "excludeAllLeaves": 1,
        "includeUserState": 0,
    }

    episodes = requests.get(
        url=f"https://{plex_server['uri']}{season['key']}?{urlencode(query_params)}",
        timeout=10,
        headers=HEADERS,
    )

    media_container = episodes.json()["MediaContainer"]
    for episode in media_container["Metadata"]:
        for media in episode["Media"]:
            if media.get("videoResolution") in IGNORE_RESOLUTIONS:
                continue

            for part in media["Part"]:
                episode_key = part.get("key")
                episode_path = part.get("file")

                if (
                    not episode_key
                    or not episode_path
                    or part.get("container") in IGNORE_EXTENSIONS
                    or part.get("size", 1) / 1000000 < EPISODE_MIN_SIZE
                ):
                    continue

                # ignore file that match a specific path-template
                if any(re.match(imt, episode_path.lower(), flags=re.I) for imt in IGNORE_EPISODE_TEMPLATES):
                    continue

                episode_path = cleanup_path(path=episode_path)
                episodes_list[episode_key] = episode_path

    rkey_shows = f"pr:shows:{plex_server['node']}"
    if r.exists(rkey_shows):
        existing_episodes_list = r.hgetall(rkey_shows)
        episodes_list.update(existing_episodes_list)

    if len(episodes_list):
        r.hmset(rkey_shows, episodes_list)
        r.expire(rkey_shows, 60 * 60)

    if media_container["size"] + media_container["offset"] < media_container["totalSize"]:
        offset += 100
        rq_queue.enqueue_in(
            datetime.timedelta(seconds=offset / 5),
            "tasks.get_episodes",
            retry=rq_retries,
            kwargs={
                "season": season,
                "plex_server": plex_server,
                "offset": offset,
            },
        )

    if last_season:
        rq_queue.enqueue_in(
            datetime.timedelta(seconds=random.randint(5, 120)),
            "tasks.process_media",
            retry=rq_retries,
            kwargs={
                "plex_server": plex_server,
                "media_type": "shows",
            },
        )


def process_media(plex_server: dict = None, media_type: str = None):
    time.sleep(0.5)
    medias_list = {}
    db = _get_pickledb(autodump=False)
    ignored_items = db.get("ignores") or []

    rkey_medias = f"pr:{media_type}:{plex_server['node']}"
    if r.exists(rkey_medias):
        medias_list = r.hgetall(rkey_medias)

    base_paths = get_common_paths(list(medias_list.values()))
    medias_list = dict(sorted(medias_list.items(), key=lambda x: x[1]))
    medias_list = dict(itertools.islice(medias_list.items(), _get_max_files())).items()

    delete_keys = list(r.scan_iter(f"pr:files:{media_type}/{plex_server['node']}*"))
    medias = {}

    for media_key, media_path in medias_list:
        for base_path in base_paths:
            # media_path = re.sub(rf"^{base_path}/", "", media_path).lstrip("/")
            media_path = re.sub(rf"{base_path}/", "", media_path).lstrip("/")

        if "###" in media_path:
            media_path, media_base_placeholder = media_path.split("###")
            media_path_chunks = list(filter(None, media_path.split("/")))

            # add parent folder for root files
            if len(media_path_chunks) == 1:
                media_path = f"{media_base_placeholder}/{media_path}"

        exclude_key = f"{plex_server['node']}/{media_path}"
        if exclude_key in ignored_items:
            continue

        media_path = f"pr:files:{media_type}/{plex_server['node']}/{media_path}"
        medias[media_key] = media_path

    delete_keys = [x for x in delete_keys if x not in set(list(medias.values()))]

    pipe = r.pipeline()
    if len(delete_keys) > 1:
        r.delete(*delete_keys)

    for media_key, media_path in medias.items():
        r.set(media_path, media_key)
        r.expire(media_path, REDIS_PATH_TTL)
    pipe.execute()
