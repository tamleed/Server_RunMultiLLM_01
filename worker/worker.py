from __future__ import annotations

from redis import Redis
from rq import Connection, Worker

from gateway.app.config import load_gateway_config


if __name__ == "__main__":
    cfg = load_gateway_config()
    conn = Redis.from_url(cfg.redis_url)
    with Connection(conn):
        worker = Worker([cfg.default_queue], name="llm-switchboard-worker")
        worker.work(with_scheduler=False)
