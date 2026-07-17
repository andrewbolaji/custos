.PHONY: up down test evals corpus lint typecheck check install

# Use the venv if it exists, otherwise fall back to python3.12 or python3
PYTHON := $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; elif command -v python3.12 >/dev/null 2>&1; then echo python3.12; else echo python3; fi)

# ---------------------------------------------------------------------------
# Dev environment
# ---------------------------------------------------------------------------

install:
	python3.12 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

up:
	@command -v docker >/dev/null 2>&1 || { echo "Error: Docker is not installed or not running."; exit 1; }
	docker compose up -d

down:
	docker compose down

# ---------------------------------------------------------------------------
# Quality gates
# ---------------------------------------------------------------------------

lint:
	$(PYTHON) -m ruff check src/ tests/ evals/ corpus/

typecheck:
	$(PYTHON) -m mypy src/

test:
	$(PYTHON) -m pytest -v

check: lint typecheck test

# ---------------------------------------------------------------------------
# Corpus and evals
# ---------------------------------------------------------------------------

corpus:
	$(PYTHON) corpus/generate.py

evals:
	$(PYTHON) -m evals.harness
