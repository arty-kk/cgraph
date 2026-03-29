# StubGraph

StubGraph — self-hosted система для анализа кодовой базы: строит граф файловых зависимостей, поддерживает поиск по коду (структурный/семантический/текстовый), запуск LLM-задач по выбранному файлу и применение patch-результатов в проект. Сервис состоит из React/Vite frontend и FastAPI backend с очередями фоновых задач через Redis + ARQ.

## Что умеет

- **Проекты и организации**: работа в рамках org-контекста (header `X-Org-ID`), список/создание проектов, импорт проекта из snapshot-архива.  
- **Граф зависимостей**: полный граф проекта и локальный граф вокруг файла (`hops`, `max_nodes`, `max_edges`).  
- **Поиск**:
  - структурный (`/projects/{id}/search`),
  - семантический (`/projects/{id}/search/semantic`),
  - текстовый (`/projects/{id}/search/text`).
- **Работа с файлами**: чтение/создание/редактирование/переименование/удаление с повторной индексацией.
- **LLM-задачи**: запуск `analyze|evolve|fix|impact`, сохранение run-истории, получение и применение patch.
- **Документация проекта**: сборка/обновление markdown-доков для выбранного проекта.

## Архитектура (кратко)

- `frontend/` — React 18 + Vite 7 + TypeScript + Tailwind + Cytoscape.
- `backend/` — FastAPI + SQLModel + Alembic + Redis + ARQ worker.
- `db` — PostgreSQL 16.
- `redis` — брокер очереди и кэш.
- `proxy` — nginx, проксирует frontend/backend в docker-compose окружении.

## Стек и версии (из репозитория)

### Backend

- Python 3.11 (Docker base image `python:3.11-slim`)
- `fastapi==0.115.0`
- `uvicorn[standard]==0.30.6`
- `sqlmodel==0.0.22`
- `alembic==1.13.2`
- `psycopg[binary]==3.2.1`
- `redis==5.0.8`
- `arq==0.26.3`
- `openai==1.99.2`

### Frontend

- Node 20 (Docker base image `node:20-alpine`)
- React 18.3.1
- Vite 7.3.0
- TypeScript 5.6.3
- Axios 1.7.7
- Cytoscape 3.30.2

## Быстрый старт (Docker Compose)

1. Подготовьте `.env` в корне репозитория (минимум):

```env
POSTGRES_DB=stubgraph
POSTGRES_USER=stubgraph
POSTGRES_PASSWORD=stubgraph
STUBGRAPH_DATABASE_URL=postgresql+psycopg://stubgraph:stubgraph@db:5432/stubgraph
STUBGRAPH_REDIS_URL=redis://redis:6379/0
VITE_API_BASE_URL=http://localhost:8000
STUBGRAPH_CORS_ALLOW_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

2. Проверьте frontend Dockerfile для compose:

```bash
test -f frontend/Dockerfile.prod && echo "ok" || echo "missing frontend/Dockerfile.prod"
```

На текущем состоянии репозитория `docker-compose.yml` ссылается на `frontend/Dockerfile.prod`, а в дереве есть `frontend/Dockerfile`. Поэтому перед запуском compose нужно сначала синхронизировать это расхождение.

3. После синхронизации Dockerfile запустите сервисы:

```bash
docker compose up --build
```

4. Проверка backend health:

```bash
curl http://localhost:8000/health
```

Ожидаемый ответ: `{"ok": true}`.

## Локальная разработка (без Docker)

### Backend

```bash
cd backend
pip install -r requirements.txt
alembic -c alembic.ini upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Worker (очередь задач)

```bash
cd backend
arq app.arq_worker.WorkerSettings
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Основные API-группы

- `/api/auth` — bootstrap/register/login/logout, API-keys.
- `/api/orgs` — организации и участники.
- `/api/projects` — проекты, сканирование, граф, поиск, docs/snapshot-операции.
- `/api/nodes` — контракт файла, node info, CRUD по файлам.
- `/api/tasks` — запуск LLM-задач, run-история, patch, task status.
- `/health` — healthcheck.

> Примечание: frontend клиент автоматически добавляет префикс `/api`, если `VITE_API_BASE_URL` не оканчивается на `/api` или `/api/v1`.

## Настройки окружения (ключевые)

- Инфраструктура: `STUBGRAPH_DATABASE_URL`, `STUBGRAPH_REDIS_URL`.
- Хранилище: `STUBGRAPH_STORAGE_BACKEND=local|s3` + `STUBGRAPH_S3_*`.
- Auth: `STUBGRAPH_AUTH_ENABLED`, `STUBGRAPH_AUTH_ALLOW_PUBLIC_SIGNUP`, `STUBGRAPH_AUTH_PASSWORD_PEPPER`.
- LLM: `OPENAI_API_KEY`, `STUBGRAPH_MODEL_TRIAGE|ANALYSIS|PATCH`.
- Agentic retrieval: `STUBGRAPH_LLM_AGENTIC_*`.
- Ограничения индексации/поиска: `STUBGRAPH_SCAN_*`, `STUBGRAPH_EMBEDDINGS_*`, `STUBGRAPH_GRAPH_METRICS_*`.

## Ограничения и допущения

- В репозитории присутствует `frontend/Dockerfile`, а `docker-compose.yml` ссылается на `frontend/Dockerfile.prod`. Это потенциальное расхождение конфигурации, которое стоит проверить перед production-запуском.
- В этом README не перечислены все env-переменные; полный список и валидация ограничений находятся в `backend/app/config.py`.
- Для LLM-функций требуется валидный `OPENAI_API_KEY`; без него не все task-сценарии будут работоспособны.

## Структура репозитория

```text
backend/      FastAPI API, сервисы, индексация, очереди ARQ, миграции
frontend/     React UI, API-клиент, компоненты графа/редактора
docker-compose.yml
infra/nginx/  конфигурация nginx proxy
```
