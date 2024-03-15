# PLEX-reshare

Combo of [openresty](https://openresty.org/) + [starlette](https://www.starlette.io/) + [rq](https://python-rq.org) + [redis](https://redis.io/) to expose your Plex shares in a basic web-browsable `:8080`  format a'la apache directory listing.

The reason behind this project it to make available your PLEX shares to other friends unrelated to the person who owns the original library.

For example, `plex-server-A` shares various libraries (Movies & TV Shows supported) to (your) `plex-server-owned-by-you-B`
using `plex-reshare` create a new local library with the files from `plex-server-A` that you can later on can be shared directly to other friends `C`.

Basically `plex-reshare` will act as a plex-library-proxy and all the traffic will pass through it (downstream+upstream). It's ignoring self-libraries.


# Use scenario

You managed to get access to one or more shared libraries from other servers, with plex-reshare as a proxy you can host your own instance of plex and share it back to other close friends.

PS: it's not mandatory to use plex to share further the access, by same principle you can also use Jellyfin/Emby/any other media manager-indexer or even simply direct http access and open urls directly in VLC/IINA for example.

USE WITH CARE, **DO NOT HEAVILY REQUEST DATA FROM TARGET SERVERS**. BE NICE!

It'll create a http directory listing under the format

```
/
|-- movies
|   |-- c0e5a2..........................
|   |   |-- movie.libraryA.movie1
|   |   |-- movie.libraryA.movie2
|   |   `-- movie.libraryB.movie1
|   |-- cb7d61..........................
|   |-- e82c68..........................
|   `-- f2423f..........................
`-- shows
    |-- c0e5a2..........................
    |   |-- tvshow.libraryA.show1
    |   |-- tvshow.libraryA.show2
    |   `-- tvshow.libraryB.show1
    |-- cb7d61..........................
    |-- e82c68..........................
    `-- f2423f..........................
```

All the movie/shows libraries exposed by a specific plex server will be listed all in one place under a single served id uniquely identifiable.

As of now it's not made to recreate the structure defined by a specific plex(admin) but more like grouping all the data available and use external option like PMM (Plex Meta Manager) to create a more structured format out of (subject to change if needed/requested, please fill an issue!).


# Installation via Docker

Docker images available https://hub.docker.com/r/peterbuga/plex-reshare

### Sample command
```
docker run -d --name=plex-reshare \
-e PLEX_TOKEN='xxxxxxxxxxxxxxx'
-p 8080:8080 \
peterbuga/plex-reshare:latest
```

### Docker compose

Copy `.env.sample` to `.env` and change the variable accordingly.

`docker compose up -d`

Browse to http://your-host-ip:8080 to access the list of plex reshares.

### Environment variables

| Variable       | Description                                                                                                                                                                                                                                                                                                                                                                                                                                       | Default |
| ---------------- |---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------| --------- |
|`PLEX_TOKEN`| (mandatory) find out [how to get a plex token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).                                                                                                                                                                                                                                                                                                         | (unset) |
|`REDIS_INTERNAL`| (optional) `true` or `false` use internal redis instance to store the files structure, using an internal refreshing system                                                                                                                                                                                                                                                                                                                        | `true` |
|`REDIS_HOST`| (optional) option to use an external redis instance if already available, set `REDIS_INTERNAL: false`                                                                                                                                                                                                                                                                                                                                             | `localhost` |
|`REDIS_PORT`| (optional) to used when `REDIS_INTERNAL: false`                                                                                                                                                                                                                                                                                                                                                                                                   | `11` |
|`REDIS_DB_RQ`| (optional) if python-rq should run on a separate redis db                                                                                                                                                                                                                                                                                                                                                                                         | `11` |
|`DATE_START`| (optional) needs to be under the format `YYYY-MM-DD`. <br>limit the number of files exposed, increment by `FILES_DAY` daily. <br><br>this is to expose a subset of files to Plex initially and can scan them daily incremental. not setting `DATE_START` will expose at once **ALL** the files it can find. <br><br>example: (today) 2024-03-05 - (DATE_START) 2024-02-01 * (FILES_DAY) 15 = 35 (days) * 15 => max 525 files will be exposed per library (either `movie` or `show` library type). | (unset) |
|`FILES_DAY`| (optional) how many files increment expose every day per library                                                                                                                                                                                                                                                                                                                                                                                  | `25` |
|`IGNORE_PLAYLIST`| (optional) generate a playlist, add items to it that you don't want to see in you library and they will slowly go away as the new refresh & trash process takes place                                                                                                                                                                                                                                                                                                                                                                                  | (unset) |
|`IGNORE_RESOLUTIONS`| (optional) list of resolutions comma separated that you'd like to ignore, ex: `sd` | (unset) |
|`IGNORE_EXTENSIONS`| (optional) list of file extension comma separated that you'd like to ignore, ex: `avi,mpeg` | (unset) |
|`MOVIE_MIN_SIZE`| (optional) minimal file size of a movie in Mb, everything below will be ignored | 512 |
|`EPISODE_MIN_SIZE`| (optional)  minimal file size of an episode in Mb, everything below will be ignored | 64 |
|`IGNORE_MOVIE_TEMPLATES`| (optional) list of python regexes to ignore being added to the list, pipe (`\|`) separated, ex: `.*sample.*` will ignore all the sample file sometimes associated with movie files | (unset) |
|`IGNORE_EPISODE_TEMPLATES`| (optional) list of python regexes to ignore being added to the list, pipe (`\|`) separated | (unset) |


# Local image build
The build image is a merge of multiple external dockerfiles (in order to kickstart the developent) that's why there's no local Dockerfile defined

`make build`

# Rclone mount
More details here https://rclone.org/http/ but I recommand using flags `--transfers 4 --low-level-retries 7 --retries 7 --tpslimit 0.7 ` to limit the access to API and files, otherwise plex scan will hammer the requests on target libraries.

# Development
### Linting:
Requires `pip install ruff==0.3.0`

`make format-code`

# Credits
- https://github.com/openresty/docker-openresty
- https://github.com/tiangolo/uvicorn-gunicorn-docker

# License
MIT license
