# Evolution Plan

## 0. Baseline (from audit)
- Architecture map:
  - Backend API: FastAPI app with middleware chain (rate limit, auth guard, request DB session lifecycle) and dual routing namespaces (`/api` and `/api/v1`). Evidence: `backend/app/main.py:65-134` (`rate_limit`, `auth_guard`, `request_db_session_lifecycle`).
  - Domain/API surface: projects, nodes, tasks endpoints, with org/project access checks in API layer and service-layer execution. Evidence: `backend/app/api/projects.py:72-279` (`create_project`, `scan`, `get_graph`, `search_*`), `backend/app/api/nodes.py:215-260` (`contract`, `node`), `backend/app/api/tasks.py:100-171` (`run_task`, `get_task_status`).
  - LLM orchestration: structured JSON responses through OpenAI Responses API, with parse/refusal handling and usage extraction. Evidence: `backend/app/llm/orchestrator.py:106-200` (`_json_call_with_usage_async`).
  - Core task pipeline: `TaskRequest` serialization/enqueue -> ARQ worker job -> run execution -> run persistence -> optional patch apply. Evidence: `backend/app/services/task_service.py:245-272` (`TaskRequest`), `backend/app/services/task_service.py:2176-2182` (`enqueue_run_task_async`), `backend/app/task_handlers.py:179-193` (`_run_task_job_async`), `backend/app/services/task_service.py:922-2168` (`_run_task_impl_async`).
  - Frontend app: React/Vite, API client interceptor normalizes `/api` prefix and injects `X-Org-ID`; UI triggers task run + polling. Evidence: `frontend/src/api/client.ts:43-71` (request interceptor), `frontend/src/api/tasks.ts:34-76` (`waitForTaskResult`).
- Critical flows:
  1. Auth/org-scoped request handling (`auth_guard`). Evidence: `backend/app/main.py:73-96`.
  2. Create/list project in org. Evidence: `backend/app/api/projects.py:72-123`.
  3. Project scan enqueue and async status. Evidence: `backend/app/api/projects.py:125-137`, `backend/app/services/task_queue.py:531-559` (`submit_scan_async`).
  4. File node/contract retrieval with on-demand indexing fallback. Evidence: `backend/app/api/nodes.py:215-260` (`contract`, `node`).
  5. LLM run submission and background execution. Evidence: `backend/app/api/tasks.py:100-136`, `backend/app/task_handlers.py:179-193`.
  6. LLM modes (`analyze|evolve|fix|impact`) with routing and quality gate. Evidence: `backend/app/services/task_service.py:967-970`, `backend/app/services/task_service.py:1500-2032`.
  7. Patch retrieval/apply path. Evidence: `backend/app/services/task_service.py:2292-2350`.
  8. Frontend task polling lifecycle and timeout boundary. Evidence: `frontend/src/api/tasks.ts:34-76`.
- Current pain points:
  - **P0/P1-01 (delivery blocker):** docker-compose points frontend build to `Dockerfile.prod`, but repository has `frontend/Dockerfile` only. Evidence: `docker-compose.yml:197-201`, `frontend/Dockerfile:1-19`, `README.md:68-69`.
  - **P1-02 (hot-path DB cost):** graph readiness warning performs full `COUNT(*)` on `FileNode` and `FileEdge`, and this warning is computed both during run execution and run retrieval. Evidence: `backend/app/services/task_service.py:792-809` (`_graph_warning_async`), `backend/app/services/task_service.py:952-955` (`_run_task_impl_async`), `backend/app/services/task_service.py:2235` (`get_run_async`).
  - **P1-03 (LLM reliability/latency):** planning (`plan_task_with_usage_async`) is mandatory in all branches and failures abort the run via `_llm_http_error("plan", ...)`, increasing latency/cost and creating extra failure surface before main mode output. Evidence: `backend/app/services/task_service.py:1333-1362` (`plan_graph`), `backend/app/services/task_service.py:1434-1464` (`plan_agentic`), `backend/app/services/task_service.py:1877-1907` (`plan_pack`).
  - **P1-04 (error-handling contract gap):** worker stores only `str(exc)` on task failure; structured error context/code from domain exceptions is dropped, while status endpoint exposes only this flattened string. Evidence: `backend/app/task_handlers.py:188-191` (`_run_task_job_async`), `backend/app/services/task_service.py:2376-2388` (`describe_task_async`).
  - **P2-05 (regression guard weakness):** `mypy` config enables strict flags but globally disables diagnostics (`ignore_errors = true`), reducing static regression signal. Evidence: `pyproject.toml:9-17`.
  - **P2-06 (high coupling):** single service (`task_service.py`) aggregates request validation, model routing, LLM calls, telemetry, patch storage/apply, and API payload shaping in one path (`_run_task_impl_async`), increasing change risk. Evidence: `backend/app/services/task_service.py:922-2168` (`_run_task_impl_async`).
- Constraints:
  - Async runtime contracts are enforced by tests (no sync DB/session patterns in runtime modules). Evidence: `backend/tests/services/test_runtime_async_db_contract.py:169-182`.
  - Frontend has explicit repo-native scripts (`lint`, `test`, `build`). Evidence: `frontend/package.json:6-12`.
  - Backend quality tool configs exist (`ruff`, `mypy`), but no repo-local canonical test command documented for backend in root docs/config. Evidence: `pyproject.toml:1-17`, `README.md:84-108`.

## 1. North Star
- UX outcomes:
  - Reduce failed/blocked first-run flows caused by environment/deploy contract mismatch to near zero (proxy metric: successful `docker compose up --build` on clean clone).
  - Reduce perceived run latency and unexpected plan-stage failures in LLM flows (proxy metrics: p50 run completion time; fraction of failed runs where failure stage=`plan_*`).
  - Improve task-status clarity so UI can show actionable failure classes instead of raw text-only error strings.
- Domain outcomes:
  - Lock task execution invariants: graph readiness signal, LLM planning/execution boundaries, and patch application constraints become explicit and deterministic.
  - Preserve single source of truth for task status/error schema across worker + API response.
- Engineering outcomes:
  - Lower regression rate for task pipeline changes by restoring meaningful static checks and adding targeted contract tests around error/status payloads.
  - Reduce risk/cost of future LLM policy changes by isolating planning stage from execution critical path.

## 2. Roadmap (incremental)

### Phase 1 (Stabilize Core) - up to 10 highest-impact tasks (prioritize P0/P1)
- Goal
  - Remove delivery blockers and reduce correctness/performance risks in critical task/LLM path.
- Scope (what we touch / what we don’t)
  - Touch compose/frontend build contract, task pipeline status/error contract, graph warning hot path, planning stage failure behavior.
  - Do not change business features (`analyze|evolve|fix|impact`) semantics.
- Deliverables (concrete changes)
  1. Align frontend Dockerfile contract used by compose and docs (single canonical filename).
  2. Replace repetitive `COUNT(*)` graph readiness checks with cached/project-metrics-based readiness source.
  3. Make planning stage non-blocking for primary mode execution (fallback to `plan_tz` skipped/partial marker with telemetry).
  4. Introduce structured task error payload persisted by worker and returned by status endpoint.
  5. Add contract tests for (a) plan-stage degradation path, (b) structured error payload shape.
- Dependencies
  - 2 depends on stable place to store/read project-level graph readiness metadata.
  - 3 depends on error/status contract decision from 4.
- Risk & Rollback strategy
  - Feature-flag non-blocking plan behavior; rollback by re-enabling strict blocking if regressions appear.
  - Keep old error string field for one compatibility window while adding structured fields.
- Validation (how to verify: tests/linter/commands from the repo)
  - `npm run lint` (frontend).
  - `npm run test` (frontend).
  - `ruff check backend/app` (backend config present in repo).

### Phase 2 (UX & Domain Consolidation) - up to 10 tasks
- Goal
  - Make task/LLM state transitions predictable in UI and domain boundaries explicit.
- Scope (what we touch / what we don’t)
  - Touch API task response schema, frontend task polling/error rendering, task service decomposition boundaries.
  - Do not redesign UI information architecture or add new LLM modes.
- Deliverables (concrete changes)
  1. Formalize task status/error response schema (typed, versioned fields), consumed by frontend without string parsing.
  2. Expose stage-level telemetry summary in status endpoint for better UX diagnostics (e.g., failed stage, retry count).
  3. Extract `plan_*` logic into dedicated internal service/module with explicit interface to reduce coupling in `_run_task_impl_async`.
  4. Add targeted regression tests for status transitions and stage telemetry propagation.
- Dependencies
  - Requires Phase 1 structured error payload and non-blocking plan behavior.
- Risk & Rollback strategy
  - Keep backward-compatible response fields during migration; remove legacy fields only after frontend migration.
- Validation (how to verify: tests/linter/commands from the repo)
  - `npm run lint`.
  - `npm run test`.
  - `ruff check backend/app`.

### Phase 3 (Scale & Maintainability)- up to 10 tasks (only if it truly blocks progress)
- Goal
  - Reduce long-term change cost in the LLM/task subsystem and restore static regression signal.
- Scope (what we touch / what we don’t)
  - Touch static-check policy and service modularization seams only.
  - Do not introduce infra/platform replacements.
- Deliverables (concrete changes)
  1. Re-enable meaningful mypy checks incrementally (remove global `ignore_errors = true`, scope suppressions locally).
  2. Split `task_service` into execution pipeline modules (validation, planning, mode execution, patch apply, persistence).
  3. Add module-level contract tests for extracted boundaries.
- Dependencies
  - Requires Phase 2 interfaces stabilized.
- Risk & Rollback strategy
  - Stepwise extraction with compatibility adapters; rollback by retaining old entrypoint wrapper.
- Validation (how to verify: tests/linter/commands from the repo)
  - `ruff check backend/app`.
  - `npm run lint`.
  - `npm run test`.

## 3. Task Specs (atomic, single-strategy)

- ID: EVO-001
- Priority: P0
- Theme: Platform
- Problem:
  - Compose frontend build references missing Dockerfile target, blocking default deployment flow.
- Evidence:
  - `docker-compose.yml:197-201` (frontend build uses `dockerfile: Dockerfile.prod`), `frontend/Dockerfile:1-19` (only `Dockerfile` exists), `README.md:68-69` (documents mismatch).
- Root Cause
  - Deployment contract drift between compose and repository tree.
- Impact
  - Broken first-run/dev onboarding; increased setup friction.
- Fix (single solution)
  - Standardize on one Dockerfile name and update compose + docs to that canonical contract.
- Steps
  1. Pick canonical filename already present in repo (`frontend/Dockerfile`).
  2. Update compose reference to canonical filename.
  3. Update README startup notes accordingly.
- Acceptance Criteria (verifiable)
  - Compose file and frontend Dockerfile path are consistent.
  - README no longer documents this mismatch as unresolved.
- Validation Commands (if visible in the project)
  - `docker compose up --build` (README startup flow).
  - `curl http://localhost:8000/health` (README health check).
- Migration/Rollback (if needed)
  - Rollback by restoring previous compose Dockerfile reference.

- ID: EVO-002
- Priority: P1
- Theme: Performance
- Problem:
  - Graph readiness check executes expensive count queries repeatedly on hot task paths.
- Evidence:
  - `backend/app/services/task_service.py:792-809` (`_graph_warning_async` counts both tables), `backend/app/services/task_service.py:952-955` (`_run_task_impl_async`), `backend/app/services/task_service.py:2235` (`get_run_async`).
- Root Cause
  - Readiness inferred from full-table counts each call instead of maintained readiness metadata.
- Impact
  - Unnecessary DB load and latency on frequent run/get-run operations.
- Fix (single solution)
  - Compute and persist readiness in project metrics during scan/mutation updates; read that value in task service instead of issuing counts.
- Steps
  1. Add readiness field in project metrics update path.
  2. Replace `_graph_warning_async` SQL counts with metrics read.
  3. Add regression tests covering readiness transitions.
- Acceptance Criteria (verifiable)
  - No `COUNT(*)` queries for warning path in run/get-run flow.
  - Warning behavior remains functionally equivalent.
- Validation Commands (if visible in the project)
  - `ruff check backend/app`.
- Migration/Rollback (if needed)
  - Fallback to old count-based logic behind temporary switch.

- ID: EVO-003
- Priority: P1
- Theme: Reliability
- Problem:
  - Plan stage failure aborts full LLM run before main mode output.
- Evidence:
  - `backend/app/services/task_service.py:1352-1362` (`plan_graph` failure -> `_llm_http_error`), `backend/app/services/task_service.py:1454-1464` (`plan_agentic`), `backend/app/services/task_service.py:1897-1907` (`plan_pack`).
- Root Cause
  - Planning treated as hard dependency rather than auxiliary artifact.
- Impact
  - Lower run success rate and higher latency/cost due to additional mandatory model call.
- Fix (single solution)
  - Make plan stage soft-fail: persist telemetry + skipped/failed plan marker, continue primary mode execution.
- Steps
  1. Replace `_llm_http_error("plan", ...)` with non-fatal branch.
  2. Mark `plan_source` and `plan_tz` as degraded with explicit reason.
  3. Add tests ensuring analyze/evolve/fix can complete when plan call fails.
- Acceptance Criteria (verifiable)
  - Primary mode result returns when plan fails.
  - Telemetry still records plan failure class.
- Validation Commands (if visible in the project)
  - `ruff check backend/app`.
- Migration/Rollback (if needed)
  - Feature flag for strict-plan mode rollback.

- ID: EVO-004
- Priority: P1
- Theme: Domain
- Problem:
  - Worker task failures lose structured error context and expose only plain string.
- Evidence:
  - `backend/app/task_handlers.py:188-191` (`error=str(exc)`), `backend/app/services/task_service.py:2383-2388` (`describe_task_async` returns raw `error` string).
- Root Cause
  - No typed error schema across worker persistence and API status response.
- Impact
  - UI cannot reliably classify/recover from failures; diagnostics are inconsistent.
- Fix (single solution)
  - Persist structured error object (`code`, `message`, `context`, `stage`) and expose it in status payload while retaining legacy `error` text temporarily.
- Steps
  1. Define task error schema in backend models/contracts.
  2. Populate schema in worker exception handling.
  3. Return schema in `describe_task_async`; update frontend consumer.
- Acceptance Criteria (verifiable)
  - Status payload contains stable structured error fields for failed tasks.
  - Existing consumers continue to work during compatibility window.
- Validation Commands (if visible in the project)
  - `npm run test`.
- Migration/Rollback (if needed)
  - Keep legacy `error` string field until frontend rollout completes.

- ID: EVO-005
- Priority: P2
- Theme: Reliability
- Problem:
  - Static typing safety net is effectively disabled globally.
- Evidence:
  - `pyproject.toml:13-17` (`warn_*` enabled but `ignore_errors = true`).
- Root Cause
  - Historical global suppression remained after stricter options were introduced.
- Impact
  - Type regressions can enter task/LLM pipeline unnoticed.
- Fix (single solution)
  - Remove global ignore and use targeted per-module ignores with explicit debt tracking.
- Steps
  1. Disable global `ignore_errors`.
  2. Add narrow suppressions only where needed.
  3. Gate changes with incremental module-by-module cleanup.
- Acceptance Criteria (verifiable)
  - Mypy reports meaningful diagnostics on changed modules.
- Validation Commands (if visible in the project)
  - `python -m mypy backend` (mypy config is defined in `pyproject.toml`).
- Migration/Rollback (if needed)
  - Temporary module-scoped suppression if blocking errors appear.

- ID: EVO-006
- Priority: P2
- Theme: Platform
- Problem:
  - Task execution path is highly coupled, increasing regression risk for LLM/domain changes.
- Evidence:
  - `backend/app/services/task_service.py:922-2168` (`_run_task_impl_async` spans validation, routing, plan, execution, persistence, patch apply).
- Root Cause
  - Multiple responsibilities accumulated in one method/service.
- Impact
  - Harder to test/change isolated behavior; higher blast radius for small edits.
- Fix (single solution)
  - Extract pipeline into dedicated internal modules with explicit interfaces while keeping existing public entrypoint.
- Steps
  1. Split into `validation`, `planning`, `execution`, `persistence`, `patch_apply` units.
  2. Keep `run_task_async` as orchestrating façade.
  3. Add contract tests for each unit and integrated path.
- Acceptance Criteria (verifiable)
  - `_run_task_impl_async` reduced to orchestration only.
  - Unit/contract tests cover extracted boundaries.
- Validation Commands (if visible in the project)
  - `ruff check backend/app`.
- Migration/Rollback (if needed)
  - Preserve old code path behind adapter during incremental extraction.

## 4. Explicit Non-Goals
- Do not change user-visible semantics of LLM modes (`analyze|evolve|fix|impact`) beyond reliability/perf fixes.
- Do not add new external dependencies or model providers without direct repository evidence/need.
- Do not redesign frontend navigation/layout.
- Do not optimize non-hot paths without evidence.

Assumptions, missing evidence, and unverified areas:
- Dynamic/runtime production metrics (actual p95 latency, DB query plans) are not present in repository artifacts; performance impact assertions are based on static call-path evidence only.
- No repository-native backend test command/script was found in root docs/scripts; backend validation commands above are inferred from tool configs and may require team confirmation.
