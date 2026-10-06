export DATABASE_URL ?= postgresql://app:app-dev-only@127.0.0.1:55240/app
PY = ./venv/bin/python
BASE = http://127.0.0.1:8240

bootstrap:      ## local virtualenv + database container
	python3 -m venv venv && ./venv/bin/pip install -q -r requirements-dev.txt
	docker compose up -d db
seed:           ## migrate and create the tenants and demo tokens (no-op if already seeded)
	$(PY) -m wh.seed --if-empty
dev:            ## API with reload on :8240, jobs run by a local worker
	($(PY) -m core.jobs wh.api &) && $(PY) -m uvicorn wh.api:app --reload --port 8240
test:
	$(PY) -m pytest --cov=wh --cov=core --cov-report=term-missing
demo:           ## the full stack in Docker, then the demo scenario against it
	docker compose up --build -d --wait && $(PY) -m core.scenario $(BASE)
load-test:      ## run `make demo` first
	$(PY) -m core.loadtest $(BASE) wh-shift_manager-demo 16 8 "GET /v1/fleet/state" "GET /v1/tasks?status=open&limit=100" "GET /v1/conflicts?kind=replan" "GET /v1/batteries"
evaluate:       ## held-out warehouses and waves -> docs/evaluation.md (about fifteen minutes)
	$(PY) -m wh.evaluate > docs/evaluation.md
reset:          ## drop all data (volume included)
	docker compose down -v
.PHONY: bootstrap seed dev test demo load-test evaluate reset
