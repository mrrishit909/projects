export DATABASE_URL ?= postgresql://app:app-dev-only@127.0.0.1:55300/app
PY = ./venv/bin/python
BASE = http://127.0.0.1:8300

bootstrap:      ## local virtualenv + database container
	python3 -m venv venv && ./venv/bin/pip install -q -r requirements-dev.txt
	docker compose up -d db
seed:           ## migrate and create the tenants and demo tokens (no-op if already seeded)
	$(PY) -m trials.seed --if-empty
dev:            ## API with reload on :8300, jobs run by a local worker
	($(PY) -m core.jobs trials.api &) && $(PY) -m uvicorn trials.api:app --reload --port 8300
test:
	$(PY) -m pytest --cov=trials --cov=core --cov-report=term-missing
demo:           ## the full stack in Docker, then the demo scenario against it
	docker compose up --build -d --wait && $(PY) -m core.scenario $(BASE)
load-test:      ## run `make demo` first
	SID=$$(curl -s -H "Authorization: Bearer net-viewer-demo" $(BASE)/v1/network/overview | $(PY) -c "import json,sys; print(json.load(sys.stdin)['studies'][0]['id'])"); \
	$(PY) -m core.loadtest $(BASE) net-study_director-demo 16 8 "GET /v1/network/overview" "GET /v1/studies/$$SID/funnel" "GET /v1/sites/S-017" "GET /v1/studies/$$SID/matches?status=potential&limit=20"
evaluate:       ## held-out networks -> docs/evaluation.md
	$(PY) -m trials.evaluate > docs/evaluation.md
reset:          ## drop all data (volume included)
	docker compose down -v
.PHONY: bootstrap seed dev test demo load-test evaluate reset
