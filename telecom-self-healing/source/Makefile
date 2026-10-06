export DATABASE_URL ?= postgresql://app:app-dev-only@127.0.0.1:55260/app
PY = ./venv/bin/python
BASE = http://127.0.0.1:8260

bootstrap:      ## local virtualenv + database container
	python3 -m venv venv && ./venv/bin/pip install -q -r requirements-dev.txt
	docker compose up -d db
seed:           ## migrate and load the synthetic world (no-op if already seeded)
	$(PY) -m noc.seed --if-empty
dev:            ## API with reload on :8260, jobs run by a local worker
	($(PY) -m core.jobs noc.api &) && $(PY) -m uvicorn noc.api:app --reload --port 8260
test:
	$(PY) -m pytest --cov=noc --cov=core --cov-report=term-missing
demo:           ## the full stack in Docker, then the demo scenario against it
	docker compose up --build -d --wait && $(PY) -m core.scenario $(BASE)
load-test:      ## run `make demo` first
	$(PY) -m core.loadtest $(BASE) metro-noc_manager-demo 16 8 "GET /v1/network/topology" "GET /v1/network/overview?hours=12" "GET /v1/cells/S10-B-L/kpis?hours=48" "GET /v1/incidents?status=all"
evaluate:       ## held-out metros -> docs/evaluation.md
	$(PY) -m noc.evaluate > docs/evaluation.md
reset:          ## drop all data (volume included)
	docker compose down -v
.PHONY: bootstrap seed dev test demo load-test evaluate reset
