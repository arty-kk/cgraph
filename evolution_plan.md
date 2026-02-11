# Evolution Plan

## 0. Baseline (from audit)
- Architecture map:
  - Backend: FastAPI app (`backend/app/main.py`) with HTTP routers in `backend/app/api/*`, domain logic in `backend/app/services/*`, persistence via SQLModel/SQLAlchemy sync engine (`backend/app/db.py`, `backend/app/models.py`), background workload in Celery (`backend/app/celery_app.py`, `backend/app/celery_tasks.py`), Redis for rate-limit/queue guards (`backend/app/infra/*`).
  - Frontend: React + Vite SPA (`frontend/src/ui/*`) with API client over HTTP polling (`frontend/src/api/tasks.ts`) and app state orchestration in `frontend/src/ui/useStubGraphApp.ts`.
  - Data/migrations: Alembic sync env and revisions (`backend/alembic/env.py`, `backend/alembic/versions/*`), Postgres via `postgresql+psycopg` DSN (`backend/app/config.py`).
- Critical flows:
  1) Auth bootstrap/login/logout/token resolution (`backend/app/api/auth.py`, `backend/app/services/auth_service.py`, `backend/app/main.py`).
  2) Org/project access checks on each request (`backend/app/policy.py`, `backend/app/api/projects.py`, `backend/app/api/tasks.py`).
  3) Project creation (path/snapshot) and indexing kickoff (`backend/app/api/projects.py`, `backend/app/services/project_service.py`, `backend/app/snapshots.py`).
  4) Graph/search/dependencies read path (`backend/app/api/projects.py`, `backend/app/services/project_service.py`, `backend/app/graph.py`).
  5) Task execution via queue + status polling (`backend/app/services/task_queue.py`, `backend/app/celery_tasks.py`, `backend/app/api/tasks.py`, `frontend/src/api/tasks.ts`).
  6) File mutations with follow-up mutation indexing (`backend/app/api/nodes.py`, `backend/app/services/file_mutation_service.py`).
  7) Docs build as async background job (`backend/app/api/projects.py`, `backend/app/services/docs_service.py`, `backend/app/celery_tasks.py`).
- Current pain points:
  - P0: Async request path executes blocking DB I/O in middleware on every protected request. Evidence: `backend/app/main.py` (`auth_guard` is `async`), it calls sync `get_user_from_token` (`backend/app/services/auth_service.py`) which uses sync `get_session()` (`backend/app/db.py`). Root cause: async middleware directly invokes sync persistence layer. Impact: event-loop stalls under concurrent auth traffic, reducing API availability/latency predictability.
  - P0: Async request path executes blocking Redis I/O in middleware on every request when rate limiting is enabled. Evidence: `backend/app/main.py` (`rate_limit` is `async`) calls sync `allow_request` (`backend/app/infra/rate_limit.py`), which uses sync redis client (`backend/app/infra/redis_client.py`). Root cause: sync Redis client wired into async middleware. Impact: event-loop stalls on network jitter/Redis latency; request throughput collapses under load.
  - P1: Mixed concurrency model (sync services + async endpoints/middleware) lacks clear boundary policy, so blocking calls are easy to reintroduce. Evidence: almost all service layer functions are sync (`backend/app/services/*.py`), while app has async middlewares and selected async endpoints (e.g., `create_project_from_snapshot` in `backend/app/api/projects.py`). Root cause: no explicit architecture guardrails or lint/tests for blocking-in-async boundaries. Impact: migration risk is high; regressions likely after partial refactors.
  - P1: File-upload endpoint is async but uses blocking stream/storage path directly. Evidence: `backend/app/api/projects.py:create_project_from_snapshot` is `async`, calls `store_snapshot_stream(archive.file, ...)`; `store_snapshot_stream` in `backend/app/snapshots.py` is synchronous and performs disk/S3 I/O. Root cause: blocking I/O executed inside coroutine context. Impact: large uploads block event loop and degrade unrelated request latency.
  - P1: Database/Redis application wiring is sync-oriented in current implementation, preventing safe end-to-end async request handling. Evidence: `backend/app/db.py` uses `create_engine` + sync `Session`; `backend/app/infra/redis_client.py` returns `redis.Redis`; these are invoked from request-time logic (`backend/app/main.py`, `backend/app/infra/rate_limit.py`). Root cause: infrastructure layer was implemented around synchronous clients for API request path. Impact: full async migration cannot be delivered incrementally without introducing async-safe infra boundaries and compatibility adapters.
  - P2: Background and API paths duplicate job state persistence logic, increasing migration surface and inconsistency risk. Evidence: status transitions in `backend/app/celery_tasks.py:_set_job_status` and enqueue-failure writebacks in multiple branches in `backend/app/services/task_queue.py`. Root cause: job state management not centralized. Impact: async migration requires touching many duplicated branches, increasing defect probability.
- Constraints:
  - Queue stack is RabbitMQ + Celery and already asynchronous out-of-process (`docker-compose.yml`, `backend/app/celery_app.py`); migration must keep this contract.
  - Existing API consumers rely on task polling contract (`/api/tasks/status/{task_id}` + frontend `waitForTaskResult`), so transport/protocol changes must be non-breaking (`backend/app/api/tasks.py`, `frontend/src/api/tasks.ts`).
  - Alembic migrations currently run with sync engine (`backend/alembic/env.py`), so schema migration path should stay stable during app-layer async transition.

## 1. North Star
- UX outcomes:
  - P95 latency of authenticated read endpoints remains stable under concurrent uploads/rate-limit checks (proxy metric: no event-loop blocking in middleware).
  - Long-running operations keep current async UX (queued task + poll) with no new client-side steps.
  - Error responses remain deterministic during queue/DB/Redis transient failures (same status semantics as now).
- Domain outcomes:
  - Single invariant for API process: request handlers/middleware never perform blocking network/disk DB calls on event loop.
  - Single source of truth for task-job state transitions (pending/running/succeeded/failed) across enqueue and worker execution.
  - Storage and indexing flows preserve current business contracts while moving I/O to async-safe boundaries.
- Engineering outcomes:
  - Async-ready infra layer (DB session factory, Redis client abstraction, request-scoped dependencies) with compatibility path for legacy sync services.
  - Contract tests protecting API behavior during migration.
  - Reduced regression risk by phase-gated rollout and explicit rollback toggles.

## 2. Roadmap (инкрементально)
### Phase 1 (Stabilize Core)
- Goal: remove blocking I/O from FastAPI async request path without changing external API contracts.
- Scope (что затрагиваем / что не трогаем):
  - Touch: middleware, auth/rate-limit boundaries, infra abstractions for DB/Redis in request path.
  - Do not touch: Celery task protocol, frontend task polling contract, domain logic semantics.
- Deliverables:
  1) Introduce async DB engine/session provider for API process and request dependency wrappers.
  2) Introduce async Redis client for request-time features (rate limit, optional auth/session cache if used).
  3) Refactor `auth_guard` and `rate_limit` middleware to async-safe service calls.
  4) Add guard tests verifying no sync session/client usage from async middleware paths.
  5) Feature flag to run API in compatibility mode (old sync adapters) for rollback.
- Dependencies:
  - Async drivers and wiring added before middleware refactor.
  - Contract tests added before enabling async path by default.
- Risk & Rollback strategy:
  - Risk: auth/rate-limit outage due to infra mismatch.
  - Rollback: env flag switches middleware back to existing sync adapters; keep old code path until Phase 2 stabilization.
- Validation (как проверить):
  - `pytest backend/tests/services/test_auth_service.py backend/tests/services/test_rate_limit.py`
  - `pytest backend/tests/services/test_auth_logout_api.py backend/tests/services/test_task_queue.py`

### Phase 2 (UX & Domain Consolidation)
- Goal: migrate business services and write paths to consistent async boundaries while keeping user-visible behavior unchanged.
- Scope (что затрагиваем / что не трогаем):
  - Touch: project/task/node API handlers, core service functions, upload/snapshot pipeline.
  - Do not touch: domain response schema unless required for parity fixes.
- Deliverables:
  1) Convert API routers to async handlers with injected async dependencies (DB session/unit of work).
  2) Migrate org/project/task auth/policy checks to async DB access.
  3) Refactor snapshot upload path to async stream handling (no blocking storage calls in coroutine).
  4) Centralize task job state writes into one async-capable repository/service used by both enqueue and worker adapters.
  5) Preserve queue API contract (`task_id/status/result/error`) and add regression tests.
  6) Add migration docs for developers (how to write new async services, forbidden sync patterns in async context).
- Dependencies:
  - Phase 1 async infra baseline.
  - Shared task state repository before removing duplicated write branches.
- Risk & Rollback strategy:
  - Risk: partial migration may create sync/async dead zones and hidden blocking.
  - Rollback: endpoint-level toggles keep selected routers on legacy sync path until parity tests pass.
- Validation (как проверить):
  - `pytest backend/tests/services/test_project_service_create_from_snapshot.py backend/tests/services/test_nodes_mutation_responses.py`
  - `pytest backend/tests/services/test_task_service_get_run.py backend/tests/services/test_task_service_impact.py backend/tests/services/test_task_service_agentic_retry.py`
  - `pytest backend/tests/services/test_api_contracts.py`

### Phase 3 (Scale & Maintainability)
- Goal: finish platform hardening for async operations and remove migration debt that blocks future evolution.
- Scope (что затрагиваем / что не трогаем):
  - Touch: residual sync adapters, observability, concurrency limits, docs.
  - Do not touch: frontend protocol model (polling) unless contract issue is proven.
- Deliverables:
  1) Remove legacy sync adapters from API process after parity confirmation.
  2) Add async-focused telemetry (request latency buckets around auth/rate-limit/upload hot-paths).
  3) Harden connection pool/timeouts/backpressure settings for async DB/Redis clients.
  4) Add CI checks preventing blocking calls inside async API modules.
  5) Align developer docs and runbooks with final async architecture.
- Dependencies:
  - Full parity in Phase 2.
- Risk & Rollback strategy:
  - Risk: aggressive removal of adapters can hinder emergency rollback.
  - Rollback: keep one release window with dormant compatibility toggle before full removal.
- Validation (как проверить):
  - `pytest backend/tests/services`
  - `pytest backend/tests/llm`
  - `npm --prefix frontend run lint`
  - `npm --prefix frontend run test`

## 3. Task Specs (атомарно, по одной стратегии)
- ID: EVO-001
  - Priority: P0
  - Theme: Reliability
  - Problem: `auth_guard` middleware performs blocking DB token resolution inside coroutine context.
  - Evidence: `backend/app/main.py:auth_guard` → `get_user_from_token`; `backend/app/services/auth_service.py:get_user_from_token`; `backend/app/db.py:get_session`.
  - Root Cause: sync DB session is used from async middleware.
  - Impact: event-loop blocking on every authenticated request.
  - Fix (single solution): implement async token resolution service and wire middleware to it via async session dependency.
  - Steps:
    1) Add async DB engine/session factory module for API process.
    2) Implement async `get_user_from_token` path using async session.
    3) Switch `auth_guard` to async resolver, keep sync fallback under feature flag.
    4) Add tests for authorized/unauthorized middleware behavior on async path.
  - Acceptance Criteria (проверяемо):
    - `auth_guard` no longer calls sync session provider in default mode.
    - Auth endpoints and protected routes keep current status codes and payload shape.
  - Validation Commands:
    - `pytest backend/tests/services/test_auth_service.py backend/tests/services/test_auth_logout_api.py`
  - Migration/Rollback:
    - Keep legacy sync resolver implementation in code during rollout; rollback is immediate switch to that legacy path in the same release branch.

- ID: EVO-002
  - Priority: P0
  - Theme: Reliability
  - Problem: `rate_limit` middleware performs blocking Redis operations in coroutine context.
  - Evidence: `backend/app/main.py:rate_limit` calls `allow_request`; `backend/app/infra/rate_limit.py:allow_request`; `backend/app/infra/redis_client.py:get_redis_client`.
  - Root Cause: sync Redis client in async middleware.
  - Impact: event-loop stalls and degraded throughput during Redis latency spikes.
  - Fix (single solution): replace middleware path with async Redis client and async rate-limit helper.
  - Steps:
    1) Add async Redis client provider.
    2) Implement async `allow_request` variant.
    3) Update middleware to await async helper.
    4) Keep degraded fallback semantics (allow request on Redis error) unchanged.
  - Acceptance Criteria (проверяемо):
    - Middleware path does not use sync Redis client in default mode.
    - Existing 429 contract remains unchanged.
  - Validation Commands:
    - `pytest backend/tests/services/test_rate_limit.py`
  - Migration/Rollback:
    - Keep legacy sync rate-limiter implementation in code during rollout; rollback is immediate switch to that legacy path in the same release branch.

- ID: EVO-003
  - Priority: P1
  - Theme: Platform
  - Problem: API process has no async DB infrastructure; only sync SQLModel session exists.
  - Evidence: `backend/app/db.py` uses `create_engine` + sync `Session`; `backend/requirements.txt` lacks async DB wiring.
  - Root Cause: initial architecture designed for sync request handlers.
  - Impact: blocks systematic migration of services/endpoints to async model.
  - Fix (single solution): introduce dedicated async DB infra module with request-scoped sessions and transaction helper.
  - Steps:
    1) Add async DB dependency module for FastAPI.
    2) Provide explicit transaction boundaries for service methods.
    3) Update selected API dependencies to consume new session provider.
  - Acceptance Criteria (проверяемо):
    - At least auth/policy/project read endpoints use async session provider in default mode.
  - Validation Commands:
    - `pytest backend/tests/services/test_policy_roles.py backend/tests/services/test_policy_unauth_org_resolution.py`
  - Migration/Rollback:
    - Keep sync `db.py` for Celery/legacy code until full migration completion.

- ID: EVO-004
  - Priority: P1
  - Theme: Reliability
  - Problem: Upload endpoint is async but executes blocking snapshot storage operations.
  - Evidence: `backend/app/api/projects.py:create_project_from_snapshot` (`async`) calls `store_snapshot_stream`; `backend/app/snapshots.py:store_snapshot_stream` does blocking disk/S3 I/O.
  - Root Cause: sync storage abstraction invoked directly in coroutine.
  - Impact: large uploads block unrelated requests in API worker.
  - Fix (single solution): implement async upload/storage pipeline and use non-blocking stream consumption in endpoint.
  - Steps:
    1) Add async snapshot storage adapter.
    2) Change endpoint to consume `UploadFile` asynchronously.
    3) Preserve existing validation and error payloads.
  - Acceptance Criteria (проверяемо):
    - Endpoint no longer calls blocking snapshot storage in coroutine path.
    - Existing response schema remains unchanged.
  - Validation Commands:
    - `pytest backend/tests/services/test_project_service_create_from_snapshot.py`
  - Migration/Rollback:
    - Temporary adapter can delegate to old sync storage in worker thread when async backend unavailable.

- ID: EVO-005
  - Priority: P1
  - Theme: Domain
  - Problem: Policy/access checks are sync and repeatedly open short-lived sessions across endpoints.
  - Evidence: `backend/app/policy.py` (`require_org_context`, `require_project_access`, etc.) uses `with get_session()`.
  - Root Cause: access control designed around sync helper calls.
  - Impact: duplicated DB access patterns complicate async migration and increase latency variance.
  - Fix (single solution): convert policy layer to async repository-backed checks with shared request session.
  - Steps:
    1) Add async policy repository methods.
    2) Inject request session into policy checks.
    3) Update API routers to await async policy guards.
  - Acceptance Criteria (проверяемо):
    - Policy guards execute within one request-scoped async session.
  - Validation Commands:
    - `pytest backend/tests/services/test_policy_roles.py backend/tests/services/test_policy_project_access_unauth.py`
  - Migration/Rollback:
    - Keep sync policy module as fallback during staged endpoint migration.

- ID: EVO-006
  - Priority: P2
  - Theme: Platform
  - Problem: Task job status persistence is duplicated across queue submit and worker execution code.
  - Evidence: status writes in `backend/app/celery_tasks.py:_set_job_status` and multiple enqueue failure branches in `backend/app/services/task_queue.py`.
  - Root Cause: no single task-job repository abstraction.
  - Impact: migration to async-safe persistence requires repeated changes and risks inconsistent status behavior.
  - Fix (single solution): extract unified task-job repository with one status transition API used by both modules.
  - Steps:
    1) Create repository for create/update/fail/complete transitions.
    2) Replace direct session writes in queue and worker modules.
    3) Add regression tests for idempotency and status transitions.
  - Acceptance Criteria (проверяемо):
    - Queue and worker paths use one shared transition API.
    - Task status contract unchanged.
  - Validation Commands:
    - `pytest backend/tests/services/test_task_queue.py backend/tests/services/test_task_service_get_run.py`
  - Migration/Rollback:
    - Repository can internally call legacy sync session while interface remains stable.

- ID: EVO-007
  - Priority: P1
  - Theme: Reliability
  - Problem: There are no guardrails preventing blocking sync calls from reappearing inside async API modules.
  - Evidence: current codebase has mixed sync/async without boundary checks (`backend/app/main.py`, `backend/app/api/projects.py`, `backend/app/infra/*`).
  - Root Cause: missing static/dynamic checks for async-safety rules.
  - Impact: regression risk remains high after migration.
  - Fix (single solution): add CI lint/test rule that fails when forbidden sync providers are imported/used in async API modules.
  - Steps:
    1) Define forbidden import/use list (sync DB/Redis providers) for async modules.
    2) Add lightweight test/lint script integrated into existing backend test run.
    3) Document exceptions for Celery/sync-only runtime.
  - Acceptance Criteria (проверяемо):
    - CI fails on new sync provider usage in async request path modules.
  - Validation Commands:
    - `pytest backend/tests/services/test_api_contracts.py`
  - Migration/Rollback:
    - Rule is additive and can be temporarily relaxed via explicit allowlist entry.

- ID: EVO-008
  - Priority: P1
  - Theme: UX
  - Problem: Async migration can break current long-running UX if task-status contract changes implicitly.
  - Evidence: frontend strictly depends on polling contract (`frontend/src/api/tasks.ts:waitForTaskResult`), backend status endpoint in `backend/app/api/tasks.py:get_task_status`.
  - Root Cause: no explicit contract freeze during migration.
  - Impact: user-visible failures (stuck polling/unknown status) during backend refactor.
  - Fix (single solution): formalize and lock task-status API contract with contract tests before/through migration.
  - Steps:
    1) Add/extend contract tests for status transitions and payload fields.
    2) Require these tests in migration PR gate.
    3) Keep response schema backward compatible.
  - Acceptance Criteria (проверяемо):
    - Frontend polling works unchanged against migrated backend.
  - Validation Commands:
    - `pytest backend/tests/services/test_api_contracts.py`
    - `npm --prefix frontend run test -- frontend/src/api/tasks.test.ts`
  - Migration/Rollback:
    - If regression appears, deploy rollback to previous backend while contract tests are fixed.

## 4. Explicit Non-Goals
- Do not replace Celery/RabbitMQ architecture with another queue system.
- Do not change frontend transport from polling to websocket/SSE in this migration.
- Do not redesign domain models or business rules unrelated to async-safety.
- Do not rewrite Alembic migration runtime to async during this initiative.
- Do not introduce broad refactors outside modules needed for async boundary migration.
