# Evolution Plan

## 0. Baseline (from audit)
- Architecture map:
  - Backend entrypoint is FastAPI with middleware chain (rate limit, auth guard, request DB-session lifecycle) and duplicated router mounting for `/api` and `/api/v1` namespaces. Evidence: `backend/app/main.py:65-134#rate_limit`, `backend/app/main.py:72-97#auth_guard`, `backend/app/main.py:99-121#request_db_session_lifecycle`.
  - Task orchestration path is API `POST /tasks/{project_id}/run` -> `enqueue_run_task_async` -> background handler `_run_task_job_async` -> runtime service `_run_task_impl_async` -> status read through `describe_task_async`. Evidence: `backend/app/api/tasks.py:124-160#run_task`, `backend/app/task_handlers.py:254-281#_run_task_job_async`, `backend/app/services/task_service.py:964-1010#_run_task_impl_async`, `backend/app/services/task_service.py:2358-2393#describe_task_async`.
  - File mutation flow is API `nodes` write operations -> queue mutation indexing task -> frontend polling via `waitForTaskResult`. Evidence: `backend/app/api/nodes.py:343-349#update_file`, `backend/app/services/task_queue.py:526-559#submit_mutation_indexing_async`, `frontend/src/ui/useStubGraphApp.ts:1610-1665#queueMutationIndexingPoll`, `frontend/src/api/tasks.ts:34-80#waitForTaskResult`.
  - Patch storage lifecycle is externalized in blob storage and referenced by DB `AnalysisRun.patch_blob_sha`; run deletion also drives blob deletion. Evidence: `backend/app/services/task_service.py:2335-2355#delete_run_async`, `backend/app/storage.py:234-257#delete_patch_blob_by_sha_async`.
  - Frontend transport layer auto-prefixes `/api` and injects `X-Org-ID` from in-memory/storage selection. Evidence: `frontend/src/api/client.ts:21-27#shouldPrefixApiPath`, `frontend/src/api/client.ts:43-71`, `frontend/src/api/client.ts:75-82#setSelectedOrgId`.
- Critical flows:
  1. API request admission (rate limit + auth token + DB session lifecycle). Evidence: `backend/app/main.py:65-69#rate_limit`, `backend/app/main.py:73-97#auth_guard`, `backend/app/main.py:99-121#request_db_session_lifecycle`.
  2. Org/project authorization at task API boundary. Evidence: `backend/app/api/tasks.py:130-160#run_task`, `backend/app/api/tasks.py:193-196#get_task_status`.
  3. Background task execution and failure serialization in worker. Evidence: `backend/app/task_handlers.py:57-80#_set_job_status_async`, `backend/app/task_handlers.py:254-281#_run_task_job_async`.
  4. Task status contract (legacy error + structured `error_payload`). Evidence: `backend/app/api/tasks.py:39-54#TaskStatusDetails`, `backend/app/services/task_service.py:2369-2390#describe_task_async`.
  5. LLM run preflight and graph readiness warning path. Evidence: `backend/app/services/task_service.py:992-999#_run_task_impl_async`, `backend/app/services/task_service.py:792-801#_graph_warning_async`.
  6. Mutation indexing queueing and UI poll completion handling. Evidence: `backend/app/services/file_mutation_service.py:58-76#build_mutation_queued_response`, `frontend/src/ui/useStubGraphApp.ts:1610-1665#queueMutationIndexingPoll`.
  7. Task polling termination logic in frontend API layer. Evidence: `frontend/src/api/tasks.ts:48-79#waitForTaskResult`.
- Current pain points:
  - **P0 — data consistency risk in run deletion:** patch blob is deleted before DB transaction for run delete is committed; on commit failure, DB run may remain while blob is already gone. Evidence: `backend/app/services/task_service.py:2345-2354#delete_run_async`, `backend/app/storage.py:234-257#delete_patch_blob_by_sha_async`.
  - **P1 — structured task error contract is dropped in UI polling path:** frontend transforms failed status into plain `Error(message)` and discards `error_payload.code/stage/context`, even though the type and backend payload provide these fields. Evidence: `frontend/src/api/tasks.ts:53-60#waitForTaskResult`, `frontend/src/api/types.ts:296-307#TaskStatus`, `backend/app/services/task_service.py:2372-2390#describe_task_async`.
  - **P1 — stale documentation causes setup friction:** README still states compose points to non-existent `frontend/Dockerfile.prod`, while compose currently points to `frontend/Dockerfile`. Evidence: `README.md:126`, `docker-compose.yml:197-201`.
  - **P2 — static typing guardrail is effectively disabled:** mypy strict warnings are configured but globally neutralized by `ignore_errors = true`. Evidence: `pyproject.toml:9-17`.
  - **P2 — duplicated runtime contract helper increases drift risk:** `isTaskStatus` is duplicated in two frontend modules with equivalent structural checks. Evidence: `frontend/src/api/tasks.ts:19-26#isTaskStatus`, `frontend/src/ui/useStubGraphApp.ts:212-219#isTaskStatus`.
- Constraints:
  - Project explicitly enforces async runtime boundaries with dedicated contract tests (no sync DB/session and no `threading.Lock` in async runtime modules). Evidence: `backend/tests/services/test_runtime_async_db_contract.py:169-182#test_runtime_modules_do_not_use_with_get_session_blocks`, `backend/tests/services/test_runtime_asyncio_run_contract.py:139-146#test_async_runtime_modules_do_not_use_threading_lock`.
  - Repo-native frontend validation commands are defined in npm scripts (`lint`, `test`, `build`). Evidence: `frontend/package.json:6-12`.
  - Backend has tool configuration for Ruff and mypy in `pyproject.toml`, but no dedicated backend script wrapper in repo root. Evidence: `pyproject.toml:1-17`.

## 1. North Star
- UX outcomes:
  - Reduce opaque task failures in UI: target proxy metric = 0 cases where failed task toast lacks stable `code` and `stage` when backend provided `error_payload`.
  - Reduce onboarding friction: target proxy metric = README setup notes match actual compose contract (no false mismatch guidance).
- Domain outcomes:
  - Enforce storage/DB consistency invariant: “an `AnalysisRun` row and its patch blob reference are removed atomically or recoverably”.
  - Keep a single canonical task failure contract across worker -> API -> frontend consumption.
- Engineering outcomes:
  - Restore static-analysis signal for changed modules by removing global type-check suppression.
  - Reduce helper drift by converging duplicated task-status type guards to one source.

## 2. Roadmap (incremental)

### Phase 1 (Stabilize Core) - up to 10 highest-impact tasks (prioritize P0/P1)
- Goal
  - Eliminate correctness risks in critical task lifecycle (delete consistency + failure observability).
- Scope (what we touch / what we don’t)
  - Touch run deletion ordering/transaction boundaries, frontend polling error propagation, README factual mismatch.
  - Do not change task business modes (`analyze|evolve|fix|impact`) or queue topology.
- Deliverables (concrete changes)
  1. Move patch blob deletion to a safe post-commit flow (or compensating retry record) so DB and blob state cannot diverge on commit failure.
  2. Preserve and propagate `error_payload` fields through `waitForTaskResult` consumer-facing error object.
  3. Remove obsolete Dockerfile mismatch statement from README.
- Dependencies
  - Item 2 depends on keeping backend `TaskStatusDetails.error_payload` contract stable.
  - Item 1 depends on existing `patch_blob_sha` ref-count check flow remaining unchanged.
- Risk & Rollback strategy (if migration/contract changes are required)
  - Keep legacy `error` message path alongside structured fields during frontend migration.
  - For run delete flow, use feature-flagged fallback to previous order only as emergency rollback.
- Validation (how to verify: tests/linter/commands from the repo)
  - `cd frontend && npm run test`
  - `cd frontend && npm run lint`
  - `cd backend && pytest tests/services/test_task_service_get_run.py -q`

### Phase 2 (UX & Domain Consolidation) - up to 10 tasks
- Goal
  - Lock single-source-of-truth contracts for task status handling and reduce UI/API desync risk.
- Scope (what we touch / what we don’t)
  - Touch frontend task-status helper reuse and typed task error handling.
  - Do not redesign UI layout or polling cadence defaults.
- Deliverables (concrete changes)
  1. Extract one shared `isTaskStatus` guard/util and consume it in both polling API and app hook layers.
  2. Add explicit UI mapping for `error_payload.code/stage` in task failure notifications.
  3. Add regression tests for failed status with structured payload.
- Dependencies
  - Requires Phase 1 item 2 (structured payload preservation at polling boundary).
- Risk & Rollback strategy (if migration/contract changes are required)
  - Keep backward compatibility for failures without `error_payload` (fallback to legacy message).
- Validation (how to verify: tests/linter/commands from the repo)
  - `cd frontend && npm run test`
  - `cd frontend && npm run lint`

### Phase 3 (Scale & Maintainability)- up to 10 tasks (only if it truly blocks progress)
- Goal
  - Re-enable static contracts that prevent silent regressions in runtime-critical modules.
- Scope (what we touch / what we don’t)
  - Touch mypy policy and targeted module-level suppressions only.
  - Do not introduce new tooling stack beyond existing pyproject configuration.
- Deliverables (concrete changes)
  1. Remove global `ignore_errors = true` and migrate to narrow, explicit ignores only where needed.
  2. Add CI/local documented command for backend type-check in changed modules.
- Dependencies
  - Should be scheduled after Phase 1 to avoid mixing logic fixes and typing debt cleanup.
- Risk & Rollback strategy (if migration/contract changes are required)
  - Roll out per-module and keep temporary scoped ignore blocks to avoid blocking hotfixes.
- Validation (how to verify: tests/linter/commands from the repo)
  - `cd backend && python -m mypy app`
  - `cd backend && pytest tests/services/test_runtime_async_db_contract.py -q`

## 3. Task Specs (atomic, single-strategy)

- ID: EVO-001
- Priority: P0
- Theme: Reliability
- Problem:
  - `delete_run_async` performs irreversible blob deletion before transaction commit of `AnalysisRun` deletion.
- Evidence:
  - `backend/app/services/task_service.py:2345-2354#delete_run_async`
  - `backend/app/storage.py:234-257#delete_patch_blob_by_sha_async`
- Root Cause
  - External side effect (blob delete) is executed inside the pre-commit path of DB mutation, without commit-success guard.
- Impact
  - Commit failure can leave run row pointing to already-deleted blob (corrupted read/download behavior).
- Fix (single solution)
  - Convert to commit-first DB deletion and execute blob delete in a post-commit step with retryable failure logging.
- Steps
  1. Persist run deletion in DB transaction and commit.
  2. After successful commit, attempt blob deletion when refcount permits.
  3. On blob-delete failure, store retryable cleanup signal/log record.
- Acceptance Criteria (verifiable)
  - No code path deletes patch blob before successful DB commit of run removal.
  - Simulated DB commit failure leaves blob untouched.
- Validation Commands (if visible in the project)
  - `cd backend && pytest tests/services/test_task_service_get_run.py -q`
- Migration/Rollback (if needed)
  - Rollback by restoring previous ordering under feature flag only for emergency.

- ID: EVO-002
- Priority: P1
- Theme: UX
- Problem:
  - Frontend polling collapses structured task failure to plain `Error(message)` and drops machine-readable diagnostics.
- Evidence:
  - `frontend/src/api/tasks.ts:53-60#waitForTaskResult`
  - `frontend/src/api/types.ts:296-307#TaskStatus`
  - `backend/app/services/task_service.py:2372-2390#describe_task_async`
- Root Cause
  - Polling utility builds generic `Error` from message string instead of preserving `error_payload` fields.
- Impact
  - UI cannot reliably classify/route recovery UX by error code/stage; debugging and support become slower.
- Fix (single solution)
  - Introduce typed `TaskFailureError` that carries `task_id`, `status`, and full `error_payload`; throw this from polling.
- Steps
  1. Add typed error class in frontend API module.
  2. Populate class fields from `TaskStatus.error_payload` and legacy fallback.
  3. Update consumers to read structured fields for notifications.
- Acceptance Criteria (verifiable)
  - Failed polling throws object exposing `error_payload.code` and `error_payload.stage` when backend provided them.
  - Legacy message-only failures still render correctly.
- Validation Commands (if visible in the project)
  - `cd frontend && npm run test`
  - `cd frontend && npm run lint`
- Migration/Rollback (if needed)
  - Keep fallback to string message if consumer has not yet switched to typed error fields.

- ID: EVO-003
- Priority: P1
- Theme: Platform
- Problem:
  - README documents a Dockerfile mismatch that no longer exists.
- Evidence:
  - `README.md:126`
  - `docker-compose.yml:197-201`
- Root Cause
  - Documentation drift after compose/frontend contract was updated.
- Impact
  - False setup warnings increase onboarding/debug time and reduce trust in docs.
- Fix (single solution)
  - Update README limitations section to reflect current compose/frontend Dockerfile contract.
- Steps
  1. Remove obsolete mismatch statement.
  2. Keep only verified runtime limitations.
- Acceptance Criteria (verifiable)
  - README and compose reference the same frontend Dockerfile path.
- Validation Commands (if visible in the project)
  - No validation commands found in repo.
- Migration/Rollback (if needed)
  - Not required (docs-only correction).

- ID: EVO-004
- Priority: P2
- Theme: Reliability
- Problem:
  - Type-checking policy is configured but globally disabled.
- Evidence:
  - `pyproject.toml:9-17`
- Root Cause
  - Historical global suppression (`ignore_errors = true`) nullifies strictness flags.
- Impact
  - Type regressions in async/runtime-sensitive code can merge without signal.
- Fix (single solution)
  - Remove global ignore and gate incrementally with module-scoped suppressions only where needed.
- Steps
  1. Delete `ignore_errors = true`.
  2. Add narrow ignores in explicitly identified modules only.
  3. Run mypy per module batch and commit fixes.
- Acceptance Criteria (verifiable)
  - Mypy reports actionable diagnostics for changed modules.
- Validation Commands (if visible in the project)
  - `cd backend && python -m mypy app`
- Migration/Rollback (if needed)
  - Temporarily scope-ignore specific modules if blocking delivery.

- ID: EVO-005
- Priority: P2
- Theme: Domain
- Problem:
  - Task status type guard logic is duplicated across API and app hook layers.
- Evidence:
  - `frontend/src/api/tasks.ts:19-26#isTaskStatus`
  - `frontend/src/ui/useStubGraphApp.ts:212-219#isTaskStatus`
- Root Cause
  - Missing shared utility for task status narrowing.
- Impact
  - Contract drift risk: one guard may diverge and produce inconsistent task-handling branches.
- Fix (single solution)
  - Extract one shared `isTaskStatus` helper in `frontend/src/api` and consume it everywhere.
- Steps
  1. Create shared helper.
  2. Replace duplicate local implementations.
  3. Add tests for malformed and valid payloads.
- Acceptance Criteria (verifiable)
  - Only one `isTaskStatus` implementation remains in frontend codebase.
- Validation Commands (if visible in the project)
  - `cd frontend && npm run test`
  - `cd frontend && npm run lint`
- Migration/Rollback (if needed)
  - Not required.

## 4. Explicit Non-Goals
- We will NOT redesign LLM prompting/routing strategy; audit evidence here targets lifecycle correctness and contract propagation only.
- We will NOT replace ARQ/Redis architecture.
- We will NOT introduce new frontend state-management libraries.
- We will NOT perform broad refactors outside tasks explicitly tied to audited defects above.

Assumptions, missing evidence, and unverified areas:
- This plan is static-audit-only and does not include runtime profiling or production telemetry not present in repo.
- No CI workflow files were found in-repo during this audit, so validation commands rely on scripts/config/tests visible in source tree.
