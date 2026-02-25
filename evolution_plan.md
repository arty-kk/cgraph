# Evolution Plan

## 0. Baseline (from audit)
- Architecture map:
  - Backend entrypoint: FastAPI app с async lifecycle и middleware-цепочкой в `backend/app/main.py` (`lifespan`, `rate_limit`, `auth_guard`, `db_session_middleware`). Evidence: `backend/app/main.py:44-80#lifespan`, `backend/app/main.py:99-139#rate_limit`, `backend/app/main.py:106-139#auth_guard`, `backend/app/main.py:133-139#db_session_middleware`.
  - API layer: async endpoints (`projects`, `tasks`, `nodes`, `auth`, `orgs`) делегируют работу в service-layer через `request.state.db_session`. Evidence: `backend/app/api/projects.py:119-145#scan`, `backend/app/api/tasks.py:100-145#run_task`.
  - Async infrastructure: отдельные bounded-runtime для FS/CPU/external I/O и отдельный lifecycle Redis pool. Evidence: `backend/app/infra/fs_runtime.py:58-183#run_fs_io_async`, `backend/app/infra/cpu_runtime.py:70-192#run_cpu_io_async`, `backend/app/infra/external_io_runtime.py:47-113#run_openai_io_async`, `backend/app/infra/redis_client.py:14-37#init_redis_pool_async`.
  - Queue/worker: Celery worker lifecycle + async task bodies в `celery_tasks`, постановка в очередь через async boundary `task_queue`. Evidence: `backend/app/celery_tasks.py:41-131#_run_async_entrypoint`, `backend/app/services/task_queue.py:49-176#_AsyncTaskTransportClient.publish_async`.
  - Async DB contract: глобальный async engine + `AsyncSessionLocal` с pool-ограничениями из `Settings`. Evidence: `backend/app/async_db.py:20-30#async_engine`, `backend/app/config.py:150-159#Settings`.
- Critical flows:
  1. HTTP request -> middleware -> async DB session -> service call. Evidence: `backend/app/main.py:99-139#db_session_middleware`, `backend/app/api/projects.py:142-145#get_graph`.
  2. API run/scan/docs -> enqueue в очередь. Evidence: `backend/app/api/projects.py:119-139#scan`, `backend/app/api/tasks.py:100-145#run_task`, `backend/app/services/task_queue.py:147-176#_enqueue_with_error_mapping_async`.
  3. Worker task execution -> async business logic -> status persistence в БД. Evidence: `backend/app/celery_tasks.py:134-176#_set_job_status_async`.
  4. Scan pipeline -> FS runtime + CPU runtime + async DB updates. Evidence: `backend/app/scan.py:99-104#_run_scan_fs_batch`, `backend/app/scan.py:103-104#_run_scan_cpu_batch`.
  5. Graph metrics path -> async DB read/write + CPU offload. Evidence: `backend/app/graph.py:193-223#compute_graph_metrics_async`.
  6. Agentic tooling -> FS/CPU runtime wrappers + async DB checks. Evidence: `backend/app/llm/agentic/tools.py:909-979#_to_thread_fs_async`.
  7. Snapshot upload/download -> async S3 + bounded semaphores + FS runtime writes. Evidence: `backend/app/snapshots.py:20-21#_SNAPSHOT_S3_IO_SEMAPHORE`, `backend/app/snapshots.py:206-253#_download_snapshot_archive_from_s3`.
- Current pain points:
  - **P0** — Per-task event-loop creation в worker через `asyncio.run`. Evidence: `backend/app/celery_tasks.py:41-48#_run_async_entrypoint`.
  - **P0** — FS/CPU runtimes пересоздают executor при loop switch; это усиливается per-task loop pattern в worker. Evidence: `backend/app/infra/fs_runtime.py:80-105#_get_fs_runtime`, `backend/app/infra/cpu_runtime.py:92-117#_get_cpu_runtime`, `backend/app/celery_tasks.py:41-48#_run_async_entrypoint`.
  - **P1** — Async enqueue содержит sync fallback `celery_app.send_task(...)` для non-redis схемы. Evidence: `backend/app/services/task_queue.py:57-59#_AsyncTaskTransportClient.publish_async`.
  - **P1** — Redis client для enqueue создаётся/закрывается на каждую публикацию. Evidence: `backend/app/services/task_queue.py:89-93#_AsyncTaskTransportClient.publish_async`.
  - **P1** — Legacy API compatibility: deprecated `background` query + no-op `background_tasks.add_task(lambda: None)`. Evidence: `backend/app/api/projects.py:124-139#scan`, `backend/app/api/tasks.py:106-145#run_task`.
  - **P1** — Scan concurrency limits зашиты константами, не в `Settings`. Evidence: `backend/app/scan.py:72-92#get_scan_runtime`.
  - **P2** — Дублирован lifecycle-список startup/shutdown между API и worker. Evidence: `backend/app/main.py:46-75#lifespan`, `backend/app/celery_tasks.py:53-90#_startup_worker_resources_async`.
- Constraints:
  - Репозиторий уже закрепляет async-only контракт для cache/storage/task_queue lifecycle. Evidence: `backend/README.md:1-27`.
  - Есть контрактные тесты на lifecycle/async boundaries, миграция обязана их сохранить. Evidence: `backend/tests/services/test_celery_tasks_async_io.py:34-92#test_worker_process_init_and_shutdown_use_async_resource_lifecycle`, `backend/tests/services/test_runtime_asyncio_run_contract.py:27-39#test_runtime_modules_do_not_use_asyncio_run_outside_allowlist`.

## 1. North Star
- UX outcomes:
  - Стабильный enqueue latency в `/projects/{id}/scan` и `/tasks/{id}/run` под burst-нагрузкой за счёт неблокирующего producer path.
  - Предсказуемые ошибки enqueue (`timeout`/`broker_error`) без event-loop stalls.
- Domain outcomes:
  - Один async execution path для queue producer и worker runtime.
  - Явный lifecycle async-ресурсов (инициализация/закрытие pool/client/runtime в одном контракте).
- Engineering outcomes:
  - Снижение регрессий благодаря AST/contract-тестам на запрет возврата legacy sync fallback.
  - Упрощение API-контрактов за счёт удаления deprecated queue-compatible обвязки.

## 2. Roadmap (incremental)

### Phase 1 (Stabilize Core) - up to 10 highest-impact tasks (prioritize P0/P1)
- Goal
  - Убрать блокировки event loop и executor-churn в hottest queue/worker paths.
- Scope (what we touch / what we don’t)
  - Touch: `backend/app/celery_tasks.py`, `backend/app/services/task_queue.py`, runtime-модули `infra/fs_runtime.py`, `infra/cpu_runtime.py`, профильные tests.
  - Don’t touch: бизнес-алгоритмы scan/LLM, DB schema/alembic.
- Deliverables
  1. Persistent async runtime в worker (без per-task `asyncio.run`).
  2. Полностью async enqueue transport без sync fallback.
  3. Reused producer client вместо per-message connect/close.
  4. Concurrency/regression tests на burst enqueue и resource reuse.
- Dependencies
  - Существующие worker lifecycle hooks уже есть и пригодны для инициализации/остановки runtime. Evidence: `backend/app/celery_tasks.py:93-131#_on_worker_process_init`.
- Risk & Rollback strategy
  - Риск: некорректный shutdown persistent worker loop.
  - Rollback: revert runtime-runner commit и возврат к текущему bridge-пути.
- Validation (repo-native)
  - `python -m pytest backend/tests/services/test_celery_tasks_async_io.py -q`
  - `python -m pytest backend/tests/services/test_task_queue_async_io.py -q`
  - `python -m pytest backend/tests/services/test_task_queue_parallel_submit.py -q`

### Phase 2 (UX & Domain Consolidation) - up to 10 tasks
- Goal
  - Удалить legacy-обвязку и консолидировать async lifecycle/config для устойчивого поведения.
- Scope (what we touch / what we don’t)
  - Touch: API handlers `projects/tasks`, `scan`, `config`, lifecycle orchestration helper.
  - Don’t touch: доменные правила анализа, внешние provider integrations.
- Deliverables
  1. Удаление deprecated `background`-веток из queue-only API.
  2. Единый lifecycle orchestrator для API/worker.
  3. Конфигурируемые scan concurrency limits из `Settings`.
- Dependencies
  - Phase 1 (иначе legacy fallback остаётся нужен для стабильности).
- Risk & Rollback strategy
  - Риск: клиенты, которые всё ещё передают deprecated query params.
  - Rollback: revert endpoint-signature изменения в одном коммите.
- Validation (repo-native)
  - `python -m pytest backend/tests/services/test_scan_async_runtime.py -q`
  - `python -m pytest backend/tests/services/test_api_contracts.py -q`
  - `python -m pytest backend/tests/services/test_async_contract_guards.py -q`

### Phase 3 (Scale & Maintainability)- up to 10 tasks (only if it truly blocks progress)
- Goal
  - Зафиксировать эксплуатационную предсказуемость async-профиля под ростом concurrency.
- Scope (what we touch / what we don’t)
  - Touch: observability/perf-tests/docs.
  - Don’t touch: core domain logic.
- Deliverables
  1. Perf smoke checks на queue backpressure + DB pool saturation.
  2. Runtime metrics (queue depth, wait time, in-flight) в едином telemetry-потоке.
  3. Документированные concurrency profiles для dev/staging/prod.
- Dependencies
  - Завершённые Phase 1-2.
- Risk & Rollback strategy
  - Риск низкий (test/metrics/docs only).
  - Rollback: revert perf/telemetry-only commits.
- Validation
  - No validation commands found in repo.

## 3. Task Specs (atomic, single-strategy)

- ID: EVO-001
- Priority: P0
- Theme: Reliability
- Problem:
  - Worker использует `asyncio.run` как универсальный bridge для task entrypoint и startup/shutdown async-вызовов.
- Evidence:
  - `backend/app/celery_tasks.py:41-48#_run_async_entrypoint`
  - `backend/app/celery_tasks.py:179-180#scan_task`
- Root Cause
  - Сохранён sync-adapter pattern для Celery task function.
- Impact
  - Loop creation overhead + нестабильность shared runtime под высокой частотой задач.
- Fix (single solution)
  - Ввести один persistent event-loop runner на worker process и выполнять все async задачи через него.
- Steps
  1. Добавить `WorkerAsyncRuntime` (start/submit/stop).
  2. Перевести `_run_async_entrypoint` на submit в runner.
  3. Гарантировать runner shutdown из `worker_process_shutdown`.
  4. Обновить lifecycle tests.
- Acceptance Criteria (verifiable)
  - Нет per-task `asyncio.run` в execution path task body.
  - Последовательные задачи используют один worker runtime.
- Validation Commands (if visible in the project)
  - `python -m pytest backend/tests/services/test_celery_tasks_async_io.py -q`
- Migration/Rollback (if needed)
  - Revert runner commit.

- ID: EVO-002
- Priority: P1
- Theme: Performance
- Problem:
  - Async producer использует sync fallback `celery_app.send_task` для non-redis broker схем.
- Evidence:
  - `backend/app/services/task_queue.py:57-59#_AsyncTaskTransportClient.publish_async`
- Root Cause
  - Legacy multi-transport compatibility branch.
- Impact
  - Риск блокировки event loop на enqueue path.
- Fix (single solution)
  - Удалить sync fallback и оставить только async publish path.
- Steps
  1. Удалить non-redis sync ветку.
  2. Добавить deterministic error mapping для unsupported broker схем.
  3. Обновить async contract tests.
- Acceptance Criteria (verifiable)
  - Нет вызовов `celery_app.send_task` в async enqueue path.
  - Unsupported scheme возвращает `ExternalServiceError` c `enqueue_reason`.
- Validation Commands (if visible in the project)
  - `python -m pytest backend/tests/services/test_task_queue_async_io.py -q`
  - `python -m pytest backend/tests/services/test_task_queue_parallel_submit.py -q`
- Migration/Rollback (if needed)
  - Revert enqueue transport commit.

- ID: EVO-003
- Priority: P1
- Theme: Performance
- Problem:
  - На каждый enqueue создаётся новый redis client и сразу закрывается.
- Evidence:
  - `backend/app/services/task_queue.py:89-93#_AsyncTaskTransportClient.publish_async`
- Root Cause
  - Отсутствует lifecycle-managed producer runtime.
- Impact
  - Connection churn и дополнительная нагрузка на broker при burst enqueue.
- Fix (single solution)
  - Ввести producer redis client reuse с явным init/close lifecycle.
- Steps
  1. Добавить `init_task_producer_runtime_async`/`close_task_producer_runtime_async`.
  2. Использовать singleton client в `publish_async`.
  3. Подключить lifecycle в API и worker startup/shutdown.
- Acceptance Criteria (verifiable)
  - `publish_async` не вызывает per-message `Redis.from_url(...).aclose()`.
  - Producer client закрывается на shutdown.
- Validation Commands (if visible in the project)
  - `python -m pytest backend/tests/services/test_task_queue_async_io.py -q`
- Migration/Rollback (if needed)
  - Revert producer-runtime commit.

- ID: EVO-004
- Priority: P0
- Theme: Reliability
- Problem:
  - FS/CPU runtime пересоздают executors при loop switch.
- Evidence:
  - `backend/app/infra/fs_runtime.py:80-105#_get_fs_runtime`
  - `backend/app/infra/cpu_runtime.py:92-117#_get_cpu_runtime`
- Root Cause
  - Runtime state жёстко привязан к конкретному `asyncio` loop.
- Impact
  - Executor churn и падение throughput под конкурентной очередью.
- Fix (single solution)
  - Закрепить runtime на persistent worker loop (после EVO-001) и исключить loop-switch recreation в рабочем цикле.
- Steps
  1. Уточнить runtime invariants в code path worker.
  2. Добавить test/guard на отсутствие repeated executor recreation.
- Acceptance Criteria (verifiable)
  - На серии задач нет повторной инициализации/остановки executors.
- Validation Commands (if visible in the project)
  - `python -m pytest backend/tests/services/test_fs_runtime.py -q`
  - `python -m pytest backend/tests/services/test_cpu_runtime.py -q`
- Migration/Rollback (if needed)
  - Revert вместе с EVO-001.

- ID: EVO-005
- Priority: P1
- Theme: Reliability
- Problem:
  - Нет явного стресс-покрытия на burst enqueue + resource reuse.
- Evidence:
  - `backend/tests/services/test_celery_tasks_async_io.py:34-92#test_worker_process_init_and_shutdown_use_async_resource_lifecycle`.
- Root Cause
  - Текущие тесты проверяют порядок lifecycle шагов, но не нагрузочный режим.
- Impact
  - Регрессии latency/churn могут пройти незамеченными.
- Fix (single solution)
  - Добавить integration tests на burst submit и invariants reuse runtime resources.
- Steps
  1. Добавить параллельный enqueue stress-test.
  2. Зафиксировать проверки отсутствия per-call init/shutdown.
- Acceptance Criteria (verifiable)
  - Тест стабильно воспроизводит и блокирует возврат legacy поведения.
- Validation Commands (if visible in the project)
  - `python -m pytest backend/tests/services/test_task_queue_parallel_submit.py -q`
- Migration/Rollback (if needed)
  - N/A (test-only).

- ID: EVO-006
- Priority: P1
- Theme: Platform
- Problem:
  - Queue-only endpoints всё ещё содержат deprecated `background` параметры и no-op background task.
- Evidence:
  - `backend/app/api/projects.py:124-139#scan`
  - `backend/app/api/tasks.py:106-145#run_task`
- Root Cause
  - Legacy compatibility после перехода на queue-first.
- Impact
  - Избыточная сложность API-контракта и риск неправильного клиентского ожидания.
- Fix (single solution)
  - Удалить deprecated `background` параметр и no-op `BackgroundTasks` обвязку.
- Steps
  1. Упростить сигнатуры endpoint функций.
  2. Обновить API contract tests и frontend API typing.
- Acceptance Criteria (verifiable)
  - В queue endpoints отсутствует `background` compatibility path.
- Validation Commands (if visible in the project)
  - `python -m pytest backend/tests/services/test_api_contracts.py -q`
  - `npm --prefix frontend run test`
- Migration/Rollback (if needed)
  - Revert endpoint-signature commit.

- ID: EVO-007
- Priority: P2
- Theme: Platform
- Problem:
  - Startup/cleanup шаги ресурсов дублируются в API и worker entrypoints.
- Evidence:
  - `backend/app/main.py:46-75#lifespan`
  - `backend/app/celery_tasks.py:53-90#_startup_worker_resources_async`
- Root Cause
  - Нет централизованного lifecycle orchestrator.
- Impact
  - Drift/расхождение поведения при добавлении новых ресурсов.
- Fix (single solution)
  - Вынести lifecycle steps в общий orchestrator-модуль с role-aware конфигурацией.
- Steps
  1. Добавить `backend/app/infra/runtime_lifecycle.py`.
  2. Подключить orchestrator в `main.py` и `celery_tasks.py`.
  3. Адаптировать lifecycle tests.
- Acceptance Criteria (verifiable)
  - Startup/shutdown steps определены в одном месте.
- Validation Commands (if visible in the project)
  - `python -m pytest backend/tests/services/test_main_lifespan_redis.py -q`
  - `python -m pytest backend/tests/services/test_celery_tasks_async_io.py -q`
- Migration/Rollback (if needed)
  - Revert orchestrator extraction commit.

- ID: EVO-008
- Priority: P1
- Theme: Performance
- Problem:
  - Scan limits не параметризованы в `Settings`, зашиты константами.
- Evidence:
  - `backend/app/scan.py:72-92#get_scan_runtime`
- Root Cause
  - Константная конфигурация вместо environment-driven tuning.
- Impact
  - Нельзя гибко настраивать scan throughput/latency по окружениям.
- Fix (single solution)
  - Перенести scan limits в `Settings` с валидацией `>=1`.
- Steps
  1. Добавить settings-поля и validator checks.
  2. Прочитать значения в `get_scan_runtime`.
  3. Обновить тесты конфигурации/runtime.
- Acceptance Criteria (verifiable)
  - Scan runtime limits управляются env-переменными.
- Validation Commands (if visible in the project)
  - `python -m pytest backend/tests/services/test_scan_async_runtime.py -q`
  - `python -m pytest backend/tests/services/test_config_storage_runtime_limits.py -q`
- Migration/Rollback (if needed)
  - Revert config wiring commit.

- ID: EVO-009
- Priority: P1
- Theme: Reliability
- Problem:
  - Не хватает точечных guard-тестов на запрет возврата sync fallback/deprecated API path.
- Evidence:
  - `backend/tests/services/test_runtime_asyncio_run_contract.py:27-39#test_runtime_modules_do_not_use_asyncio_run_outside_allowlist`.
- Root Cause
  - Текущие AST-guards не покрывают все миграционные зоны.
- Impact
  - Регрессии async-only контракта могут попасть в main branch.
- Fix (single solution)
  - Добавить AST/contract tests на отсутствие `celery_app.send_task` и legacy `background` path.
- Steps
  1. Создать тесты в `backend/tests/services`.
  2. Включить их в существующий contract suite.
- Acceptance Criteria (verifiable)
  - Тест падает при возврате sync fallback/deprecated path.
- Validation Commands (if visible in the project)
  - `python -m pytest backend/tests/services/test_async_contract_guards.py -q`
- Migration/Rollback (if needed)
  - N/A (test-only).

- ID: EVO-010
- Priority: P2
- Theme: Platform
- Problem:
  - Нет формализованного perf baseline для queue backpressure/DB pool saturation.
- Evidence:
  - `backend/app/config.py:150-151#Settings` (default pool limits), `backend/app/async_db.py:20-27#async_engine`.
- Root Cause
  - Отсутствует выделенный perf regression harness.
- Impact
  - Деградации под высокой concurrency обнаруживаются поздно.
- Fix (single solution)
  - Добавить perf smoke-tests + telemetry thresholds на queue/DB wait.
- Steps
  1. Ввести saturation scenario для queue/DB.
  2. Зафиксировать threshold-based checks.
- Acceptance Criteria (verifiable)
  - Есть автоматическая проверка деградации под нагрузкой.
- Validation Commands (if visible in the project)
  - No validation commands found in repo.
- Migration/Rollback (if needed)
  - N/A.

## 4. Explicit Non-Goals
- Не менять доменную логику сканирования/анализа и LLM-решения в рамках этого evolution-плана.
- Не менять схему БД/Alembic migration в данной итерации.
- Не добавлять новые sync-fallback/adapters (наоборот, они подлежат удалению в миграционных задачах).
- Не делать широких рефакторингов вне hot paths queue/worker/runtime/lifecycle.
