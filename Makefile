PYTHON ?= python3
PYTHONPATH := src
WEB_DIR ?= web/admin
LOCAL_WORKSPACE ?= .local/workspace
DEMO_WORKSPACE ?= .local/demo-workspace

.PHONY: test lint validate demo local-workspace infra-up infra-down online-backends-up online-backends-smoke local-up local-down local-smoke local-logs failure-drill api worker web-dev sync-skills sync-skills-dry-run check-skills help

help:
	@echo "make test      - run stdlib unittest suite"
	@echo "make lint      - compile Python sources"
	@echo "make validate  - validate Novel Forge workspace structure and JSON assets"
	@echo "make demo      - run sample end-to-end pipeline"
	@echo "make local-workspace - create ignored local runtime workspace"
	@echo "make infra-up  - start PostgreSQL, Redis, Qdrant, and MinIO"
	@echo "make online-backends-up - start pgvector-capable PostgreSQL and ClickHouse"
	@echo "make online-backends-smoke - verify opt-in pgvector and ClickHouse online backends"
	@echo "make local-up  - start full local production stack with Docker"
	@echo "make local-smoke - run local production smoke checks"
	@echo "make local-logs - tail API, worker, and web logs"
	@echo "make local-down - stop local production stack"
	@echo "make failure-drill - run non-destructive failure recovery drill"
	@echo "make api       - run FastAPI backend"
	@echo "make worker    - run Celery worker"
	@echo "make web-dev   - run Next.js admin console"
	@echo "make sync-skills-dry-run - preview syncing skills to .claude/skills"
	@echo "make sync-skills - sync repository skills to .claude/skills"
	@echo "make check-skills - fail if .claude/skills drifts from repository skills"

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

api:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.cli serve-api --root $(LOCAL_WORKSPACE)

worker:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.cli worker --root $(LOCAL_WORKSPACE)

web-dev:
	npm --prefix $(WEB_DIR) run dev

sync-skills-dry-run:
	$(PYTHON) scripts/sync_claude_skills.py --dry-run

sync-skills:
	$(PYTHON) scripts/sync_claude_skills.py

check-skills:
	$(PYTHON) scripts/sync_claude_skills.py --check
