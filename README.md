# Novalton OS

Novalton OS is an AI-native operating system foundation for coordinating governed, specialized AI capabilities. This repository currently contains only the I-001 monorepo scaffold; agents, authentication, memory, policy, and orchestration are intentionally out of scope.

## Prerequisites

- Python 3.12 or newer
- Node.js 22 or newer and npm 10 or newer
- Docker with Docker Compose v2

## Configuration

Copy the development environment template and keep local values out of Git:

```bash
cp .env.example .env
```

The defaults are suitable for the development containers. No provider credentials are required for this scaffold.

## Start infrastructure

```bash
docker compose --env-file .env -f infra/compose.yaml up -d
docker compose --env-file .env -f infra/compose.yaml ps
```

PostgreSQL, Redis, and Qdrant use named volumes and expose development-only ports on localhost.

## Run the API

```bash
python3 -m venv apps/api/.venv
apps/api/.venv/bin/pip install -e './apps/api[dev]'
apps/api/.venv/bin/uvicorn novalton_api.main:app --reload --app-dir apps/api/src
```

The health endpoint is available at <http://127.0.0.1:8000/api/v1/health>.

## Run the web app

```bash
npm install
npm run dev
```

The web app is available at <http://localhost:3000>.

## Verification

```bash
npm run lint
npm run typecheck
apps/api/.venv/bin/ruff check apps/api
apps/api/.venv/bin/pytest apps/api
docker compose --env-file .env.example -f infra/compose.yaml config
```

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
