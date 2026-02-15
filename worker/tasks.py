from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from rq import get_current_job

from gateway.app.config import load_gateway_config, load_models_config
from gateway.app.queue import get_state, set_state
from gateway.app.switcher import SwitchError, Switcher


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def execute_job(model: str, payload: dict[str, Any]) -> dict[str, Any]:
    cfg = load_gateway_config()
    models = load_models_config()
    job = get_current_job()
    assert job is not None

    job.meta["status"] = "running"
    job.meta["started_at"] = _utc_now()
    job.meta["requested_model"] = model
    job.save_meta()
    set_state(current_job_id=job.id)

    switcher = Switcher(models)
    try:
        active_model = get_state().get("active_model")
        if model != active_model:
            switcher.ensure_model(model)

        backend_port = int(models["models"][model].get("backend", {}).get("port", 8001))
        url = f"http://127.0.0.1:{backend_port}/v1/chat/completions"
        with httpx.Client(timeout=cfg.inference_timeout_sec) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()

        job.meta["status"] = "succeeded"
        job.meta["finished_at"] = _utc_now()
        job.meta["progress"] = 1.0
        job.meta["result"] = result
        job.save_meta()
        return result
    except SwitchError as e:
        job.meta["status"] = "failed"
        job.meta["finished_at"] = _utc_now()
        job.meta["error"] = str(e)
        job.save_meta()
        raise
    except Exception as e:
        job.meta["status"] = "failed"
        job.meta["finished_at"] = _utc_now()
        job.meta["error"] = f"Job execution failed: {e}"
        job.save_meta()
        raise
    finally:
        set_state(current_job_id=None)
