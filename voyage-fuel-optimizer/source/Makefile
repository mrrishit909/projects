export DATABASE_URL ?= postgresql://app:app-dev-only@127.0.0.1:55310/app
PY = ./venv/bin/python
BASE = http://127.0.0.1:8310

bootstrap:      ## local virtualenv + database container
	python3 -m venv venv && ./venv/bin/pip install -q -r requirements-dev.txt
	docker compose up -d db
seed:           ## migrate and load the synthetic world (no-op if already seeded)
	$(PY) -m voyage.seed --if-empty
dev:            ## API with reload on :8310, jobs run by a local worker
	($(PY) -m core.jobs voyage.api &) && $(PY) -m uvicorn voyage.api:app --reload --port 8310
test:
	$(PY) -m pytest --cov=voyage --cov=core --cov-report=term-missing
demo:           ## the full stack in Docker, then the demo scenario against it
	docker compose up --build -d --wait && $(PY) -m core.scenario $(BASE)
load-test:       ## run `make demo` first; VOYAGE is the demo voyage id from GET /v1/fleet
	$(PY) -m core.loadtest $(BASE) northline-operator-demo 16 8 "GET /v1/fleet" "GET /v1/voyages/$(VOYAGE)" "GET /v1/voyages/$(VOYAGE)/variance" "GET /v1/vessels/V01/performance?days=120"
evaluate:       ## held-out worlds -> docs/evaluation.md
	$(PY) -m voyage.evaluate > docs/evaluation.md
reset:          ## drop all data (volume included)
	docker compose down -v
.PHONY: bootstrap seed dev test demo load-test evaluate reset
