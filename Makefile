PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PYTHONPATH := src
PYTEST := $(PYTHON) -m pytest
WEB_DIR ?= web/admin
AUTHORITY_COMPOSE ?= docker compose -f compose.yml
QUALIFICATION_COMPOSE ?= $(if $(strip $(NOVEL_FORGE_DOCKER_COMPOSE_BIN)),$(NOVEL_FORGE_DOCKER_COMPOSE_BIN),docker compose)
P0_PROFILE ?= local
P0_EVIDENCE_DIR ?= /tmp/novel-forge-p0
QUALIFICATION_CONFIG_TOKEN := 00000000000000000000000000000000
QUALIFICATION_CONFIG_RUN_ID := p0-$(QUALIFICATION_CONFIG_TOKEN)
QUALIFICATION_CONFIG_PROJECT := nf-p0-$(QUALIFICATION_CONFIG_TOKEN)-config
QUALIFICATION_CONFIG_DATABASE := nf_p0_$(QUALIFICATION_CONFIG_TOKEN)_test

.PHONY: test lint lint-authority lint-ratchet validate demo authority-demo infra-up infra-down postgres-authority-test authority-up authority-down authority-build authority-smoke authority-logs authority-test authority-postgres-test authority-compose-config-check authority-query-plan-release p0-backend-list-gates p0-backend-static p0-backend-qualification api worker web-dev sync-skills sync-skills-dry-run check-skills instruction-reality-check test-reality-check head-integrity-check architecture-manifests-check architecture-fitness-check authority-only-config-check documentation-reality-check d0-provider-probe real-provider-qualification help

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
	@echo "make demo      - run the canonical exact-SHA P0 backend qualification"
	@echo "make authority-up - build and start the PostgreSQL Authority backend"
	@echo "make authority-down - stop the PostgreSQL Authority backend"
	@echo "make authority-build - build Authority API and worker images"
	@echo "make authority-smoke - alias the canonical exact-SHA P0 backend qualification"
	@echo "make authority-logs - tail Authority API and worker logs"
	@echo "make authority-test - run local Authority lint, architecture, unit, and acceptance gates"
	@echo "make authority-postgres-test - run non-skippable Authority PostgreSQL tests"
	@echo "make authority-compose-config-check - validate Authority Compose"
	@echo "make authority-query-plan-release - run representative-scale real Planner proof"
	@echo "make p0-backend-list-gates - print the canonical backend gate list as JSON"
	@echo "make p0-backend-static - run backend-only static and manifest checks"
	@echo "make p0-backend-qualification - run exact-SHA backend qualification without Admin UI"
	@echo "make infra-up  - start Authority PostgreSQL and object storage"
	@echo "make postgres-authority-test - run the complete collection against a caller-owned isolated database"
	@echo "make api       - run FastAPI backend"
	@echo "make worker    - run the Chapter Authority worker"
	@echo "make web-dev   - run Next.js admin console"
	@echo "make sync-skills-dry-run - preview syncing skills to .claude/skills"
	@echo "make sync-skills - sync repository skills to .claude/skills"
	@echo "make check-skills - fail if .claude/skills drifts from repository skills"
	@echo "make instruction-reality-check - verify every repository AI instruction source and copy"
	@echo "make test-reality-check - classify every retained test and enforce proof ceilings"
	@echo "make head-integrity-check - fail on untracked or dangling runtime wiring"
	@echo "make architecture-manifests-check - verify module/migration/worker/test/console manifests"
	@echo "make architecture-fitness-check - enforce import, Legacy, Schema and entry classifications"
	@echo "make authority-only-config-check - validate the Track B production composition"
	@echo "make documentation-reality-check - verify canonical docs, evidence references, and comments"
	@echo "make d0-provider-probe - run the fail-closed D0 Provider qualification probe"
	@echo "make real-provider-qualification - run exact-SHA credentialed Provider qualification"

test:
	PYTHONPATH=$(PYTHONPATH) $(PYTEST) tests
	npm --prefix $(WEB_DIR) test

lint:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m compileall -q src tests

lint-authority:
	$(RUFF) check $(AUTHORITY_RUFF_PATHS)

lint-ratchet:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/check_ruff_ratchet.py --ruff $(RUFF)

validate: lint lint-authority lint-ratchet architecture-manifests-check architecture-fitness-check authority-only-config-check documentation-reality-check instruction-reality-check test-reality-check

demo: authority-demo

authority-demo: p0-backend-qualification

infra-up:
	$(AUTHORITY_COMPOSE) up -d --wait postgresql object-store

infra-down:
	$(AUTHORITY_COMPOSE) stop postgresql object-store

postgres-authority-test:
	@test -n "$${NOVEL_FORGE_DATABASE_URL:-}" || { echo "NOVEL_FORGE_DATABASE_URL is required; fixed qualification ports are forbidden" >&2; exit 2; }
	@test -n "$${NOVEL_FORGE_QUALIFICATION_DATABASE_NAME:-}" || { echo "NOVEL_FORGE_QUALIFICATION_DATABASE_NAME is required" >&2; exit 2; }
	@test -n "$${NOVEL_FORGE_POSTGRES_EVIDENCE_DIR:-}" || { echo "NOVEL_FORGE_POSTGRES_EVIDENCE_DIR is required" >&2; exit 2; }
	NOVEL_FORGE_DATABASE_URL="$${NOVEL_FORGE_DATABASE_URL}" \
	NOVEL_FORGE_QUALIFICATION_DATABASE_NAME="$${NOVEL_FORGE_QUALIFICATION_DATABASE_NAME}" \
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_authority_postgres_tests.py \
		--junit-xml "$${NOVEL_FORGE_POSTGRES_EVIDENCE_DIR}/postgresql-pytest.xml" \
		--collection-report "$${NOVEL_FORGE_POSTGRES_EVIDENCE_DIR}/postgresql-pytest-collection.json"

authority-up:
	$(AUTHORITY_COMPOSE) up -d --build --wait --wait-timeout 300

authority-down:
	$(AUTHORITY_COMPOSE) down --timeout 45

authority-build:
	$(AUTHORITY_COMPOSE) build authority-migration authority-api agent-authority-worker chapter-authority-worker content-authority-worker source-authority-worker source-import-worker mkaos-authority-worker book-authority-worker book-followup-authority-worker outbox-worker maintenance-worker

authority-smoke: p0-backend-qualification

authority-logs:
	$(AUTHORITY_COMPOSE) logs -f authority-api agent-authority-worker chapter-authority-worker content-authority-worker source-authority-worker source-import-worker mkaos-authority-worker book-authority-worker book-followup-authority-worker outbox-worker maintenance-worker

authority-test: lint lint-authority lint-ratchet architecture-manifests-check architecture-fitness-check head-integrity-check documentation-reality-check
	PYTHONPATH=$(PYTHONPATH) $(PYTEST) tests/unit tests/architecture tests/acceptance

authority-postgres-test: postgres-authority-test

authority-compose-config-check:
	env -u COMPOSE_ENV_FILES COMPOSE_DISABLE_ENV_FILE=1 \
	NOVEL_FORGE_QUALIFICATION_RUN_ID=$(QUALIFICATION_CONFIG_RUN_ID) \
	$(QUALIFICATION_COMPOSE) -f compose.yml config --quiet
	env -u COMPOSE_ENV_FILES COMPOSE_DISABLE_ENV_FILE=1 \
	NOVEL_FORGE_QUALIFICATION_RUN_ID=$(QUALIFICATION_CONFIG_RUN_ID) \
	NOVEL_FORGE_POSTGRES_TEST_DATABASE=$(QUALIFICATION_CONFIG_DATABASE) \
	$(QUALIFICATION_COMPOSE) -p $(QUALIFICATION_CONFIG_PROJECT)-postgresql \
		-f compose.postgres-test.yml config --quiet
	env -u COMPOSE_ENV_FILES COMPOSE_DISABLE_ENV_FILE=1 \
	NOVEL_FORGE_QUALIFICATION_RUN_ID=$(QUALIFICATION_CONFIG_RUN_ID) \
	NOVEL_FORGE_AUTHORITY_API_HOST_IP=127.0.0.1 \
	NOVEL_FORGE_AUTHORITY_API_PORT=0 \
	$(QUALIFICATION_COMPOSE) -p $(QUALIFICATION_CONFIG_PROJECT)-runtime \
		-f compose.yml -f compose.qualification.yml config --quiet
	env -u COMPOSE_ENV_FILES COMPOSE_DISABLE_ENV_FILE=1 \
	NOVEL_FORGE_QUALIFICATION_RUN_ID=$(QUALIFICATION_CONFIG_RUN_ID) \
	NOVEL_FORGE_AUTHORITY_API_HOST_IP=127.0.0.1 \
	NOVEL_FORGE_AUTHORITY_API_PORT=0 \
	$(QUALIFICATION_COMPOSE) -p $(QUALIFICATION_CONFIG_PROJECT)-worker \
		-f compose.yml -f compose.worker-e2e.yml -f compose.qualification.yml config --quiet

authority-query-plan-release:
	@test -n "$${NOVEL_FORGE_DATABASE_URL:-}" || { echo "NOVEL_FORGE_DATABASE_URL is required; fixed qualification ports are forbidden" >&2; exit 2; }
	NOVEL_FORGE_DATABASE_URL="$${NOVEL_FORGE_DATABASE_URL}" \
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/qualify_authority_query_plans.py

p0-backend-list-gates:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_p0_backend_qualification.py --list-gates

p0-backend-static: lint lint-authority lint-ratchet head-integrity-check architecture-manifests-check architecture-fitness-check sync-skills check-skills instruction-reality-check test-reality-check authority-compose-config-check

p0-backend-qualification:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_p0_backend_qualification.py --profile $(P0_PROFILE) --output "$(P0_EVIDENCE_DIR)/p0-backend-qualification-$$(git rev-parse HEAD).json"

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

instruction-reality-check:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.tools.instruction_surface --repo-root .

test-reality-check:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.tools.test_reality --repo-root .

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

documentation-reality-check:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.tools.documentation_reality --repo-root .

d0-provider-probe:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_d0_provider_probe.py

real-provider-qualification:
	@test -n "$${NOVEL_FORGE_DATABASE_URL:-}" || { echo "NOVEL_FORGE_DATABASE_URL is required" >&2; exit 2; }
	@test -n "$${NOVEL_FORGE_MINIO_ENDPOINT:-}" || { echo "NOVEL_FORGE_MINIO_ENDPOINT is required" >&2; exit 2; }
	@test -n "$${NOVEL_FORGE_REAL_PROVIDER_RUNTIME_ROOT:-}" || { echo "NOVEL_FORGE_REAL_PROVIDER_RUNTIME_ROOT is required" >&2; exit 2; }
	@test -n "$${NOVEL_FORGE_REAL_PROVIDER_EVIDENCE_PATH:-}" || { echo "NOVEL_FORGE_REAL_PROVIDER_EVIDENCE_PATH is required" >&2; exit 2; }
	@test -n "$${NOVEL_FORGE_REAL_PROVIDER_EXPECTED_SHA:-}" || { echo "NOVEL_FORGE_REAL_PROVIDER_EXPECTED_SHA is required" >&2; exit 2; }
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_real_provider_qualification.py \
		--database-url "$${NOVEL_FORGE_DATABASE_URL}" \
		--minio-endpoint "$${NOVEL_FORGE_MINIO_ENDPOINT}" \
		--runtime-root "$${NOVEL_FORGE_REAL_PROVIDER_RUNTIME_ROOT}" \
		--output "$${NOVEL_FORGE_REAL_PROVIDER_EVIDENCE_PATH}" \
		--expected-sha "$${NOVEL_FORGE_REAL_PROVIDER_EXPECTED_SHA}"
