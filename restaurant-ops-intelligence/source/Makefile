export DATABASE_URL ?= postgresql://app:app-dev-only@127.0.0.1:55320/app
PY = ./venv/bin/python
BASE = http://127.0.0.1:8320

bootstrap:      ## local virtualenv + database container
	python3 -m venv venv && ./venv/bin/pip install -q -r requirements-dev.txt
	docker compose up -d db
seed:           ## migrate and load the synthetic world (no-op if already seeded)
	$(PY) -m resto.seed --if-empty
dev:            ## API with reload on :8320, jobs run by a local worker
	($(PY) -m core.jobs resto.api &) && $(PY) -m uvicorn resto.api:app --reload --port 8320
test:
	$(PY) -m pytest --cov=resto --cov=core --cov-report=term-missing
demo:           ## the full stack in Docker, then the demo scenario against it
	docker compose up --build -d --wait && $(PY) -m core.scenario $(BASE)
load-test:      ## run `make demo` first
	$(PY) -m core.loadtest $(BASE) resto-store_manager-demo 16 8 "GET /v1/chain/overview" "GET /v1/forecast?location=S11" "GET /v1/waste/risk?limit=20" "GET /v1/margins/explain?days=7"
evaluate:       ## held-out chains -> docs/evaluation.md
	$(PY) -m resto.evaluate > docs/evaluation.md
reset:          ## drop all data (volume included)
	docker compose down -v
.PHONY: bootstrap seed dev test demo load-test evaluate reset
