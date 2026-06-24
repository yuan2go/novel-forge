PYTHON ?= python3
PYTHONPATH := src

.PHONY: test lint validate demo help

help:
	@echo "make test      - run stdlib unittest suite"
	@echo "make lint      - compile Python sources"
	@echo "make validate  - validate V5 structure and JSON assets"
	@echo "make demo      - run sample end-to-end pipeline"

test:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests -p 'test_*.py'

lint:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m compileall -q src tests

validate:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.cli validate --root .

demo:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m novel_forge.cli run-pipeline --sample --root .
