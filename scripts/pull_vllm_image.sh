#!/usr/bin/env bash
set -euo pipefail

MODELS_FILE=${MODELS_YAML_PATH:-/opt/llm-switchboard/configs/models.yaml}
DEFAULT_IMAGE=$(python3 - <<'PY'
import os, yaml
p = os.environ.get('MODELS_YAML_PATH', '/opt/llm-switchboard/configs/models.yaml')
with open(p, 'r', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)
models = cfg.get('models', [])
print(models[0].get('backend', {}).get('image', 'nvcr.io/nvidia/vllm:25.11-py3'))
PY
)

docker pull "$DEFAULT_IMAGE"
