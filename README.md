# StubGraph (local)

StubGraph — локальный сервис и веб‑интерфейс для исследования репозиториев. Приложение индексирует код, строит граф связей по файлам, позволяет искать узлы и запускать LLM‑задачи над выбранным файлом (с учетом контракта). Для LLM‑задач доступен agentic‑режим получения контекста (tool‑based retrieval), когда модель сама выбирает необходимые файлы через инструментарий. Интерфейс рассчитан на разработчиков, которым нужно быстро разобраться в структуре проекта, оценить связи и получить анализ/фиксы по конкретным файлам с учетом связей по контракту.

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

4. Запустите Celery worker (очереди `light`, `medium`, `heavy`):
   ```bash
   cd backend
   celery -A app.celery_app.celery_app worker -Q light,medium,heavy --loglevel=INFO
   ```

Перед запуском backend нужно выполнить миграции:
```bash
alembic -c backend/alembic.ini upgrade head
```

Backend поднимается на `http://localhost:8000` (эндпоинт здоровья: `/health`).
API доступен в двух вариантах: `/api/...` (без версии) и `/api/v1/...` (стабильная версия).

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
- PostgreSQL 16 (или совместимый сервис) для хранения данных.
- RabbitMQ (broker для Celery фоновых задач).
- 
## Production compose

Для прод‑окружения есть `docker-compose.prod.yml` (без открытых портов и с обязательными env‑переменными). Перед запуском задайте `STUBGRAPH_DATABASE_URL`, `STUBGRAPH_REDIS_URL`, `STUBGRAPH_CELERY_BROKER_URL`, `VITE_API_BASE_URL` и параметры Postgres (`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`).

## Как пользователи заходят в сервис

Если сервис доступен по домену, пользователь взаимодействует через UI, а доступ к API защищён авторизацией.

- Первый пользователь создаётся через bootstrap‑эндпоинт: `POST /api/v1/auth/bootstrap` с `email` и `password` (разрешён только если пользователей нет).
- Дальше пользователи регистрируются через `POST /api/v1/auth/register` (если регистрация включена).
- Для входа используется `POST /api/v1/auth/login`, ответ содержит `token`. Этот токен нужен для UI и API вызовов (`Authorization: Bearer <token>`).

Если авторизация отключена, сервис работает без логина, но для прод‑окружения рекомендуется держать `STUBGRAPH_AUTH_ENABLED=true`. По умолчанию в примере окружения авторизация выключена, чтобы UI работал без токенов в локальной разработке.

## Основные API‑сценарии

- Создание проекта из snapshot: `POST /api/v1/projects/from-snapshot` (multipart form: `name`, `archive` с `.zip` или `.tar/.tar.gz/.tgz`).
- Локальный `root_path` доступен только при `STUBGRAPH_ALLOW_LOCAL_ROOT_PATH=true` (для dev/self-hosted).
- Сканирование: `POST /api/v1/projects/{id}/scan` (можно `background=true`).
- Для корректного контекста LLM/impact нужен полный Scan: если в индексе меньше 2 узлов или нет рёбер, backend считает граф не готов и возвращает предупреждение `warning: "graph not built"` в ответах `run`/`runs/{run_id}`.
- Граф: `GET /api/v1/projects/{id}/graph` или локальный `GET /api/v1/projects/{id}/graph/local?path=...&hops=1&max_nodes=400`.
- Поиск: `GET /api/v1/projects/{id}/search?q=...`.
- Семантический поиск: `GET /api/v1/projects/{id}/search/semantic?q=...&limit=20&prefix=...` (требуются включённые эмбеддинги и `OPENAI_API_KEY`).
- Метаданные узла: `GET /api/v1/nodes/{id}/{path}/node`; контракт файла: `GET /api/v1/nodes/{id}/{path}/contract`.
- Запуск LLM‑задачи: `POST /api/v1/tasks/{id}/run` с `target_path`, `prompt`, `mode` (опционально), `profile` (опционально), `depth`, `dep_mode`, `apply_patch`, `agentic` и опциональными `agentic_*` (`max_calls`, `max_file_chars`, `max_total_tool_output_chars`, `temperature`, `reasoning_effort`). Для `mode=impact` доступны лимиты `impact_max_nodes` и `impact_max_depth`; в ответе добавляются поля `truncated`, `max_nodes`, `max_depth`.
- История запусков и патчи: `GET /api/v1/tasks/{id}/runs`, `GET /api/v1/tasks/{id}/runs/{run_id}`, `GET /api/v1/tasks/{id}/runs/{run_id}/patch`.
- Статус фоновой задачи: `GET /api/v1/tasks/status/{task_id}`.

### Organizations & RBAC (Этап 7)

- Список организаций пользователя: `GET /api/v1/orgs`.
- Создание организации: `POST /api/v1/orgs` с `name`.
- Информация об организации: `GET /api/v1/orgs/{org_id}`.
- Участники организации (требуются права `admin/owner`): `GET /api/v1/orgs/{org_id}/members`.
- Добавить/обновить участника (требуются `admin/owner`): `POST /api/v1/orgs/{org_id}/members` с `email`, `role`.
- Удалить участника (требуются `admin/owner`): `DELETE /api/v1/orgs/{org_id}/members/{user_id}`.

Для операций уровня организации используйте заголовок `X-Org-ID` (если у пользователя несколько организаций). Роли: `owner`, `admin`, `member`, `viewer`.

### Entitlements (Этап 9)

Entitlements на организацию хранятся в `orgentitlement` и задают доступ/лимиты по ключам:
- `llm_enabled` (bool) — доступ к LLM.
- `llm_daily_request_limit` (int) — дневной лимит LLM‑запросов.
- `embeddings_enabled` (bool) — доступ к embeddings/semantic.
- `embeddings_daily_chunk_limit` (int) — дневной лимит embedding‑чанков.
- `embeddings_daily_query_limit` (int) — дневной лимит semantic‑запросов.

## Переменные окружения

### Backend (`backend/app/config.py`)

- `OPENAI_API_KEY` — ключ для LLM‑функций.
- `STUBGRAPH_STORAGE_BACKEND` — хранилище артефактов: `local` или `s3`.
- `STUBGRAPH_S3_BUCKET` — bucket для S3‑хранилища (обязателен при `STUBGRAPH_STORAGE_BACKEND=s3`).
- `STUBGRAPH_S3_REGION` — регион S3 (опционально).
- `STUBGRAPH_S3_ENDPOINT_URL` — кастомный endpoint (например, MinIO).
- `STUBGRAPH_S3_ACCESS_KEY_ID`, `STUBGRAPH_S3_SECRET_ACCESS_KEY` — ключи доступа (если не используются IAM/роль).
- `STUBGRAPH_S3_PREFIX` — префикс ключей в бакете.
- `STUBGRAPH_S3_SIGNED_URL_TTL_SECONDS` — TTL signed URL для скачивания артефактов.
- `STUBGRAPH_PATCH_RETENTION_DAYS` — срок хранения больших патчей (в днях).
- `STUBGRAPH_SNAPSHOT_MAX_BYTES` — максимальный размер загружаемого snapshot‑архива (в байтах).
- `STUBGRAPH_SNAPSHOT_MAX_FILES` — лимит количества файлов при распаковке snapshot.
- `STUBGRAPH_SNAPSHOT_MAX_FILE_BYTES` — лимит размера одного файла при распаковке snapshot.
- `STUBGRAPH_SNAPSHOT_MAX_UNPACKED_BYTES` — лимит суммарного распакованного объёма snapshot.
- `STUBGRAPH_AUTH_ENABLED` — включить обязательную авторизацию для `/api` и `/api/v1`.
- `STUBGRAPH_AUTH_ALLOW_PUBLIC_SIGNUP` — разрешить публичную регистрацию.
- `STUBGRAPH_AUTH_PASSWORD_PEPPER` — pepper для хеширования паролей/токенов.
- `STUBGRAPH_AUTH_SESSION_TTL_HOURS` — TTL сессии в часах.
- `STUBGRAPH_AUTH_API_KEY_TTL_DAYS` — TTL API‑ключей в днях (если не задан, ключи бессрочные).
- `STUBGRAPH_REDIS_URL` — адрес Redis для кеша, rate limit и счётчиков.
- `STUBGRAPH_CACHE_ENABLED` — включить кеширование ответов поиска.
- `STUBGRAPH_CACHE_DEFAULT_TTL_SECONDS` — TTL кеша (в секундах).
- `STUBGRAPH_RATE_LIMIT_ENABLED` — включить rate limit по IP.
- `STUBGRAPH_RATE_LIMIT_REQUESTS_PER_MINUTE` — лимит запросов в минуту на IP.
- `STUBGRAPH_TASK_QUEUE_INFLIGHT_HEAVY_LIMIT` — лимит одновременных heavy задач (если не задан, лимита нет).
- `STUBGRAPH_CELERY_BROKER_URL` — строка подключения к RabbitMQ (например, `amqp://guest:guest@localhost:5672//`).
- `STUBGRAPH_CELERY_QUEUE_DEFAULT` — очередь по умолчанию (обычно `medium`).
- `STUBGRAPH_DATABASE_URL` — строка подключения Postgres (например, `postgresql+psycopg://user:pass@localhost:5432/stubgraph`).
- `STUBGRAPH_DB_DIR` — каталог для файлов патчей и локальных артефактов (по умолчанию `~/.StubGraph`).
- `STUBGRAPH_DEFAULT_DEPTH` — глубина обхода зависимостей (0..6).
- `STUBGRAPH_IMPACT_MAX_NODES` — лимит числа узлов в impact (если не задан, лимита нет).
- `STUBGRAPH_IMPACT_MAX_DEPTH` — лимит глубины impact (если не задан, лимита нет).
- `STUBGRAPH_CORS_ALLOW_ORIGINS` — разрешённые origin‑ы для фронтенда.
- `STUBGRAPH_MODEL_TRIAGE`, `STUBGRAPH_MODEL_ANALYSIS`, `STUBGRAPH_MODEL_PATCH` — модели для LLM‑режимов.
- `STUBGRAPH_OPENAI_TIMEOUT_SECONDS`, `STUBGRAPH_OPENAI_MAX_RETRIES` — таймаут и ретраи запросов к OpenAI.
- `STUBGRAPH_EMBEDDINGS_ENABLED` — включить генерацию embeddings при сканировании.
- `STUBGRAPH_EMBEDDINGS_MODEL` — модель embeddings.
- `STUBGRAPH_EMBEDDINGS_CHUNK_SIZE` — размер чанка для embeddings.
- `STUBGRAPH_EMBEDDINGS_CHUNK_OVERLAP` — overlap для embeddings.
- `STUBGRAPH_EMBEDDINGS_MAX_FILE_CHARS` — максимум символов файла для embeddings.
- `STUBGRAPH_EMBEDDINGS_SEARCH_MAX_CANDIDATES` — лимит кандидатов для семантического поиска.
- `STUBGRAPH_EMBEDDINGS_SEARCH_MAX_RESULTS` — лимит результатов семантического поиска.
- `STUBGRAPH_EMBEDDINGS_DAILY_CHUNK_LIMIT` — дневной лимит количества embedding‑чанков на организацию (если не задан, лимит отсутствует).
- `STUBGRAPH_EMBEDDINGS_DAILY_QUERY_LIMIT` — дневной лимит запросов семантического поиска на организацию (если не задан, лимит отсутствует).
- `STUBGRAPH_LLM_DAILY_REQUEST_LIMIT` — дневной лимит LLM‑запросов на организацию (если не задан, лимит отсутствует).
- `STUBGRAPH_LLM_AGENTIC_RETRIEVAL` — включить agentic‑режим получения контекста (tool‑based retrieval) вместо `pack_context`.
- `STUBGRAPH_LLM_AGENTIC_MAX_CALLS` — лимит числа вызовов инструментов в agentic‑режиме.
- `STUBGRAPH_LLM_AGENTIC_MAX_TOTAL_TOOL_OUTPUT_CHARS` — лимит общего объёма вывода инструментов в agentic‑режиме.
- `STUBGRAPH_LLM_AGENTIC_MAX_FILE_CHARS` — лимит символов при чтении файла в agentic‑режиме.
- `STUBGRAPH_LLM_AGENTIC_TEMPERATURE` — температура для agentic‑режима (0..2).
- `STUBGRAPH_LLM_AGENTIC_TRACE_ENABLED` — включает выдачу `tool_trace` в `retrieval_settings` agentic‑ответов (по умолчанию включено).
- В agentic‑режиме фактические лимиты могут динамически увеличиваться (в пределах серверных caps), учитывая глубину (`depth`), `mode`, длину промпта и размер проекта (количество `FileNode`). Итоговые значения возвращаются в `retrieval_settings` ответа.
- В `retrieval_settings.agentic.budget_reason` возвращается список активных факторов бюджета: `depth`, `prompt_size`, `project_size`, `mode` (и `self_check_retry`, если был повтор).
- `retrieval_settings.agentic.temperature` и `reasoning_effort` вычисляются из базовых значений с учётом `complexity_coeff` (ступенчатое повышение, capped серверными лимитами): `temperature` +0.05/+0.1/+0.15 при `complexity_coeff` ≥1.25/1.5/1.75, `reasoning_effort` повышается на 1 ступень при ≥1.3 и на 2 ступени при ≥1.6.
- При `self_check_retry=true` лимиты повышаются: `max_calls` ×1.5, `max_total_tool_output_chars` ×1.5, `max_file_chars` ×1.25, `temperature` +0.05 и `reasoning_effort` +1 ступень (все значения остаются в рамках server caps).

### LLM‑профили (agentic/pack)

Доступные профили: `surgical`, `architect`, `incident`. Если поле `profile` не передано, используется `architect`.

Профиль задаётся через `profile` в `POST /api/tasks/{id}/run`. Для agentic‑режима профиль определяет базовые лимиты (`max_calls`, `max_total_tool_output_chars`, `max_file_chars`) и `temperature`. Для pack‑режима влияет на `depth` и `SYSTEM_INSTRUCTIONS`. Явные `agentic_*` в запросе всегда имеют приоритет над значениями профиля.

| Профиль | Назначение | Instructions (суть) | Temperature | Max calls | Max total tool output chars | Max file chars | Depth (min..max, default) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `architect` | Основной режим | Используются текущие `SYSTEM_INSTRUCTIONS` сервера | По умолчанию из `STUBGRAPH_LLM_AGENTIC_TEMPERATURE` | По умолчанию из `STUBGRAPH_LLM_AGENTIC_MAX_CALLS` | По умолчанию из `STUBGRAPH_LLM_AGENTIC_MAX_TOTAL_TOOL_OUTPUT_CHARS` | По умолчанию из `STUBGRAPH_LLM_AGENTIC_MAX_FILE_CHARS` | 0..6, default из `STUBGRAPH_DEFAULT_DEPTH` |
| `surgical` | Минимальные точечные изменения | Хирургический режим: минимальный радиус правок | `0.0` | `12` | `60000` | `8000` | 0..2, default `1` |
| `incident` | Быстрый отклик на инциденты | Быстрое восстановление с безопасными правками | `0.2` | `40` | `140000` | `16000` | 0..4, default `2` |
- `STUBGRAPH_GO_BUILD_TAGS` — список build‑tag значений Go (через запятую или пробел) для фильтрации импорта/символов.
- `GOFLAGS` — стандартные Go‑флаги; поддержка `-tags` и `-tags=` влияет на набор build‑tag при индексации Go‑файлов (можно дополнить через `STUBGRAPH_GO_BUILD_TAGS`).
- `STUBGRAPH_GO_INCLUDE_UNEXPORTED_SYMBOLS` — включать неэкспортируемые Go‑символы в индексации.

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

Если `STUBGRAPH_LLM_AGENTIC_TRACE_ENABLED=true`, в `retrieval_settings.agentic.tool_trace` возвращается список объектов со следующими полями: `name`, `args`, `reason`, `duration_ms`, `cache_hit`, `response_chars`, `response_bytes`, `status`, `error_code`, `error_message`, а также `truncated_due_to_budget` при усечении.

В agentic‑режиме доступен инструмент `search_tests`, который ищет тестовые файлы по стандартным паттернам (`tests/`, `__tests__/`, `*.spec.*`, `*.test.*`, `test_*.py`, `*_test.*`) и возвращает пути с метаданными узлов (язык, fan‑in/fan‑out) согласно реализации в backend.

### Frontend

- `VITE_API_BASE_URL` — базовый URL API (по умолчанию `http://localhost:8000`).

## Локальные данные

- Postgres используется как основная БД (строка подключения задаётся через `STUBGRAPH_DATABASE_URL`).
- Большие патчи сохраняются в object storage (S3) или локально. При использовании S3 в `patch_unified_diff_meta` возвращается `download_url`, а при локальном хранении файлы лежат в `~/.StubGraph/patches`.

## Ручная проверка

- Включить Semantic search без `OPENAI_API_KEY` → увидеть авто‑fallback на обычный поиск и информационное уведомление.
- Запустить agentic‑задачу с промптом, который требует внешнего контекста, и проверить, что в `retrieval_settings.agentic` появились `self_check_ok`, `self_check_notes`, `self_check_missing_context`, а при непустом `self_check_missing_context` выполняется один дополнительный заход модели с увеличенными лимитами (флаг `self_check_retry=true`).

## Проверки (опционально)

- Backend: `pip install -r backend/requirements-dev.txt && ruff backend/app && mypy backend/app`.
- Frontend: `cd frontend && npm run lint`.
