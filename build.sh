VERSION="0.0.1"

#build openresty + python
curl -s https://raw.githubusercontent.com/openresty/docker-openresty/master/bullseye/Dockerfile | docker build \
	--no-cache -t myopenresty \
	--build-arg RESTY_IMAGE_BASE=python --build-arg RESTY_IMAGE_TAG=3.10-bullseye \
	-f - ./nginx

(
cat << EOL
FROM myopenresty

RUN apt-get update && apt-get install -y supervisor

ENV REDIS_DB=11

COPY /app/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

ADD https://raw.githubusercontent.com/tiangolo/uvicorn-gunicorn-docker/master/docker-images/start.sh /start.sh
RUN chmod +x /start.sh

ADD https://raw.githubusercontent.com/tiangolo/uvicorn-gunicorn-docker/master/docker-images/gunicorn_conf.py /gunicorn_conf.py

ADD https://raw.githubusercontent.com/tiangolo/uvicorn-gunicorn-docker/master/docker-images/start-reload.sh /start-reload.sh
RUN chmod +x /start-reload.sh

COPY supervisord.conf /etc/supervisor/conf.d/

# RUN mkdir -p /app
COPY ./app /app
# COPY ./rq /rq
WORKDIR /app/

ENV PYTHONPATH=/app

# EXPOSE 8080

# Run the start script, it will check for an /app/prestart.sh script (e.g. for migrations)
# And then will start Gunicorn with Uvicorn
# CMD ["/start.sh"]
CMD ["/usr/bin/supervisord"]
EOL
) | docker build --no-cache -t peterbuga/plex-reshare:latest -t "peterbuga/plex-reshare:${VERSION}" -f - .

# cleanup
docker rmi myopenresty

# docker push "peterbuga/plex-reshare:latest"
# docker push "peterbuga/plex-reshare:${VERSION}"
