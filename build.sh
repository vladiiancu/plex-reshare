#!/bin/bash

VERSION=${VERSION:-latest}

(
cat << EOL
$(curl -s https://raw.githubusercontent.com/openresty/docker-openresty/master/alpine-apk/Dockerfile)

ENV REDIS_HOST=redis
ENV REDIS_PORT=6379
ENV REDIS_DB_RQ=11
ENV PYTHONPATH=/app

COPY /app/requirements.txt /tmp/requirements.txt

RUN apk add --update supervisor py3-pip && \
	pip install --no-cache-dir -r /tmp/requirements.txt && \
	rm  -rf /tmp/* /var/cache/apk/*



ADD https://raw.githubusercontent.com/tiangolo/uvicorn-gunicorn-docker/master/docker-images/start.sh /start.sh
RUN chmod +x /start.sh

ADD https://raw.githubusercontent.com/tiangolo/uvicorn-gunicorn-docker/master/docker-images/gunicorn_conf.py /gunicorn_conf.py

ADD https://raw.githubusercontent.com/tiangolo/uvicorn-gunicorn-docker/master/docker-images/start-reload.sh /start-reload.sh
RUN chmod +x /start-reload.sh

COPY ./app /app
COPY supervisord.conf /etc/

WORKDIR /app/

CMD ["supervisord", "--nodaemon", "--configuration", "/etc/supervisord.conf"]
EOL
) | docker build --no-cache -t "peterbuga/plex-reshare:${VERSION}" -f - .

docker push "peterbuga/plex-reshare:${VERSION}"

if [ "$VERSION" != "latest" ]; then
	docker image tag "peterbuga/plex-reshare:${VERSION}" "peterbuga/plex-reshare:latest"
	docker push "peterbuga/plex-reshare:latest"
fi
