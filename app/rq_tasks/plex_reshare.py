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

import redis
import requests
import rq
from starlette.config import Config

config = Config()
PLEX_TOKEN = config("PLEX_TOKEN", cast=str, default="")
REDIS_REFRESH_TTL = 3 * 60 * 60
REDIS_PATH_TTL = 48 * 60 * 60
IGNORE_EXTENSIONS = ["avi", None]
IGNORE_RESOLUTIONS = ["sd", None]
IGNORE_MOVIE_TEMPLATES = [r"^\d{2}\s.*\.\w{3,4}$"]
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"
    " (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
}

r = redis.Redis(
    host=config("REDIS_HOST", default="redis"),
    port=config("REDIS_PORT", cast=int, default=6379),
    db=11,
    decode_responses=True,
)
rq_redis = redis.Redis(
    host=config("REDIS_HOST", default="redis"),
    port=config("REDIS_PORT", cast=int, default=6379),
    db=config("REDIS_DB_RQ", cast=int, default=11),
)
rq_queue = rq.Queue(name="default", connection=rq_redis)
rq_retries = rq.Retry(max=3, interval=[10, 30, 120])


class DynamicAccessNestedDict:
    """Dynamically get/set nested dictionary keys of 'data' dict"""

    def __init__(self, data: dict):
        self.data = data

    def getval(self, keys: list):
        data = self.data
        for k in keys:
            data = data[k]
        return data

    def setval(self, keys: list, val) -> None:
        data = self.data
        lastkey = keys[-1]
        for k in keys[:-1]:  # when assigning drill down to *second* last key
            data = data[k]
        data[lastkey] = val


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
    for server in req.json():
        if not server["owned"] and server["provides"] == "server":
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

                    if not servers.get(server["clientIdentifier"]) or custom_access:
                        servers[server["clientIdentifier"]] = {
                            "node": node,
                            "uri": uri,
                            "ip": ip,
                            "port": port,
                            "token": token,
                        }

    return list(servers.values())


def _get_common_paths(paths: list) -> list:
    common_paths = {}

    for path in paths:
        path_folders = path.split("/")[:-2]

        while len(path_folders) > 0:
            p = "/".join(path_folders)
            if not common_paths.get(p):
                common_paths[p] = 1
            else:
                common_paths[p] += 1

            path_folders.pop()

    common_paths = [cp for cp, cpc in common_paths.items() if (cpc * 100) / len(paths) > 25]
    common_paths.sort(key=lambda cp: len(cp.split("/")), reverse=True)

    return common_paths


# set dir structure in redis
def _set_dir_structure(d, parent=""):
    for k, v in d.items():
        key = f"{parent}/{k}".strip("/")

        # do not remove root folders `movies` `shows`
        if r.exists(key) and parent:
            r.delete(key)

        if isinstance(v, dict):
            if len(list(v.keys())) > 0:
                keys = list(v.keys())
                r.sadd(key, *keys)
                r.expire(key, REDIS_PATH_TTL)
            _set_dir_structure(v, parent=key)
        else:
            r.set(key, v)
            r.expire(key, REDIS_PATH_TTL)


def _cleanup_path(path: list = None) -> list:
    # path = list(filter(None, path.split("/")))
    # remove paths with less than 3 chars
    path = list(filter(lambda x: len(x) > 2, path.split("/")))

    # clean paths a bit
    path = list(
        map(
            lambda p: re.sub(r"(?:(.+)(\[.*\]))$", r"\1", p).strip(),  # remove [xyz] ending
            path,
        )
    )

    path = list(
        map(
            lambda p: re.sub(r"^(\[.*?\])(.*)", r"\2", p).strip(),  # remove starting [xyz]
            path,
        )
    )

    return path


def get_plex_servers() -> None:
    rkey = "pr:servers"

    if not r.exists(rkey):
        time.sleep(random.randint(1, 60))

    if not r.exists(rkey):
        plex_servers = _get_servers()
        r.set(rkey, json.dumps(plex_servers))
        r.expire(rkey, int(REDIS_REFRESH_TTL / 3))
        rq_queue.enqueue_in(
            datetime.timedelta(seconds=int(REDIS_REFRESH_TTL / 3 + 60)), "rq_tasks.get_plex_servers", retry=rq_retries
        )
    else:
        plex_servers = json.loads(r.get(rkey))

    for plex_server in plex_servers:
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
            REDIS_REFRESH_TTL + random.randint(6, 24) * 60 * 60,
        )

        r.set(rkey_node_ip, plex_server["ip"])
        r.set(rkey_node_port, str(plex_server["port"]))
        r.set(rkey_node_token, plex_server["token"])

        rq_queue.enqueue("rq_tasks.get_plex_libraries", retry=rq_retries, kwargs={"plex_server": plex_server})


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
                "rq_tasks.get_plex_library",
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
        f"rq_tasks.get_{library['type']}s", kwargs={"media_container": media_container, "plex_server": plex_server}
    )

    if media_container["size"] + media_container["offset"] < media_container["totalSize"]:
        offset += 100
        rq_queue.enqueue_in(
            datetime.timedelta(seconds=offset / (10 if library["type"] == "show" else 50)),
            "rq_tasks.get_plex_library",
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
                movie_name = part.get("file")

                if not movie_key or not movie_name:
                    continue

                if part.get("container") in IGNORE_EXTENSIONS:
                    continue

                if part["size"] / 1000000 < 200:
                    continue

                movie_file = movie_name.split("/")[-1]

                # ignore file that match a specific name-template
                ignore_file = False
                for imt in IGNORE_MOVIE_TEMPLATES:
                    if re.match(imt, movie_file, flags=re.I):
                        ignore_file = True
                        break

                if ignore_file:
                    continue

                movie_path = _cleanup_path(path=movie_path)
                movies_list[movie_key] = "/".join(movie_path) + f"#{movie['title']} ({movie.get('year')})".replace(
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
        datetime.timedelta(seconds=5), "rq_tasks.process_movies", retry=rq_retries, kwargs={"plex_server": plex_server}
    )


def process_movies(media_container: dict = None, plex_server: dict = None) -> None:
    movies = {}
    movies_list = {}

    rkey_movies = f"pr:movies:{plex_server['node']}"
    if r.exists(rkey_movies):
        movies_list = r.hgetall(rkey_movies)

    base_paths = _get_common_paths(list(movies_list.values()))

    for movie_key, movie_name in dict(itertools.islice(movies_list.items(), _get_max_files())).items():
        movie_base_placeholder = movie_name.split("#")[-1]

        movie_name = movie_name.split("#")[0]

        for base_path in base_paths:
            movie_name = re.sub(rf"^{base_path}", "", movie_name).lstrip("/")

        movie_path = list(filter(None, movie_name.split("/")))
        movie_file = movie_path[-1]

        # add parent folder for root files
        if len(movie_path) == 1:
            movie_path = [movie_base_placeholder] + movie_path

        node = movies
        for idx, level in enumerate(movie_path):
            if idx < len(movie_path) - 1:
                node = node.setdefault(level, dict())
            else:
                d_files = DynamicAccessNestedDict(movies).getval(movie_path[:-1])

                if d_files:
                    d_files.update({movie_file: movie_key})
                else:
                    d_files = {movie_file: movie_key}

                DynamicAccessNestedDict(movies).setval(movie_path[:-1], d_files)

    _set_dir_structure({"movies": {plex_server["node"]: movies}}, parent="")


def get_shows(media_container: dict = None, plex_server: dict = None) -> None:
    for sid, show in enumerate(media_container["Metadata"]):
        # rq_queue.enqueue_in(
        #     datetime.timedelta(seconds=sid * 5),
        rq_queue.enqueue(
            "rq_tasks.get_seasons",
            retry=rq_retries,
            at_front=True,
            kwargs={
                "show": show,
                "plex_server": plex_server,
            },
        )


def get_seasons(show: dict = None, plex_server: dict = None):
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
        # rq_queue.enqueue_in(
        #     datetime.timedelta(seconds=sid * 2),
        rq_queue.enqueue(
            "rq_tasks.get_episodes",
            retry=rq_retries,
            at_front=True,
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
                episode_name = part.get("file")

                if not episode_key or not episode_name:
                    continue

                if part.get("container") in IGNORE_EXTENSIONS:
                    continue

                if part["size"] / 1000000 < 50:
                    continue

                if "anime" in episode_name.lower():
                    continue

                episode_path = _cleanup_path(path=episode_path)
                episodes_list[episode_key] = "/".join(episode_path)

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
            "rq_tasks.get_episodes",
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
            "rq_tasks.process_episodes",
            retry=rq_retries,
            kwargs={
                "plex_server": plex_server,
            },
        )


def process_episodes(plex_server: dict = None) -> None:
    # jobs_registry = rq.registry.ScheduledJobRegistry(queue=rq_queue)
    # print(jobs_registry.get_jobs_to_schedule())
    # #job = Job.fetch('my_job_id', connection=redis)

    shows = {}
    episodes_list = {}
    rkey_shows = f"pr:shows:{plex_server['node']}"
    if r.exists(rkey_shows):
        episodes_list = r.hgetall(rkey_shows)
    base_paths = _get_common_paths(list(episodes_list.values()))

    for episode_key, episode_name in dict(itertools.islice(episodes_list.items(), _get_max_files())).items():
        for base_path in base_paths:
            episode_name = re.sub(rf"^{base_path}", "", episode_name).lstrip("/")
        episode_path = list(filter(None, episode_name.split("/")))

        # no root file or 1st ones
        if len(episode_path) <= 1:
            continue

        episode_file = episode_path[-1]

        node = shows
        for idx, level in enumerate(episode_path):
            if idx < len(episode_path) - 1:
                node = node.setdefault(level, dict())
            else:
                d_files = DynamicAccessNestedDict(shows).getval(episode_path[:-1])

                if d_files:
                    d_files.update({episode_file: episode_key})
                else:
                    d_files = {episode_file: episode_key}

                DynamicAccessNestedDict(shows).setval(episode_path[:-1], d_files)

    _set_dir_structure({"shows": {plex_server["node"]: shows}}, parent="")
