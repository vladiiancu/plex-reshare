#!/bin/bash

VERSION=${VERSION:-latest}
DOCKER_PUSH=${DOCKER_PUSH:-false}

(
cat << EOL
$(curl -s https://raw.githubusercontent.com/openresty/docker-openresty/master/alpine-apk/Dockerfile)

# WORKERS_PER_CORE=1
# MAX_WORKERS=40
# WEB_CONCURRENCY=10
# GRACEFUL_TIMEOUT=120
# TIMEOUT: 130
# PORT: 8000

ENV REDIS_HOST=localhost
ENV REDIS_PORT=6379
ENV REDIS_DB_RQ=12
ENV REDIS_INTERNAL=true
ENV PYTHONPATH=/app

COPY /app/requirements.txt /tmp/requirements.txt

RUN apk add --update supervisor py3-pip redis && \
    pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm  -rf /tmp/* /var/cache/apk/*

ADD https://raw.githubusercontent.com/tiangolo/uvicorn-gunicorn-docker/master/docker-images/start.sh /start.sh
ADD https://raw.githubusercontent.com/tiangolo/uvicorn-gunicorn-docker/master/docker-images/gunicorn_conf.py /gunicorn_conf.py
ADD https://raw.githubusercontent.com/tiangolo/uvicorn-gunicorn-docker/master/docker-images/start-reload.sh /start-reload.sh

RUN mkdir -p /redis && chmod +x /start*.sh

COPY ./app /app
COPY supervisord.conf /etc/

WORKDIR /tmp

CMD ["supervisord", "--nodaemon", "--configuration", "/etc/supervisord.conf"]
EOL
) | docker build --no-cache -t "peterbuga/plex-reshare:${VERSION}" -f - .

if [ "$VERSION" != "latest" ]; then
    docker image tag "peterbuga/plex-reshare:${VERSION}" "peterbuga/plex-reshare:latest"

fi

if [ "$DOCKER_PUSH" = "true" ]; then
    docker push "peterbuga/plex-reshare:${VERSION}"
    docker push "peterbuga/plex-reshare:latest"
fi
