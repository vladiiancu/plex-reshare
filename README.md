# PLEX-reshare

Combo of `openresty` + `python starlette` + `rq` to expose your Plex shares in a basic web-browsable `:8080`  format a'la apache directory listing.

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
