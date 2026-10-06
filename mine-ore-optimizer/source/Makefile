export DATABASE_URL ?= postgresql://app:app-dev-only@127.0.0.1:55280/app
PY = ./venv/bin/python
BASE = http://127.0.0.1:8280

bootstrap:      ## local virtualenv + database container
	python3 -m venv venv && ./venv/bin/pip install -q -r requirements-dev.txt
	docker compose up -d db
seed:           ## migrate and load the synthetic world (no-op if already seeded)
	$(PY) -m mine.seed --if-empty
dev:            ## API with reload on :8280, jobs run by a local worker
	($(PY) -m core.jobs mine.api &) && $(PY) -m uvicorn mine.api:app --reload --port 8280
test:
	$(PY) -m pytest --cov=mine --cov=core --cov-report=term-missing
demo:           ## the full stack in Docker, then the demo scenario against it
	docker compose up --build -d --wait && $(PY) -m core.scenario $(BASE)
load-test:      ## run `make demo` first
	$(PY) -m core.loadtest $(BASE) mine-shift_supervisor-demo 16 8 "GET /v1/mine/overview?hours=12" "GET /v1/orebody/tiles?bench=3" "GET /v1/fleet" "GET /v1/plant/forecast?hours=8"
evaluate:       ## held-out mines -> docs/evaluation.md
	$(PY) -m mine.evaluate > docs/evaluation.md
reset:          ## drop all data (volume included)
	docker compose down -v
.PHONY: bootstrap seed dev test demo load-test evaluate reset
