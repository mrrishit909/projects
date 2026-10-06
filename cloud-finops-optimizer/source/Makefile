export DATABASE_URL ?= postgresql://app:app-dev-only@127.0.0.1:55270/app
PY = ./venv/bin/python
BASE = http://127.0.0.1:8270

bootstrap:      ## local virtualenv + database container
	python3 -m venv venv && ./venv/bin/pip install -q -r requirements-dev.txt
	docker compose up -d db
seed:           ## migrate and create the tenants and demo tokens (no-op if already seeded)
	$(PY) -m finops.seed --if-empty
dev:            ## API with reload on :8270, jobs run by a local worker
	($(PY) -m core.jobs finops.api &) && $(PY) -m uvicorn finops.api:app --reload --port 8270
test:
	$(PY) -m pytest --cov=finops --cov=core --cov-report=term-missing
demo:           ## the full stack in Docker, then the demo scenario against it
	docker compose up --build -d --wait && $(PY) -m core.scenario $(BASE)
load-test:      ## run `make demo` first
	$(PY) -m core.loadtest $(BASE) acme-finops_lead-demo 16 8 "GET /v1/estate/overview" "GET /v1/recommendations?status=all&limit=100" "GET /v1/costs/explain?days=7" "GET /v1/accounts"
evaluate:       ## held-out estates -> docs/evaluation.md
	$(PY) -m finops.evaluate > docs/evaluation.md
reset:          ## drop all data (volume included)
	docker compose down -v
.PHONY: bootstrap seed dev test demo load-test evaluate reset
