import os
import re

import redis

redis_connection = redis.Redis(
    host=os.getenv("REDIS_HOST", default="localhost"),
    port=os.getenv("REDIS_PORT", default=6379),
    db=os.getenv("REDIS_DB_RQ", default=11),
)


def get_common_paths(paths: list) -> list:
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


def cleanup_path(path: str = None) -> str:
    # remove paths with less than 3 chars
    path_segments = list(filter(lambda x: len(x) > 2, path.split("/")))

    # clean paths a bit
    path_segments = list(
        map(
            lambda p: re.sub(r"(?:(.+)(\[.*\]))$", r"\1", p).strip(),  # remove [xyz] ending
            path_segments,
        )
    )

    path_segments = list(
        map(
            lambda p: re.sub(r"^(\[.*?\])(.*)", r"\2", p).strip(),  # remove starting [xyz]
            path_segments,
        )
    )

    return "/".join(path_segments)
