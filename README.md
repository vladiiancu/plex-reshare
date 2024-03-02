# PLEX-reshare

Combo of [openresty](https://openresty.org/) + [starlette](https://www.starlette.io/) + [rq](https://python-rq.org) to expose your Plex shares in a basic web-browsable `:8080`  format a'la apache directory listing.

The reason behind this project it to make available your PLEX shares to other friends unrelated to the person who owns the original library.

For example, `plex-server-A` shares various libraries (Movies & TV Shows supported) to (your) `plex-server-owned-by-you-B`
using `plex-reshare` create a new local library with the files from `plex-server-A` that you can later on can be shared directly to other friends `C`.

Basically `plex-reshare` will act as a plex-library-proxy and all the traffic will pass through it (downstream+upstream). It's ignoring self-libraries.


# Installation via Docker

Docker images available https://hub.docker.com/r/peterbuga/plex-reshare

Mandatory: It requires access to an external redis instance

Minunim required env variables:

```
PLEX_TOKEN: <google it>
REDIS_HOST: <ip or container (host)name>
REDIS_PORT: 6379 (or other custom port, no auth support yet)
REDIS_DB_RQ: 11 (redis db for rq)
```

By default it'll use redis db #11.


### Development

Linting: pip install ruff==0.3.0


```
ruff check --select I --fix .
ruff format .
```
