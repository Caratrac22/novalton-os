SHELL := /bin/sh

ENV_FILE ?= .env
COMPOSE := docker compose --env-file $(ENV_FILE) -f infra/compose.yaml
API_VENV ?= apps/api/.venv
API_PYTHON := $(API_VENV)/bin/python
API_RUFF := $(API_VENV)/bin/ruff
API_PYTEST := $(API_VENV)/bin/pytest

.PHONY: help setup-env infra-config infra-up infra-down infra-status db-upgrade db-current db-downgrade db-check db-bootstrap backend-check frontend-check dependency-audit verify

help:
	@echo "Novalton OS development commands"
	@echo "  make setup-env       Create .env from .env.example if missing"
	@echo "  make infra-config    Validate the Docker Compose configuration"
	@echo "  make infra-up        Start infrastructure and wait for healthy services"
	@echo "  make infra-status    Show infrastructure container and health status"
	@echo "  make infra-down      Stop infrastructure while preserving named volumes"
	@echo "  make db-upgrade      Upgrade PostgreSQL to the latest Alembic revision"
	@echo "  make db-current      Show the current PostgreSQL Alembic revision"
	@echo "  make db-downgrade    Downgrade PostgreSQL by one Alembic revision"
	@echo "  make db-check        Run upgrade/current/downgrade/upgrade migration smoke test"
	@echo "  make db-bootstrap    Create the idempotent local tenant/workspace scope"
	@echo "  make backend-check   Run backend lint, format check, and tests"
	@echo "  make frontend-check  Run frontend lint, typecheck, and production build"
	@echo "  make dependency-audit Audit Python and npm dependencies for vulnerabilities"
	@echo "  make verify          Run Compose validation and all application checks"

setup-env:
	@if [ -f "$(ENV_FILE)" ]; then \
		echo "$(ENV_FILE) already exists; leaving it unchanged"; \
	else \
		cp .env.example "$(ENV_FILE)"; \
		echo "Created $(ENV_FILE) from .env.example"; \
	fi

infra-config:
	$(COMPOSE) config --quiet

infra-up: infra-config
	$(COMPOSE) up -d --wait

infra-down:
	$(COMPOSE) down

infra-status:
	$(COMPOSE) ps

db-upgrade:
	set -a; . "./$(ENV_FILE)"; set +a; $(API_VENV)/bin/alembic -c apps/api/alembic.ini upgrade head

db-current:
	set -a; . "./$(ENV_FILE)"; set +a; $(API_VENV)/bin/alembic -c apps/api/alembic.ini current

db-downgrade:
	set -a; . "./$(ENV_FILE)"; set +a; $(API_VENV)/bin/alembic -c apps/api/alembic.ini downgrade -1

db-check:
	$(MAKE) db-upgrade
	$(MAKE) db-current
	$(MAKE) db-downgrade
	$(MAKE) db-upgrade

db-bootstrap:
	set -a; . "./$(ENV_FILE)"; set +a; $(API_PYTHON) -m novalton_api.bootstrap

backend-check:
	@test -x "$(API_PYTHON)" || { \
		echo "Missing $(API_PYTHON). Create the backend virtual environment first." >&2; \
		exit 1; \
	}
	$(API_RUFF) check apps/api
	$(API_RUFF) format --check apps/api
	$(API_PYTEST) apps/api

frontend-check:
	npm run lint
	npm run typecheck
	npm run build

dependency-audit:
	$(API_PYTHON) -m pip_audit
	npm audit --audit-level=high

verify: infra-config backend-check frontend-check dependency-audit
