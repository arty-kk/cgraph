# Evolution Plan

## 0. Baseline (from audit)
- Architecture map: Backend — FastAPI with routers for projects/nodes/tasks/auth/orgs, middleware for rate limiting + optional auth, DB init on startup; Celery queues for scan/docs/run_task; storage for snapshots/patches; Frontend — React/Vite SPA with main App composing graph canvas, editor, node panel, explorer, notifications, command palette; API client layer in frontend; domain entities stored via SQLModel (projects, nodes, edges, runs, docs, snapshots). (Evidence: backend/app/main.py; backend/app/celery_app.py; frontend/src/ui/App.tsx; PRODUCT.md)
- Critical flows: create project (local/snapshot) → scan → graph load; node/file view + edit; graph local subgraph; search (node/text/semantic); run LLM tasks (analyze/evolve/fix/impact) with agentic/pack retrieval; build/view project docs. (Evidence: backend/app/api/projects.py; backend/app/api/nodes.py; backend/app/api/tasks.py; PRODUCT.md)
- Current pain points:
  1) Snapshot upload buffers entire archive in memory up to `snapshot_max_bytes` (200MB default). Root cause: `create_project_from_snapshot` reads into a bytearray before passing to storage. Impact: high memory usage and request latency; potential OOM under concurrent uploads. (Evidence: backend/app/api/projects.py; backend/app/config.py)
  2) File explorer loads up to 50k files in one request and builds an in-memory tree on the client. Root cause: API default limit is 50,000 and frontend requests the full list, then constructs the tree by iterating every file. Impact: slow initial load, UI jank, high memory on large repos. (Evidence: backend/app/api/projects.py; frontend/src/api/projects.ts; frontend/src/ui/components/ExplorerTree.tsx)
  3) Client computes full dependency maps for every graph load by iterating all nodes and edges. Root cause: dependency derivation done in the UI from raw graph data. Impact: hot-path CPU cost on large graphs, UI latency. (Evidence: frontend/src/ui/App.tsx)
  4) Error-handling gaps with silent `try/catch` around localStorage reads/writes. Root cause: storage access errors are swallowed without user-visible feedback. Impact: preferences silently reset or fail to persist, reducing UX predictability. (Evidence: frontend/src/ui/App.tsx)
  5) Snapshot cleanup suppresses deletion errors without logging. Root cause: `delete_snapshot(...)` is wrapped with a broad `except` and `pass`. Impact: orphaned storage blobs and untracked storage growth. (Evidence: backend/app/services/project_service.py)
  6) Context packing reads files/contracts directly from disk per run without shared caching. Root cause: `pack_context` uses `read_text` and `get_or_build_contract` on every request. Impact: repeated disk IO for agentic/pack runs, slower task start. (Evidence: backend/app/context_pack.py)
- Constraints: Local root paths are disabled by default (`allow_local_root_path=false`); snapshot upload has hard size limits; auth can be disabled; Redis cache is optional. (Evidence: backend/app/config.py)

## 1. North Star (12–16 недель)
- UX outcomes: initial project open under 2s for 90% of projects (proxy: time to render explorer tree + graph); file explorer operations (expand/search/open) under 200ms; background tasks always show progress/status within 3s; error states have explicit copy and recovery actions.
- Domain outcomes: single-source-of-truth for graph/dependency views (server-provided dependency summaries); consistent project snapshot lifecycle (upload/cleanup fully tracked); deterministic task context sizing and reuse.
- Engineering outcomes: reduce regression risk via contract tests for critical API flows; faster iteration via caching and incremental data loads; measurable agentic efficiency (tool calls, cache hits, and context size surfaced and enforced).

## 2. Roadmap (инкрементально)

### Phase 1 (Stabilize Core)
- Goal: eliminate high-risk perf bottlenecks and cleanup gaps in core flows (snapshot, file list, dependency computation, task context).
- Scope: backend snapshot + file listing APIs, graph/dependency data exposure, pack/agentic context retrieval caching, cleanup error logging.
- Deliverables:
  - Stream snapshot upload to storage; avoid in-memory buffering; enforce size limits progressively.
  - Introduce paginated/streamed file listing API + UI integration for incremental loading.
  - Add server-side “dependencies for file” endpoint so UI doesn’t recompute full dependency maps.
  - Add structured logging for snapshot deletion failures and metrics for cleanup.
  - Add caching for contract and file reads used in context pack/agentic tools.
- Dependencies: Redis cache (optional) for context caching; UI work depends on new pagination API.
- Risk & Rollback strategy: guard new endpoints behind feature flag; fallback to current API if pagination fails.
- Validation: `python -m pytest`, `python -m ruff check backend/app`, `npm run lint --prefix frontend`.

### Phase 2 (UX & Domain Consolidation)
- Goal: reduce UX friction and align domain boundaries across UI/API.
- Scope: file explorer UX, graph navigation, task panels, error UX.
- Deliverables:
  - Virtualized file explorer tree with search-as-you-type and incremental fetch.
  - Graph navigation UX: load dependency slice on demand; show loading/error states; preserve graph state per project.
  - Consistent error UI for storage/session issues (localStorage failures, auth, missing data).
  - Task panel presets (architect/surgical/incident) with validated defaults and explanations.
- Dependencies: Phase 1 APIs; UI state persistence helpers.
- Risk & Rollback strategy: enable via UI toggles; keep legacy tree view as fallback in case of regressions.
- Validation: `npm run lint --prefix frontend`, targeted UI smoke tests (existing scripts).

### Phase 3 (Scale & Maintainability)
- Goal: guard against regressions and keep UX fast as project sizes grow.
- Scope: observability, contract tests, long-running task handling.
- Deliverables:
  - Contract tests for critical API flows (project create/scan/files/tasks) + golden responses.
  - Metrics dashboard for task duration, cache hits, graph size, and UI performance proxies.
  - Background task resilience: retry strategy visibility and UX for partial results.
- Dependencies: logging/metrics pipeline; consistent API response schemas.
- Risk & Rollback strategy: metrics are additive; no changes to external contract unless versioned.
- Validation: `python -m pytest`, any existing CI scripts for contracts/metrics.

## 3. Task Specs (атомарно, по одной стратегии)

- ID: EVO-001
  - Priority: P1
  - Theme: Performance
  - Problem: Snapshot upload buffers entire archive in memory before storage.
  - Evidence: backend/app/api/projects.py (create_project_from_snapshot reads into bytearray); backend/app/config.py (snapshot_max_bytes default 200MB).
  - Root Cause: upload handler accumulates chunks before calling storage.
  - Impact: high memory usage and slower uploads, especially with concurrent users.
  - Fix (single solution): stream upload to storage backend with progressive size checks; avoid `bytearray` buffer.
  - Steps:
    1) Implement streaming writer in snapshot storage (local/S3) with size tracking.
    2) Update API to pipe UploadFile stream directly to storage.
    3) Add tests for size limit enforcement without buffering.
  - Acceptance Criteria: upload of large snapshot does not exceed small memory footprint; size limit still enforced.
  - Validation Commands: `python -m pytest`.
  - Migration/Rollback: keep old path behind a flag; rollback by disabling streaming.

- ID: EVO-002
  - Priority: P1
  - Theme: UX
  - Problem: File explorer loads up to 50k files and builds full tree on client.
  - Evidence: backend/app/api/projects.py (files limit=50_000); frontend/src/api/projects.ts (default limit=50_000); frontend/src/ui/components/ExplorerTree.tsx (tree built from all files).
  - Root Cause: single bulk API + full in-memory tree build.
  - Impact: slow initial load and UI jank for large repos.
  - Fix (single solution): add paginated file listing API + lazy tree expansion; fetch directories on demand.
  - Steps:
    1) Add endpoint `/files/tree` or `/files` with cursor + directory filter.
    2) Update ExplorerTree to request children on expand and virtualize list.
    3) Add UI empty/loading/error states for each tree node.
  - Acceptance Criteria: initial load renders with no more than one directory fetch; total payload per request bounded.
  - Validation Commands: `npm run lint --prefix frontend`, `python -m pytest`.
  - Migration/Rollback: keep legacy `/files` path behind feature flag; fallback to old behavior if tree load fails.

- ID: EVO-003
  - Priority: P1
  - Theme: Performance
  - Problem: Dependency lists are recomputed in the browser by iterating all graph nodes/edges.
  - Evidence: frontend/src/ui/App.tsx (graphDependencies computed from graph nodes/edges).
  - Root Cause: server returns raw graph only; dependency summaries derived on client.
  - Impact: UI latency on large graphs; repeated CPU work on refresh.
  - Fix (single solution): add backend endpoint returning dependency summaries for a file (in/out lists and counts), consumed by UI on demand.
  - Steps:
    1) Implement API in backend graph service that queries FileEdge for a target path.
    2) Update UI to request dependencies when a file is selected, with loading state.
    3) Keep raw graph for visualization only.
  - Acceptance Criteria: dependency panel fetches on demand; graph load doesn’t trigger full dependency map build.
  - Validation Commands: `python -m pytest`, `npm run lint --prefix frontend`.
  - Migration/Rollback: fall back to client computation if endpoint unavailable.

- ID: EVO-004
  - Priority: P2
  - Theme: Reliability
  - Problem: Snapshot cleanup ignores deletion errors without visibility.
  - Evidence: backend/app/services/project_service.py (delete_snapshot wrapped in broad except + pass).
  - Root Cause: cleanup exceptions suppressed without logging.
  - Impact: orphaned blobs and untracked storage costs.
  - Fix (single solution): add logging and metrics for cleanup errors; store failure context for retries.
  - Steps:
    1) Replace silent `except` with logged warning including snapshot identifiers.
    2) Add optional retry job for failed deletes.
  - Acceptance Criteria: cleanup failures appear in logs and are traceable.
  - Validation Commands: `python -m pytest`.
  - Migration/Rollback: safe to deploy; no rollback required (logging only).

- ID: EVO-005
  - Priority: P2
  - Theme: UX
  - Problem: localStorage errors are swallowed, causing silent loss of preferences.
  - Evidence: frontend/src/ui/App.tsx (multiple `try/catch` without feedback).
  - Root Cause: storage access failures are ignored.
  - Impact: user settings reset without explanation; inconsistent UX.
  - Fix (single solution): introduce a storage helper that logs a warning + surfaces a non-blocking UI notice on failures.
  - Steps:
    1) Implement `safeStorage` wrapper returning status.
    2) Replace direct `localStorage` use in UI components.
    3) Add a single notification when storage is unavailable.
  - Acceptance Criteria: storage failures produce one visible notification; settings degrade gracefully.
  - Validation Commands: `npm run lint --prefix frontend`.
  - Migration/Rollback: wrapper can default to current silent behavior if needed.

- ID: EVO-006
  - Priority: P1
  - Theme: Performance
  - Problem: Context pack reads file contents/contracts from disk on every run.
  - Evidence: backend/app/context_pack.py (read_text + get_or_build_contract in pack_context).
  - Root Cause: no caching across requests.
  - Impact: repeated IO for frequent tasks; slower LLM runs.
  - Fix (single solution): cache file contents/contracts with TTL and invalidate on file changes.
  - Steps:
    1) Use existing cache layer for file content + contract JSON (keyed by project + path + file hash).
    2) Invalidate on file update/scan events.
    3) Add cache hit metrics in task logs.
  - Acceptance Criteria: repeated runs hit cache; task start latency improves.
  - Validation Commands: `python -m pytest`.
  - Migration/Rollback: disable cache by config if issues appear.

- ID: EVO-007
  - Priority: P1
  - Theme: UX
  - Problem: Long-running operations (scan/docs/task) lack consistent progress feedback across UI sections.
  - Evidence: backend/app/api/projects.py + backend/app/api/tasks.py expose async task statuses; frontend only shows partial scan status in NodePanel.
  - Root Cause: task status polling is localized, not global.
  - Impact: users uncertain about task state; repeated clicks/retries.
  - Fix (single solution): global task status banner with polling for any background task IDs.
  - Steps:
    1) Add task status store in `useStubGraphApp`.
    2) Display global progress banners for scan/docs/run tasks.
    3) Provide cancel/refresh hooks if supported.
  - Acceptance Criteria: background task status is visible from anywhere in UI within 3s of start.
  - Validation Commands: `npm run lint --prefix frontend`.
  - Migration/Rollback: optional UI-only change; rollback by disabling banner.

- ID: EVO-008
  - Priority: P2
  - Theme: Domain
  - Problem: Project root constraints are enforced but not surfaced in UI copy.
  - Evidence: backend/app/config.py (allow_local_root_path default false); frontend uses createProjectFromRoot in API layer.
  - Root Cause: UI lacks constraint-driven messaging.
  - Impact: user confusion when local path creation fails.
  - Fix (single solution): fetch server config/entitlements and show “local path disabled” states in UI.
  - Steps:
    1) Add config endpoint exposing relevant flags (allow_local_root_path).
    2) Update create project UI to hide/disable local path when not allowed.
  - Acceptance Criteria: UI prevents invalid creation flow; errors reduced.
  - Validation Commands: `python -m pytest`, `npm run lint --prefix frontend`.
  - Migration/Rollback: default to current behavior if config endpoint unavailable.

- ID: EVO-009
  - Priority: P2
  - Theme: Reliability
  - Problem: Agentic retrieval diagnostics are stored but not consistently emphasized in UI for user decisions.
  - Evidence: backend/app/services/task_service.py stores retrieval_settings; frontend shows a subset in NodePanel.
  - Root Cause: limited UI surface for retrieval plan/trace and missing-context guidance.
  - Impact: users can’t efficiently tune prompts/limits when agentic retrieval misses context.
  - Fix (single solution): add a compact “retrieval diagnostics” panel with plan + missing-context hints.
  - Steps:
    1) Extend NodePanel to show retrieval plan and missing context hints prominently.
    2) Add “re-run with context” quick action using suggested depth/limits.
  - Acceptance Criteria: agentic runs show retrieval plan + missing context at a glance; re-run uses recommended settings.
  - Validation Commands: `npm run lint --prefix frontend`.
  - Migration/Rollback: UI-only; can hide behind a toggle.

- ID: EVO-010
  - Priority: P2
  - Theme: Platform
  - Problem: API contracts are implicit in code, but not validated via automated contract tests.
  - Evidence: API routes and models defined in backend/app/api/*.py without contract tests.
  - Root Cause: no explicit schema test coverage.
  - Impact: regressions in API responses risk breaking UI.
  - Fix (single solution): add contract tests for critical endpoints (projects/files/graph/tasks).
  - Steps:
    1) Define JSON schema snapshots for key endpoints.
    2) Add tests in backend/tests to validate schemas.
  - Acceptance Criteria: contract tests fail on incompatible API changes.
  - Validation Commands: `python -m pytest`.
  - Migration/Rollback: additive tests only.

## 4. Explicit Non-Goals
- Replacing the current framework stack (FastAPI/React/Celery).
- Introducing new storage backends beyond those already configured.
- Large-scale refactors or UI redesign unrelated to observed UX friction points.
- Changing external API contracts without explicit versioning and migration steps.
