#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR=${PROJECT_DIR:-/opt/llm-switchboard}
PYTHON_BIN=${PYTHON_BIN:-python3}
JUPYTER_VENV=${JUPYTER_VENV:-/opt/jupyter-venv}

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi

if ! dpkg -s nvidia-container-toolkit >/dev/null 2>&1; then
  distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -s -L https://nvidia.github.io/libnvidia-container/${distribution}/libnvidia-container.list \
      | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
      | tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update
  apt-get install -y nvidia-container-toolkit
fi

nvidia-ctk runtime configure --runtime=docker
systemctl restart docker

if [[ -n "${SUDO_USER:-}" ]]; then
  usermod -aG docker "$SUDO_USER" || true
fi

mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"

$PYTHON_BIN -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

$PYTHON_BIN -m venv "$JUPYTER_VENV"
source "$JUPYTER_VENV/bin/activate"
pip install --upgrade pip
pip install jupyterlab

mkdir -p /home/${SUDO_USER:-root}/work

nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi

echo "Prerequisites installed. Re-login may be required for docker group changes."
