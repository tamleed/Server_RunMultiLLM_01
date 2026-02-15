from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class AppConfig:
    host: str
    port: int
    redis_url: str
    default_queue: str
    switch_timeout_sec: int
    inference_timeout_sec: int
    backend_ready_timeout_sec: int
    default_async: bool
    sync_only_when_queue_empty_and_model_active: bool
    switching_policy: str
    wait_timeout_sec: int


class ConfigError(RuntimeError):
    pass


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config file must contain object root: {path}")
    return data


def load_gateway_config() -> AppConfig:
    cfg_path = Path(os.getenv("GATEWAY_YAML_PATH", "/opt/llm-switchboard/configs/gateway.yaml"))
    raw = _read_yaml(cfg_path)

    timeouts = raw.get("timeouts", {})
    policies = raw.get("policies", {})

    return AppConfig(
        host=raw.get("host", "127.0.0.1"),
        port=int(raw.get("port", 8000)),
        redis_url=os.getenv("REDIS_URL", raw.get("redis_url", "redis://127.0.0.1:6379/0")),
        default_queue=raw.get("default_queue", "default"),
        switch_timeout_sec=int(timeouts.get("switch_timeout_sec", 120)),
        inference_timeout_sec=int(timeouts.get("inference_timeout_sec", 900)),
        backend_ready_timeout_sec=int(timeouts.get("backend_ready_timeout_sec", 180)),
        default_async=bool(policies.get("default_async", True)),
        sync_only_when_queue_empty_and_model_active=bool(
            policies.get("sync_allowed_only_if_queue_empty_and_model_active", True)
        ),
        switching_policy=policies.get("when_switching", "wait"),
        wait_timeout_sec=int(policies.get("wait_timeout_sec", 300)),
    )


def load_models_config() -> dict[str, Any]:
    models_path = Path(os.getenv("MODELS_YAML_PATH", "/opt/llm-switchboard/configs/models.yaml"))
    raw = _read_yaml(models_path)
    models = raw.get("models", [])
    if not isinstance(models, list):
        raise ConfigError("configs/models.yaml must define a list under 'models'")
    by_name: dict[str, Any] = {}
    for model in models:
        name = model.get("name")
        if not name:
            raise ConfigError("Every model entry must have a 'name'")
        by_name[name] = model
    return {"models": by_name}
