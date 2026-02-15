#!/usr/bin/env bash
set -euo pipefail

BASE_URL=${BASE_URL:-http://127.0.0.1:8000}
API_KEY_HEADER=()
if [[ -n "${GATEWAY_API_KEY:-}" ]]; then
  API_KEY_HEADER=(-H "X-API-Key: ${GATEWAY_API_KEY}")
fi

curl -fsS "$BASE_URL/health"
curl -fsS "${API_KEY_HEADER[@]}" "$BASE_URL/v1/models"

JOB1=$(curl -fsS -X POST "${API_KEY_HEADER[@]}" "$BASE_URL/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3-30b","messages":[{"role":"user","content":"Say ping"}],"async":true}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')

echo "Job1=$JOB1"
for _ in {1..120}; do
  STATUS=$(curl -fsS "${API_KEY_HEADER[@]}" "$BASE_URL/jobs/$JOB1" | python3 -c 'import sys,json;print(json.load(sys.stdin)["status"])')
  [[ "$STATUS" == "succeeded" ]] && break
  [[ "$STATUS" == "failed" ]] && exit 1
  sleep 2
done
curl -fsS "${API_KEY_HEADER[@]}" "$BASE_URL/jobs/$JOB1/result"

JOB2=$(curl -fsS -X POST "${API_KEY_HEADER[@]}" "$BASE_URL/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{"model":"gpt-oss120","messages":[{"role":"user","content":"Say pong"}],"async":true}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')

echo "Job2=$JOB2"
curl -fsS "${API_KEY_HEADER[@]}" "$BASE_URL/status"

JOB3=$(curl -fsS -X POST "${API_KEY_HEADER[@]}" "$BASE_URL/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3-30b","messages":[{"role":"user","content":"Write 10000 words"}],"max_tokens":4096,"async":true}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')

echo "Job3=$JOB3 cancel"
curl -fsS -X POST "${API_KEY_HEADER[@]}" "$BASE_URL/jobs/$JOB3/cancel"

