# Evolution Plan

## 0. Baseline (from audit)
- Architecture map: Backend — FastAPI app with routers for projects/nodes/tasks/auth/orgs, domain services, SQLModel persistence, graph/scanning utilities, and snapshot/storage handling. Frontend — React/Vite app with a single state hook (`useStubGraphApp`) orchestrating data flows and UI components (graph, explorer, editor). Evidence: `backend/app/main.py`, `backend/app/api/*`, `backend/app/services/*`, `backend/app/graph.py`, `backend/app/scan.py`, `backend/app/snapshots.py`, `frontend/src/ui/App.tsx`, `frontend/src/ui/useStubGraphApp.ts`.
- Critical flows:
  1) Create project (local or snapshot) → scan → graph view. Evidence: `backend/app/api/projects.py`, `backend/app/services/project_service.py`, `frontend/src/ui/useStubGraphApp.ts`.
  2) Browse tree → open file editor → edit/save → reindex/graph updates. Evidence: `frontend/src/ui/components/ExplorerTree.tsx`, `frontend/src/ui/useStubGraphApp.ts`, `backend/app/api/nodes.py`, `backend/app/graph.py`.
  3) Search nodes / semantic / text. Evidence: `backend/app/api/projects.py`, `backend/app/services/project_service.py`, `backend/app/search.py`, `frontend/src/ui/useStubGraphApp.ts`.
  4) Run LLM task → receive patch → apply. Evidence: `backend/app/api/tasks.py`, `backend/app/services/task_service.py`, `frontend/src/ui/useStubGraphApp.ts`.
  5) Build docs → read docs. Evidence: `backend/app/api/projects.py`, `backend/app/services/docs_service.py`, `frontend/src/ui/useStubGraphApp.ts`.
- Current pain points:
  - P1: File-save success can mask failed reindexing, causing graph/UI desync. Evidence: `backend/app/api/nodes.py` (`update_file` returns `saved: true` with `reindexed: false` + `error` in several branches), `frontend/src/ui/useStubGraphApp.ts` (`saveFileEditorPath` treats any `saved` as success and clears dirty state without checking `reindexed`/`error`). Root cause: inconsistent response contract + UI only checks `saved`. Impact: users believe graph is updated when it is not; potential incorrect dependency/risk info.
  - P1: Empty files are reloaded repeatedly when opened. Evidence: `frontend/src/ui/useStubGraphApp.ts` (`openFileEditor` computes `shouldLoad` using falsy checks on `content`/`original`, so empty strings trigger repeated fetch). Root cause: `content` presence is used as load sentinel. Impact: unnecessary network calls, slower navigation.
  - P1: Dependency lists can be truncated without UX disclosure/action. Evidence: `backend/app/services/project_service.py` returns `truncated_inbound`/`truncated_outbound` in `get_file_dependencies`; `frontend/src/ui/useStubGraphApp.ts` and `frontend/src/ui/App.tsx` only use inbound/outbound arrays and total counts. Root cause: metadata not surfaced in UI. Impact: users may miss dependencies without knowing the list is partial.
  - P2: Workspace persistence drops unsaved content on reload (only `dirty` flags are stored). Evidence: `frontend/src/ui/useStubGraphApp.ts` (`buildWorkspaceState` stores only `dirty` flags; restore recreates empty editors). Root cause: storage schema omits buffer contents. Impact: unsaved work lost after crash/refresh despite a dirty indicator.
  - P2: File mutation logic is duplicated across create/update/rename/delete paths. Evidence: repeated `scan_files` + `update_graph_metrics_incremental` + rescan handling in `backend/app/api/nodes.py`. Root cause: no shared service helper. Impact: higher risk of inconsistent behavior/bugs when modifying file-flow logic.
  - P2: `list_project_files` returns large payloads (default limit 50k) without cursor pagination. Evidence: `backend/app/services/project_service.py` (`list_project_files`), `backend/app/api/projects.py` endpoint. Root cause: no pagination strategy for file lists. Impact: performance risk for large repos and external clients.
- Constraints: auth can be disabled; local root paths can be disabled; Redis-based rate limit/cache; Postgres DB; snapshot and file-size limits; LLM/embeddings are optional and gated by config. Evidence: `backend/app/config.py`, `backend/app/infra/rate_limit.py`.

## 1. North Star (12–16 недель)
- UX outcomes: 
  - 100% file save attempts show explicit indexing status (ok/rescan/failed) and actionable guidance.
  - Empty-file navigation avoids redundant reloads (≤1 fetch per tab open).
  - Dependency panels indicate truncation and offer a “show more/open in graph” action when partial.
  - Optional “recover drafts” flow for unsaved buffers after reload (with size guard).
- Domain outcomes:
  - Single, consistent file-mutation response contract across create/update/rename/delete.
  - Clear invariant: `saved` means file on disk updated; `reindexed` reflects graph freshness; `rescan_task`/`warnings` communicate eventual consistency.
- Engineering outcomes:
  - Regression risk reduced via backend tests for file-mutation responses and UI handling of partial saves.
  - Shared service helpers replace duplicated file-mutation logic.

## 2. Roadmap (инкрементально)
### Phase 1 (Stabilize Core)
- Goal: Eliminate incorrect success signals and reduce high-friction UI issues in core edit flow.
- Scope: File save/update workflow, dependency panel signaling, editor open behavior. No changes to external behavior beyond adding response fields and UI messaging.
- Deliverables:
  1) Standardized file mutation response contract with explicit indexing status and warnings.
  2) UI handling of partial save/reindex failures (status banner + rescan CTA).
  3) Fix empty-file reload sentinel.
  4) Surface dependency truncation indicators and “show more/open graph” actions.
  5) Backend tests covering file-mutation response paths.
  6) Frontend API types updated to include new response fields.
- Dependencies: Backend response contract before frontend handling and type updates.
- Risk & Rollback strategy: Additive response fields (backward-compatible). UI changes gated by presence of new fields; fall back to previous behavior if fields are absent.
- Validation: `pytest` (backend), `npm run lint` (frontend).

### Phase 2 (UX & Domain Consolidation)
- Goal: Consolidate file-flow logic and introduce recovery/visibility features for consistency.
- Scope: File editor persistence, global graph-stale indicators, shared backend helper.
- Deliverables:
  1) Draft recovery for dirty buffers with size guard and user confirmation.
  2) Global “graph stale / rescan pending” indicator cleared on successful scan.
  3) Shared backend helper for file mutation + reindex/rescan logic.
  4) UI handling of conflict/rollback statuses with explicit messaging.
  5) Lightweight API doc/update for file mutation contract (developer-facing).
- Dependencies: Phase 1 response contract.
- Risk & Rollback strategy: Draft recovery behind opt-in toggle; ability to clear stored drafts.
- Validation: `pytest`, `npm run lint`.

### Phase 3 (Scale & Maintainability)
- Goal: Reduce performance risk for large repos and make heavy operations safer.
- Scope: File list pagination, search hot paths, graph metric computation.
- Deliverables:
  1) Cursor-based pagination for `list_project_files` with backward-compatible defaults.
  2) Optimize text search snippet extraction to avoid disk reads when `filetext` can serve snippets.
  3) Background/async graph-metric recomputation for large components or slow runs.
  4) Extend dependency queries with pagination parameters (cursor/offset) for large fan-in/out.
  5) Add performance regression checks for large-project fixtures (where available).
- Dependencies: Schema/API extensions and client usage updates.
- Risk & Rollback strategy: Keep old parameters working; new pagination optional.
- Validation: `pytest`.

## 3. Task Specs (атомарно, по одной стратегии)
- ID: EVO-001
  - Priority: P1
  - Theme: Domain | Reliability
  - Problem: File-save responses do not distinguish “saved but not reindexed” vs fully consistent updates.
  - Evidence: `backend/app/api/nodes.py` (`update_file` returns `saved: true` with `reindexed: false` and `error`), `frontend/src/ui/useStubGraphApp.ts` (`saveFileEditorPath` assumes `saved` is fully successful).
  - Root Cause: Ad-hoc response payloads across file mutation endpoints.
  - Impact: UI reports success while graph state is stale or partially updated.
  - Fix (single solution): Introduce a consistent response schema with `saved`, `reindexed`, `index_status` (`ok|rescan_scheduled|failed`), `warnings`, and optional `rescan_task` across create/update/rename/delete.
  - Steps:
    1) Define response model (Pydantic) and apply to file mutation endpoints.
    2) Ensure each branch populates `index_status` and `warnings` consistently.
    3) Update tests for response fields.
  - Acceptance Criteria:
    - All file mutation endpoints return the same response shape with `index_status`.
    - Responses include `warnings` when `reindexed` is false.
  - Validation Commands: `pytest`
  - Migration/Rollback: Additive fields only; no breaking change.

- ID: EVO-002
  - Priority: P1
  - Theme: UX | Reliability
  - Problem: UI clears dirty state and shows “File saved” even when reindexing failed.
  - Evidence: `frontend/src/ui/useStubGraphApp.ts` (`saveFileEditorPath` checks only `res.saved`).
  - Root Cause: Frontend ignores reindex/error metadata.
  - Impact: Users trust stale graph and dependencies.
  - Fix (single solution): Handle `index_status`/`reindexed`/`warnings` and show a banner with rescan CTA; only show success toast when `index_status=ok`.
  - Steps:
    1) Extend API types for new fields.
    2) Update save logic to set UI banner state and avoid success toast on partial saves.
    3) Add CTA to trigger scan when rescan scheduled.
  - Acceptance Criteria:
    - Partial save shows warning banner and no success toast.
    - Rescan CTA triggers scan and clears stale banner on completion.
  - Validation Commands: `npm run lint`
  - Migration/Rollback: If new fields missing, fallback to current behavior.

- ID: EVO-003
  - Priority: P1
  - Theme: Performance | UX
  - Problem: Empty files are reloaded every time they are opened.
  - Evidence: `frontend/src/ui/useStubGraphApp.ts` (`shouldLoad` uses falsy checks on `content`/`original`).
  - Root Cause: Empty string treated as “not loaded”.
  - Impact: Extra network calls and slower navigation.
  - Fix (single solution): Add explicit `loaded` flag (or sentinel) on file editor entries; use it for `shouldLoad`.
  - Steps:
    1) Add `loaded` boolean in `FileEditorEntry`.
    2) Set `loaded=true` on successful `getFileContent`.
    3) Update `shouldLoad` to check `loaded` instead of `content` truthiness.
  - Acceptance Criteria:
    - Opening a previously loaded empty file does not trigger a new fetch.
  - Validation Commands: `npm run lint`
  - Migration/Rollback: Safe local state change.

- ID: EVO-004
  - Priority: P1
  - Theme: UX | Domain
  - Problem: Dependency lists can be truncated without UI disclosure.
  - Evidence: `backend/app/services/project_service.py` (`truncated_inbound/outbound` in `get_file_dependencies`), `frontend/src/ui/useStubGraphApp.ts` ignores truncation metadata.
  - Root Cause: UI discards backend truncation metadata.
  - Impact: Incomplete dependency context for users.
  - Fix (single solution): Carry truncation flags to UI and show “partial results” with an explicit “Open in graph” or “Load more” action.
  - Steps:
    1) Extend dependency state to track truncation.
    2) Update editor panel to show truncation warning and CTA.
  - Acceptance Criteria:
    - When `truncated_*` is true, UI shows a warning and CTA.
  - Validation Commands: `npm run lint`
  - Migration/Rollback: Additive UI state only.

- ID: EVO-005
  - Priority: P1
  - Theme: Reliability
  - Problem: File mutation response branches are untested for partial/failure states.
  - Evidence: Lack of test coverage for `update_file` error branches in `backend/tests`.
  - Root Cause: No tests around scan-abort/rescan/rollback branches.
  - Impact: High regression risk.
  - Fix (single solution): Add targeted tests covering response fields for scan abort, rollback skipped, and rescan scheduled flows (using monkeypatch/mocks).
  - Steps:
    1) Add unit tests for `update_file` (and optionally create/rename/delete) response fields.
    2) Mock `scan_files` and `update_graph_metrics_incremental` to force branches.
  - Acceptance Criteria:
    - Tests assert `index_status`, `reindexed`, and `warnings` in relevant branches.
  - Validation Commands: `pytest`
  - Migration/Rollback: Test-only change.

- ID: EVO-006
  - Priority: P2
  - Theme: Platform
  - Problem: Frontend types do not model new file mutation response fields.
  - Evidence: `frontend/src/api/types.ts` (current `FileSaveResult` lacks fields for reindex status/warnings).
  - Root Cause: API contract change not reflected in types.
  - Impact: Type gaps and unsafe access in UI.
  - Fix (single solution): Extend `FileSaveResult` to include `index_status`, `warnings`, and `rescan_task` metadata.
  - Steps:
    1) Update TypeScript types.
    2) Update code that consumes these fields.
  - Acceptance Criteria:
    - TypeScript compiles with strict types for new response fields.
  - Validation Commands: `npm run lint`
  - Migration/Rollback: Backward-compatible typing change.

- ID: EVO-007
  - Priority: P2
  - Theme: UX | Reliability
  - Problem: Unsaved editor content is lost on reload/crash.
  - Evidence: `frontend/src/ui/useStubGraphApp.ts` only persists dirty flags and recreates empty editors.
  - Root Cause: Workspace persistence schema omits buffer contents.
  - Impact: User data loss on reload/crash.
  - Fix (single solution): Persist draft content with size guard and explicit “restore draft” prompt on reopen.
  - Steps:
    1) Store drafts per path with size limit.
    2) On reopen, prompt to restore or discard.
    3) Provide “clear drafts” action.
  - Acceptance Criteria:
    - Reloading the app offers to restore unsaved buffers.
  - Validation Commands: `npm run lint`
  - Migration/Rollback: Drafts are optional and can be cleared.

- ID: EVO-008
  - Priority: P1
  - Theme: UX
  - Problem: Rescan status for partial saves is not visible at the project level.
  - Evidence: `backend/app/api/nodes.py` returns `rescan_task`/`rescan_scheduled` in some branches; UI does not surface global status.
  - Root Cause: No shared UI state for graph freshness.
  - Impact: Users miss necessary rescans and continue with stale graph data.
  - Fix (single solution): Track a “graph stale” flag in app state and show a project-level banner with rescan CTA.
  - Steps:
    1) Set flag when `index_status` is `rescan_scheduled`/`failed`.
    2) Clear flag on successful scan completion.
  - Acceptance Criteria:
    - Banner appears after partial saves and clears after scan.
  - Validation Commands: `npm run lint`
  - Migration/Rollback: UI-only; safe to revert.

- ID: EVO-009
  - Priority: P2
  - Theme: Platform
  - Problem: File mutation endpoints duplicate scan/reindex/rescan logic.
  - Evidence: `backend/app/api/nodes.py` repeated patterns across `update_file`, `create_file`, `rename_file`, `delete_file`.
  - Root Cause: No shared helper/service.
  - Impact: Higher maintenance cost and inconsistent behavior risk.
  - Fix (single solution): Extract a shared service helper to perform “write → scan → reindex → rescan on failure” and reuse across endpoints.
  - Steps:
    1) Create helper in a services module.
    2) Replace repeated logic in endpoints.
    3) Update tests accordingly.
  - Acceptance Criteria:
    - File mutation endpoints call the shared helper.
  - Validation Commands: `pytest`
  - Migration/Rollback: Refactor only; verify behavior parity with tests.

- ID: EVO-010
  - Priority: P1
  - Theme: UX | Reliability
  - Problem: Conflict/rollback statuses are not surfaced to users.
  - Evidence: `backend/app/api/nodes.py` returns `conflict_reason`/`rollback` fields in some branches; UI ignores them.
  - Root Cause: UI does not display error metadata when `saved=true` with partial flags.
  - Impact: Users are unaware of conflicts and stale data.
  - Fix (single solution): Add a dedicated warning banner that surfaces `conflict_reason`/`rollback` and suggests reload/rescan.
  - Steps:
    1) Extend UI state for conflict warnings.
    2) Show banner and actionable buttons (reload file, rescan).
  - Acceptance Criteria:
    - Conflict banners appear when backend returns conflict metadata.
  - Validation Commands: `npm run lint`
  - Migration/Rollback: UI-only change.

- ID: EVO-011
  - Priority: P2
  - Theme: Platform
  - Problem: Developers have no single reference for file-mutation response contract.
  - Evidence: Contract details spread across `backend/app/api/nodes.py` and UI usage.
  - Root Cause: Lack of centralized documentation.
  - Impact: Higher risk of regressions when changing response shapes.
  - Fix (single solution): Add a short developer doc describing the file mutation response contract and state transitions.
  - Steps:
    1) Add doc near API or in repo root.
    2) Link it from relevant code comments.
  - Acceptance Criteria:
    - Doc exists and is referenced in code.
  - Validation Commands: `pytest`
  - Migration/Rollback: Documentation-only change.

- ID: EVO-012
  - Priority: P2
  - Theme: Performance | Platform
  - Problem: Large file lists are returned in a single response without pagination.
  - Evidence: `backend/app/services/project_service.py` (`list_project_files` limit default 50_000).
  - Root Cause: No cursor pagination for file list endpoint.
  - Impact: Large responses and slow clients for big repos.
  - Fix (single solution): Add cursor-based pagination (`cursor`, `next_cursor`) to `list_project_files` similar to tree entries.
  - Steps:
    1) Extend API parameters and response meta.
    2) Update clients to use paging when needed.
  - Acceptance Criteria:
    - API returns `next_cursor` when truncated.
  - Validation Commands: `pytest`
  - Migration/Rollback: Keep old params; default behavior unchanged.

- ID: EVO-013
  - Priority: P2
  - Theme: Performance
  - Problem: Text search reads file contents from disk for each query.
  - Evidence: `backend/app/services/project_service.py` (`search_project_text` opens files to build snippets).
  - Root Cause: Snippet extraction bypasses indexed text storage.
  - Impact: Slow searches for large repos and high I/O.
  - Fix (single solution): Use indexed `filetext` data for snippets when available; fall back to disk read only when necessary.
  - Steps:
    1) Extend `search_text_paths` or add helper to fetch stored text snippets.
    2) Use fallback only for missing indexed data.
  - Acceptance Criteria:
    - Searches avoid disk reads when `filetext` contains content.
  - Validation Commands: `pytest`
  - Migration/Rollback: Fallback preserves old behavior.

- ID: EVO-014
  - Priority: P2
  - Theme: Performance | Reliability
  - Problem: Graph metric recomputation can be expensive and is invoked inline.
  - Evidence: `backend/app/graph.py` `compute_graph_metrics` loads full graphs; invoked by scan and file updates.
  - Root Cause: Synchronous computation on request path.
  - Impact: Slow responses on large repos.
  - Fix (single solution): Move large recomputations to background tasks when size thresholds are exceeded; return “metrics pending” status.
  - Steps:
    1) Add threshold check and task submission.
    2) Update responses to include “metrics pending” indicator.
  - Acceptance Criteria:
    - Large graphs trigger async computation without blocking requests.
  - Validation Commands: `pytest`
  - Migration/Rollback: Keep synchronous path for small graphs.

- ID: EVO-015
  - Priority: P2
  - Theme: Performance | UX
  - Problem: Dependency lists can become too large without pagination, leading to big payloads.
  - Evidence: `backend/app/services/project_service.py` (`get_file_dependencies` uses a limit but no cursor).
  - Root Cause: Missing pagination for dependency edges.
  - Impact: Heavy responses for high fan-in/out files.
  - Fix (single solution): Add cursor/offset pagination for inbound/outbound edges and expose it in UI when needed.
  - Steps:
    1) Extend API with pagination params.
    2) Update UI to load additional pages on demand.
  - Acceptance Criteria:
    - Dependencies can be paged without increasing `limit`.
  - Validation Commands: `pytest`, `npm run lint`
  - Migration/Rollback: Default behavior unchanged unless pagination params provided.

## 4. Explicit Non-Goals
- Rewriting the graph/scanner pipeline or changing scanning algorithms without a concrete defect.
- Adding new LLM features or models outside of the existing task flow.
- Large refactors of frontend architecture (state management migration, routing changes).
- Changing auth defaults or deployment topology without explicit requirements.
