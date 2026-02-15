#!/usr/bin/env bash
set -euo pipefail

MODELS_FILE=${MODELS_YAML_PATH:-/opt/llm-switchboard/configs/models.yaml}
HF_CACHE=${HF_HOME:-/var/lib/huggingface}
mkdir -p "$HF_CACHE"

if ! command -v huggingface-cli >/dev/null 2>&1; then
  pip install "huggingface_hub[cli]"
fi

python3 - <<'PY'
import os, yaml, subprocess
models_file = os.environ.get('MODELS_YAML_PATH', '/opt/llm-switchboard/configs/models.yaml')
cache = os.environ.get('HF_HOME', '/var/lib/huggingface')
with open(models_file, 'r', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)
for m in cfg.get('models', []):
    src = m.get('source', {})
    if src.get('type') == 'huggingface_repo':
        repo = src.get('value')
        if not repo:
            continue
        print(f"Downloading {repo}")
        subprocess.run([
            'huggingface-cli', 'download', repo,
            '--local-dir', os.path.join(cache, repo.replace('/', '__')),
            '--resume-download'
        ], check=True)
PY
