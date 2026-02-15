from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Response, status
from rq.command import send_stop_job_command
from rq.exceptions import NoSuchJobError

from gateway.app.auth import check_api_key
from gateway.app.config import ConfigError, load_gateway_config, load_models_config
from gateway.app.models import (
    ChatCompletionsRequest,
    JobCreateRequest,
    JobCreateResponse,
    JobResultResponse,
    JobStatusResponse,
    QueueStatusResponse,
    SwitchRequest,
)
from gateway.app.proxy import chat_completion
from gateway.app.queue import (
    cancel_queued_job,
    create_job,
    get_active_job_id,
    get_job,
    get_state,
    queue_length,
    redis_conn,
    set_state,
)
from gateway.app.switcher import SwitchError, Switcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s level=%(levelname)s msg=%(message)s")
logger = logging.getLogger("llm-switchboard")

app = FastAPI(title="LLM Switchboard", version="1.0.0")
startup_ts = time.time()
global_lock = asyncio.Lock()


@app.on_event("startup")
async def startup() -> None:
    set_state(switching="0")


def _cfg_and_models() -> tuple[Any, dict[str, Any]]:
    try:
        return load_gateway_config(), load_models_config()
    except ConfigError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/health")
async def health() -> dict[str, str]:
    cfg, _ = _cfg_and_models()
    try:
        redis_conn().ping()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {e}") from e
    return {"status": "ok", "redis": cfg.redis_url}


@app.get("/status", dependencies=[Depends(check_api_key)])
async def status_endpoint() -> dict[str, Any]:
    state = get_state()
    return {
        "uptime_sec": int(time.time() - startup_ts),
        "active_model": state.get("active_model"),
        "switching": state.get("switching") == "1",
        "current_job_id": state.get("current_job_id"),
    }


@app.get("/queue", response_model=QueueStatusResponse, dependencies=[Depends(check_api_key)])
async def queue_endpoint() -> QueueStatusResponse:
    state = get_state()
    return QueueStatusResponse(
        queue_length=queue_length(),
        current_job_id=state.get("current_job_id"),
        active_model=state.get("active_model"),
        switching=state.get("switching") == "1",
    )


@app.get("/v1/models", dependencies=[Depends(check_api_key)])
async def list_models() -> dict[str, Any]:
    _, models = _cfg_and_models()
    active = get_state().get("active_model")
    data = [{"id": n, "object": "model", "active": n == active} for n in models["models"].keys()]
    return {"object": "list", "data": data}


@app.post("/jobs", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(check_api_key)])
async def create_job_endpoint(req: JobCreateRequest) -> JobCreateResponse:
    _, models = _cfg_and_models()
    if req.model not in models["models"]:
        raise HTTPException(status_code=404, detail="Model not found")
    job = create_job(req.model, req.payload)
    return JobCreateResponse(job_id=job.id, status="queued")


@app.post("/v1/chat/completions", dependencies=[Depends(check_api_key)])
async def chat(req: ChatCompletionsRequest, response: Response) -> dict[str, Any]:
    cfg, models = _cfg_and_models()
    if req.model not in models["models"]:
        raise HTTPException(status_code=404, detail="Model not found")

    async_mode = cfg.default_async if req.async_mode is None else req.async_mode
    state = get_state()
    current_model = state.get("active_model")
    q_len = queue_length()

    payload = req.model_dump(by_alias=True)
    payload.pop("async", None)

    if not async_mode:
        if q_len != 0 or current_model != req.model:
            raise HTTPException(
                status_code=409,
                detail="Queue not empty or model switch required; use async",
            )
        backend_port = int(models["models"][req.model].get("backend", {}).get("port", 8001))
        return await chat_completion(backend_port, payload, cfg.inference_timeout_sec)

    job = create_job(req.model, payload)
    response.status_code = status.HTTP_202_ACCEPTED
    return {"job_id": job.id, "status": "queued"}


@app.get("/jobs/{job_id}", response_model=JobStatusResponse, dependencies=[Depends(check_api_key)])
async def get_job_status(job_id: str) -> JobStatusResponse:
    try:
        job = get_job(job_id)
    except NoSuchJobError:
        raise HTTPException(status_code=404, detail="Job not found")

    meta = job.meta or {}
    return JobStatusResponse(
        job_id=job.id,
        status=meta.get("status", "queued"),
        requested_model=meta.get("requested_model", "unknown"),
        created_at=_parse_dt(meta.get("created_at")),
        started_at=_parse_dt(meta.get("started_at")),
        finished_at=_parse_dt(meta.get("finished_at")),
        progress=meta.get("progress"),
        error=meta.get("error"),
    )


@app.get("/jobs/{job_id}/result", response_model=JobResultResponse, dependencies=[Depends(check_api_key)])
async def get_job_result(job_id: str) -> JobResultResponse:
    try:
        job = get_job(job_id)
    except NoSuchJobError:
        raise HTTPException(status_code=404, detail="Job not found")
    meta = job.meta or {}
    return JobResultResponse(job_id=job_id, status=meta.get("status", "queued"), result=meta.get("result"))


@app.post("/jobs/{job_id}/cancel", dependencies=[Depends(check_api_key)])
async def cancel_job(job_id: str) -> dict[str, str]:
    _, models = _cfg_and_models()
    switcher = Switcher(models)
    try:
        job = get_job(job_id)
    except NoSuchJobError:
        raise HTTPException(status_code=404, detail="Job not found")

    meta = job.meta or {}
    status_val = meta.get("status", "queued")
    if status_val == "queued":
        cancel_queued_job(job)
        return {"status": "cancelled"}

    if status_val == "running":
        try:
            worker_name = job.worker_name
            if worker_name:
                send_stop_job_command(redis_conn(), worker_name)
        except Exception:
            logger.exception("Failed to signal worker stop")

        try:
            switcher.hard_cancel()
        except SwitchError as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

        job.meta["status"] = "cancelled"
        job.meta["finished_at"] = datetime.utcnow().isoformat()
        job.save_meta()
        return {"status": "cancelled"}

    return {"status": status_val}


@app.post("/admin/switch", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(check_api_key)])
async def admin_switch(req: SwitchRequest) -> dict[str, str]:
    _, models = _cfg_and_models()
    if req.model not in models["models"]:
        raise HTTPException(status_code=404, detail="Model not found")

    if queue_length() == 0 and not get_active_job_id():
        switcher = Switcher(models)
        async with global_lock:
            try:
                switcher.ensure_model(req.model)
            except SwitchError as e:
                raise HTTPException(status_code=500, detail=str(e)) from e
        return {"status": "switched", "model": req.model}

    admin_payload = {"messages": [{"role": "system", "content": "switch-only noop"}], "max_tokens": 1}
    job = create_job(req.model, admin_payload, priority_front=True)
    return {"status": "queued", "job_id": job.id}


def _parse_dt(value: Any):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None
