from os import getenv

import redis
from rq import Connection, Queue, Worker

if __name__ == "__main__":
    redis_conn = redis.Redis(
        host=getenv("REDIS_HOST", default="redis"),
        port=getenv("REDIS_PORT", default=6379),
        db=getenv("REDIS_DB_RQ", default=11),
    )

    with Connection(redis_conn):
        worker = Worker(
            list(map(Queue, ["default"])), default_result_ttl=120, maintenance_interval=600, default_worker_ttl=300
        )
        worker.work(with_scheduler=True)
