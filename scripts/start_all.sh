#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR=${PROJECT_DIR:-/opt/llm-switchboard}

cd "$PROJECT_DIR"
docker compose -f docker/docker-compose.yml up -d

install -m 0644 systemd/llm-gateway.service /etc/systemd/system/llm-gateway.service
install -m 0644 systemd/llm-worker.service /etc/systemd/system/llm-worker.service
install -m 0644 systemd/jupyter.service /etc/systemd/system/jupyter.service

systemctl daemon-reload
systemctl enable --now llm-gateway.service llm-worker.service jupyter.service

systemctl status --no-pager llm-gateway.service llm-worker.service jupyter.service
