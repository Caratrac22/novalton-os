# Novalton OS

Novalton OS is an AI-native operating system foundation for coordinating governed, specialized AI capabilities. This repository currently contains the initial monorepo and local development infrastructure; agents, authentication, memory, policy, and orchestration are intentionally out of scope.

## Prerequisites

- Python 3.13.x (3.13.15 is the pinned CI/development baseline; Python 3.14 is not yet supported)
- Node.js 24.x LTS (24.19.0 is the pinned CI/development baseline) with its bundled npm
- Docker with Docker Compose v2

## Configuration

Create the ignored local environment file from the safe development template:

```bash
make setup-env
```

The command is repeatable and never overwrites an existing `.env`. The documented defaults bind infrastructure ports to localhost and are intended only for local development. No provider credentials are required.

## Start infrastructure

```bash
make infra-config
make infra-up
make infra-status
```

`make infra-up` waits until PostgreSQL, Redis, and Qdrant report healthy. They use named volumes and predictable localhost ports:

| Service | Local endpoint | Default port |
|---|---|---:|
| PostgreSQL | `localhost` | `5432` |
| Redis | `localhost` | `6379` |
| Qdrant HTTP | <http://localhost:6333> | `6333` |
| Qdrant gRPC | `localhost` | `6334` |

Ports and development credentials can be changed in `.env`. Docker Compose remains the source of truth in `infra/compose.yaml`.

## Run the API

```bash
python3 -m venv apps/api/.venv
apps/api/.venv/bin/pip install -e './apps/api[dev]'
apps/api/.venv/bin/uvicorn novalton_api.main:app --reload --app-dir apps/api/src
```

The liveness endpoint is available at <http://127.0.0.1:8000/api/v1/health>. PostgreSQL
connectivity is reported separately at <http://127.0.0.1:8000/api/v1/health/dependencies>;
failures return a sanitized `503` response.

The backend reads `NOVALTON_ENV`, `NOVALTON_LOG_LEVEL`, `DATABASE_URL`, `REDIS_URL`, and
`QDRANT_URL` from the process environment. SQLAlchemy uses asyncpg for PostgreSQL access;
credentials and credential-bearing URLs are never included in application health responses.

Apply and inspect the Alembic baseline after PostgreSQL is healthy:

```bash
make db-upgrade
make db-current
```

`make db-check` runs the full upgrade/current/downgrade/upgrade smoke flow. Revision
`20260820_0002` adds the I-005 `tenants` and tenant-scoped `workspaces` tables after the empty
I-004 baseline. Revision `20260820_0003` adds only the I-006 workspace-scoped `projects` table.

Create the deterministic local development scope explicitly after migrating:

```bash
make db-bootstrap
```

The command creates one `tenant_local` tenant and its `workspace_default` workspace using the
stable UUIDs configured in `.env`. It is transactionally idempotent, refuses conflicting existing
records, and is disabled when `NOVALTON_ENV=production`. It never creates users or other business
records.

Every HTTP response includes `X-Correlation-ID`. A client may supply this header using 1–128 ASCII letters, digits, `.`, `_`, `:`, or `-`; invalid or missing values are replaced with a generated `req_...` identifier. The same identifier is attached to request-scoped structured logs and deterministic API error responses.

Projects are exposed only through an explicit tenant and workspace path:

```text
POST   /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/projects
GET    /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/projects
GET    /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/projects/{project_id}
PATCH  /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/projects/{project_id}
DELETE /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/projects/{project_id}
```

Every operation first verifies that the workspace belongs to the supplied tenant. Project reads
and mutations then retain workspace scope, and inaccessible or unknown scope combinations return
the same not-found response. Lists use stable creation-time/UUID ordering and accept `limit`
(default 50, maximum 100) plus `offset`.

## Run the web app

```bash
npm install
npm run dev
```

The web app is available at <http://localhost:3000>.

## Development checks

Run each application check set independently:

```bash
make backend-check
make frontend-check
```

`backend-check` runs Ruff linting, Ruff formatting validation, and pytest. `frontend-check` runs ESLint, TypeScript checking, and a production Next.js build. Audit installed Python dependencies and the npm lockfile with:

```bash
make dependency-audit
```

Run the complete local verification set, including Compose validation and dependency vulnerability audits:

```bash
make verify
```

## Stop infrastructure

```bash
make infra-down
```

This stops and removes the development containers and network while preserving the named PostgreSQL, Redis, and Qdrant volumes. A later `make infra-up` reuses the stored development data.

Run `make help` to list the supported developer commands.

## Repository layout

```text
apps/api           FastAPI modular-monolith foundation
apps/web           Next.js application
apps/node          Future Novalton Node placeholder
packages/contracts Future shared contracts
packages/ui        Future shared UI components
packages/sdk       Future client SDK
infra              Development infrastructure and migration placeholders
scripts            Repository automation placeholders
```
