SHELL := /bin/sh

ENV_FILE ?= .env
COMPOSE := docker compose --env-file $(ENV_FILE) -f infra/compose.yaml
API_VENV ?= apps/api/.venv
API_PYTHON := $(API_VENV)/bin/python
API_RUFF := $(API_VENV)/bin/ruff
API_PYTEST := $(API_VENV)/bin/pytest

.PHONY: help setup-env setup-test-env dev-shell test-shell dev-api dev-db-check test-db-check test db-upgrade db-current db-downgrade db-check test-db-upgrade test-db-current db-bootstrap backend-check frontend-check dependency-audit verify

help:
	@echo "Novalton OS development commands"
	@echo "  make setup-env       Create .env from .env.example if missing"
	@echo "  make setup-test-env  Create .env.test from .env.test.example if missing"
	@echo "  make dev-shell       Open a clean validated development child shell"
	@echo "  make test-shell      Open a clean validated test child shell"
	@echo "  make dev-api         Start the API with the validated development profile"
	@echo "  make dev-db-check    Prove the development database identity safely"
	@echo "  make test-db-check   Prove the isolated test database identity safely"
	@echo "  make test            Run pytest in the validated test profile"
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

setup-test-env:
	@if [ -f .env.test ]; then \
		echo ".env.test already exists; leaving it unchanged"; \
	else \
		cp .env.test.example .env.test; \
		echo "Created .env.test from .env.test.example."; \
		echo "ACTION REQUIRED: replace the placeholder PostgreSQL credentials in both .env.test URLs."; \
		echo "Use the trusted local Compose/development role (or an intentionally separate local role), keep novalton_test, then run make test-db-check."; \
	fi

dev-shell:
	NOVALTON_PROFILE_VALIDATOR="$(API_PYTHON)" scripts/with-profile.sh development -- "$$SHELL"

test-shell:
	NOVALTON_PROFILE_VALIDATOR="$(API_PYTHON)" scripts/with-profile.sh test -- "$$SHELL"

dev-api:
	NOVALTON_PROFILE_VALIDATOR="$(API_PYTHON)" scripts/with-profile.sh development -- $(API_PYTHON) -m uvicorn novalton_api.main:app --reload --app-dir apps/api/src

dev-db-check:
	NOVALTON_PROFILE_VALIDATOR="$(API_PYTHON)" scripts/with-profile.sh development -- $(API_PYTHON) -m novalton_api.core.environment db-check

test-db-check:
	NOVALTON_PROFILE_VALIDATOR="$(API_PYTHON)" scripts/with-profile.sh test -- $(API_PYTHON) -m novalton_api.core.environment db-check

test:
	NOVALTON_PROFILE_VALIDATOR="$(API_PYTHON)" scripts/with-profile.sh test -- $(API_PYTEST) apps/api

infra-config:
	$(COMPOSE) config --quiet

infra-up: infra-config
	$(COMPOSE) up -d --wait

infra-down:
	$(COMPOSE) down

infra-status:
	$(COMPOSE) ps

db-upgrade:
	NOVALTON_PROFILE_VALIDATOR="$(API_PYTHON)" NOVALTON_PROFILE_REQUIRE_DB_IDENTITY=1 scripts/with-profile.sh development -- $(API_VENV)/bin/alembic -c apps/api/alembic.ini upgrade head

db-current:
	NOVALTON_PROFILE_VALIDATOR="$(API_PYTHON)" NOVALTON_PROFILE_REQUIRE_DB_IDENTITY=1 scripts/with-profile.sh development -- $(API_VENV)/bin/alembic -c apps/api/alembic.ini current

db-downgrade:
	NOVALTON_PROFILE_VALIDATOR="$(API_PYTHON)" NOVALTON_PROFILE_REQUIRE_DB_IDENTITY=1 scripts/with-profile.sh development -- $(API_VENV)/bin/alembic -c apps/api/alembic.ini downgrade -1

test-db-upgrade:
	NOVALTON_PROFILE_VALIDATOR="$(API_PYTHON)" NOVALTON_PROFILE_REQUIRE_DB_IDENTITY=1 scripts/with-profile.sh test -- $(API_VENV)/bin/alembic -c apps/api/alembic.ini upgrade head

test-db-current:
	NOVALTON_PROFILE_VALIDATOR="$(API_PYTHON)" NOVALTON_PROFILE_REQUIRE_DB_IDENTITY=1 scripts/with-profile.sh test -- $(API_VENV)/bin/alembic -c apps/api/alembic.ini current

db-check:
	$(MAKE) db-upgrade
	$(MAKE) db-current
	$(MAKE) db-downgrade
	$(MAKE) db-upgrade

db-bootstrap:
	NOVALTON_PROFILE_VALIDATOR="$(API_PYTHON)" NOVALTON_PROFILE_REQUIRE_DB_IDENTITY=1 scripts/with-profile.sh development -- $(API_PYTHON) -m novalton_api.bootstrap

backend-check:
	@test -x "$(API_PYTHON)" || { \
		echo "Missing $(API_PYTHON). Create the backend virtual environment first." >&2; \
		exit 1; \
	}
	$(API_RUFF) check apps/api
	$(API_RUFF) format --check apps/api
	$(MAKE) test

frontend-check:
	npm run lint
	npm run typecheck
	npm run build

dependency-audit:
	$(API_PYTHON) -m pip_audit
	npm audit --audit-level=high

verify: infra-config backend-check frontend-check dependency-audit
