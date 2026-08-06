.PHONY: up down test test-ui evals evals-full corpus lint typecheck check install index serve ui migrate-pgvector demo demo-down demo-reset

# Use the venv if it exists, otherwise fall back to python3.12 or python3
PYTHON := $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; elif command -v python3.12 >/dev/null 2>&1; then echo python3.12; else echo python3; fi)

# Proof-of-value demo kit: state for the background API/UI processes make
# demo starts, so demo-down can find and stop them again.
DEMO_CORPUS_DIR := demo/corpus
DEMO_STATE_DIR := .demo
DEMO_API_LOG := $(DEMO_STATE_DIR)/api.log
DEMO_API_PID := $(DEMO_STATE_DIR)/api.pid
DEMO_UI_LOG := $(DEMO_STATE_DIR)/ui.log
DEMO_UI_PID := $(DEMO_STATE_DIR)/ui.pid

# ---------------------------------------------------------------------------
# Dev environment
# ---------------------------------------------------------------------------

install:
	python3.12 -m venv .venv
	.venv/bin/pip install -e ".[dev]"
	cd ui && npm install

up:
	@command -v docker >/dev/null 2>&1 || { echo "Error: Docker is not installed or not running."; exit 1; }
	docker compose up -d

down:
	docker compose down

# ---------------------------------------------------------------------------
# Quality gates
# ---------------------------------------------------------------------------

lint:
	$(PYTHON) -m ruff check src/ tests/ evals/ corpus/ scripts/

typecheck:
	$(PYTHON) -m mypy src/ corpus/ evals/ scripts/

test:
	$(PYTHON) -m pytest -v

test-ui:
	cd ui && npx vitest run

check: lint typecheck test test-ui

# ---------------------------------------------------------------------------
# Corpus, ingest, and serve
# ---------------------------------------------------------------------------

corpus:
	$(PYTHON) corpus/generate.py

index:
	$(PYTHON) -m custos.ingest

migrate-pgvector:
	$(PYTHON) scripts/migrate_pgvector.py

serve:
	$(PYTHON) -m uvicorn custos.api:app --reload --host 127.0.0.1 --port 8000

ui:
	cd ui && npm run dev

# ---------------------------------------------------------------------------
# Evals
# ---------------------------------------------------------------------------

evals:
	$(PYTHON) -m evals.harness

evals-full:
	$(PYTHON) -m evals.harness --llm

# ---------------------------------------------------------------------------
# Proof-of-value demo kit (demo/)
# ---------------------------------------------------------------------------
# make demo: brings up Qdrant, indexes demo/corpus, starts the API and UI in
# the background, and prints the URL + persona logins. Idempotent: safe to
# run twice in a row (re-ingest recreates the collection instead of
# appending to it -- see custos.ingest.ingest_corpus -- and the API/UI
# startup steps are skipped if a health check shows they're already up).
# Polls for readiness instead of sleeping a fixed duration; fails fast,
# naming the missing thing, if a prerequisite isn't met.

demo:
	@echo "==> Checking prerequisites"
	@command -v docker >/dev/null 2>&1 || { echo "Error: Docker is not installed or not running."; exit 1; }
	@command -v curl >/dev/null 2>&1 || { echo "Error: curl is required on PATH and was not found."; exit 1; }
	@[ -n "$$ANTHROPIC_API_KEY" ] || { echo "Error: ANTHROPIC_API_KEY is not set. Export it first, e.g.: set -a; source .env; set +a"; exit 1; }
	@[ -x .venv/bin/python ] || { echo "Error: .venv not found. Run 'make install' first."; exit 1; }
	@[ -d ui/node_modules ] || { echo "Error: ui/node_modules not found. Run 'make install' first."; exit 1; }
	@mkdir -p $(DEMO_STATE_DIR)
	@echo "==> Starting Qdrant"
	@$(MAKE) up
	@echo "==> Waiting for Qdrant to be ready"
	@i=0; until curl -sf http://localhost:6333/collections >/dev/null 2>&1; do \
		i=$$((i + 1)); \
		if [ $$i -ge 60 ]; then echo "Error: Qdrant did not become ready within 60s. Check: docker compose logs qdrant"; exit 1; fi; \
		sleep 1; \
	done
	@echo "==> Indexing demo corpus ($(DEMO_CORPUS_DIR))"
	@CUSTOS_CORPUS_DIR=$(DEMO_CORPUS_DIR) $(PYTHON) -m custos.ingest
	@echo "==> Starting the API"
	@if curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1; then \
		echo "    Already running at http://127.0.0.1:8000"; \
	else \
		CUSTOS_CORPUS_DIR=$(DEMO_CORPUS_DIR) CUSTOS_DATA_DIR=$(DEMO_STATE_DIR)/data \
			nohup $(PYTHON) -m uvicorn custos.api:app --host 127.0.0.1 --port 8000 \
			> $(DEMO_API_LOG) 2>&1 & echo $$! > $(DEMO_API_PID); \
	fi
	@echo "==> Waiting for the API to report healthy"
	@i=0; until curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1; do \
		i=$$((i + 1)); \
		if [ $$i -ge 90 ]; then echo "Error: API did not become healthy within 90s. See $(DEMO_API_LOG)."; exit 1; fi; \
		sleep 1; \
	done
	@echo "==> Starting the UI"
	@if curl -sf http://localhost:5173 >/dev/null 2>&1; then \
		echo "    Already running at http://localhost:5173"; \
	else \
		( cd ui; nohup npm run dev -- --port 5173 --strictPort > ../$(DEMO_UI_LOG) 2>&1 & echo $$! > ../$(DEMO_UI_PID) ); \
	fi
	@echo "==> Waiting for the UI to be reachable"
	@i=0; until curl -sf http://localhost:5173 >/dev/null 2>&1; do \
		i=$$((i + 1)); \
		if [ $$i -ge 60 ]; then echo "Error: UI dev server did not come up within 60s. See $(DEMO_UI_LOG)."; exit 1; fi; \
		sleep 1; \
	done
	@echo ""
	@echo "==> Demo ready."
	@echo ""
	@echo "    Open:  http://localhost:5173"
	@echo ""
	@echo "    Personas (full detail in demo/corpus/README.md):"
	@echo "      dana  Standard employee  -> UI access switcher: Standard"
	@echo "      raj   Finance            -> UI access switcher: Finance"
	@echo "      sam   Contractor         -> not in the UI switcher; call the API directly"
	@echo "                                  with user_permissions: [\"contractor\"]"
	@echo ""
	@echo "    Script: demo/DEMO_SCRIPT.md"
	@echo "    Tear down: make demo-down     Fresh restart: make demo-reset"

demo-down:
	@echo "==> Stopping the UI"
	@if [ -f $(DEMO_UI_PID) ]; then kill $$(cat $(DEMO_UI_PID)) 2>/dev/null || true; rm -f $(DEMO_UI_PID); else echo "    (not running, or started outside make demo)"; fi
	@echo "==> Stopping the API"
	@if [ -f $(DEMO_API_PID) ]; then kill $$(cat $(DEMO_API_PID)) 2>/dev/null || true; rm -f $(DEMO_API_PID); else echo "    (not running, or started outside make demo)"; fi
	@echo "==> Stopping Qdrant"
	@$(MAKE) down

demo-reset: demo-down demo
