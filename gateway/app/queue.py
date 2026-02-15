from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from redis import Redis
from rq import Queue
from rq.job import Job

from gateway.app.config import load_gateway_config

JOB_META_KEY = "llm_switchboard:job_meta"
STATE_KEY = "llm_switchboard:state"


def redis_conn() -> Redis:
    cfg = load_gateway_config()
    return Redis.from_url(cfg.redis_url, decode_responses=True)


def rq_queue() -> Queue:
    cfg = load_gateway_config()
    return Queue(name=cfg.default_queue, connection=redis_conn(), default_timeout=cfg.inference_timeout_sec)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_job_meta(job_id: str, meta: dict[str, Any]) -> None:
    redis_conn().hset(JOB_META_KEY, job_id, str(meta))


def create_job(model: str, payload: dict[str, Any], priority_front: bool = False) -> Job:
    queue = rq_queue()
    job = queue.enqueue(
        "worker.tasks.execute_job",
        kwargs={"model": model, "payload": payload},
        job_timeout=load_gateway_config().inference_timeout_sec,
        result_ttl=86400,
        failure_ttl=86400,
        at_front=priority_front,
    )
    job.meta.update(
        {
            "status": "queued",
            "requested_model": model,
            "created_at": utc_now(),
            "started_at": None,
            "finished_at": None,
            "progress": 0.0,
            "error": None,
            "result": None,
        }
    )
    job.save_meta()
    return job


def get_job(job_id: str) -> Job:
    return Job.fetch(job_id, connection=redis_conn())


def cancel_queued_job(job: Job) -> None:
    job.cancel()
    job.meta["status"] = "cancelled"
    job.meta["finished_at"] = utc_now()
    job.save_meta()


def queue_length() -> int:
    return len(rq_queue())


def get_active_job_id() -> str | None:
    return redis_conn().hget(STATE_KEY, "current_job_id")


def set_state(**kwargs: str | None) -> None:
    conn = redis_conn()
    for key, value in kwargs.items():
        if value is None:
            conn.hdel(STATE_KEY, key)
        else:
            conn.hset(STATE_KEY, key, value)


def get_state() -> dict[str, str]:
    return redis_conn().hgetall(STATE_KEY)
