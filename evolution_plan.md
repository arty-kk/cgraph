# Evolution Plan

## 0. Baseline (from audit)
- Architecture map:
  - Backend: FastAPI app with lifecycle startup/shutdown, auth + rate-limit middleware, task routes under `/api` and `/api/v1`, and async queue submission for background runs. Evidence: `backend/app/main.py:25-49#lifespan`, `backend/app/main.py:70-100#auth_guard`, `backend/app/api/tasks.py:99-179#run_task`, `backend/app/services/task_service.py:2170-2176#enqueue_run_task_async`, `backend/app/services/task_queue.py:457-498#submit_run_async`.
  - LLM pipeline: optional triage (`mode=None`) -> runtime policy/routing -> planning call -> execution (agentic or pack) with stage telemetry persisted into `AnalysisStageTelemetry`. Evidence: `backend/app/services/task_service.py:993-1069#_run_task_impl_async`, `backend/app/services/task_service.py:1328-1368#_run_task_impl_async`, `backend/app/services/task_service.py:1429-1560#_run_task_impl_async`, `backend/app/models.py:183-223#AnalysisRun`.
  - Frontend: `useStubGraphApp` orchestrates run/scan/docs, tracks task statuses, and currently waits for run completion inside the primary run action. Evidence: `frontend/src/ui/useStubGraphApp.ts:2285-2313#useStubGraphApp`, `frontend/src/api/tasks.ts:33-75#waitForTaskResult`, `frontend/src/ui/useStubGraphApp.ts:757-817#useStubGraphApp`.
- Critical flows: 
  1. Run submit -> queue -> status polling. Evidence: `backend/app/api/tasks.py:99-179#run_task`, `backend/app/services/task_queue.py:457-498#submit_run_async`, `frontend/src/api/tasks.ts:28-75#getTaskStatus`.
  2. Auto-triage when mode is omitted. Evidence: `backend/app/services/task_service.py:993-1050#_run_task_impl_async`, `backend/app/llm/orchestrator.py:202-226#triage_with_usage_async`.
  3. Planning (`plan_task_with_usage_async`) before execution path. Evidence: `backend/app/services/task_service.py:1328-1368#_run_task_impl_async`, `backend/app/llm/orchestrator.py:286-319#plan_task_with_usage_async`.
  4. Agentic retrieval + retry loop + evidence metadata. Evidence: `backend/app/services/task_service.py:1469-1760#_run_task_impl_async`.
  5. Run history read model (`list_runs`, `get_run`). Evidence: `backend/app/services/task_service.py:2185-2247#list_runs_async`.
  6. Heavy queue inflight guard and global limit. Evidence: `backend/app/config.py:135-137#Settings`, `backend/app/services/task_queue.py:343-395#_guard_inflight_async`.
- Current pain points:
  - **P1 (UX/throughput):** primary run UX blocks on `waitForTaskResult`, and UI disables actions while busy. Evidence: `frontend/src/ui/useStubGraphApp.ts:2285-2313#useStubGraphApp`, `frontend/src/api/tasks.ts:33-75#waitForTaskResult`, `frontend/src/ui/App.tsx:169-175#App`.
  - **P1 (domain continuity):** no explicit task-thread/session entity; runs are flat records. Evidence: `backend/app/models.py:183-203#AnalysisRun`, `backend/app/services/task_service.py:2185-2212#list_runs_async`.
  - **P1 (clarification gap):** triage contract has no explicit clarification branch/questions, and execution proceeds directly after triage/planning. Evidence: `backend/app/llm/schemas.py:78-94#TRIAGE_SCHEMA`, `backend/app/services/task_service.py:993-1050#_run_task_impl_async`, `backend/app/services/task_service.py:1429-1560#_run_task_impl_async`.
  - **P2 (cost governance default):** stage policy exists, but default triage/analysis/patch models are identical (`gpt-5-nano`). Evidence: `backend/app/config.py:192-194#Settings`, `backend/app/llm/policy.py:12-20#ModelPolicy`.
  - **P2 (tariff concurrency):** concurrency limit is global env value; entitlement service is available but not wired into queue guard. Evidence: `backend/app/config.py:135-137#Settings`, `backend/app/services/task_queue.py:351-395#_guard_inflight_async`, `backend/app/services/entitlements_service.py:10-30#get_entitlement_int_async`.
- Constraints:
  - Runtime contracts are explicitly async-only for cache/storage/queue boundaries. Evidence: `backend/README.md:1-29`.
  - Existing task API contracts are already consumed by frontend client calls and should stay backward compatible. Evidence: `backend/app/api/tasks.py:99-179#run_task`, `frontend/src/api/tasks.ts:77-109#runTask`.

## 1. North Star
- UX outcomes:
  - Run request becomes non-blocking in primary UI flow (enqueue + track), so user can continue work immediately.
  - Ambiguous prompts produce a deterministic clarification response before expensive execution.
  - Proxy metrics (until dedicated analytics is added):
    - `% run requests that return immediately with background tracking`.
    - `% ambiguous prompts routed to clarification before execution`.
- Domain outcomes:
  - Introduce one source of truth for task continuity (`task_session`) and attach runs to it.
  - Make stage transitions (`triage`, `plan`, `clarification`, `execution`) explicit in persisted run/session state.
- Engineering outcomes:
  - Reduce regression risk via contract tests for clarification branch and session continuity.
  - Enforce explicit stage-model tier config to control cost/latency profile.

## 2. Roadmap (incremental)
### Phase 1 (Stabilize Core) - up to 10 highest-impact tasks (prioritize P0/P1)
- Goal
  - Introduce durable task continuity and remove blocking run UX.
- Scope (what we touch / what we don’t)
  - Touch: task-session schema/API, run submit/read paths, frontend run interaction model.
  - Don’t touch: scan/indexing internals and patch-apply engine logic.
- Deliverables (concrete changes)
  1. Add `task_session` table and link `analysisrun` to `task_session_id`.
  2. Extend run submit API with optional `session_id` (auto-create when missing).
  3. Frontend: enqueue run without awaiting full result in primary action; keep status tracking panel as source of truth.
  4. Add per-org concurrent heavy-run enforcement using entitlement with global fallback.
- Dependencies
  - DB migration before API changes; API changes before frontend adoption.
- Risk & Rollback strategy (if migration/contract changes are required)
  - Additive migration and additive API field; rollback by ignoring `session_id` path and keeping legacy behavior.
- Validation (how to verify: tests/linter/commands from the repo)
  - `npm --prefix frontend run lint`
  - `npm --prefix frontend run test`
  - `npm --prefix frontend run build`

### Phase 2 (UX & Domain Consolidation) - up to 10 tasks
- Goal
  - Add explicit clarification stage and deterministic resume flow.
- Scope (what we touch / what we don’t)
  - Touch: triage schema, task service stage branching, frontend clarification UX.
  - Don’t touch: route scanning/indexing contracts.
- Deliverables (concrete changes)
  1. Extend triage contract with `clarification_required` and `clarification_questions`.
  2. Persist `needs_clarification` state and prevent execution until clarification is resolved.
  3. Add resume endpoint/flow that continues the same `session_id`.
  4. Add tests for `triage -> clarification -> resume -> execution` chain.
- Dependencies
  - Phase 1 task-session persistence.
- Risk & Rollback strategy (if migration/contract changes are required)
  - Feature-flag new clarification branch; rollback by disabling the flag and preserving current triage path.
- Validation (how to verify: tests/linter/commands from the repo)
  - `npm --prefix frontend run lint`
  - `npm --prefix frontend run test`

### Phase 3 (Scale & Maintainability)- up to 10 tasks (only if it truly blocks progress)
- Goal
  - Make model-tier and concurrency policies predictable per deployment/tariff.
- Scope (what we touch / what we don’t)
  - Touch: startup config validation, entitlement wiring, queue admission telemetry.
  - Don’t touch: provider SDK abstraction shape.
- Deliverables (concrete changes)
  1. Add strict startup validation for stage model-tier configuration.
  2. Bind heavy queue inflight limit to org entitlement (`task_queue_inflight_heavy_limit`) with global fallback.
  3. Persist queue admission telemetry (`effective_limit`, `limit_source`, rejection reason).
- Dependencies
  - Phase 1 entitlement-based queue gating path.
- Risk & Rollback strategy (if migration/contract changes are required)
  - Strict checks behind feature flag; rollback by disabling strict mode.
- Validation (how to verify: tests/linter/commands from the repo)
  - `npm --prefix frontend run lint`
  - `npm --prefix frontend run test`

## 3. Task Specs (atomic, single-strategy)
- ID: EVO-001
- Priority: P1
- Theme: Domain
- Problem:
  - Нет сущности task session/thread для сохранения непрерывности пользовательской задачи.
- Evidence: `backend/app/models.py:183-203#AnalysisRun`, `backend/app/services/task_service.py:2185-2212#list_runs_async`.
- Root Cause
  - Модель хранения построена вокруг независимых `AnalysisRun`, без группирующего контекста.
- Impact
  - Нельзя надёжно вести долгоживущую задачу с уточнениями и повторными итерациями в одном треде.
- Fix (single solution)
  - Ввести таблицу `TaskSession` и FK `AnalysisRun.task_session_id`.
- Steps
  1. Добавить миграцию таблицы `task_session` + индексы.
  2. Добавить `task_session_id` в `analysisrun` и сервисный слой сериализации.
  3. Обновить API run submit/list/get для работы с `session_id`.
- Acceptance Criteria (verifiable)
  - Каждый новый run имеет `session_id`.
  - `list_runs` поддерживает фильтр по `session_id` без поломки текущего default поведения.
- Validation Commands (if visible in the project)
  - No validation commands found in repo.
- Migration/Rollback (if needed)
  - Аддитивная миграция; rollback — оставить nullable колонку и не использовать её в API.

- ID: EVO-002
- Priority: P1
- Theme: UX
- Problem:
  - Основной run-flow блокирует пользователя ожиданием результата.
- Evidence: `frontend/src/ui/useStubGraphApp.ts:2285-2313#useStubGraphApp`, `frontend/src/api/tasks.ts:33-75#waitForTaskResult`, `frontend/src/ui/App.tsx:169-175#App`.
- Root Cause
  - Первичный UI-action реализован как синхронный сценарий поверх async API задач.
- Impact
  - Нельзя эффективно запускать несколько независимых задач в фоне в рамках одной рабочей сессии.
- Fix (single solution)
  - Перевести primary run action в fire-and-track (enqueue + статусная панель), без блокирующего `waitForTaskResult`.
- Steps
  1. Изменить `onRun` так, чтобы action завершался сразу после enqueue.
  2. Оставить загрузку результата через существующий task status и history.
  3. Добавить явный обработчик открытия результата после завершения фоновой задачи.
- Acceptance Criteria (verifiable)
  - После нажатия Run UI не блокирует запуск других действий.
  - Завершённый результат доступен через status/history.
- Validation Commands (if visible in the project)
  - `npm --prefix frontend run lint`
  - `npm --prefix frontend run test`
  - `npm --prefix frontend run build`
- Migration/Rollback (if needed)
  - Rollback через feature flag с возвратом прежнего await-режима.

- ID: EVO-003
- Priority: P1
- Theme: Reliability
- Problem:
  - Нет формализованного этапа уточнения запроса перед дорогим анализом/правками.
- Evidence: `backend/app/llm/schemas.py:78-94#TRIAGE_SCHEMA`, `backend/app/services/task_service.py:993-1050#_run_task_impl_async`, `backend/app/services/task_service.py:1429-1560#_run_task_impl_async`.
- Root Cause
  - Контракт triage ограничен выбором mode/depth/dep_mode и не хранит уточняющие вопросы.
- Impact
  - Повышенный риск нерелевантных запусков и повторных прогонов при неясном запросе.
- Fix (single solution)
  - Добавить в triage обязательный clarification-контракт и ветку раннего выхода `needs_clarification`.
- Steps
  1. Расширить `TRIAGE_SCHEMA` полями clarification.
  2. Добавить ветку раннего возврата в `task_service` до execution stage.
  3. Сохранять clarification payload в session/run для последующего resume.
- Acceptance Criteria (verifiable)
  - При `clarification_required=true` execution не запускается.
  - После уточнения run продолжается в рамках того же `session_id`.
- Validation Commands (if visible in the project)
  - No validation commands found in repo.
- Migration/Rollback (if needed)
  - Feature flag для уточняющей ветки; rollback отключает flag.

- ID: EVO-004
- Priority: P2
- Theme: Platform
- Problem:
  - Дефолтные stage-модели одинаковые, что не даёт гарантированного cheap->expensive профиля из коробки.
- Evidence: `backend/app/config.py:192-194#Settings`, `backend/app/llm/policy.py:12-20#ModelPolicy`.
- Root Cause
  - Routing-policy поддерживает stage split, но стартовая конфигурация не принуждает tier separation.
- Impact
  - Непредсказуемый cost/latency профиль без ручной настройки окружения.
- Fix (single solution)
  - Ввести strict startup validator для stage-model tiers.
- Steps
  1. Проверять валидность pools и обязательность stage-split в strict-режиме.
  2. Падать на старте при невалидной tier конфигурации.
  3. Документировать env-настройки routing tiers.
- Acceptance Criteria (verifiable)
  - В strict режиме сервер не стартует при невалидной tier-конфигурации.
  - При валидной конфигурации старт проходит успешно.
- Validation Commands (if visible in the project)
  - No validation commands found in repo.
- Migration/Rollback (if needed)
  - Strict проверка включается флагом; rollback — отключить флаг.

- ID: EVO-005
- Priority: P2
- Theme: Platform
- Problem:
  - Ограничение по heavy background задачам глобальное, не per-org/per-tariff.
- Evidence: `backend/app/config.py:135-137#Settings`, `backend/app/services/task_queue.py:351-395#_guard_inflight_async`, `backend/app/services/entitlements_service.py:10-30#get_entitlement_int_async`.
- Root Cause
  - Очередной guard не использует entitlement слой.
- Impact
  - Нельзя корректно обеспечить тарифный лимит фоновых задач (например, 3 одновременные задачи).
- Fix (single solution)
  - Привязать inflight limit к org entitlement `task_queue_inflight_heavy_limit` с fallback на глобальный config.
- Steps
  1. Добавить entitlement lookup в path постановки heavy run задач.
  2. Возвращать effective limit/source в ошибке и telemetry.
  3. Оставить текущий global fallback для обратной совместимости.
- Acceptance Criteria (verifiable)
  - Для org с entitlement=3 четвёртая heavy задача отклоняется.
  - Для org без entitlement поведение совпадает с текущим global limit.
- Validation Commands (if visible in the project)
  - No validation commands found in repo.
- Migration/Rollback (if needed)
  - Rollback — отключить entitlement ветку и использовать global limit.

## 4. Explicit Non-Goals
- Не менять scan/indexer движок, так как в текущем whitelist-аудите по затронутой задаче нет фактических проблем в этих частях.
- Не рефакторить UI-компоненты вне run/task-status/clarification потоков.
- Не менять существующий format `result` payload run, кроме аддитивных полей session/clarification.
- Не добавлять новых LLM/queue провайдеров.
