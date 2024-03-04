# PLEX-reshare

Combo of [openresty](https://openresty.org/) + [starlette](https://www.starlette.io/) + [rq](https://python-rq.org) to expose your Plex shares in a basic web-browsable `:8080`  format a'la apache directory listing.

The reason behind this project it to make available your PLEX shares to other friends unrelated to the person who owns the original library.

For example, `plex-server-A` shares various libraries (Movies & TV Shows supported) to (your) `plex-server-owned-by-you-B`
using `plex-reshare` create a new local library with the files from `plex-server-A` that you can later on can be shared directly to other friends `C`.

Basically `plex-reshare` will act as a plex-library-proxy and all the traffic will pass through it (downstream+upstream). It's ignoring self-libraries.


### Use scenario

You managed to get access to one or more shared libraries from other servers, with plex-reshare as a proxy you can host your own instance of plex and share it back to other close friends.

PS: it's not mandatory to use plex to share further the access, by same principle you can also use Jellyfin/Emby/any other media manager-indexer or even simply direct http access and open urls directly in VLC/IINA for example.

USE WITH CARE, **DO NOT HEAVILY REQUEST DATA FROM TARGET SERVERS**. BE NICE!


# Installation via Docker

Docker images available https://hub.docker.com/r/peterbuga/plex-reshare

Mandatory: It requires access to an external redis instance

Minunim required env variables:

```
PLEX_TOKEN: <google it>
REDIS_HOST: <ip or container (host)name>
REDIS_PORT: 6379 (or other custom port, no auth support yet)
REDIS_DB_RQ: 11 (redis db for rq)

# limit the number of files exposed, increment by `FILES_DAY` daily.
# this is to expose a subset of files to Plex initially and can them daily incremental
DATE_START: YYYY-MM-DD
FILES_DAY: 15
```

By default it'll use redis db #11.


# Rclone mount

More details here https://rclone.org/http/ but I recommand using flags `--transfers 4 --low-level-retries 7 --retries 7 --tpslimit 0.7 ` to limit the access to API and files, otherwise plex scan will hammer the requests on target libraries


### Development

Linting: pip install ruff==0.3.0


```
ruff check --select I --fix .
ruff format .
```
