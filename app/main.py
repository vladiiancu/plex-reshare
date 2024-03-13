import json
import os
import re
import time

import redis
from starlette.applications import Starlette
from starlette.config import Config
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.routing import Route
from starlette.templating import Jinja2Templates

import rq

config = Config()

# https://www.plexopedia.com/plex-media-server/api/library/movies/
templates = Jinja2Templates(directory=".")
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


class SetRqMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)

    async def dispatch(self, request, call_next):
        rq_queue.enqueue("tasks.get_plex_servers", job_id="get_plex_servers", retry=rq_retries)

        response = await call_next(request)
        return response


async def home(request):
    context = {"request": request, "paths": []}
    location = request.path_params.get("path").strip("/")
    location_esc = ''.join([(c if re.match(r"[a-zA-Z0-9\.\\]", c) else ("\\" + c)) for c in location])
    entries = list(r.scan_iter(f"pr:files:{location_esc}*"))

    paths = {}
    for entry in entries:
        entry = entry.replace(f"pr:files:{location}", "").strip("/")
        entry_chunks = entry.split("/")

        paths[entry_chunks[0]] = {
            "url": (f"/{location}/{entry_chunks[0]}" + ("/" if len(entry_chunks) > 1 else "")).replace("//", "/"),
            "name": entry_chunks[0] + ("/" if len(entry_chunks) > 1 else ""),
        }

    paths = dict(sorted(paths.items(), key=lambda x: x[0].lower()))
    context["paths"].extend(paths.values())

    return templates.TemplateResponse("index.html", context)


async def startup(*args, **kwargs):
    r.flushdb()
    rq_queue.enqueue("tasks.get_plex_servers", job_id="get_plex_servers", retry=rq_retries)


routes = [
    Route("/{path:path}", home),
]

middleware = [Middleware(SetRqMiddleware)]

app = Starlette(debug=True, routes=routes, middleware=middleware, on_startup=[startup])
