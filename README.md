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

Пример ответа для режима `fix` (с непустым `tests`):

```json
{
  "diagnosis": "Причина ошибки в обработке пустого списка.",
  "plan": ["Обновить схему валидации.", "Уточнить инструкцию для модели."],
  "patch_unified_diff": "*** Begin Patch\n*** Update File: backend/app/llm/schemas.py\n@@\n-      \"tests\": {\"type\": \"array\", \"items\": {\"type\": \"string\"}},\n+      \"tests\": {\"type\": \"array\", \"items\": {\"type\": \"string\"}, \"minItems\": 1},\n*** End Patch\n",
  "tests": ["Запустить unit-тесты backend/llm", "Проверить, что пустой список tests отклоняется схемой."],
  "notes": "Проверки обязательны даже при малых изменениях."
}
```

## JS/TS индексатор

- Статические `import`/`export from`/`require` резолвятся и участвуют в графе.
- Динамические `import()`/`require()` с нелитеральным аргументом отмечаются как `kind=runtime_dynamic` и `spec=<dynamic>`, но не резолвятся, чтобы не создавать ложные рёбра.

## PHP индексатор

- `include`/`require` с строковым литералом (`'path.php'`, `"path.php"`).
- Конкатенация строковых литералов с базой `__DIR__`, `dirname(__FILE__)`, `dirname(__DIR__)` (например, `include __DIR__ . '/file.php'`).
- `realpath(...)` вокруг таких конкатенаций (например, `require realpath(__DIR__ . '/../vendor/autoload.php')`).
- Динамические `include`/`require` с аргументом, который не является строковым литералом или не сводится к конкатенации строк, отмечаются как `kind=include_dynamic` и `spec=<dynamic>` без резолва пути.

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
- Для корректного контекста LLM/impact нужен полный Scan: если в индексе меньше 2 узлов или нет рёбер, backend считает граф не готов и возвращает предупреждение `warning: "graph not built"` в ответах `run`/`runs/{run_id}`.
- Граф: `GET /api/projects/{id}/graph` или локальный `GET /api/projects/{id}/graph/local?path=...&hops=1&max_nodes=400`.
- Поиск: `GET /api/projects/{id}/search?q=...`.
- Семантический поиск: `GET /api/projects/{id}/search/semantic?q=...&limit=20&prefix=...` (требуются включённые эмбеддинги и `OPENAI_API_KEY`).
- Метаданные узла: `GET /api/nodes/{id}/{path}/node`; контракт файла: `GET /api/nodes/{id}/{path}/contract`.
- Запуск LLM‑задачи: `POST /api/tasks/{id}/run` с `target_path`, `prompt`, `mode` (опционально), `profile` (опционально), `depth`, `dep_mode`, `apply_patch`, `agentic` и опциональными `agentic_*` (`max_calls`, `max_file_chars`, `max_total_tool_output_chars`, `temperature`, `reasoning_effort`). Для `mode=impact` доступны лимиты `impact_max_nodes` и `impact_max_depth`; в ответе добавляются поля `truncated`, `max_nodes`, `max_depth`.
- История запусков и патчи: `GET /api/tasks/{id}/runs`, `GET /api/tasks/{id}/runs/{run_id}`, `GET /api/tasks/{id}/runs/{run_id}/patch`.
- Статус фоновой задачи: `GET /api/tasks/status/{task_id}`.

## Переменные окружения

### Backend (`backend/app/config.py`)

- `OPENAI_API_KEY` — ключ для LLM‑функций.
- `CGRAPH_DB_DIR` — каталог для SQLite и файлов патчей (по умолчанию `~/.CGRAPH`).
- `CGRAPH_DEFAULT_DEPTH` — глубина обхода зависимостей (0..6).
- `CGRAPH_IMPACT_MAX_NODES` — лимит числа узлов в impact (если не задан, лимита нет).
- `CGRAPH_IMPACT_MAX_DEPTH` — лимит глубины impact (если не задан, лимита нет).
- `CGRAPH_CORS_ALLOW_ORIGINS` — разрешённые origin‑ы для фронтенда.
- `CGRAPH_MODEL_TRIAGE`, `CGRAPH_MODEL_ANALYSIS`, `CGRAPH_MODEL_PATCH` — модели для LLM‑режимов.
- `CGRAPH_OPENAI_TIMEOUT_SECONDS`, `CGRAPH_OPENAI_MAX_RETRIES` — таймаут и ретраи запросов к OpenAI.
- `CGRAPH_LLM_AGENTIC_RETRIEVAL` — включить agentic‑режим получения контекста (tool‑based retrieval) вместо `pack_context`.
- `CGRAPH_LLM_AGENTIC_MAX_CALLS` — лимит числа вызовов инструментов в agentic‑режиме.
- `CGRAPH_LLM_AGENTIC_MAX_TOTAL_TOOL_OUTPUT_CHARS` — лимит общего объёма вывода инструментов в agentic‑режиме.
- `CGRAPH_LLM_AGENTIC_MAX_FILE_CHARS` — лимит символов при чтении файла в agentic‑режиме.
- `CGRAPH_LLM_AGENTIC_TEMPERATURE` — температура для agentic‑режима (0..2).
- `CGRAPH_LLM_AGENTIC_TRACE_ENABLED` — включает выдачу `tool_trace` в `retrieval_settings` agentic‑ответов (по умолчанию включено).
- В agentic‑режиме фактические лимиты могут динамически увеличиваться (в пределах серверных caps), учитывая глубину (`depth`), `mode`, длину промпта и размер проекта (количество `FileNode`). Итоговые значения возвращаются в `retrieval_settings` ответа.
- В `retrieval_settings.agentic.budget_reason` возвращается список активных факторов бюджета: `depth`, `prompt_size`, `project_size`, `mode` (и `self_check_retry`, если был повтор).
- `retrieval_settings.agentic.temperature` и `reasoning_effort` вычисляются из базовых значений с учётом `complexity_coeff` (ступенчатое повышение, capped серверными лимитами): `temperature` +0.05/+0.1/+0.15 при `complexity_coeff` ≥1.25/1.5/1.75, `reasoning_effort` повышается на 1 ступень при ≥1.3 и на 2 ступени при ≥1.6.
- При `self_check_retry=true` лимиты повышаются: `max_calls` ×1.5, `max_total_tool_output_chars` ×1.5, `max_file_chars` ×1.25, `temperature` +0.05 и `reasoning_effort` +1 ступень (все значения остаются в рамках server caps).

### LLM‑профили (agentic/pack)

Доступные профили: `surgical`, `architect`, `incident`. Если поле `profile` не передано, используется `architect`.

Профиль задаётся через `profile` в `POST /api/tasks/{id}/run`. Для agentic‑режима профиль определяет базовые лимиты (`max_calls`, `max_total_tool_output_chars`, `max_file_chars`) и `temperature`. Для pack‑режима влияет на `depth` и `SYSTEM_INSTRUCTIONS`. Явные `agentic_*` в запросе всегда имеют приоритет над значениями профиля.

| Профиль | Назначение | Instructions (суть) | Temperature | Max calls | Max total tool output chars | Max file chars | Depth (min..max, default) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `architect` | Основной режим | Используются текущие `SYSTEM_INSTRUCTIONS` сервера | По умолчанию из `CGRAPH_LLM_AGENTIC_TEMPERATURE` | По умолчанию из `CGRAPH_LLM_AGENTIC_MAX_CALLS` | По умолчанию из `CGRAPH_LLM_AGENTIC_MAX_TOTAL_TOOL_OUTPUT_CHARS` | По умолчанию из `CGRAPH_LLM_AGENTIC_MAX_FILE_CHARS` | 0..6, default из `CGRAPH_DEFAULT_DEPTH` |
| `surgical` | Минимальные точечные изменения | Хирургический режим: минимальный радиус правок | `0.0` | `12` | `60000` | `8000` | 0..2, default `1` |
| `incident` | Быстрый отклик на инциденты | Быстрое восстановление с безопасными правками | `0.2` | `40` | `140000` | `16000` | 0..4, default `2` |
- `CGRAPH_GO_BUILD_TAGS` — список build‑tag значений Go (через запятую или пробел) для фильтрации импорта/символов.
- `GOFLAGS` — стандартные Go‑флаги; поддержка `-tags` и `-tags=` влияет на набор build‑tag при индексации Go‑файлов (можно дополнить через `CGRAPH_GO_BUILD_TAGS`).
- `CGRAPH_GO_INCLUDE_UNEXPORTED_SYMBOLS` — включать неэкспортируемые Go‑символы в индексации.

При наличии одновременно `//go:build` и `// +build` используется приоритет `go:build`. Если выражение `go:build` не парсится, применяется fallback на `+build`. Если оба выражения валидны, но дают разный результат, индексатор безопасно считает контекст активным, чтобы избежать ложного исключения файла из индексации.

### Agentic‑режим: контракт ответа инструмента

Каждый tool‑вызов возвращает единый формат:

```json
{"ok": true, "data": {"path": "...", "content": "..."}, "error": null}
```

или при ошибке:

```json
{"ok": false, "data": null, "error": {"code": "bad_args", "message": "path is required", "details": {"path": "..."}}}
```

Поля `error.code` и `error.message` обязательны; `details` опционально.

В agentic‑режиме `retrieval_settings.agentic.retrieval_plan` содержит план извлечения контекста, зафиксированный через инструмент `plan_retrieval`.

Если `CGRAPH_LLM_AGENTIC_TRACE_ENABLED=true`, в `retrieval_settings.agentic.tool_trace` возвращается список объектов со следующими полями: `name`, `args`, `reason`, `duration_ms`, `cache_hit`, `response_chars`, `response_bytes`, `status`, `error_code`, `error_message`, а также `truncated_due_to_budget` при усечении.

В agentic‑режиме доступен инструмент `search_tests`, который ищет тестовые файлы по стандартным паттернам (`tests/`, `__tests__/`, `*.spec.*`, `*.test.*`, `test_*.py`, `*_test.*`) и возвращает пути с метаданными узлов (язык, fan‑in/fan‑out) согласно реализации в backend.

### Frontend

- `VITE_API_BASE_URL` — базовый URL API (по умолчанию `http://localhost:8000`).

## Локальные данные

- SQLite хранится в `~/.CGRAPH/cgraph.sqlite3` (можно переопределить `CGRAPH_DB_DIR`).
- Большие патчи сохраняются в `~/.CGRAPH/patches` и возвращаются по отдельному запросу, если превышен лимит 50k символов.

## Ручная проверка

- Включить Semantic search без `OPENAI_API_KEY` → увидеть авто‑fallback на обычный поиск и информационное уведомление.
- Запустить agentic‑задачу с промптом, который требует внешнего контекста, и проверить, что в `retrieval_settings.agentic` появились `self_check_ok`, `self_check_notes`, `self_check_missing_context`, а при непустом `self_check_missing_context` выполняется один дополнительный заход модели с увеличенными лимитами (флаг `self_check_retry=true`).

## Проверки (опционально)

- Backend: `pip install -r backend/requirements-dev.txt && ruff backend/app && mypy backend/app`.
- Frontend: `cd frontend && npm run lint`.
