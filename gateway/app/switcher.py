from __future__ import annotations

import os
import shlex
import time
from typing import Any

import docker
from docker.errors import DockerException, NotFound
from filelock import FileLock, Timeout

from gateway.app.config import load_gateway_config
from gateway.app.queue import set_state

CONTAINER_NAME = "llm-switchboard-vllm"
LOCK_PATH = "/var/lock/llm-switch.lock"


class SwitchError(RuntimeError):
    pass


class Switcher:
    def __init__(self, models_cfg: dict[str, Any]) -> None:
        self.models_cfg = models_cfg
        self.cfg = load_gateway_config()
        self.client = docker.from_env()

    def _container(self):
        try:
            return self.client.containers.get(CONTAINER_NAME)
        except NotFound:
            return None

    def stop_current_backend(self) -> None:
        container = self._container()
        if not container:
            return

        timeout = self.cfg.switch_timeout_sec
        try:
            container.stop(timeout=timeout)
        except DockerException:
            pass

        container.reload()
        if container.status not in {"exited", "dead", "created"}:
            container.kill()

        try:
            container.remove(force=True)
        except DockerException as e:
            raise SwitchError(f"Failed to remove existing backend container: {e}") from e

    def _build_command(self, model_cfg: dict[str, Any]) -> list[str]:
        source = model_cfg["source"]["value"]
        args = model_cfg.get("backend", {}).get("vllm_args", [])
        if isinstance(args, str):
            args = shlex.split(args)
        return [
            "python",
            "-m",
            "vllm.entrypoints.openai.api_server",
            "--model",
            source,
            "--host",
            "0.0.0.0",
            "--port",
            str(model_cfg.get("backend", {}).get("port", 8001)),
            *args,
        ]

    def start_backend(self, model_name: str) -> None:
        if model_name not in self.models_cfg["models"]:
            raise SwitchError(f"Model not found: {model_name}")
        model_cfg = self.models_cfg["models"][model_name]
        backend = model_cfg.get("backend", {})
        resources = model_cfg.get("resources", {})
        image = backend.get("image", "nvcr.io/nvidia/vllm:25.11-py3")
        port = int(backend.get("port", 8001))
        gpus = backend.get("gpus", "all")

        mounts: dict[str, dict[str, str]] = {}
        models_dir = resources.get("models_dir")
        hf_cache_dir = resources.get("hf_cache_dir")
        if models_dir:
            mounts[models_dir] = {"bind": "/models", "mode": "rw"}
        if hf_cache_dir:
            mounts[hf_cache_dir] = {"bind": "/var/lib/huggingface", "mode": "rw"}

        env = {"HF_TOKEN": os.getenv("HF_TOKEN", "")}
        for key, value in os.environ.items():
            if key.startswith("NCCL_") or key in {"CUDA_VISIBLE_DEVICES"}:
                env[key] = value

        device_request = [docker.types.DeviceRequest(capabilities=[["gpu"]], count=-1)]
        if gpus != "all" and gpus.startswith("device="):
            ids = gpus.split("=", 1)[1]
            device_request = [docker.types.DeviceRequest(capabilities=[["gpu"]], device_ids=ids.split(","))]

        try:
            self.client.images.pull(image)
        except DockerException as e:
            raise SwitchError(f"Unable to pull image {image}. Check NVIDIA NGC auth/network. {e}") from e

        try:
            self.client.containers.run(
                image=image,
                name=CONTAINER_NAME,
                command=self._build_command(model_cfg),
                detach=True,
                remove=False,
                runtime="nvidia",
                device_requests=device_request,
                environment=env,
                volumes=mounts,
                ports={f"{port}/tcp": ("127.0.0.1", port)},
                shm_size="16g",
            )
        except DockerException as e:
            raise SwitchError(f"Failed to start backend: {e}") from e

    def wait_ready(self, model_name: str) -> None:
        import httpx

        model_cfg = self.models_cfg["models"][model_name]
        port = int(model_cfg.get("backend", {}).get("port", 8001))
        url = f"http://127.0.0.1:{port}/v1/models"
        deadline = time.time() + self.cfg.backend_ready_timeout_sec

        while time.time() < deadline:
            try:
                r = httpx.get(url, timeout=5)
                if r.status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(2)

        logs = ""
        container = self._container()
        if container:
            try:
                logs = container.logs(tail=200).decode("utf-8", errors="replace")
            except DockerException:
                pass
        raise SwitchError(f"Backend readiness timeout for {model_name}. Recent logs:\n{logs}")

    def ensure_model(self, model_name: str) -> None:
        with FileLock(LOCK_PATH, timeout=self.cfg.wait_timeout_sec):
            set_state(switching="1")
            self.stop_current_backend()
            self.start_backend(model_name)
            self.wait_ready(model_name)
            set_state(active_model=model_name, switching="0")

    def hard_cancel(self) -> None:
        try:
            with FileLock(LOCK_PATH, timeout=3):
                self.stop_current_backend()
                set_state(active_model=None, switching="0")
        except Timeout as e:
            raise SwitchError(f"Unable to acquire switch lock for cancel: {e}") from e
