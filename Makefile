#!/usr/bin/make -f

VERSION ?= latest
DOCKER_PUSH ?= false

define DOCKERFILE
# samba
# https://gitlab.com/encircle360-oss/rclone-samba-server
# important because otherwise there are problems with write/move access to the rclone mounts
ENV GLOBAL="vfs objects ="
ENV GROUPID=0
ENV USERID=0
ENV PERMISSIONS=true
ENV RECYCLE=false

ENV USER="user;pass"
ENV SHARE="reshare;/mnt;yes;no;no;user;none;;;"

# starlette
ENV WORKERS_PER_CORE=1
ENV MAX_WORKERS=40
ENV WEB_CONCURRENCY=10
ENV GRACEFUL_TIMEOUT=120
ENV TIMEOUT=130
ENV PORT=8000

# nginx + rq
ENV REDIS_HOST=localhost
ENV REDIS_PORT=6379
ENV REDIS_DB_RQ=12
ENV REDIS_INTERNAL=true
ENV PYTHONPATH=/app

ENV RCLONE_ENABLE=false
ENV SAMBA_ENABLE=false

ENV DEVELOPMENT=false

COPY ./app/requirements.txt /tmp/requirements.txt

RUN apk add --update supervisor py3-pip redis curl fuse3 && \
	pip3 install --upgrade --no-cache-dir -r /tmp/requirements.txt && \
	rm  -rf /tmp/* /var/cache/apk/*

ADD https://raw.githubusercontent.com/tiangolo/uvicorn-gunicorn-docker/master/docker-images/start.sh /start.sh
ADD https://raw.githubusercontent.com/tiangolo/uvicorn-gunicorn-docker/master/docker-images/gunicorn_conf.py /gunicorn_conf.py
ADD https://raw.githubusercontent.com/tiangolo/uvicorn-gunicorn-docker/master/docker-images/start-reload.sh /start-reload.sh
ADD https://raw.githubusercontent.com/dperson/samba/master/samba.sh /usr/bin/samba.sh

RUN mkdir -p /redis && \
    sed -i 's/smbd -FS/smbd -F --debug-stdout/g' /usr/bin/samba.sh && \
    chmod +x /start*.sh /usr/bin/samba.sh

RUN cd /tmp && curl -s -o rclone.zip https://downloads.rclone.org/rclone-current-linux-amd64.zip && \
	unzip -qq rclone.zip && \
	mv rclone-*/rclone /usr/bin && \
	rm -rf rclone*

COPY ./app /app
COPY ./rq /rq
COPY supervisord.conf /etc/

RUN mkdir -p /rclone/config && \
    mkdir -p /rclone/cache

VOLUME ["/rclone/config", "/rclone/cache"]

WORKDIR /tmp

CMD ["supervisord", "--nodaemon", "--configuration", "/etc/supervisord.conf"]
endef
export DOCKERFILE

define OPENRESTY
$$(curl -s https://raw.githubusercontent.com/openresty/docker-openresty/master/alpine-apk/Dockerfile | \
   sed -E 's/(COPY) (nginx.*)/\1 \.\/nginx\/\2/g' | grep -vE 'CMD|LABEL')
endef
export OPENRESTY

define SAMBA
$$(curl -s https://raw.githubusercontent.com/dperson/samba/master/Dockerfile | \
   grep -vE 'COPY|HEALTHCHECK|CMD|ENTRYPOINT|FROM|MAINTAINER')
endef
export SAMBA

format-code:
	ruff check --select I --fix .
	ruff format .

docker-compose:
	@docker compose up -d --force-recreate

build:
	@echo "$(OPENRESTY)\n$(SAMBA)\n$${DOCKERFILE}" | docker build --no-cache -t "peterbuga/plex-reshare:$(VERSION)" -f - .
ifneq ($(VERSION), latest)
	@docker image tag "peterbuga/plex-reshare:$(VERSION)" "peterbuga/plex-reshare:latest"
endif
ifeq ($(DOCKER_PUSH), true)
	@docker push "peterbuga/plex-reshare:$(VERSION)"
	@docker push "peterbuga/plex-reshare:latest"
endif

.PHONY: build
