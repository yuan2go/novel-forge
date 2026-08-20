PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PYTHONPATH := src
PYTEST := $(PYTHON) -m pytest
WEB_DIR ?= web/admin
AUTHORITY_COMPOSE ?= docker compose -f compose.yml

.PHONY: test lint lint-authority lint-ratchet validate demo authority-demo infra-up infra-down postgres-authority-test-up postgres-authority-test-down postgres-authority-test authority-up authority-down authority-build authority-smoke authority-logs authority-test authority-postgres-test authority-compose-config-check authority-query-plan-release api worker web-dev sync-skills sync-skills-dry-run check-skills head-integrity-check architecture-manifests-check architecture-fitness-check authority-only-config-check d0-provider-probe help

RUFF ?= ruff
AUTHORITY_RUFF_PATHS := \
	src/novel_forge/modules/agent_runtime \
	src/novel_forge/modules/agent_collaboration \
	src/novel_forge/modules/command_kernel \
	src/novel_forge/modules/production_execution \
	src/novel_forge/modules/chapter_authority

help:
	@echo "make test      - run the canonical pytest suite"
	@echo "make lint      - compile Python sources"
	@echo "make lint-authority - require Ruff-clean Authority production surfaces"
	@echo "make lint-ratchet - reject new or increased repository Ruff debt"
	@echo "make validate  - validate Authority code, manifests, fitness, and Compose configuration"
	@echo "make demo      - run the PostgreSQL Authority fixture/recovery demo"
	@echo "make authority-up - build and start the PostgreSQL Authority backend"
	@echo "make authority-down - stop the PostgreSQL Authority backend"
	@echo "make authority-build - build Authority API and worker images"
	@echo "make authority-smoke - run the isolated Authority Compose recovery smoke"
	@echo "make authority-logs - tail Authority API and worker logs"
	@echo "make authority-test - run local Authority lint, architecture, unit, and acceptance gates"
	@echo "make authority-postgres-test - run non-skippable Authority PostgreSQL tests"
	@echo "make authority-compose-config-check - validate Authority Compose"
	@echo "make authority-query-plan-release - run representative-scale real Planner proof"
	@echo "make infra-up  - start Authority PostgreSQL and object storage"
	@echo "make postgres-authority-test-up - start isolated PostgreSQL authority test service"
	@echo "make postgres-authority-test - run non-skippable authority PostgreSQL tests"
	@echo "make api       - run FastAPI backend"
	@echo "make worker    - run the Chapter Authority worker"
	@echo "make web-dev   - run Next.js admin console"
	@echo "make sync-skills-dry-run - preview syncing skills to .claude/skills"
	@echo "make sync-skills - sync repository skills to .claude/skills"
	@echo "make check-skills - fail if .claude/skills drifts from repository skills"
	@echo "make head-integrity-check - fail on untracked or dangling runtime wiring"
	@echo "make architecture-manifests-check - verify module/migration/worker/test/console manifests"
	@echo "make architecture-fitness-check - enforce import, Legacy, Schema and entry classifications"
	@echo "make authority-only-config-check - validate the Track B production composition"
	@echo "make d0-provider-probe - run the fail-closed D0 Provider qualification probe"

test:
	PYTHONPATH=$(PYTHONPATH) $(PYTEST) tests
	npm --prefix $(WEB_DIR) test

lint:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m compileall -q src tests

lint-authority:
	$(RUFF) check $(AUTHORITY_RUFF_PATHS)

lint-ratchet:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/check_ruff_ratchet.py --ruff $(RUFF)

validate: lint lint-authority lint-ratchet architecture-manifests-check architecture-fitness-check authority-only-config-check

demo: authority-demo

authority-demo:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/verify_authority_compose.py

infra-up:
	$(AUTHORITY_COMPOSE) up -d --wait postgresql object-store

infra-down:
	$(AUTHORITY_COMPOSE) stop postgresql object-store

postgres-authority-test-up:
	docker compose -f compose.postgres-test.yml up -d --wait authority-postgres-test

postgres-authority-test-down:
	docker compose -f compose.postgres-test.yml down

postgres-authority-test:
	NOVEL_FORGE_DATABASE_URL=$${NOVEL_FORGE_DATABASE_URL:-postgresql://novel_forge:novel_forge@localhost:55432/novel_forge_authority_test} \
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_authority_postgres_tests.py

authority-up:
	$(AUTHORITY_COMPOSE) up -d --build --wait --wait-timeout 300

authority-down:
	$(AUTHORITY_COMPOSE) down --timeout 45

authority-build:
	$(AUTHORITY_COMPOSE) build authority-migration authority-api agent-authority-worker chapter-authority-worker content-authority-worker source-authority-worker source-import-worker mkaos-authority-worker book-authority-worker book-followup-authority-worker outbox-worker maintenance-worker

authority-smoke:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/verify_authority_compose.py

authority-logs:
	$(AUTHORITY_COMPOSE) logs -f authority-api agent-authority-worker chapter-authority-worker content-authority-worker source-authority-worker source-import-worker mkaos-authority-worker book-authority-worker book-followup-authority-worker outbox-worker maintenance-worker

authority-test: lint lint-authority lint-ratchet architecture-manifests-check architecture-fitness-check head-integrity-check
	PYTHONPATH=$(PYTHONPATH) $(PYTEST) tests/unit tests/architecture tests/acceptance

authority-postgres-test: postgres-authority-test

authority-compose-config-check:
	$(AUTHORITY_COMPOSE) config --quiet
	docker compose -f compose.postgres-test.yml config --quiet

authority-query-plan-release:
	NOVEL_FORGE_DATABASE_URL=$${NOVEL_FORGE_DATABASE_URL:-postgresql://novel_forge:novel_forge@localhost:55432/novel_forge_authority_test} \
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/qualify_authority_query_plans.py

api:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.cli.authority serve-api

worker:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.workers.chapter_authority

web-dev:
	npm --prefix $(WEB_DIR) run dev

sync-skills-dry-run:
	$(PYTHON) scripts/sync_claude_skills.py --dry-run

sync-skills:
	$(PYTHON) scripts/sync_claude_skills.py

check-skills:
	$(PYTHON) scripts/sync_claude_skills.py --check

head-integrity-check:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.tools.head_integrity --repo-root .

architecture-manifests-check:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/check_module_manifest.py
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/check_migration_manifest.py
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/check_worker_manifest.py
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/check_required_test_manifest.py
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/check_console_script_manifest.py

architecture-fitness-check:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/check_architecture_fitness.py

authority-only-config-check:
	$(AUTHORITY_COMPOSE) config --quiet

d0-provider-probe:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_d0_provider_probe.py
