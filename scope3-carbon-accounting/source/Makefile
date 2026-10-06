export DATABASE_URL ?= postgresql://app:app-dev-only@127.0.0.1:55250/carbon
PY = ./venv/bin/python
BASE = http://127.0.0.1:8250

bootstrap:      ## local virtualenv + database container
	python3 -m venv venv && ./venv/bin/pip install -q -r requirements-dev.txt
	docker compose up -d db
seed:           ## migrate and create the tenants and demo tokens (no-op if already seeded)
	$(PY) -m carbon.seed --if-empty
dev:            ## API with reload on :8250, jobs run by a local worker
	($(PY) -m core.jobs carbon.api &) && $(PY) -m uvicorn carbon.api:app --reload --port 8250
test:
	$(PY) -m pytest --cov=carbon --cov=core --cov-report=term-missing
demo:           ## the full stack in Docker, then the demo scenario against it (about 4-5 minutes: two million invoice lines)
	docker compose up --build -d --wait && $(PY) -m core.scenario $(BASE)
load-test:      ## run `make demo` first; CALC, LINE and SUPPLIER from the demo (a calculation, one of its activity ids, a supplier id)
	$(PY) -m core.loadtest $(BASE) meridale-viewer-demo 16 8 "GET /v1/inventory/scope3?calculation_id=$(CALC)" "GET /v1/calculations/$(CALC)/lineage?activity_id=$(LINE)" "GET /v1/suppliers/$(SUPPLIER)" "GET /v1/review-tasks?kind=category&limit=20"
evaluate:       ## held-out companies -> docs/evaluation.md
	$(PY) -m carbon.evaluate > docs/evaluation.md
reset:          ## drop all data (volume included)
	docker compose down -v
.PHONY: bootstrap seed dev test demo load-test evaluate reset
