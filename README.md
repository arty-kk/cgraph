# CGRAPH (local)

CGRAPH — локальный сервис и веб‑интерфейс для исследования репозиториев. Приложение индексирует код, строит граф связей по файлам, позволяет искать узлы и запускать LLM‑задачи над выбранным файлом. Интерфейс рассчитан на разработчиков, которым нужно быстро разобраться в структуре проекта, оценить связи и получить анализ/фиксы по конкретным файлам.

## Возможности

- **Индексация кода**: Python, JavaScript/TypeScript и Go, прочие файлы обрабатываются generic‑индексатором.
- **Граф зависимостей**: глобальный граф и локальные подграфы с лимитами по узлам/рёбрам; поиск узлов по подстроке пути через API.
- **Контракты и метаданные**: для файла можно получить контракт и статистику узла (язык, LOC, сложность, fan‑in/out, SCC).
- **LLM‑режимы**: `analyze`, `evolve`, `fix`, `impact`; если режим не указан, запускается триаж для выбора режима и параметров контекста.
- **Очередь задач**: все режимы можно запускать синхронно или в фоне; статус доступен по `task_id`.
- **Большие патчи**: для `fix`‑задач патчи больше 50k символов сохраняются на диск и возвращаются с метаданными для скачивания через отдельный эндпоинт.

## Установка и запуск (macOS / Windows)

### Backend

1. Создайте виртуальное окружение и активируйте его:
   - macOS:
     ```bash
     python3 -m venv .venv && source .venv/bin/activate
     ```
   - Windows (PowerShell):
     ```powershell
     py -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```
2. Установите зависимости:
   ```bash
   pip install --upgrade pip && pip install -r requirements.txt
   ```
3. Запустите API:
   ```bash
   export OPENAI_API_KEY="..."     # Windows: setx OPENAI_API_KEY "..."
   uvicorn app.main:app --reload
   ```

Backend поднимается на `http://localhost:8000` (эндпоинт здоровья: `/health`).

### Frontend

1. Перейдите в папку фронтенда и установите зависимости:
   ```bash
   cd frontend && npm install
   ```
2. Запустите:
   ```bash
   npm run build && npm run preview -- --host 0.0.0.0 --port 4173
   ```
3. Откройте UI: http://localhost:5173 | http://localhost:4173 (API слушает на http://localhost:8000).

По умолчанию frontend обращается к API на `http://localhost:8000`. Чтобы использовать другой адрес, задайте `VITE_API_BASE_URL` (например, в `frontend/.env`).

## Архитектура

- **Backend** — FastAPI + SQLModel. Роутеры: `projects` (создание, сканирование, граф, поиск, docs), `nodes` (контракты и метаданные), `tasks` (LLM‑задачи и история запусков).
- **Frontend** — React + TypeScript (Vite). Общение с API через клиент в `frontend/src/api` и базовый URL из `VITE_API_BASE_URL`.

## Требования

- Python (в проекте настроен `python_version = 3.11`).
- Node.js и npm (frontend на Vite/React).
- Переменная окружения `OPENAI_API_KEY` нужна для LLM‑задач; без неё будут работать только операции навигации/графа.
- 
## Основные API‑сценарии

- Создание проекта: `POST /api/projects` с `name` и `root_path`.
- Сканирование: `POST /api/projects/{id}/scan` (можно `background=true`).
- Граф: `GET /api/projects/{id}/graph` или локальный `GET /api/projects/{id}/graph/local?path=...&hops=1&max_nodes=400`.
- Поиск: `GET /api/projects/{id}/search?q=...`.
- Метаданные узла: `GET /api/nodes/{id}/{path}/node`; контракт файла: `GET /api/nodes/{id}/{path}/contract`.
- Запуск LLM‑задачи: `POST /api/tasks/{id}/run` с `target_path`, `prompt`, `mode` (опционально), `depth`, `dep_mode`, `apply_patch`.
- История запусков и патчи: `GET /api/tasks/{id}/runs`, `GET /api/tasks/{id}/runs/{run_id}`, `GET /api/tasks/{id}/runs/{run_id}/patch`.
- Статус фоновой задачи: `GET /api/tasks/status/{task_id}`.

## Переменные окружения

### Backend (`backend/app/config.py`)

- `OPENAI_API_KEY` — ключ для LLM‑функций.
- `CGRAPH_DB_DIR` — каталог для SQLite и файлов патчей (по умолчанию `~/.CGRAPH`).
- `CGRAPH_DEFAULT_DEPTH` — глубина обхода зависимостей (0..6).
- `CGRAPH_CORS_ALLOW_ORIGINS` — разрешённые origin‑ы для фронтенда.
- `CGRAPH_MODEL_TRIAGE`, `CGRAPH_MODEL_ANALYSIS`, `CGRAPH_MODEL_PATCH` — модели для LLM‑режимов.
- `CGRAPH_OPENAI_TIMEOUT_SECONDS`, `CGRAPH_OPENAI_MAX_RETRIES` — таймаут и ретраи запросов к OpenAI.

### Frontend

- `VITE_API_BASE_URL` — базовый URL API (по умолчанию `http://localhost:8000`).

## Локальные данные

- SQLite хранится в `~/.CGRAPH/cgraph.sqlite3` (можно переопределить `CGRAPH_DB_DIR`).
- Большие патчи сохраняются в `~/.CGRAPH/patches` и возвращаются по отдельному запросу, если превышен лимит 50k символов.

## Проверки (опционально)

- Backend: `pip install -r backend/requirements-dev.txt && ruff backend/app && mypy backend/app`.【F:pyproject.toml†L1-L15】
- Frontend: `cd frontend && npm run lint`.
