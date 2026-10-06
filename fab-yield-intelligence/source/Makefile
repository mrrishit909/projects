export DATABASE_URL ?= postgresql://app:app-dev-only@127.0.0.1:55230/app
PY = ./venv/bin/python
BASE = http://127.0.0.1:8230

bootstrap:      ## local virtualenv + database container
	python3 -m venv venv && ./venv/bin/pip install -q -r requirements-dev.txt
	docker compose up -d db
seed:           ## migrate and load the synthetic world (no-op if already seeded)
	$(PY) -m fab.seed --if-empty
dev:            ## API with reload on :8230, jobs run by a local worker
	($(PY) -m core.jobs fab.api &) && $(PY) -m uvicorn fab.api:app --reload --port 8230
test:
	$(PY) -m pytest --cov=fab --cov=core --cov-report=term-missing
demo:           ## the full stack in Docker, then the demo scenario against it
	docker compose up --build -d --wait && $(PY) -m core.scenario $(BASE)
load-test:      ## run `make demo` first
	$(PY) -m core.loadtest $(BASE) fab-yield_manager-demo 16 8 "GET /v1/fab/overview?last=48" "GET /v1/tools/ETCH-03/health?runs=240" "GET /v1/alerts?kind=all"
evaluate:       ## held-out fabs -> docs/evaluation.md
	$(PY) -m fab.evaluate > docs/evaluation.md
reset:          ## drop all data (volume included)
	docker compose down -v
.PHONY: bootstrap seed dev test demo load-test evaluate reset
