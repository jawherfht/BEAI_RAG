# BEAI RAG - developer entry points.
SHELL := /bin/bash
UV ?= uv
RUN := $(UV) run
API_DIR := services/rag-api
INFRA := qdrant postgres redis rabbitmq seaweedfs

.PHONY: help up down logs install migrate bootstrap run-api run-worker run-embedder phase2-check eval-retrieval kb1-data sample-data lint format typecheck test test-unit test-integration readyz show-collection phase1-check seed demo eval licenses openapi

help:
	@grep -E '^[a-z0-9-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-18s %s\n", $$1, $$2}'

.env:
	cp .env.example .env

install: .env ## Install the Python workspace (uv)
	$(UV) sync --frozen

up: .env install ## Start the dev infrastructure, run migrations, create the Qdrant collection
	docker compose up -d --wait $(INFRA)
	$(MAKE) migrate

down: ## Stop the dev stack (keeps volumes; use `docker compose down -v` to wipe)
	docker compose down

logs:
	docker compose logs -f --tail=100

migrate: ## Apply DB migrations and bootstrap Qdrant collection + bucket
	cd $(API_DIR) && $(RUN) alembic upgrade head
	cd $(API_DIR) && $(RUN) python -m app.bootstrap

run-api: ## Run rag-api locally on :8000 against the compose stack
	cd $(API_DIR) && $(RUN) uvicorn --factory app.main:create_app --host 0.0.0.0 --port 8000

lint: ## ruff lint + format check
	$(RUN) ruff check .
	$(RUN) ruff format --check .

format:
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

typecheck: ## mypy --strict
	$(RUN) mypy packages/beai_rag_core/beai_rag_core services/rag-api/app services/ingestion-worker/worker services/embed-server/embed_server tests scripts eval

test: ## All tests (unit + integration via testcontainers; needs Docker)
	$(RUN) pytest

test-unit:
	$(RUN) pytest -m "not integration"

test-integration:
	$(RUN) pytest -m integration

show-collection: ## Print the Qdrant collection config (vectors, quantization, payload indexes)
	cd $(API_DIR) && $(RUN) python -m app.bootstrap --show

phase1-check: ## Phase 1 acceptance: start the API, print /readyz and the collection config
	$(RUN) python scripts/phase1_check.py

phase2-check: ## Phase 2 acceptance with real models (needs TEI + Hugging Face access)
	$(RUN) python scripts/phase2_check.py $(PDF)

run-embedder: ## CPU embedding server on :8080 (TEI /embed contract; EMBED_PROVIDER=local)
	cd services/embed-server && $(RUN) uvicorn --factory embed_server.main:create_app --port 8080

run-worker: ## Run the ingestion worker locally against the compose stack
	cd services/ingestion-worker && $(RUN) python -m worker.main

eval-retrieval: ## Phase 3: recall@4, MRR@10 and latency on KB #1 (real models; ARGS=--rerank)
	$(RUN) python eval/retrieval_eval.py $(ARGS)

kb1-data: ## (Re)generate the KB #1 documents and questions from eval/datasets/kb1_retail/facts.py
	$(RUN) python eval/datasets/kb1_retail/build.py

sample-data: ## (Re)generate eval/datasets/kb1_retail/returns-policy.pdf
	$(RUN) python eval/datasets/make_returns_policy_pdf.py

licenses: ## Python dependency licence report
	$(RUN) pip-licenses --from=mixed --format=markdown --order=license

seed demo eval:
	@echo "'$@' is implemented in a later phase (see BEAI_RAG_BUILD_SPEC.md section 15)"; exit 1

openapi: ## Regenerate docs/openapi.json
	PYTHONPATH=$(API_DIR) $(RUN) python scripts/export_openapi.py
