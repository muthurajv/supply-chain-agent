SHELL := /bin/bash

# ── Config ────────────────────────────────────────────────────────────────────
ACR         ?= your-acr.azurecr.io
IMAGE_TAG   ?= $(shell git rev-parse --short HEAD)
NAMESPACE    = supply-chain
API_PORT     = 8080
SAP_PORT     = 8001

.PHONY: help install dev dev-api dev-sap test test-unit test-integration \
        lint format build push deploy smoke clean

# ── Default target ────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  Supply Chain Agent — available targets"
	@echo ""
	@echo "  Dev"
	@echo "    install          uv sync (install all dependencies)"
	@echo "    dev              start sap-mock + agents-api with hot reload"
	@echo "    dev-api          start agents-api only (port $(API_PORT))"
	@echo "    dev-sap          start sap-mock only  (port $(SAP_PORT))"
	@echo ""
	@echo "  Test"
	@echo "    test             full test suite"
	@echo "    test-unit        unit tests only"
	@echo "    test-integration integration tests only"
	@echo "    test-cov         full suite + coverage report"
	@echo ""
	@echo "  Code quality"
	@echo "    lint             ruff check"
	@echo "    format           ruff format"
	@echo ""
	@echo "  Deploy"
	@echo "    build            docker build both images (ACR=$(ACR))"
	@echo "    push             build + push to ACR"
	@echo "    deploy           kubectl apply all K8s manifests"
	@echo "    smoke            health check + /chat sanity query"
	@echo ""
	@echo "  Misc"
	@echo "    clean            remove build artefacts and __pycache__"
	@echo ""

# ── Local development ─────────────────────────────────────────────────────────
install:
	uv sync

dev:
	@echo "Starting sap-mock on :$(SAP_PORT) and agents-api on :$(API_PORT) ..."
	@trap 'echo "Stopping..."; kill %1 %2 2>/dev/null; exit' INT TERM; \
	uvicorn sap_mock.main:app --host 0.0.0.0 --port $(SAP_PORT) --reload & \
	uvicorn app.main:app     --host 0.0.0.0 --port $(API_PORT) --reload & \
	wait

dev-api:
	uvicorn app.main:app --host 0.0.0.0 --port $(API_PORT) --reload

dev-sap:
	uvicorn sap_mock.main:app --host 0.0.0.0 --port $(SAP_PORT) --reload

# ── Testing ───────────────────────────────────────────────────────────────────
test:
	python -m pytest tests/ -v

test-unit:
	python -m pytest tests/unit/ -v

test-integration:
	python -m pytest tests/integration/ -v

test-cov:
	python -m pytest tests/ --cov=app --cov-report=term-missing --cov-report=html
	@echo "HTML report: htmlcov/index.html"

# ── Code quality ──────────────────────────────────────────────────────────────
lint:
	ruff check app/ sap_mock/ tests/

format:
	ruff format app/ sap_mock/ tests/

# ── Image build ───────────────────────────────────────────────────────────────
# Dockerfiles expected at docker/api.Dockerfile and docker/sap-mock.Dockerfile
# (§4, §11.4). Tags use the git SHA — never 'latest'.
build:
	docker build -f docker/api.Dockerfile      -t $(ACR)/supply-chain-agent:$(IMAGE_TAG) .
	docker build -f docker/sap-mock.Dockerfile -t $(ACR)/sap-mock:$(IMAGE_TAG)           .

push: build
	docker push $(ACR)/supply-chain-agent:$(IMAGE_TAG)
	docker push $(ACR)/sap-mock:$(IMAGE_TAG)
	@echo "Pushed supply-chain-agent:$(IMAGE_TAG) and sap-mock:$(IMAGE_TAG) to $(ACR)"

# ── K8s deployment ────────────────────────────────────────────────────────────
# Applies all manifests in order. A Helm chart is the long-term target (§11.4);
# until then, kubectl apply is the deploy mechanism for the POC.
deploy:
	kubectl apply -f deploy/k8s/configmap.yaml
	kubectl apply -f deploy/k8s/secrets-provider.yaml
	kubectl apply -f deploy/k8s/sap-mock-deployment.yaml
	kubectl apply -f deploy/k8s/deployment.yaml
	kubectl apply -f deploy/k8s/service.yaml
	kubectl apply -f deploy/k8s/ingress.yaml
	kubectl apply -f deploy/k8s/cronjob.yaml
	kubectl rollout status deployment/supply-chain-agent -n $(NAMESPACE)
	kubectl rollout status deployment/sap-mock           -n $(NAMESPACE)

# ── Smoke test ────────────────────────────────────────────────────────────────
# Default target is localhost; override with: make smoke HOST=https://your-domain
HOST ?= http://localhost:$(API_PORT)

smoke:
	@echo "==> GET $(HOST)/healthz"
	@curl -sf $(HOST)/healthz | python -m json.tool
	@echo ""
	@echo "==> POST $(HOST)/chat"
	@curl -sf -X POST $(HOST)/chat \
		-H "Content-Type: application/json" \
		-d '{"message": "Do I need to reorder M-1042?"}' \
		| python -m json.tool

# ── Clean ─────────────────────────────────────────────────────────────────────
clean:
	find . -path ./.venv -prune -o -type d -name __pycache__ -print -exec rm -rf {} + 2>/dev/null || true
	find . -path ./.venv -prune -o -name "*.pyc"             -print -delete         2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov dist build *.egg-info
