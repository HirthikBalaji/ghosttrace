# GHOSTTRACE — local commands (same as CI). Synthetic demo only.
SHELL := /bin/bash
BACK := cd backend &&
export GT_DEMO_TOKEN ?= dev-demo-token

.PHONY: help check-env up down falkordb install seed reset api web test test-unit test-integration e2e evals evals-quick lint typecheck audit secrets ci backup restore start stop

help:  ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'

start:  ## start all services (FalkorDB, API, UI) locally without Docker
	scripts/start_all.sh

stop:  ## stop all local services
	scripts/stop_all.sh

check-env:  ## verify toolchain + FalkorDB client smoke test
	scripts/check_environment.sh

install:  ## install backend + frontend deps (pinned lockfiles)
	$(BACK) uv sync --frozen
	cd frontend && npm ci --no-audit --no-fund

falkordb:  ## start FalkorDB locally without Docker
	scripts/start_falkordb.sh

up:  ## full stack in Docker: http://localhost:8080 (API :8000)
	docker compose up -d --build

down:  ## stop the stack (data volume kept)
	docker compose down

seed:  ## seed workspace 'demo' with Ghost Credential A
	$(BACK) uv run python ../scripts/seed_demo.py ghost_credential_a demo

reset: seed  ## alias: reset the demo workspace

api:  ## run API locally on :8000
	$(BACK) uv run uvicorn app.main:app --port 8000

web:  ## run the UI dev server on :5174 (proxies /api to :8000)
	cd frontend && npm run dev

test:  ## all backend tests (unit, property, integration — needs FalkorDB)
	$(BACK) uv run pytest -p no:warnings

test-unit:
	$(BACK) uv run pytest -p no:warnings -m "not integration"

test-integration:
	$(BACK) uv run pytest -p no:warnings -m integration

e2e:  ## Playwright e2e + axe (needs `make api` running and FalkorDB)
	cd frontend && npx vite build && npx playwright test

evals:  ## full evaluation → evals/report.md (fails on any soundness violation)
	$(BACK) uv run python ../evals/run_evals.py --n 100 --falkordb

evals-quick:
	$(BACK) uv run python ../evals/run_evals.py --quick

lint:
	$(BACK) uv run ruff check app tests ../verifier ../evals && uv run ruff format --check app tests ../verifier ../evals

typecheck:
	$(BACK) uv run mypy app ../verifier
	cd frontend && npx tsc --noEmit -p tsconfig.json

audit:  ## dependency audits
	$(BACK) uv export --frozen --no-hashes --format requirements-txt > ../.artifacts/requirements.txt && uv run pip-audit -r ../.artifacts/requirements.txt
	cd frontend && npm audit --omit=dev

secrets:  ## lightweight secret scan of tracked files
	scripts/secret_scan.sh

ci: lint typecheck test evals-quick secrets  ## what CI runs (plus e2e/audit jobs)

backup:  ## snapshot the FalkorDB volume to ./backups
	scripts/backup_falkordb.sh

restore:  ## restore from BACKUP=backups/<file>.tgz
	scripts/restore_falkordb.sh $(BACKUP)
