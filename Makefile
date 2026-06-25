PYTHON ?= python3
PYTHONPATH := src
WEB_DIR ?= web/admin

.PHONY: test lint validate demo infra-up infra-down local-up local-down local-smoke local-logs failure-drill api worker web-dev sync-skills sync-skills-dry-run check-skills help

help:
	@echo "make test      - run stdlib unittest suite"
	@echo "make lint      - compile Python sources"
	@echo "make validate  - validate V5 structure and JSON assets"
	@echo "make demo      - run sample end-to-end pipeline"
	@echo "make infra-up  - start PostgreSQL, Redis, Qdrant, and MinIO"
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

lint:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m compileall -q src tests

validate:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.cli validate --root .

demo:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.cli run-pipeline --sample --root .

infra-up:
	docker compose up -d postgres redis qdrant minio

infra-down:
	docker compose down

local-up:
	test -f .env || cp .env.example .env
	docker compose up -d postgres redis qdrant minio
	docker compose build api worker web
	docker compose run --rm api python -m novel_forge.cli postgres-init --root /workspace
	docker compose run --rm api python -m novel_forge.cli postgres-sync --root /workspace
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
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.cli serve-api --root .

worker:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.cli worker --root .

web-dev:
	npm --prefix $(WEB_DIR) run dev

sync-skills-dry-run:
	$(PYTHON) scripts/sync_claude_skills.py --dry-run

sync-skills:
	$(PYTHON) scripts/sync_claude_skills.py

check-skills:
	$(PYTHON) scripts/sync_claude_skills.py --check
