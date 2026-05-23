# StubGraph

StubGraph is a full-stack code intelligence application: a FastAPI backend builds and serves project graph data, while a React/Vite frontend provides graph exploration, search, task execution, and in-browser file editing workflows.

## Overview

StubGraph manages projects per organization, indexes repository files into graph structures, and exposes APIs for graph traversal, node/file inspection, semantic/text search, and asynchronous analysis tasks.

The backend runs as an API plus ARQ workers with Redis and PostgreSQL dependencies. The frontend is a single-page app served by Vite in development and Nginx in containerized runtime.

## Features

- Organization-scoped projects with role-gated API access.
- Project ingestion from local root path or uploaded snapshot archive.
- Graph scanning and retrieval (`full` and local neighborhood graph modes).
- File/node search, semantic search, and text search endpoints.
- Async task execution (scan, docs, mutation indexing, analysis) through ARQ queues.
- In-app workspace with graph canvas, project sidebar, node panel, command palette, notifications, and file editor.

## Repository Structure

| Path | Purpose |
|---|---|
| `backend/app/main.py` | FastAPI entrypoint, middleware stack, router registration, health endpoint. |
| `backend/app/api/` | HTTP route handlers for auth, orgs, projects, nodes, tasks, config. |
| `backend/app/services/` | Service-layer business logic for projects, tasks, auth, docs, orgs, usage. |
| `backend/app/llm/` | LLM orchestration, routing, policy, and agentic tool modules. |
| `backend/alembic/` | Database migration environment and migration revisions. |
| `backend/tests/` | Backend service/API/LLM contract and runtime tests. |
| `frontend/src/ui/` | Main UI shell, hooks, and components for graph/editor workflows. |
| `frontend/src/api/` | Frontend API client functions and typed request/response contracts. |
| `docker-compose.yml` | Multi-service local runtime (proxy, frontend, backend, workers, postgres, redis). |
| `infra/nginx/stubgraph.conf` | Reverse proxy configuration used by the `proxy` service. |

## Quick Start

### Prerequisites

- Docker and Docker Compose.
- For non-container local frontend dev: Node.js + npm.
- For non-container backend dev/testing: Python 3.11.
- Running PostgreSQL and Redis reachable via configured URLs.

### Installation

```bash
# 1) Clone and enter repository
git clone <repo-url>
cd stubgraph

# 2) Prepare environment values (compose reads from shell/.env)
# Required at minimum for compose services:
# STUBGRAPH_DATABASE_URL, STUBGRAPH_REDIS_URL,
# POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD,
# STUBGRAPH_CORS_ALLOW_ORIGINS, VITE_API_BASE_URL
```

### Configuration

| Variable | Purpose | Required | Source |
|---|---|---|---|
| `STUBGRAPH_DATABASE_URL` | Async SQLAlchemy/Postgres connection string used by API/workers/migrations. | yes | `backend/app/config.py`, `docker-compose.yml` |
| `STUBGRAPH_REDIS_URL` | Redis broker/cache URL for API and ARQ workers. | yes | `backend/app/config.py`, `docker-compose.yml` |
| `STUBGRAPH_CORS_ALLOW_ORIGINS` | Comma-separated allowed CORS origins for API middleware. | yes | `backend/app/config.py`, `docker-compose.yml` |
| `STUBGRAPH_AUTH_ENABLED` | Enables API auth middleware for `/api*` routes. | no | `backend/app/config.py`, `docker-compose.yml` |
| `OPENAI_API_KEY` | Enables OpenAI-backed LLM calls when agentic/LLM paths are used. | unknown | `backend/app/config.py`, `docker-compose.yml` |
| `VITE_API_BASE_URL` | Frontend API base URL injected at build/runtime. | yes | `docker-compose.yml`, `frontend/Dockerfile` |

### Run Locally

```bash
# Full stack via containers
docker compose up --build

# Optional: run DB migrations explicitly
docker compose run --rm migrations
```

Frontend-only local dev (against an existing API):

```bash
cd frontend
npm install
npm run dev
```

## Commands

| Command | Purpose | Notes |
|---|---|---|
| `docker compose up --build` | Starts proxy, frontend, backend, migrations, workers, postgres, redis. | Run at repository root. |
| `docker compose run --rm migrations` | Applies Alembic migrations to head. | Requires DB connectivity and `STUBGRAPH_DATABASE_URL`. |
| `cd frontend && npm run dev` | Starts Vite dev server. | Requires `VITE_API_BASE_URL` for API calls. |
| `cd frontend && npm run build` | Type-check + production frontend build. | Uses `tsc -b && vite build`. |
| `cd frontend && npm run test` | Runs frontend test suite via Vitest. | Non-watch CI-style run. |
| `cd frontend && npm run lint` | TypeScript no-emit check. | Script is `tsc --noEmit --pretty false`. |
| `cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000` | Runs backend API server directly. | Requires Python deps + configured env + DB/Redis access. |

## Architecture

- **API runtime**: `backend/app/main.py` defines FastAPI app lifecycle, CORS, rate limiting, auth guard, and request-scoped DB session lifecycle.
- **Service boundaries**: route handlers in `backend/app/api/` call async service modules in `backend/app/services/`; queue submission is centralized through `app.services.task_queue`.
- **Persistence**: SQLModel entities in `backend/app/models.py`; schema evolution via Alembic revisions in `backend/alembic/versions/`.
- **Background jobs**: ARQ workers use `app.arq_worker.WorkerSettings` with queue separation (`light`, `medium`, `heavy`) configured in compose.
- **UI runtime**: React app bootstraps from `frontend/src/main.tsx`; top-level workspace composition is in `frontend/src/ui/App.tsx` with state/operations in `frontend/src/ui/useStubGraphApp.ts`.

## Data and Integrations

| Service / System | Purpose | Evidence |
|---|---|---|
| PostgreSQL | Primary relational store for projects, graph data, users/sessions, runs, telemetry. | `backend/app/models.py`, `docker-compose.yml` |
| Redis | Cache/rate-limit backend and ARQ task broker. | `backend/app/config.py`, `docker-compose.yml`, `backend/app/infra/*.py` |
| OpenAI API | LLM orchestration/agentic analysis features. | `backend/app/config.py`, `backend/app/llm/` |
| S3-compatible storage (optional) | Snapshot/patch blob storage when backend set to `s3`. | `backend/app/config.py`, `docker-compose.yml`, `backend/app/storage.py` |
| Nginx | Reverse proxy and static frontend serving in container deployments. | `infra/nginx/stubgraph.conf`, `frontend/nginx.conf`, `docker-compose.yml` |

## UI and Design

User-facing UI is a SPA composed around:

- `ProjectsSidebar` for project/org context and switching.
- `GraphCanvas` for visual graph exploration.
- `NodePanel` and task panel behavior controlled by `useStubGraphApp`.
- Editor surfaces (`FileEditorPane`, `ExplorerTree`, command palette, modals, notifications).

`DESIGN.md` was not found in the repository root, so visual/design authority is currently embedded in implementation and component-level styling.

## Domain Rules and Invariants

- API auth guard applies to `/api` and `/api/v1` except `/health` and auth endpoints when `STUBGRAPH_AUTH_ENABLED=true`.
- Organization and project access checks are enforced before project/task operations (`require_org_context_async`, `require_project_access_async`).
- Task queue submission uses async-only contract (`submit_*_async`) and ARQ-based dispatch.
- Database uniqueness constraints enforce key invariants (e.g., unique user email, per-project unique file path, unique edges by `(project_id, src, dst, kind)`).

## Validation

```bash
# Compose manifest validation
docker compose config

# Frontend validation scripts from package.json
cd frontend && npm run lint
cd frontend && npm run test
cd frontend && npm run build
```

- `docker compose config` validates service wiring and environment interpolation in `docker-compose.yml`.
- Frontend scripts are explicitly defined in `frontend/package.json`.
- No backend lint/test script is declared in repository task runners/manifests; backend validation is typically executed via project-specific pytest selection outside a documented root script.

## Deployment / Runtime

- Container runtime is defined in `docker-compose.yml`.
- Backend image starts `uvicorn app.main:app` via `backend/entrypoint.sh`.
- Frontend image is built by Vite and served through Nginx.
- Reverse proxy service exposes port `80` and routes to frontend/backend based on `infra/nginx/stubgraph.conf`.

## Common Workflows

- Create/list/delete org-scoped projects through `/api/projects` routes.
- Trigger project scan via `/api/projects/{project_id}/scan` and poll task status APIs.
- Use graph and search endpoints (`/graph`, `/graph/local`, `/search`, `/search/semantic`, `/search/text`) to power UI exploration and retrieval.
- Upload snapshot archives via `/api/projects/from-snapshot` for non-local project import.

## Troubleshooting

- `401 unauthorized` on API requests: verify auth token flow and `STUBGRAPH_AUTH_ENABLED` setting.
- Missing CORS access from frontend: verify `STUBGRAPH_CORS_ALLOW_ORIGINS` includes your dev host/port.
- Background jobs not processing: verify Redis availability and ARQ worker containers are running.
- Graph/search outputs stale or empty: ensure project scan task has completed successfully.

## Open Questions

- The canonical backend validation entrypoint (single repo-defined test/lint command) is unknown because no root Makefile/script target or CI workflow was found in inspected files.
- Required minimum environment variable set for fully functional LLM/agentic flows is partially implicit in code (no dedicated `.env.example` was found).
