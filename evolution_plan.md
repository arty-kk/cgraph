# Evolution Plan

## 0. Baseline (from audit)
- Architecture map:
  - API entrypoint: FastAPI app with middleware chain (rate limit, auth, DB session), routers under `/api` and `/api/v1` in `backend/app/main.py:69-123` (`rate_limit`, `auth_guard`, `db_session_middleware`).
  - Business logic is concentrated in service modules (e.g., auth/project/task queue flows in `backend/app/services/auth_service.py:183-199` `authenticate_user_async`, `backend/app/services/project_service.py:856-912` `create_project_async`, `backend/app/services/task_queue.py:475-520` `submit_scan_async`), with async DB access via `AsyncSessionLocal` from `backend/app/async_db.py:20-30`.
  - Background processing is Celery-based (`backend/app/celery_app.py:9-20` `celery_app`) and bridges into async coroutines in `backend/app/celery_tasks.py:79-93` (`_run_async_entrypoint`).
  - Async runtime abstraction exists for FS/CPU/external I/O (`backend/app/infra/fs_runtime.py:58-183` `init_fs_runtime/run_fs_io_async`, `backend/app/infra/cpu_runtime.py:70-192` `init_cpu_runtime/run_cpu_io_async`, `backend/app/infra/external_io_runtime.py:49-119` `init_external_io_runtime/run_openai_io_async`), orchestrated by lifecycle builder (`backend/app/infra/runtime_lifecycle.py:11-63` `build_startup_steps/build_cleanup_steps`).
  - Queue producer boundary is async-only API (`backend/app/services/task_queue.py:44-103` `_AsyncTaskTransportClient/_AsyncTaskProducer`, `backend/README.md:22-31` `Task queue async contract`).
- Critical flows:
  1. HTTP request -> middleware -> DB session attach -> API handlers (`backend/app/main.py:69-109` `rate_limit/auth_guard/db_session_middleware`).
  2. API enqueue -> async task producer -> Redis/Celery broker (`backend/app/services/task_queue.py:44-90` `_AsyncTaskTransportClient.publish_async`, `backend/app/services/task_queue.py:176-205` `_enqueue_with_error_mapping_async`).
  3. Celery task -> async bridge -> service execution (`backend/app/celery_tasks.py:79-93` `_run_async_entrypoint`, `backend/app/celery_tasks.py:198-216` `scan_task/docs_task`, `backend/app/celery_tasks.py:234-299` `run_task_job/mutation_indexing_task`).
  4. Scan pipeline: file discovery + staged async/FS/CPU processing (`backend/app/scan.py:273-310` `iter_code_files/_stream_code_file_batches`, `backend/app/scan.py:1028-1179` `scan_project_async`).
  5. Snapshot import/export with S3 + local archive handling (`backend/app/snapshots.py:216-255` `_download_snapshot_archive_from_s3`, `backend/app/snapshots.py:342-405` `_upload_snapshot_archive_to_s3`, `backend/app/snapshots.py:441-454` `_ensure_archive_and_extract`).
  6. Semantic search: DB embeddings + bounded FS reads + OpenAI calls (`backend/app/graph.py:549-604` `read_semantic_candidate_files_async`, `backend/app/graph.py:669-700` `search_semantic_async`).
  7. Patch apply flow: task service -> FS runtime -> unified diff apply (`backend/app/services/task_service.py:140-154` `_apply_unified_diff_async`, `backend/app/patches.py:20-105` `apply_unified_diff`).
  8. Rate limiting via Redis LUA script (`backend/app/infra/rate_limit.py:58-69` `_run_rate_limit_increment`, `backend/app/infra/rate_limit.py:127-139` `allow_request_async`).
- Current pain points:
  - P0: contract violation and runtime mismatch in queue transport: default broker is AMQP (`backend/app/config.py:104-107` `Settings.celery_broker_url`), while async producer rejects non-Redis schemes (`backend/app/services/task_queue.py:52-54` `_AsyncTaskTransportClient.publish_async`, `backend/app/services/task_queue.py:116-118` `init_task_producer_runtime_async`), causing enqueue failure path by design (`backend/app/services/task_queue.py:176-205` `_enqueue_with_error_mapping_async`).
  - P1: Celery worker uses loop-thread bridge (`run_coroutine_threadsafe`, `Future.result`) in `_run_async_entrypoint` (`backend/app/celery_tasks.py:79-93` `_run_async_entrypoint`) despite async contract text requiring no loop-thread bridge (`backend/README.md:30-35` `Task queue async contract`).
  - P1: request-scoped DB session is held for entire API request in middleware (`backend/app/main.py:103-109` `db_session_middleware`) with low default pool size (`backend/app/async_db.py:24-27` `async_engine`, `backend/app/config.py:163-167` `Settings.db_pool_*`), increasing connection contention at high concurrency.
  - P1: project lock polling performs repeated DB round-trips (`SELECT pg_try_advisory_lock`) every interval (`backend/app/utils.py:100-123` `project_lock_async`, `backend/app/config.py:178-185` `Settings.project_lock_*`), creating avoidable load in high contention scenarios.
  - P2: async producer runtime uses `threading.Lock` inside async init/close (`backend/app/services/task_queue.py:8` import, `backend/app/services/task_queue.py:37` `_producer_runtime_guard`, `backend/app/services/task_queue.py:120-133` init/close critical sections), which can block event loop on contention and duplicates async synchronization patterns already used elsewhere (`backend/app/infra/rate_limit.py:29-41` `_get_rate_limit_lua_sha_lock`).
- Constraints:
  - Existing architecture explicitly enforces async-only contracts for cache/storage/task enqueue (`backend/README.md:3-35` `Backend cache lifecycle` + `Task queue async contract`).
  - Lifecycle startup/cleanup centralization already present and should remain single source of truth (`backend/app/infra/runtime_lifecycle.py:11-63` `build_startup_steps/build_cleanup_steps`).
  - Repo-native validation commands are visible only in frontend scripts (`frontend/package.json:6-11` `dev/build/lint/test`); checked backend scope has no package scripts/Makefile and only technical contract notes in `backend/README.md:1-35`.

## 1. North Star
- UX outcomes:
  - Queue-backed actions (scan/docs/run task) stop returning enqueue failures caused by broker mismatch; proxy metric: error responses with `enqueue_reason=unsupported_broker_scheme` trend to 0 (`backend/app/services/task_queue.py:139-145` `_classify_enqueue_failure`, `backend/app/services/task_queue.py:195-204` `_enqueue_with_error_mapping_async`).
  - Predictable latency under concurrency by reducing DB pool starvation from request-wide sessions and advisory-lock polling contention (`backend/app/main.py:103-109` `db_session_middleware`, `backend/app/utils.py:110-123` `project_lock_async`).
- Domain outcomes:
  - Single async contract for queue producer and worker runtime, without hidden sync/loop-bridge fallback (`backend/README.md:28-35` `Task queue async contract`, `backend/app/celery_tasks.py:79-93` `_run_async_entrypoint`).
  - Explicit lifecycle ownership for async resources (startup/cleanup only through runtime lifecycle steps) (`backend/app/infra/runtime_lifecycle.py:21-62`).
- Engineering outcomes:
  - Lower regression risk via explicit contract tests for broker compatibility, worker bridge removal, and lock behavior (`backend/tests/services/test_task_queue_async_io.py:243-250` `test_transport_client_rejects_unsupported_broker_scheme`, `backend/tests/services/test_runtime_asyncio_run_contract.py:28-39` `test_runtime_modules_do_not_use_asyncio_run_outside_allowlist`).
  - Higher throughput on hot paths by bounding waits and eliminating event-loop blocking sections in async boundaries.

## 2. Roadmap (incremental)
### Phase 1 (Stabilize Core) - up to 10 highest-impact tasks (prioritize P0/P1)
- Goal
  - Remove contract-breaking async bottlenecks and correctness issues that directly break queue/task execution under load.
- Scope (what we touch / what we don’t)
  - Touch: queue producer transport, Celery async entrypoint, DB session ownership and project lock strategy.
  - Don’t touch: API contracts/payload schemas, business semantics of scan/docs/run operations.
- Deliverables (concrete changes)
  - Broker-compatible async enqueue path without unsupported default behavior.
  - Worker runtime without loop-thread bridge.
  - Reduced DB connection hold time and lock contention.
- Dependencies
  - Must land broker compatibility before tightening async contract tests.
  - DB session and lock refactors require integration tests against current middleware and services.
- Risk & Rollback strategy (if migration/contract changes are required)
  - Rollback by feature-flagged transition points in producer and lock path; rollback keeps old behavior behind temporary guard until validated.
- Validation (how to verify: tests/linter/commands from the repo)
  - Repo-native commands visible in repository: `npm run lint`, `npm run test`, `npm run build` from `frontend/package.json:8-10`; backend-specific package scripts/Makefile are not visible.

Tasks:
1. EVO-001, EVO-002, EVO-003, EVO-004, EVO-005 (см. раздел 3).

### Phase 2 (UX & Domain Consolidation) - up to 10 tasks
- Goal
  - Consolidate async boundaries and observability for predictable behavior in high parallel workloads.
- Scope (what we touch / what we don’t)
  - Touch: runtime synchronization primitives, lifecycle consistency, queue/worker telemetry.
  - Don’t touch: core domain entities and DB schema unless required by migration.
- Deliverables (concrete changes)
  - Async-safe producer runtime guards.
  - Unified lifecycle invariant checks for API + worker.
  - Concurrency regression tests for enqueue/scan heavy paths.
- Dependencies
  - Requires Phase 1 async boundary stabilization.
- Risk & Rollback strategy (if migration/contract changes are required)
  - Additive telemetry/guards with reversible toggles; no irreversible data migration.
- Validation (how to verify: tests/linter/commands from the repo)
  - Repo-native commands visible in repository: `npm run lint`, `npm run test`, `npm run build` from `frontend/package.json:8-10`; backend-specific package scripts/Makefile are not visible.

Tasks:
2. EVO-006, EVO-007, EVO-008.

### Phase 3 (Scale & Maintainability)- up to 10 tasks (only if it truly blocks progress)
- Goal
  - Preserve async architecture cleanliness and prevent sync regressions.
- Scope (what we touch / what we don’t)
  - Touch: contract tests and lightweight docs for async invariants.
  - Don’t touch: functional product behavior.
- Deliverables (concrete changes)
  - Static/runtime guards against reintroducing loop-thread bridge and unsupported producer paths.
  - Updated operational docs for lifecycle and concurrency limits.
- Dependencies
  - Needs completion of Phase 1/2 implementation.
- Risk & Rollback strategy (if migration/contract changes are required)
  - Pure test/docs hardening; rollback is straightforward git revert.
- Validation (how to verify: tests/linter/commands from the repo)
  - Repo-native commands visible in repository: `npm run lint`, `npm run test`, `npm run build` from `frontend/package.json:8-10`; backend-specific package scripts/Makefile are not visible.

Tasks:
3. EVO-009.

## 3. Task Specs (atomic, single-strategy)
- ID: EVO-001
- Priority: P0
- Theme: Reliability
- Problem:
  - Async queue producer rejects non-Redis brokers, but default broker in settings is AMQP; enqueue can deterministically fail.
- Evidence: `backend/app/config.py:104-107` (`Settings.celery_broker_url`), `backend/app/services/task_queue.py:52-54` (`_AsyncTaskTransportClient.publish_async`), `backend/app/services/task_queue.py:116-118` (`init_task_producer_runtime_async`), `backend/app/services/task_queue.py:176-205` (`_enqueue_with_error_mapping_async`).
- Root Cause
  - Transport implementation is Redis-list specific and has no async path for configured AMQP default.
- Impact
  - Task creation flow degrades to failure status instead of enqueuing jobs.
- Fix (single solution)
  - Standardize broker contract to Redis-only at config boundary and enforce fail-fast startup validation (not per-request enqueue).
- Steps
  1. Validate broker scheme during app/worker startup lifecycle.
  2. Remove runtime lazy “unsupported scheme” branch from enqueue hot path.
  3. Align defaults/docs/tests to Redis-only async producer contract.
- Acceptance Criteria (verifiable)
  - Startup fails clearly on unsupported broker.
  - Enqueue path no longer contains scheme branching.
  - Existing submit APIs still return same business payload shape.
- Validation Commands (if visible in the project)
  - Repo-native commands visible in repository: `npm run lint`, `npm run test`, `npm run build` from `frontend/package.json:8-10`; backend-specific package scripts/Makefile are not visible.
- Migration/Rollback (if needed)
  - Rollback: temporary compatibility flag that re-enables previous lazy failure behavior.

- ID: EVO-002
- Priority: P1
- Theme: Platform
- Problem:
  - Worker async execution relies on dedicated loop thread + `run_coroutine_threadsafe` + blocking `future.result()`.
- Evidence: `backend/app/celery_tasks.py:31-35` (loop/thread globals), `backend/app/celery_tasks.py:38-63` (`_start_worker_event_loop`), `backend/app/celery_tasks.py:79-93` (`_run_async_entrypoint`), `backend/README.md:30-35` (contract forbidding loop-thread bridge).
- Root Cause
  - Legacy adapter pattern retained in Celery task wrappers.
- Impact
  - Hard-to-debug deadlock/blocking risks and contract divergence from declared async architecture.
- Fix (single solution)
  - Replace loop-thread bridge with per-task direct event loop entry (`asyncio.run`) isolated in Celery sync task boundary.
- Steps
  1. Remove global loop thread lifecycle.
  2. Execute each async task body with a direct event loop boundary in task wrapper.
  3. Keep startup/cleanup in Celery signals using same direct boundary.
  4. Update contract tests to forbid `run_coroutine_threadsafe` in runtime modules.
- Acceptance Criteria (verifiable)
  - `celery_tasks.py` no longer defines worker loop globals/thread runner.
  - No `run_coroutine_threadsafe` usage in backend runtime.
- Validation Commands (if visible in the project)
  - Repo-native commands visible in repository: `npm run lint`, `npm run test`, `npm run build` from `frontend/package.json:8-10`; backend-specific package scripts/Makefile are not visible.
- Migration/Rollback (if needed)
  - Rollback by restoring previous adapter in one module if worker-specific incompatibility appears.

- ID: EVO-003
- Priority: P1
- Theme: Performance
- Problem:
  - DB session is attached for full request lifetime, increasing pool occupancy under concurrent requests.
- Evidence: `backend/app/main.py:103-109` (`db_session_middleware`), `backend/app/async_db.py:24-30` (pool/session config), `backend/app/config.py:163-167` (default pool sizing).
- Root Cause
  - Middleware-level session ownership instead of operation-scoped session ownership.
- Impact
  - Increased queuing and latency spikes when concurrent API traffic exceeds small DB pool.
- Fix (single solution)
  - Move DB session ownership from global middleware to per-handler/service dependency scope with explicit commit/rollback boundaries.
- Steps
  1. Introduce dependency provider for short-lived async sessions.
  2. Refactor routers/services to consume scoped session.
  3. Remove request-state DB session middleware.
  4. Add concurrency integration tests for pool behavior.
- Acceptance Criteria (verifiable)
  - No request-wide DB session middleware.
  - Concurrent read-heavy API requests do not hold idle DB sessions across full response lifecycle.
- Validation Commands (if visible in the project)
  - Repo-native commands visible in repository: `npm run lint`, `npm run test`, `npm run build` from `frontend/package.json:8-10`; backend-specific package scripts/Makefile are not visible.
- Migration/Rollback (if needed)
  - Rollback via temporary dual mode (dependency + middleware), then remove middleware after soak.

- ID: EVO-004
- Priority: P1
- Theme: Performance
- Problem:
  - Project advisory lock uses polling loop with frequent DB queries.
- Evidence: `backend/app/utils.py:100-123` (`project_lock_async`), `backend/app/config.py:178-185` (poll timeout/interval knobs).
- Root Cause
  - Non-blocking `pg_try_advisory_lock` loop + sleep polling strategy.
- Impact
  - Extra DB load and delayed lock acquisition fairness under contention.
- Fix (single solution)
  - Switch to blocking advisory lock acquisition with bounded statement timeout per lock attempt.
- Steps
  1. Replace polling SQL with blocking lock SQL under DB timeout guard.
  2. Keep same timeout semantics at API layer.
  3. Add integration tests for contention and timeout behavior.
- Acceptance Criteria (verifiable)
  - Lock acquisition no longer loops on repeated `pg_try_advisory_lock` queries.
  - Timeout behavior remains explicit and test-covered.
- Validation Commands (if visible in the project)
  - Repo-native commands visible in repository: `npm run lint`, `npm run test`, `npm run build` from `frontend/package.json:8-10`; backend-specific package scripts/Makefile are not visible.
- Migration/Rollback (if needed)
  - Rollback by restoring polling implementation behind config flag.

- ID: EVO-005
- Priority: P1
- Theme: Reliability
- Problem:
  - Enqueue error mapping opens an additional DB session on failure path (`_mark_enqueue_failure_for_task_id_async`), which can amplify stress during broker outage storms.
- Evidence: `backend/app/services/task_queue.py:171-173` `_mark_enqueue_failure_for_task_id_async`, `backend/app/services/task_queue.py:183-204` `_enqueue_with_error_mapping_async`.
- Root Cause
  - Failure path side-effect requires independent DB write outside caller transaction scope.
- Impact
  - Under broker incident, extra DB pressure competes with normal traffic and can cascade errors.
- Fix (single solution)
  - Move enqueue failure persistence to caller-owned session/transaction (single write path), with best-effort fallback logging only.
- Steps
  1. Thread session context into enqueue mapping path.
  2. Remove unconditional session creation in failure helper.
  3. Add outage simulation tests validating bounded DB writes.
- Acceptance Criteria (verifiable)
  - Enqueue failure path does not create standalone DB session per failure.
- Validation Commands (if visible in the project)
  - Repo-native commands visible in repository: `npm run lint`, `npm run test`, `npm run build` from `frontend/package.json:8-10`; backend-specific package scripts/Makefile are not visible.
- Migration/Rollback (if needed)
  - Rollback by reintroducing isolated failure-session helper.

- ID: EVO-006
- Priority: P2
- Theme: Platform
- Problem:
  - Async producer runtime uses `threading.Lock` inside async functions.
- Evidence: `backend/app/services/task_queue.py:8` (import), `backend/app/services/task_queue.py:37` (`_producer_runtime_guard`), `backend/app/services/task_queue.py:120-133`.
- Root Cause
  - Mixed sync/async synchronization primitive in coroutine paths.
- Impact
  - Potential event-loop blocking during lock contention and reduced async composability.
- Fix (single solution)
  - Replace with loop-bound `asyncio.Lock` pattern consistent with other runtime modules.
- Steps
  1. Introduce loop-aware async lock factory.
  2. Refactor init/close producer runtime critical sections to async lock.
  3. Add stress test for concurrent init/close idempotency.
- Acceptance Criteria (verifiable)
  - No `threading.Lock` guarding async producer runtime critical paths.
- Validation Commands (if visible in the project)
  - Repo-native commands visible in repository: `npm run lint`, `npm run test`, `npm run build` from `frontend/package.json:8-10`; backend-specific package scripts/Makefile are not visible.
- Migration/Rollback (if needed)
  - Safe rollback by reverting lock primitive change.

- ID: EVO-007
- Priority: P2
- Theme: Reliability
- Problem:
  - Lifecycle contract is documented but lacks explicit invariant test that API and worker initialize/cleanup identical async resources set.
- Evidence: `backend/app/infra/runtime_lifecycle.py:11-63` `build_startup_steps/build_cleanup_steps`, `backend/README.md:33-35` `Task queue async contract`.
- Root Cause
  - Contract is textual; no strict regression guard for resource set drift.
- Impact
  - Future partial migrations may leave resources leaking or uninitialized in one role.
- Fix (single solution)
  - Add contract tests validating startup/cleanup resource set and order constraints per role.
- Steps
  1. Snapshot expected step names for API/worker.
  2. Assert no sync fallback resources are introduced.
  3. Verify close-order preserves dependent teardown safety.
- Acceptance Criteria (verifiable)
  - Tests fail on startup/cleanup drift from declared lifecycle contract.
- Validation Commands (if visible in the project)
  - Repo-native commands visible in repository: `npm run lint`, `npm run test`, `npm run build` from `frontend/package.json:8-10`; backend-specific package scripts/Makefile are not visible.
- Migration/Rollback (if needed)
  - Test-only; rollback is trivial.

- ID: EVO-008
- Priority: P2
- Theme: Performance
- Problem:
  - Scan pipeline uses thread-to-event-loop bridging (`call_soon_threadsafe`) and bounded semaphore choreography, increasing complexity and cancellation risk.
- Evidence: `backend/app/scan.py:1078-1113` `_produce_paths_async`, `backend/app/scan.py:1116-1167` `_produce_paths_async/_consume_paths_async`.
- Root Cause
  - Hybrid producer design between FS thread worker and async consumer queue.
- Impact
  - Harder reasoning about cancellation/backpressure; elevated maintenance cost on hot path.
- Fix (single solution)
  - Collapse to single async producer model using `run_fs_io_async` batch fetch API without manual cross-thread enqueue callbacks.
- Steps
  1. Extract FS iterator into pull-based batch function.
  2. Drive batching fully from async loop.
  3. Preserve current metrics semantics and add cancellation tests.
- Acceptance Criteria (verifiable)
  - No `call_soon_threadsafe` in scan path producer logic.
  - Backpressure remains bounded by queue size/runtime settings.
- Validation Commands (if visible in the project)
  - Repo-native commands visible in repository: `npm run lint`, `npm run test`, `npm run build` from `frontend/package.json:8-10`; backend-specific package scripts/Makefile are not visible.
- Migration/Rollback (if needed)
  - Rollback by restoring previous producer implementation.

- ID: EVO-009
- Priority: P2
- Theme: Platform
- Problem:
  - Async architecture constraints (no loop-thread bridge, no unsupported broker fallback) are not fully enforced by static tests.
- Evidence: `backend/tests/services/test_runtime_asyncio_run_contract.py:28-39` (checks only `asyncio.run`), `backend/tests/services/test_task_queue_async_io.py:243-250` (one-off broker scheme behavior test).
- Root Cause
  - Guard tests cover only subset of anti-patterns.
- Impact
  - Sync/bridge regressions can re-enter critical paths unnoticed.
- Fix (single solution)
  - Expand contract test suite with AST/runtime guards for forbidden constructs in designated runtime modules.
- Steps
  1. Add AST guard for `run_coroutine_threadsafe`, loop-thread globals in worker runtime modules.
  2. Add startup contract tests for broker compatibility enforcement.
  3. Add lifecycle close-verification tests for producer/redis/db resources.
- Acceptance Criteria (verifiable)
  - New guard tests fail on reintroduction of forbidden constructs.
- Validation Commands (if visible in the project)
  - Repo-native commands visible in repository: `npm run lint`, `npm run test`, `npm run build` from `frontend/package.json:8-10`; backend-specific package scripts/Makefile are not visible.
- Migration/Rollback (if needed)
  - Test-only; rollback is straightforward.

## 4. Explicit Non-Goals
- Не выполняем переписывание доменной логики scan/docs/task на новые алгоритмы, если это не требуется для async-границ.
- Не меняем публичные API-контракты роутов и payload-форматы.
- Не проводим массовые рефакторинги вне узких hot-path и lifecycle задач.
- Не добавляем альтернативные sync-fallback пути.
- Не меняем схему БД без прямой необходимости для задач EVO-001..EVO-009.
