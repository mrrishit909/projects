export DATABASE_URL ?= postgresql://app:app-dev-only@127.0.0.1:55290/app
PY = ./venv/bin/python
BASE = http://127.0.0.1:8290

bootstrap:      ## local virtualenv + database container
	python3 -m venv venv && ./venv/bin/pip install -q -r requirements-dev.txt
	docker compose up -d db
seed:           ## migrate and create the tenants, demo tokens and the people they sign in as (no-op if already seeded)
	$(PY) -m ekg.seed --if-empty
dev:            ## API with reload on :8290, jobs run by a local worker
	($(PY) -m core.jobs ekg.api &) && $(PY) -m uvicorn ekg.api:app --reload --port 8290
test:
	$(PY) -m pytest --cov=ekg --cov=core --cov-report=term-missing
demo:           ## the full stack in Docker, then the demo scenario against it
	docker compose up --build -d --wait && $(PY) -m core.scenario $(BASE)
load-test:      ## run `make demo` first
	$(PY) -m core.loadtest $(BASE) halden-viewer-demo 16 8 "GET /v1/overview" "GET /v1/entities?q=rate-limiter" "GET /v1/resolution"
evaluate:       ## held-out corpora -> docs/evaluation.md
	$(PY) -m ekg.evaluate > docs/evaluation.md
reset:          ## drop all data (volume included)
	docker compose down -v
.PHONY: bootstrap seed dev test demo load-test evaluate reset
