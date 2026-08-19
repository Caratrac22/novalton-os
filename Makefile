SHELL := /bin/sh

ENV_FILE ?= .env
COMPOSE := docker compose --env-file $(ENV_FILE) -f infra/compose.yaml
API_VENV ?= apps/api/.venv
API_PYTHON := $(API_VENV)/bin/python
API_RUFF := $(API_VENV)/bin/ruff
API_PYTEST := $(API_VENV)/bin/pytest

.PHONY: help setup-env infra-config infra-up infra-down infra-status backend-check frontend-check verify

help:
	@echo "Novalton OS development commands"
	@echo "  make setup-env       Create .env from .env.example if missing"
	@echo "  make infra-config    Validate the Docker Compose configuration"
	@echo "  make infra-up        Start infrastructure and wait for healthy services"
	@echo "  make infra-status    Show infrastructure container and health status"
	@echo "  make infra-down      Stop infrastructure while preserving named volumes"
	@echo "  make backend-check   Run backend lint, format check, and tests"
	@echo "  make frontend-check  Run frontend lint, typecheck, and production build"
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

verify: infra-config backend-check frontend-check
