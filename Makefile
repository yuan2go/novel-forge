PYTHON ?= python3
PYTHONPATH := src

.PHONY: test lint validate demo sync-skills sync-skills-dry-run check-skills help

help:
	@echo "make test      - run stdlib unittest suite"
	@echo "make lint      - compile Python sources"
	@echo "make validate  - validate V5 structure and JSON assets"
	@echo "make demo      - run sample end-to-end pipeline"
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

sync-skills-dry-run:
	$(PYTHON) scripts/sync_claude_skills.py --dry-run

sync-skills:
	$(PYTHON) scripts/sync_claude_skills.py

check-skills:
	$(PYTHON) scripts/sync_claude_skills.py --check
