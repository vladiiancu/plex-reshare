import json
import os
import time

import redis
import rq
from starlette.applications import Starlette
from starlette.config import Config
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.routing import Route
from starlette.templating import Jinja2Templates

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
LISTING_TEMPLATE = "listing.html"


class SetPlexServersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)

    async def dispatch(self, request, call_next):
        rq_queue.enqueue("rq_tasks.get_plex_servers", retry=rq.Retry(max=3, interval=[10, 30, 60]))

        response = await call_next(request)
        return response


async def home(request):
    context = {"request": request, "paths": []}
    location = request.path_params.get("path").strip("/")

    if not len(location):  # root path
        context["paths"] = [
            {"url": "/shows/", "name": "shows"},
            {"url": "/movies/", "name": "movies"},
        ]

    else:
        entries = list(r.smembers(location))
        entries.sort()
        context["paths"].extend(
            [
                {
                    "url": f"/{location}/{e}{'/' if r.type(f'{location}/{e}') == 'set' else ''}",
                    "name": e,
                }
                for e in entries
            ]
        )

    return templates.TemplateResponse(LISTING_TEMPLATE, context)


async def startup(*args, **kwargs):
    r.flushdb()
    rq_queue.enqueue("rq_tasks.get_plex_servers", retry=rq.Retry(max=3, interval=[10, 30, 60]))


routes = [
    Route("/{path:path}", home),
]

middleware = [Middleware(SetPlexServersMiddleware)]

app = Starlette(debug=True, routes=routes, middleware=middleware, on_startup=[startup])
