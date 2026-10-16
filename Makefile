# BEAI RAG - developer entry points.
SHELL := /bin/bash
UV ?= uv
RUN := $(UV) run
API_DIR := services/rag-api
INFRA := qdrant postgres redis rabbitmq seaweedfs

.PHONY: help up down logs install migrate bootstrap run-api run-worker run-embedder phase2-check phase4-check calibrate eval-retrieval kb-data faithfulness sample-data lint format typecheck test test-unit test-integration readyz show-collection phase1-check seed demo eval licenses openapi proto web-install web-check e2e stack-stop

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

phase4-check: ## Phase 4 acceptance: /test sample question, fallback without LLM, TTFT
	$(RUN) python scripts/phase4_check.py

calibrate: ## Calibrate grounding thresholds from eval/runs (all KBs) -> config/thresholds.<model>.json
	$(RUN) python eval/calibrate.py --tag $(EVAL_TAG)

run-worker: ## Run the ingestion worker locally against the compose stack
	cd services/ingestion-worker && $(RUN) python -m worker.main

eval-retrieval: ## Retrieval only: recall@4, MRR@10, latency (ARGS="--kb kb2_saas_fr --rerank")
	$(RUN) python eval/retrieval_eval.py $(ARGS)

kb-data: ## (Re)generate the three eval KBs (documents + questions) from their facts.py
	for kb in $(EVAL_KBS); do $(RUN) python eval/datasets/build_kb.py $$kb || exit 1; done

sample-data: ## (Re)generate eval/datasets/kb1_retail/returns-policy.pdf
	$(RUN) python eval/datasets/make_returns_policy_pdf.py

licenses: ## Python dependency licence report
	$(RUN) pip-licenses --from=mixed --format=markdown --order=license

# Phase 6 evaluation (spec section 12). Comparison mode: make eval CHUNK=256 RERANK=on SUBSET=60
# LABEL=qwen3emb (other models: set EMBED_MODEL / LLM_MODEL etc. in the environment as well).
EVAL_KBS := kb1_retail kb2_saas_fr kb3_hr_ar
CHUNK ?= 512
RERANK ?= off
SUBSET ?= 0
LABEL ?=
EVAL_TAG := c$(CHUNK)$(if $(filter on,$(RERANK)),-rerank,)$(if $(filter-out 0,$(SUBSET)),-s$(SUBSET),)$(if $(LABEL),-$(LABEL),)
eval: ## Run the KBs through /test (one LLM call per question), then write eval/reports/phase6-eval.md
	cd eval && for kb in $(EVAL_KBS); do \
		$(RUN) python run_eval.py --kb $$kb --chunk $(CHUNK) --subset $(SUBSET) $(if $(filter on,$(RERANK)),--rerank,) $(if $(LABEL),--label $(LABEL),) || exit 1; \
	done
	cd eval && $(RUN) python report.py --tag $(EVAL_TAG)

faithfulness: ## RAGAS faithfulness on a stratified subset of answered questions (LLM judge)
	$(UV) run --script eval/faithfulness.py --tag $(EVAL_TAG) $(ARGS)

seed demo:
	@echo "'$@' is implemented in a later phase (see BEAI_RAG_BUILD_SPEC.md section 15)"; exit 1

openapi: ## Regenerate docs/openapi.json
	PYTHONPATH=$(API_DIR) $(RUN) python scripts/export_openapi.py

proto: ## Regenerate gRPC code from proto/beai/rag/v1/rag.proto into app/grpc_gen
	$(RUN) python -m grpc_tools.protoc -I proto --python_out=$(API_DIR)/app/grpc_gen \
		--grpc_python_out=$(API_DIR)/app/grpc_gen --pyi_out=$(API_DIR)/app/grpc_gen proto/beai/rag/v1/rag.proto
	touch $(API_DIR)/app/grpc_gen/__init__.py $(API_DIR)/app/grpc_gen/beai/__init__.py \
		$(API_DIR)/app/grpc_gen/beai/rag/__init__.py $(API_DIR)/app/grpc_gen/beai/rag/v1/__init__.py
	sed -i 's/^from beai.rag.v1 import/from app.grpc_gen.beai.rag.v1 import/' $(API_DIR)/app/grpc_gen/beai/rag/v1/rag_pb2_grpc.py

WEB := web/knowledge-base-ui

web-install: ## Install the screen B (Next.js) dependencies
	cd $(WEB) && npm ci --no-audit --no-fund

web-check: ## Lint, type-check and build screen B
	cd $(WEB) && npx eslint . --max-warnings 0 && npx tsc --noEmit && npx next build

e2e: ## Playwright E2E for screen B against the real stack (make up first; needs LLM + models)
	scripts/dev-stack.sh
	cd $(WEB) && [ -f .env.local ] || cp .env.example .env.local
	cd $(WEB) && npx next build && npx playwright test

stack-stop: ## Stop rag-api, worker and embed-server started by scripts/dev-stack.sh
	scripts/dev-stack.sh stop
