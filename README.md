# CGRAPH (local)

CGRAPH — локальный сервис и веб‑интерфейс для исследования репозиториев. Приложение индексирует код, строит граф связей по файлам, позволяет искать узлы и запускать LLM‑задачи над выбранным файлом (с учетом контракта). Для LLM‑задач доступен agentic‑режим получения контекста (tool‑based retrieval), когда модель сама выбирает необходимые файлы через инструментарий. Интерфейс рассчитан на разработчиков, которым нужно быстро разобраться в структуре проекта, оценить связи и получить анализ/фиксы по конкретным файлам с учетом связей по контракту.

## Возможности

- **Индексация кода**: Python, JavaScript/TypeScript и Go, прочие файлы обрабатываются generic‑индексатором.
- **Граф зависимостей**: глобальный граф и локальные подграфы с лимитами по узлам/рёбрам; поиск узлов по подстроке пути через API.
- **Контракты и метаданные**: для файла можно получить контракт и статистику узла (язык, LOC, сложность, fan‑in/out, SCC).
- **LLM‑режимы**: `analyze`, `evolve`, `fix`, `impact`; если режим не указан, запускается триаж для выбора режима, глубины и `dep_mode`.
- **Agentic‑контекст**: при включении используется tool‑based retrieval вместо `pack_context`; лимитируется число вызовов инструментов, максимальный размер файла для чтения и общий объём вывода инструментария.
- **Очередь задач**: все режимы можно запускать синхронно или в фоне; статус доступен по `task_id`.
- **Большие патчи**: для `fix`‑задач патчи больше 50k символов сохраняются на диск и возвращаются с метаданными для скачивания через отдельный эндпоинт.

## JS/TS индексатор

- Статические `import`/`export from`/`require` резолвятся и участвуют в графе.
- Динамические `import()`/`require()` с нелитеральным аргументом отмечаются как `kind=runtime_dynamic` и `spec=<dynamic>`, но не резолвятся, чтобы не создавать ложные рёбра.

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
- Запуск LLM‑задачи: `POST /api/tasks/{id}/run` с `target_path`, `prompt`, `mode` (опционально), `depth`, `dep_mode`, `apply_patch`, `agentic` и опциональными `agentic_*` (`max_calls`, `max_file_chars`, `max_total_tool_output_chars`, `temperature`).
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
- `CGRAPH_LLM_AGENTIC_RETRIEVAL` — включить agentic‑режим получения контекста (tool‑based retrieval) вместо `pack_context`.
- `CGRAPH_LLM_AGENTIC_MAX_CALLS` — лимит числа вызовов инструментов в agentic‑режиме.
- `CGRAPH_LLM_AGENTIC_MAX_TOTAL_TOOL_OUTPUT_CHARS` — лимит общего объёма вывода инструментов в agentic‑режиме.
- `CGRAPH_LLM_AGENTIC_MAX_FILE_CHARS` — лимит символов при чтении файла в agentic‑режиме.
- `CGRAPH_LLM_AGENTIC_TEMPERATURE` — температура для agentic‑режима (0..2).
- `CGRAPH_GO_BUILD_TAGS` — список build‑tag значений Go (через запятую или пробел) для фильтрации импорта/символов.
- `CGRAPH_GO_INCLUDE_UNEXPORTED_SYMBOLS` — включать неэкспортируемые Go‑символы в индексации.

При наличии одновременно `//go:build` и `// +build` используется приоритет `go:build`. Если выражение `go:build` не парсится, применяется fallback на `+build`. Если оба выражения валидны, но дают разный результат, индексатор безопасно считает контекст активным, чтобы избежать ложного исключения файла из индексации.

### Frontend

- `VITE_API_BASE_URL` — базовый URL API (по умолчанию `http://localhost:8000`).

## Локальные данные

- SQLite хранится в `~/.CGRAPH/cgraph.sqlite3` (можно переопределить `CGRAPH_DB_DIR`).
- Большие патчи сохраняются в `~/.CGRAPH/patches` и возвращаются по отдельному запросу, если превышен лимит 50k символов.

## Проверки (опционально)

- Backend: `pip install -r backend/requirements-dev.txt && ruff backend/app && mypy backend/app`.
- Frontend: `cd frontend && npm run lint`.
