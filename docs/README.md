# LLM Switchboard (A100, x86_64, no-k8s)

Проект предоставляет единый OpenAI-like gateway с очередью задач и **жёсткой гарантией**, что одновременно работает только **один** vLLM backend-контейнер.

## 1) Что делает решение

- FastAPI gateway (`127.0.0.1:8000`) с endpoint'ами `/v1/models`, `/v1/chat/completions`, `/jobs/*`, `/admin/switch`, `/status`, `/health`.
- Redis + RQ очередь для long-running задач.
- Один RQ worker (один process/job одновременно).
- Переключение модели только через остановку/удаление текущего контейнера vLLM => освобождение VRAM.
- JupyterLab как systemd сервис (`127.0.0.1:8888`) для удалённой разработки через Tailscale.

## 2) Структура

Репозиторий хранит содержимое, которое нужно развернуть в `/opt/llm-switchboard`.

## 3) Что делать дальше: пошагово (для первого запуска)

### Шаг 0. Подготовить сервер
Убедитесь, что уже работают:
- NVIDIA драйвер
- `nvidia-smi`
- Tailscale (авторизация в tailnet)

### Шаг 1. Скопировать проект
```bash
sudo mkdir -p /opt/llm-switchboard
sudo rsync -a ./ /opt/llm-switchboard/
cd /opt/llm-switchboard
```

### Шаг 2. Создать env-файл
```bash
sudo cp .env.example /etc/llm-gateway.env
sudo nano /etc/llm-gateway.env
```
Минимум задайте:
- `GATEWAY_API_KEY`
- `JUPYTER_TOKEN`
- `HF_TOKEN` (если модели приватные)

### Шаг 3. Установить зависимости
```bash
sudo bash scripts/install_prereqs.sh
```
Скрипт поставит Docker, `nvidia-container-toolkit`, Python venv, Jupyter и проверит GPU внутри Docker.

### Шаг 4. Поднять Redis
```bash
sudo docker compose -f docker/docker-compose.yml up -d
```

### Шаг 5. Подтянуть vLLM image
```bash
sudo bash scripts/pull_vllm_image.sh
```

### Шаг 6. Проверить модели
Откройте `configs/models.yaml` и проверьте:
- корректные repo/path
- `tensor_parallel_size` под ваши GPU
- `gpus` (`all` или `device=0,1`)

### Шаг 7. Запустить сервисы
```bash
sudo bash scripts/start_all.sh
```

### Шаг 8. Проверка API
```bash
curl http://127.0.0.1:8000/health
curl -H "X-API-Key: $GATEWAY_API_KEY" http://127.0.0.1:8000/v1/models
```

### Шаг 9. Проверка end-to-end
```bash
GATEWAY_API_KEY=... bash scripts/smoke_test.sh
```

---

## 4) Конфиги

- `configs/models.yaml`: логические модели и vLLM аргументы, включая `tensor_parallel_size`, `quantization`, `gpus`.
- `configs/gateway.yaml`: host/port, redis, таймауты, политики sync/async.

## 5) Environment (`/etc/llm-gateway.env`)

```bash
GATEWAY_API_KEY=change-me
HF_TOKEN=
REDIS_URL=redis://127.0.0.1:6379/0
MODELS_YAML_PATH=/opt/llm-switchboard/configs/models.yaml
GATEWAY_YAML_PATH=/opt/llm-switchboard/configs/gateway.yaml
# optional
CUDA_VISIBLE_DEVICES=0,1
JUPYTER_TOKEN=change-jupyter-token
```

## 6) API examples

Создать async job:

```bash
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $GATEWAY_API_KEY" \
  -d '{"model":"qwen3-30b","messages":[{"role":"user","content":"Hello"}],"async":true}'
```

Статус:

```bash
curl -H "X-API-Key: $GATEWAY_API_KEY" http://127.0.0.1:8000/jobs/<job_id>
```

Результат:

```bash
curl -H "X-API-Key: $GATEWAY_API_KEY" http://127.0.0.1:8000/jobs/<job_id>/result
```

Отмена:

```bash
curl -X POST -H "X-API-Key: $GATEWAY_API_KEY" http://127.0.0.1:8000/jobs/<job_id>/cancel
```

Ручной switch:

```bash
curl -X POST http://127.0.0.1:8000/admin/switch \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $GATEWAY_API_KEY" \
  -d '{"model":"gpt-oss120"}'
```

## 7) Публикация через Tailscale (без public internet)

Вариант A (`tailscale serve`):

```bash
tailscale serve --http=80 127.0.0.1:8000
tailscale serve --http=8888 127.0.0.1:8888
```

Вариант B (SSH tunnel):

```bash
ssh -L 8000:127.0.0.1:8000 user@<tailscale-host>
ssh -L 8888:127.0.0.1:8888 user@<tailscale-host>
```

## 8) VS Code / PyCharm

### VS Code
- Подключиться через Remote-SSH к tailscale hostname.
- Выбрать интерпретатор `/opt/llm-switchboard/.venv/bin/python`.
- Для notebooks: URL `http://127.0.0.1:8888` + token.

### PyCharm
- Настроить SSH Interpreter на сервере (`/opt/llm-switchboard/.venv/bin/python`).
- Открыть проект на удалённой машине или синхронизировать через deployment mapping.

## 9) CI/CD и тесты — что это и как внедрить

### Что такое CI
**CI (Continuous Integration)** — это автоматическая проверка проекта при каждом push/PR:
- устанавливаются зависимости,
- запускаются проверки (линтеры, тесты, compile check),
- вы сразу видите, сломали что-то или нет.

В проекте добавлен workflow GitHub Actions: `.github/workflows/ci.yml`.
Сейчас он делает базовую проверку Python-кода (установка deps + `compileall`).

### Что такое CD
**CD (Continuous Delivery/Deployment)**:
- **Delivery**: после успешного CI у вас готов артефакт/релиз, который можно выкатывать.
- **Deployment**: выкатывание происходит автоматически (например, на сервер).

Для production LLM-сервиса рекомендую начинать с **Continuous Delivery**, а не auto-deploy:
1. CI проходит.
2. Вы вручную запускаете deploy-скрипт на сервере.
3. Проверяете health/smoke.

### Минимальный практический процесс для вас
1. Работаете в отдельной ветке.
2. Делаете commit/push.
3. Ждёте зелёный CI.
4. Мержите PR.
5. На сервере:
   ```bash
   cd /opt/llm-switchboard
   git pull
   sudo bash scripts/start_all.sh
   GATEWAY_API_KEY=... bash scripts/smoke_test.sh
   ```

### Какие тесты добавить дальше
- Unit tests для:
  - валидации конфигов,
  - API-логики sync/async,
  - cancel semantics.
- Integration tests (локально, с docker) для:
  - switch между моделями,
  - hard cancel running job.
- E2E smoke (уже есть `scripts/smoke_test.sh`).

## 10) Логи и troubleshooting

- Gateway logs: `journalctl -u llm-gateway -f`
- Worker logs: `journalctl -u llm-worker -f`
- Jupyter logs: `journalctl -u jupyter -f`
- Redis: `docker logs llm-switchboard-redis`
- Активный backend: `docker ps --filter name=llm-switchboard-vllm`
- Логи backend: `docker logs llm-switchboard-vllm --tail 200`

Проблемы:
- **OOM / модель не стартует**: уменьшить `max-model-len`, `gpu_memory_utilization`, повысить `tensor_parallel_size`.
- **Docker не видит GPU**: проверить `nvidia-smi`, `nvidia-ctk runtime configure --runtime=docker`, тест `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`.
- **Нужно вручную остановить backend**: `docker rm -f llm-switchboard-vllm`.

## 11) Если потом понадобится k8s/k3s

Текущая версия специально без k8s. При миграции сохраняйте семантику single-active-backend через distributed lock и singleton deployment.
