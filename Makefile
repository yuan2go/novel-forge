.PHONY: help check test init-sample

PYTHON ?= python3

help:
	@echo "NovelForge commands:"
	@echo "  make check       Check docs/templates/project skeleton"
	@echo "  make test        Run unit tests"
	@echo "  make init-sample Create a sample novel project in dry-run compatible mode"

check:
	$(PYTHON) scripts/check_docs_structure.py

test:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py'

init-sample:
	$(PYTHON) scripts/init_novel_project.py --project-id project_sample --title "示例项目" --genre "都市悬疑" --force
