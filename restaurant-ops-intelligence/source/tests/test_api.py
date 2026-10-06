"""Integration, end-to-end and security tests against a real Postgres."""
import uuid

import pytest

from core import db, jobs, scenario

from .conftest import bearer

MANAGER, PLANNER, VIEWER, OTHER = bearer("resto", "store_manager"), bearer("resto", "planner"), bearer("resto", "viewer"), bearer("other", "store_manager")


def test_nothing_works_before_a_chain_is_loaded(client):
    assert client.get("/v1/chain/overview", headers=VIEWER).json()["code"] == "no_chain"
    assert client.post("/v1/prep/plan", headers=PLANNER, json={}).json()["code"] == "no_chain"
    assert client.post("/v1/sales/ingest", headers=PLANNER, json={"tickets": [{"ticket_id": "t1", "location": "S01", "at": "2026-09-28T12:00:00",
                                                                             "channel": "dine_in", "lines": [{"item": "fries", "qty": 1}]}]}).json()["code"] == "no_chain"


@pytest.fixture(scope="module")
def demo(client):
    results, _ = scenario.run(client, drain=jobs.drain)
    return results


def one(sql, params=(), tenant=None):
    with db.tx(tenant) as c:
        return c.execute(sql, params).fetchone()


def test_demo_journey(demo):
    load = demo["load"]["result"]
    assert load["stores"] == 50 and load["days"] == 56 and load["units_sold"] > 2_000_000 and load["shrinkage_flags"] == 4 and load["threshold_flags"] == 50
    dm = load["models"]["demand"]
    assert dm["lunch_slot_wape"] < dm["baseline_lunch_slot_wape"] and 0.85 <= dm["item_lunch_coverage_90"] <= 0.95 and 0.85 <= dm["lunch_slot_pit_coverage_90"] <= 0.95
    assert abs(dm["rain_effect"]["dine_in"] + 0.5) < 0.1 and load["models"]["consumption"]["usage_wape"] < load["models"]["consumption"]["baseline_recipes_only_wape"]
    assert load["models"]["hazard"]["auc"] > load["models"]["hazard"]["auc_printed_date"]
    assert one("SELECT count(*) AS n FROM model_artifacts WHERE approved")["n"] == 3 and one("SELECT count(*) AS n FROM sales WHERE business_date < '2026-09-28'")["n"] == load["sales_rows"]
    fc1, get1 = demo["fc1"]["result"], demo["get1"]
    assert fc1["stores"] == 50 and fc1["slots"] == 57_600 and fc1["duration_ms"] < 120_000
    ch = get1["chain"]
    assert ch["lunch_lo"] < ch["lunch_mean"] < ch["lunch_hi"] and abs(sum(s["lunch_mean"] for s in get1["stores"]) - ch["lunch_mean"]) < 1   # the levels add up
    assert abs(sum(i["lunch_mean"] for i in get1["location"]["items"]) - next(s["lunch_mean"] for s in get1["stores"] if s["id"] == "S11")) < 0.5
    plan1, rec1 = demo["plan1"], demo["rec1"]["result"]
    assert plan1["summary"]["tasks"] == 450 and all(t["qty"] >= t["forecast_mean"] for t in plan1["example"]["tasks"])
    assert rec1["lines"] > 500 and not rec1["delays_known"] and demo["risk"]["lots"][0]["expected_loss_usd"] >= demo["risk"]["lots"][-1]["expected_loss_usd"]
    # the injection reaches the service as notices; the forecast and the plans move
    assert [n["kind"] for n in demo["inject"]["result"]["notices"]] == ["supplier_delay", "weather_forecast"] and demo["inject"]["result"]["simulation_truth"]["told"]
    assert demo["pos"]["accepted"][0]["units"] == 24 and [r["why"] for r in demo["pos"]["refused"]] == ["unknown item nachos_supreme", "duplicate ticket"]
    s11 = lambda g: next(s for s in g["stores"] if s["id"] == "S11")                # noqa: E731
    assert s11(demo["get2"])["lunch_mean"] < s11(demo["get1"])["lunch_mean"] and s11(demo["get2"])["delivery_share_lunch"] > s11(demo["get1"])["delivery_share_lunch"]
    assert s11(demo["get2"])["rain_lunch"] >= 0.8 and demo["get2"]["chain"]["lunch_mean"] < demo["get1"]["chain"]["lunch_mean"]
    assert demo["plan2"]["superseded"] == demo["plan1"]["plan_id"] and one("SELECT status FROM prep_plans WHERE id = %s", [demo["plan1"]["plan_id"]])["status"] == "superseded"
    rec2 = demo["rec2"]["result"]
    assert rec2["superseded"] == rec1["recommendation_id"] and rec2["delays_known"][0]["supplier"] == "produce" and rec2["by_supplier"]["backup"]["lines"] > 20
    backed = {r["location"] for r in rec2["example_lines"] if r["supplier"] == "backup"} | {r["location"] for r in rec2["needs_approval"]}
    assert backed and rec2["proposed"] > 0 and all(x["value_usd"] > 250 for x in rec2["needs_approval"])
    assert demo["self"]["status"] == 403 and demo["approve"]["status"] == "approved" and demo["approve"]["lines"] == rec2["proposed"]
    # the days ran on the approved plan; the replay reproduces them and both other plans do worse
    adv, cmp = demo["adv"]["result"], demo["cmp"]["result"]
    assert len(adv["days"]) == 3 and adv["orders_placed_at_start"] and adv["days"][0]["backup_deliveries_usd"] > 0
    assert one("SELECT count(*) AS n FROM prep_tasks WHERE plan_id = %s AND status = 'done'", [demo["plan2"]["plan_id"]])["n"] == 300   # lunch rows; dinner re-planned at 15:00
    alts = {a["name"]: a for a in cmp["alternatives"]}
    assert cmp["reproduces_actual"] and set(alts) == {"as run", "plan before the notices", "usual practice"}
    assert alts["as run"]["stockout_rate"] < alts["plan before the notices"]["stockout_rate"] < alts["usual practice"]["stockout_rate"]
    assert alts["as run"]["waste_usd"] < alts["plan before the notices"]["waste_usd"] < alts["usual practice"]["waste_usd"]
    assert alts["as run"]["lost_units"] == adv["simulation_truth"]["lost_units"]
    m = demo["margins"]
    assert m["bridge"][0]["step"].startswith("theoretical") and abs(sum(b["usd"] for b in m["bridge"][:-1]) - m["bridge"][-1]["usd"]) < 1
    assert any(p["item"] == "chicken_tacos" and p["incremental_units"] > 0 for p in m["promotions"])
    sh = demo["shrink"]
    assert sh["stores_flagged"] == 4 and sh["threshold_baseline"]["stores_flagged"] == 50 and {f["class"] for f in sh["flagged"]} == {"over-portioning", "theft or unrecorded loss"}
    assert one("SELECT count(*) AS n FROM model_runs WHERE inputs_hash !~ '^[0-9a-f]{16}$'")["n"] == 0 and one("SELECT count(*) AS n FROM model_runs")["n"] >= 300
    assert demo["audit"]["chain_valid"] and {"chain.loaded", "forecast.refreshed", "prep.planned", "orders.recommended", "chain.told", "sales.ingested",
                                             "orders.approved", "chain.advanced", "outcomes.compared"} <= {e["action"] for e in demo["audit"]["events"]}


def test_reads_and_drilldowns(client, demo):
    assert client.get("/v1/forecast?date=2026-10-05", headers=VIEWER).json()["code"] == "no_forecast"
    assert client.get("/v1/forecast?date=2026-09-29&location=NOPE", headers=VIEWER).status_code == 404
    day2 = client.get("/v1/forecast?date=2026-09-29&location=S03", headers=VIEWER).json()
    assert day2["location"]["id"] == "S03" and len(day2["chain"]["slots"]) == 48
    m = client.get("/v1/margins/explain?days=14&location=S15", headers=VIEWER).json()
    assert m["scope"] == "S15" and m["ingredients"][0]["unexplained_usd"] >= m["ingredients"][-1]["unexplained_usd"]
    assert client.get("/v1/margins/explain?location=NOPE", headers=VIEWER).status_code == 404
    r = client.get("/v1/waste/risk?location=S11&limit=5", headers=VIEWER).json()
    assert all(x["location"] == "S11" for x in r["lots"]) and r["model"].startswith("spoilage")
    ov = client.get("/v1/chain/overview", headers=VIEWER).json()
    assert ov["next_business_day"] == "2026-10-01" and len(ov["stores"]) == 50 and len(ov["notices"]) == 2 and ov["decisions_awaiting"] == 0
    assert client.get("/v1/decisions", headers=VIEWER).json()["items"][0]["status"] == "approved"


def test_validation(client, demo):
    tk = lambda **kw: {"tickets": [{"ticket_id": "T-1", "location": "S01", "at": "2026-10-01T12:00:00", "channel": "dine_in", "lines": [{"item": "fries", "qty": 2}], **kw}]}   # noqa: E731
    post = lambda body: client.post("/v1/sales/ingest", headers=PLANNER, json=body)      # noqa: E731
    assert post(tk()).json()["accepted"][0]["slot"] == "12:00" and post(tk()).json()["refused"][0]["why"] == "duplicate ticket"
    assert post(tk(ticket_id="T-2", location="S99")).json()["refused"][0]["why"] == "unknown location S99"
    assert post(tk(ticket_id="T-3", at="2026-09-30T12:00:00")).json()["refused"][0]["why"].startswith("business day is 2026-10-01")
    assert post(tk(ticket_id="T-4", at="2026-10-01T23:10:00")).json()["refused"][0]["why"] == "outside opening hours (10:00-22:00)"
    assert post(tk(ticket_id="T-5", lines=[{"item": "fries", "qty": 0}])).status_code == 422
    assert post(tk(ticket_id="bad id!")).status_code == 422 and post({"tickets": []}).status_code == 422
    adv = lambda body: client.post("/v1/chain:advance", headers=MANAGER, json=body).json()              # noqa: E731
    assert adv({"days": 0, "inject": [{"kind": "supplier_delay", "regions": ["Harbor"]}]})["code"] == "supplier_required"
    assert adv({"days": 0, "inject": [{"kind": "rainstorm", "regions": ["Harbor"], "from_hour": 14, "to_hour": 12}]})["code"] == "bad_window"
    assert adv({"days": 0, "inject": [{"kind": "supplier_delay", "supplier": "broadline", "regions": ["Harbor"]}]})["code"] == "no_delivery_tomorrow"
    assert adv({"days": 0, "inject": [{"kind": "hail", "regions": ["Harbor"]}]})["code"] == "validation_failed"
    assert adv({"days": 9})["code"] == "validation_failed"
    assert client.post("/v1/prep/plan", headers=PLANNER, json={"date": "2026-10-05"}).json()["code"] == "not_tomorrow"
    assert client.post(f"/v1/decisions/{uuid.uuid4()}/approve", headers=MANAGER).status_code == 404


def test_roles_and_the_second_person(client, demo):
    assert client.get("/v1/chain/overview").status_code == 401 and client.get("/v1/chain/overview", headers={"Authorization": "Bearer nope"}).status_code == 401
    for path, body in (("/v1/sales/ingest", {"tickets": []}), ("/v1/forecast:refresh", {}), ("/v1/prep/plan", {}), ("/v1/orders/recommend", None), ("/v1/outcomes:compare", None)):
        assert client.post(path, headers=VIEWER, json=body).status_code == 403, path
    assert client.post("/v1/chain:advance", headers=PLANNER, json={"days": 1}).status_code == 403 and client.post("/v1/chain:load", headers=PLANNER, json={}).status_code == 403
    assert client.get("/v1/audit", headers=PLANNER).status_code == 403
    # a store manager who asks for a recommendation cannot approve its changes: tell the generator about tomorrow's late truck first
    told = client.post("/v1/chain:advance", headers=MANAGER, json={"days": 0, "inject": [{"kind": "supplier_delay", "supplier": "produce", "regions": ["Lakeside", "Midtown"]}]})
    assert jobs.drain() and client.get(told.json()["status_url"], headers=MANAGER).json()["status"] == "succeeded"
    rec = client.post("/v1/orders/recommend", headers=MANAGER)
    jobs.drain()
    r = client.get(rec.json()["status_url"], headers=MANAGER).json()["result"]
    assert r["proposed"] > 0 and r["delays_known"][-1]["regions"] == ["Lakeside", "Midtown"]
    assert client.post(f"/v1/decisions/{r['decision_id']}/approve", headers=MANAGER).json()["code"] == "proposer_cannot_approve"
    assert client.post(f"/v1/decisions/{demo['rec2']['result']['decision_id']}/approve", headers=MANAGER).json()["code"] == "already_decided"


def test_another_group_sees_nothing(client, demo, seeded):
    assert client.get("/v1/chain/overview", headers=OTHER).json()["code"] == "no_chain"
    assert client.get("/v1/forecast", headers=bearer("other", "viewer")).json()["code"] == "no_chain"
    assert client.get(f"/v1/jobs/{demo['adv']['job_id']}", headers=OTHER).status_code == 404
    for table in ("chains", "locations", "sales", "conditions", "inventory_lots", "inventory_counts", "supplier_orders", "prep_tasks", "waste_events",
                  "forecasts", "forecast_runs", "promotions", "notices", "decisions", "model_artifacts", "model_runs", "outcomes", "alerts"):
        assert one(f"SELECT count(*) AS n FROM {table}", tenant=seeded["other"])["n"] == 0 < one(f"SELECT count(*) AS n FROM {table}", tenant=seeded["resto"])["n"], table
    with pytest.raises(Exception, match="row-level security"), db.tx(seeded["other"]) as c:
        c.execute("INSERT INTO notices (id, tenant_id, kind, received_on, detail) VALUES (%s,%s,'supplier_delay','2026-09-27','{}')", [uuid.uuid4(), seeded["resto"]])


def test_idempotent_writes(client, demo):
    again = client.post("/v1/prep/plan", headers={**PLANNER, "Idempotency-Key": "demo-1:plan2"}, json={})
    assert again.status_code == 201 and again.headers["Idempotent-Replay"] == "true" and again.json()["plan_id"] == demo["plan2"]["plan_id"]
    assert client.post("/v1/prep/plan", headers={**PLANNER, "Idempotency-Key": "demo-1:plan2"}, json={"date": "2026-09-28"}).json()["code"] == "idempotency_key_reused"
    replay = client.post("/v1/sales/ingest", headers={**PLANNER, "Idempotency-Key": "demo-1:pos"}, json=scenario.load()["steps"][3]["calls"][2]["body"])
    assert replay.headers["Idempotent-Replay"] == "true" and replay.json()["accepted"][0]["units"] == 24
    assert client.post("/v1/chain:load", headers=MANAGER, json={"seed": 9}).json()["code"] == "chain_exists"
    assert client.post("/v1/outcomes:compare", headers={**PLANNER, "Idempotency-Key": "demo-1:cmp"}).json()["job_id"] == demo["cmp"]["job_id"]
