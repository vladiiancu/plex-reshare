from tasks.utilities import redis_connection

from rq import Connection, Queue, Worker

if __name__ == "__main__":
    with Connection(redis_connection):
        worker = Worker(
            list(map(Queue, ["default"])), default_result_ttl=120, maintenance_interval=600, default_worker_ttl=300
        )
        worker.work(with_scheduler=True)
