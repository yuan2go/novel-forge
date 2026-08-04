PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PYTHONPATH := src
WEB_DIR ?= web/admin
LOCAL_WORKSPACE ?= .local/workspace
DEMO_WORKSPACE ?= .local/demo-workspace

.PHONY: test lint validate demo local-workspace infra-up infra-down postgres-authority-test-up postgres-authority-test-down postgres-authority-test online-backends-up online-backends-smoke local-up local-down local-smoke local-logs failure-drill v1-slow-acceptance governance-dead-letter-regression runtime-growth-regression source-governance-regression api worker web-dev sync-skills sync-skills-dry-run check-skills authority-parity-check head-integrity-check architecture-manifests-check architecture-fitness-check authority-only-config-check d0-provider-probe help

help:
	@echo "make test      - run stdlib unittest suite"
	@echo "make lint      - compile Python sources"
	@echo "make validate  - validate Novel Forge workspace structure and JSON assets"
	@echo "make demo      - run sample end-to-end pipeline"
	@echo "make local-workspace - create ignored local runtime workspace"
	@echo "make infra-up  - start PostgreSQL, Redis, Qdrant, and MinIO"
	@echo "make postgres-authority-test-up - start isolated PostgreSQL authority test service"
	@echo "make postgres-authority-test - run non-skippable authority PostgreSQL tests"
	@echo "make online-backends-up - start pgvector-capable PostgreSQL and ClickHouse"
	@echo "make online-backends-smoke - verify opt-in pgvector and ClickHouse online backends"
	@echo "make local-up  - start full local production stack with Docker"
	@echo "make local-smoke - run local production smoke checks"
	@echo "make local-logs - tail API, worker, and web logs"
	@echo "make local-down - stop local production stack"
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

validate: local-workspace
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.cli validate --root $(LOCAL_WORKSPACE)

local-workspace:
	mkdir -p $(LOCAL_WORKSPACE)

demo: local-workspace
	mkdir -p $(DEMO_WORKSPACE)
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.cli run-pipeline --sample --root $(DEMO_WORKSPACE)

infra-up:
	docker compose up -d postgres redis qdrant minio

infra-down:
	docker compose down

postgres-authority-test-up:
	docker compose -f compose.postgres-test.yml up -d --wait authority-postgres-test

postgres-authority-test-down:
	docker compose -f compose.postgres-test.yml down

postgres-authority-test:
	NOVEL_FORGE_DATABASE_URL=$${NOVEL_FORGE_DATABASE_URL:-postgresql://novel_forge:novel_forge@localhost:55432/novel_forge_authority_test} \
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_authority_postgres_tests.py

online-backends-up:
	docker compose --profile analytics up -d postgres clickhouse

online-backends-smoke:
	NOVEL_FORGE_PGVECTOR_ONLINE=1 \
	NOVEL_FORGE_CLICKHOUSE_ONLINE=1 \
	NOVEL_FORGE_DATABASE_URL=$${NOVEL_FORGE_DATABASE_URL:-postgresql://novel_forge:novel_forge@localhost:5432/novel_forge} \
	NOVEL_FORGE_CLICKHOUSE_URL=$${NOVEL_FORGE_CLICKHOUSE_URL:-http://localhost:8123} \
	NOVEL_FORGE_CLICKHOUSE_DATABASE=$${NOVEL_FORGE_CLICKHOUSE_DATABASE:-novel_forge} \
	NOVEL_FORGE_CLICKHOUSE_USER=$${NOVEL_FORGE_CLICKHOUSE_USER:-novel_forge} \
	NOVEL_FORGE_CLICKHOUSE_PASSWORD=$${NOVEL_FORGE_CLICKHOUSE_PASSWORD:-novel_forge} \
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/verify_online_backends.py --project-id local-online --require-online

local-up: local-workspace
	test -f .env || cp .env.example .env
	docker compose up -d postgres redis qdrant minio
	docker compose build api worker web
	docker compose run --rm api python -m novel_forge.cli postgres-init --root /runtime
	docker compose run --rm api python -m novel_forge.cli postgres-sync --root /runtime
	docker compose up -d api worker web
	$(PYTHON) scripts/local_smoke.py

local-down:
	docker compose down

local-smoke:
	$(PYTHON) scripts/local_smoke.py

local-logs:
	docker compose logs -f api worker web

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
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.cli serve-api --root $(LOCAL_WORKSPACE)

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
	docker compose -f compose.authority-only.yml config --quiet

d0-provider-probe:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_d0_provider_probe.py

authority-parity-check: head-integrity-check
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.tools.authority_parity_manifest --repo-root .
