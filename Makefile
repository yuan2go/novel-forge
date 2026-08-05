PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PYTHONPATH := src
WEB_DIR ?= web/admin
LOCAL_WORKSPACE ?= .local/workspace
DEMO_WORKSPACE ?= .local/demo-workspace
AUTHORITY_COMPOSE ?= docker compose -f compose.yml
LEGACY_COMPOSE ?= docker compose -f compose.legacy.yml --profile legacy

.PHONY: test lint validate demo authority-demo legacy-validate legacy-demo local-workspace infra-up infra-down postgres-authority-test-up postgres-authority-test-down postgres-authority-test authority-up authority-down authority-build authority-smoke authority-logs authority-test authority-postgres-test authority-compose-config-check authority-query-plan-release legacy-up legacy-down legacy-logs local-up local-down local-smoke local-logs failure-drill v1-slow-acceptance governance-dead-letter-regression runtime-growth-regression source-governance-regression api worker web-dev sync-skills sync-skills-dry-run check-skills authority-parity-check head-integrity-check architecture-manifests-check architecture-fitness-check authority-only-config-check d0-provider-probe help

help:
	@echo "make test      - run stdlib unittest suite"
	@echo "make lint      - compile Python sources"
	@echo "make validate  - validate Authority code, manifests, fitness, and Compose configuration"
	@echo "make demo      - run the PostgreSQL Authority fixture/recovery demo"
	@echo "make legacy-validate - explicitly validate a Legacy development workspace"
	@echo "make legacy-demo - explicitly run the Legacy development fixture"
	@echo "make local-workspace - create ignored local runtime workspace"
	@echo "make authority-up - build and start the PostgreSQL Authority backend"
	@echo "make authority-down - stop the PostgreSQL Authority backend"
	@echo "make authority-build - build Authority API and worker images"
	@echo "make authority-smoke - run the isolated Authority Compose recovery smoke"
	@echo "make authority-logs - tail Authority API and worker logs"
	@echo "make authority-test - run local Authority lint, architecture, unit, and acceptance gates"
	@echo "make authority-postgres-test - run non-skippable Authority PostgreSQL tests"
	@echo "make authority-compose-config-check - validate Authority and explicit Legacy Compose"
	@echo "make authority-query-plan-release - run representative-scale real Planner proof"
	@echo "make legacy-up - explicitly start the Legacy development profile"
	@echo "make legacy-down - stop the explicit Legacy development profile"
	@echo "make legacy-logs - tail explicit Legacy profile logs"
	@echo "make infra-up  - start Authority PostgreSQL and object storage"
	@echo "make postgres-authority-test-up - start isolated PostgreSQL authority test service"
	@echo "make postgres-authority-test - run non-skippable authority PostgreSQL tests"
	@echo "make local-up/local-down/local-smoke/local-logs - compatibility aliases for Authority targets"
	@echo "make failure-drill - run non-destructive failure recovery drill"
	@echo "make v1-slow-acceptance - run explicit 10-chapter V1 slow acceptance"
	@echo "make governance-dead-letter-regression - run focused governance dead-letter regression"
	@echo "make runtime-growth-regression - run focused runtime write-growth regression"
	@echo "make source-governance-regression - run focused source governance regression"
	@echo "make api       - run FastAPI backend"
	@echo "make worker    - run Celery worker"
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
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests -p 'test_*.py'
	npm --prefix $(WEB_DIR) test

lint:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m compileall -q src tests

validate: lint architecture-manifests-check architecture-fitness-check authority-only-config-check

local-workspace:
	mkdir -p $(LOCAL_WORKSPACE)

demo: authority-demo

authority-demo:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/verify_authority_compose.py

legacy-validate: local-workspace
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.cli legacy validate --root $(LOCAL_WORKSPACE)

legacy-demo: local-workspace
	mkdir -p $(DEMO_WORKSPACE)
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.cli legacy run-pipeline --sample --root $(DEMO_WORKSPACE)

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
	$(AUTHORITY_COMPOSE) build authority-migration authority-api agent-authority-worker chapter-authority-worker content-authority-worker source-authority-worker mkaos-authority-worker book-authority-worker outbox-worker maintenance-worker

authority-smoke:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/verify_authority_compose.py

authority-logs:
	$(AUTHORITY_COMPOSE) logs -f authority-api agent-authority-worker chapter-authority-worker content-authority-worker source-authority-worker mkaos-authority-worker book-authority-worker outbox-worker maintenance-worker

authority-test: lint architecture-manifests-check architecture-fitness-check head-integrity-check
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests/unit -p 'test_*.py'
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests/acceptance -p 'test_*.py'

authority-postgres-test: postgres-authority-test

authority-compose-config-check:
	$(AUTHORITY_COMPOSE) config --quiet
	docker compose -f compose.postgres-test.yml config --quiet
	$(LEGACY_COMPOSE) config --quiet

authority-query-plan-release:
	NOVEL_FORGE_DATABASE_URL=$${NOVEL_FORGE_DATABASE_URL:-postgresql://novel_forge:novel_forge@localhost:55432/novel_forge_authority_test} \
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/qualify_authority_query_plans.py

legacy-up:
	$(LEGACY_COMPOSE) up -d --build

legacy-down:
	$(LEGACY_COMPOSE) down

legacy-logs:
	$(LEGACY_COMPOSE) logs -f legacy-api legacy-worker legacy-redis

local-up: authority-up

local-down: authority-down

local-smoke: authority-smoke

local-logs: authority-logs

failure-drill:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/failure_drill.py

v1-slow-acceptance:
	PYTHONPATH=$(PYTHONPATH) NOVEL_FORGE_MODEL_PROVIDER=$${NOVEL_FORGE_MODEL_PROVIDER:-mock} $(PYTHON) scripts/run_v1_chapter_sequence_acceptance.py --chapter-count 10

governance-dead-letter-regression:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_governance_dead_letter_regression.py

runtime-growth-regression:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_runtime_growth_regression.py

source-governance-regression:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_source_governance_regression.py

api:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.cli serve-api

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

authority-parity-check: head-integrity-check
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.tools.authority_parity_manifest --repo-root .
