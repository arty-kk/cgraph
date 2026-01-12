# CGRAPH (local)

CGRAPH — локальный сервис и веб‑интерфейс для исследования репозиториев. Приложение индексирует код, строит граф связей по файлам, позволяет искать узлы и запускать LLM‑задачи над выбранным файлом. Интерфейс рассчитан на разработчиков, которым нужно быстро разобраться в структуре проекта, оценить связи и получить анализ/фиксы по конкретным файлам.【F:backend/app/api/projects.py†L1-L79】【F:backend/app/api/tasks.py†L1-L77】【F:backend/app/main.py†L1-L30】

## Возможности

- **Индексация кода**: Python, JavaScript/TypeScript и Go, прочие файлы обрабатываются generic‑индексатором.【F:backend/app/indexers/__init__.py†L1-L22】
- **Граф зависимостей**: глобальный граф и локальные подграфы с лимитами по узлам/рёбрам; поиск узлов по подстроке пути через API.【F:backend/app/api/projects.py†L33-L63】【F:backend/app/graph.py†L344-L380】
- **Контракты и метаданные**: для файла можно получить контракт и статистику узла (язык, LOC, сложность, fan‑in/out, SCC).【F:backend/app/api/nodes.py†L14-L63】
- **LLM‑режимы**: `analyze`, `evolve`, `fix`, `impact`; если режим не указан, запускается триаж для выбора режима и параметров контекста.【F:backend/app/api/tasks.py†L15-L44】【F:backend/app/services/task_service.py†L86-L213】
- **Очередь задач**: все режимы можно запускать синхронно или в фоне; статус доступен по `task_id`.【F:backend/app/api/tasks.py†L47-L77】
- **Большие патчи**: для `fix`‑задач патчи больше 50k символов сохраняются на диск и возвращаются с метаданными для скачивания через отдельный эндпоинт.【F:backend/app/services/task_service.py†L29-L118】【F:backend/app/services/task_service.py†L268-L349】【F:backend/app/api/tasks.py†L65-L73】

## Архитектура

- **Backend** — FastAPI + SQLModel. Роутеры: `projects` (создание, сканирование, граф, поиск, docs), `nodes` (контракты и метаданные), `tasks` (LLM‑задачи и история запусков).【F:backend/app/api/projects.py†L1-L79】【F:backend/app/api/nodes.py†L1-L63】【F:backend/app/api/tasks.py†L1-L77】
- **Frontend** — React + TypeScript (Vite). Общение с API через клиент в `frontend/src/api` и базовый URL из `VITE_API_BASE_URL`.【F:frontend/src/api/client.ts†L1-L14】

## Требования

- Python (в проекте настроен `python_version = 3.11`).【F:pyproject.toml†L7-L15】
- Node.js и npm (frontend на Vite/React).【F:frontend/package.json†L1-L33】
- Переменная окружения `OPENAI_API_KEY` нужна для LLM‑задач; без неё будут работать только операции навигации/графа.【F:backend/app/config.py†L16-L49】【F:backend/app/llm/client.py†L10-L20】

## Установка и запуск (macOS / Windows)

### Backend

1. Создайте виртуальное окружение и активируйте его:
   - macOS:
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```
   - Windows (PowerShell):
     ```powershell
     py -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```
2. Установите зависимости:
   ```bash
   pip install -r backend/requirements.txt
   ```
3. Запустите API:
   ```bash
   uvicorn backend.app.main:app --reload
   ```

Backend поднимается на `http://localhost:8000` (эндпоинт здоровья: `/health`).【F:backend/app/main.py†L11-L30】

### Frontend

1. Перейдите в папку фронтенда и установите зависимости:
   ```bash
   cd frontend
   npm install
   ```
2. Запустите dev‑сервер:
   ```bash
   npm run dev
   ```

По умолчанию frontend обращается к API на `http://localhost:8000`. Чтобы использовать другой адрес, задайте `VITE_API_BASE_URL` (например, в `frontend/.env`).【F:frontend/src/api/client.ts†L1-L14】

## Быстрый dev‑сценарий

1. **Backend**
   ```bash
   export OPENAI_API_KEY="..."     # Windows: setx OPENAI_API_KEY "..."
   uvicorn backend.app.main:app --reload
   ```
2. **Frontend** — в новом терминале:
   ```bash
   cd frontend
   npm run dev
   ```
3. Откройте UI: http://localhost:5173 (API слушает на http://localhost:8000).【F:backend/app/main.py†L11-L30】【F:backend/app/config.py†L12-L18】

## Запуск не в dev‑режиме

### Backend

```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm run build
npm run preview -- --host 0.0.0.0 --port 4173
```

## Основные API‑сценарии

- Создание проекта: `POST /api/projects` с `name` и `root_path`.【F:backend/app/api/projects.py†L16-L27】
- Сканирование: `POST /api/projects/{id}/scan` (можно `background=true`).【F:backend/app/api/projects.py†L37-L41】
- Граф: `GET /api/projects/{id}/graph` или локальный `GET /api/projects/{id}/graph/local?path=...&hops=1&max_nodes=400`.【F:backend/app/api/projects.py†L44-L61】
- Поиск: `GET /api/projects/{id}/search?q=...`.【F:backend/app/api/projects.py†L64-L66】
- Метаданные узла: `GET /api/nodes/{id}/{path}/node`; контракт файла: `GET /api/nodes/{id}/{path}/contract`.【F:backend/app/api/nodes.py†L14-L63】
- Запуск LLM‑задачи: `POST /api/tasks/{id}/run` с `target_path`, `prompt`, `mode` (опционально), `depth`, `dep_mode`, `apply_patch`.【F:backend/app/api/tasks.py†L15-L52】
- История запусков и патчи: `GET /api/tasks/{id}/runs`, `GET /api/tasks/{id}/runs/{run_id}`, `GET /api/tasks/{id}/runs/{run_id}/patch`.【F:backend/app/api/tasks.py†L55-L73】
- Статус фоновой задачи: `GET /api/tasks/status/{task_id}`.【F:backend/app/api/tasks.py†L75-L77】

## Переменные окружения

### Backend (`backend/app/config.py`)

- `OPENAI_API_KEY` — ключ для LLM‑функций.【F:backend/app/config.py†L16-L23】
- `CGRAPH_DB_DIR` — каталог для SQLite и файлов патчей (по умолчанию `~/.CGRAPH`).【F:backend/app/config.py†L24-L33】【F:backend/app/db.py†L13-L21】
- `CGRAPH_DEFAULT_DEPTH` — глубина обхода зависимостей (0..6).【F:backend/app/config.py†L24-L33】【F:backend/app/services/task_service.py†L148-L213】
- `CGRAPH_CORS_ALLOW_ORIGINS` — разрешённые origin‑ы для фронтенда.【F:backend/app/config.py†L12-L18】
- `CGRAPH_MODEL_TRIAGE`, `CGRAPH_MODEL_ANALYSIS`, `CGRAPH_MODEL_PATCH` — модели для LLM‑режимов.【F:backend/app/config.py†L34-L39】
- `CGRAPH_OPENAI_TIMEOUT_SECONDS`, `CGRAPH_OPENAI_MAX_RETRIES` — таймаут и ретраи запросов к OpenAI.【F:backend/app/config.py†L47-L48】

### Frontend

- `VITE_API_BASE_URL` — базовый URL API (по умолчанию `http://localhost:8000`).【F:frontend/src/api/client.ts†L1-L14】

## Локальные данные

- SQLite хранится в `~/.CGRAPH/cgraph.sqlite3` (можно переопределить `CGRAPH_DB_DIR`).【F:backend/app/config.py†L24-L33】【F:backend/app/db.py†L13-L21】
- Большие патчи сохраняются в `~/.CGRAPH/patches` и возвращаются по отдельному запросу, если превышен лимит 50k символов.【F:backend/app/services/task_service.py†L29-L118】【F:backend/app/services/task_service.py†L268-L349】

## Проверки (опционально)

- Backend: `pip install -r backend/requirements-dev.txt && ruff backend/app && mypy backend/app`.【F:backend/requirements-dev.txt†L1-L2】【F:pyproject.toml†L1-L15】
- Frontend: `cd frontend && npm run lint`.【F:frontend/package.json†L1-L12】
