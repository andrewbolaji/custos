.PHONY: up down test evals evals-full corpus lint typecheck check install index serve

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
	$(PYTHON) -m mypy src/ corpus/ evals/

test:
	$(PYTHON) -m pytest -v

check: lint typecheck test

# ---------------------------------------------------------------------------
# Corpus, ingest, and serve
# ---------------------------------------------------------------------------

corpus:
	$(PYTHON) corpus/generate.py

index:
	$(PYTHON) -m custos.ingest

serve:
	$(PYTHON) -m uvicorn custos.api:app --reload --port 8000

# ---------------------------------------------------------------------------
# Evals
# ---------------------------------------------------------------------------

evals:
	$(PYTHON) -m evals.harness

evals-full:
	$(PYTHON) -m evals.harness --llm
