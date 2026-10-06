"""Integration, end-to-end and security tests against a real Postgres."""
import uuid

import pytest

from core import db, jobs, scenario

from .conftest import bearer

SUPER, ENGINEER, VIEWER, OTHER = bearer("mine", "shift_supervisor"), bearer("mine", "mine_engineer"), bearer("mine", "viewer"), bearer("other", "shift_supervisor")


def test_nothing_works_before_a_mine_is_loaded(client):
    assert client.get("/v1/mine/overview", headers=VIEWER).json()["code"] == "no_mine"
    assert client.post("/v1/dispatch/optimize", headers=ENGINEER, json={}).json()["code"] == "no_mine"


@pytest.fixture(scope="module")
def demo(client):
    results, _ = scenario.run(client, drain=jobs.drain)
    return results


def one(sql, params=(), tenant=None):
    with db.tx(tenant) as c:
        return c.execute(sql, params).fetchone()


def test_demo_journey(demo):
    load = demo["load"]["result"]
    assert load["blocks"] == 28800 and load["trucks_up"] == 28 and load["history_shifts"] == 14 and load["clock"].startswith("2026-10-01T06:00")
    m = load["models"]
    assert m["grade"]["model"]["rmse"] < m["grade"]["idw"]["rmse"] < m["grade"]["nearest_hole"]["rmse"] and m["grade"]["model"]["misclassified"] < m["grade"]["idw"]["misclassified"]
    assert m["cycle_time"]["mape_pct"] < 10 < m["cycle_time"]["baseline_mape_pct"] and m["plant"]["mae_tph"] < m["plant"]["baseline_mae_tph"]
    assert m["anomaly"]["model"]["false_per_1000_truck_hours"] < m["anomaly"]["static_thresholds"]["false_per_1000_truck_hours"]
    assert not demo["ov0"]["open_alerts"] and demo["ov0"]["fleet"] == {"up": 28}                     # the history ends clean
    assert one("SELECT count(*) AS n FROM model_artifacts WHERE approved")["n"] == 5
    s1_before = demo["tiles0"]["shovels"][0]
    assert s1_before["shovel"] == "S1" and min(s1_before["next_cu"][:8]) > 0.45                     # ore control thinks S1's next blast is high grade
    adv = demo["adv"]["result"]
    feed = [h["feed_cu"] for h in adv["plant_hours"]]
    assert feed[0] > 0.48 > feed[-1] and adv["trucks_up"] == 25 and adv["reestimate"]["blocks_reclassified"] > 0
    alerts = {(a["kind"], a["truck"]): a for a in adv["alerts"]}
    assert alerts[("breakdown", "T07")]["anomaly_alert_lead_min"] is None                            # a tyre gives no warning
    assert alerts[("breakdown", "T16")]["anomaly_alert_lead_min"] >= 30 and alerts[("breakdown", "T22")]["anomaly_alert_lead_min"] >= 30
    assert adv["simulation_truth"]["told"][0]["kind"] == "low_grade_zone"
    s1_after = demo["tiles1"]["shovels"][0]
    assert max(s1_after["next_cu"][:5]) < 0.45 and "HG" not in s1_after["next_cls"][:5]               # the assays revealed the dyke
    assert demo["tele"]["accepted"] == 1 and demo["tele"]["refused"][0]["why"] == "unknown truck"
    assert demo["fc1"]["hours_inside_window"] < demo["fc0"]["hours_inside_window"]
    opt = demo["opt"]["result"]
    assert opt["trucks_up"] == 25 and sum(s["optimized"]["trucks"] for s in opt["shovels"]) <= 25 and opt["solve_ms"] < 10000 and opt["gap"] < 0.01
    bl = demo["blend"]["result"]
    assert bl["hours_inside"] > bl["baseline_hours_inside"] and all(v % 50 == 0 for h in bl["hours"] for v in h["reclaim_tph"].values())
    tw = demo["twin"]["result"]
    diff = next(v for p in tw["plans"].values() for k, v in p.items() if k.startswith("vs_"))
    assert diff["net_value_usd"]["mean"] > 0 and diff["revenue_usd"]["better_in"] == 1 and diff["fuel_l"]["mean"] < 0 and diff["hours_in_window"]["mean"] > 0
    assert demo["prop"]["policy_checks"] == {"blend_schedule": True, "twin_not_worse": True} and demo["self"]["status"] == 403 and demo["approve"]["status"] == "approved"
    assert one("SELECT kind FROM dispatch_plan WHERE status = 'active'")["kind"] == "optimized"
    out = demo["adv2"]["result"]["simulation_truth"]["shift_outcome"]
    d = out["difference"]                                                                          # what the generator then did, against the plan kept
    assert d["revenue_usd"] > 0 and d["copper_t"] > 0 and d["fuel_l"] < 0 and d["hours_in_window"] > 0 and d["moved_t"] > 0
    assert one("SELECT count(*) AS n FROM model_runs WHERE inputs_hash !~ '^[0-9a-f]{16}$'")["n"] == 0 and one("SELECT count(*) AS n FROM model_runs")["n"] > 1000
    assert demo["audit"]["chain_valid"] and {"mine.loaded", "mine.advanced", "telemetry.ingested", "dispatch.optimized", "blend.solved", "twin.simulated", "plan.proposed",
                                             "plan.approved"} <= {e["action"] for e in demo["audit"]["events"]}


def test_validation(client, demo):
    adv = lambda body: client.post("/v1/mine:advance", headers=SUPER, json=body)                   # noqa: E731
    assert adv({"minutes": 60}).json()["code"] == "shift_over" and adv({"minutes": 5}).status_code == 422
    rec = {"truck": "T03", "at": "2026-10-01T17:50:00Z", "state": "working", "duty": 0.4, "speed_kmh": 20, "payload_t": 210, "loaded_frac": 0.5, "ambient_c": 30,
           "coolant_c": 95, "oil_kpa": 400, "exhaust_c": 480, "fuel_lph": 170}
    post = lambda *rs: client.post("/v1/telemetry", headers=ENGINEER, json={"source": "probe", "records": list(rs)}).json()   # noqa: E731
    r = post(rec, {**rec, "at": "2026-10-01T17:55:00Z"}, {**rec, "at": "2026-10-02T09:00:00Z"}, {**rec, "at": "2026-09-29T09:00:00Z"}, {**rec, "truck": "T04", "coolant_c": 400},
             {**rec, "truck": "T05", "oil_kpa": None}, rec)
    assert r["accepted"] == 1 and [x["why"] for x in r["refused"]] == ["at must be on a 10-minute boundary", "ahead of the mine clock", "older than a day",
                                                                       "coolant_c = 400.0 is outside -20..140", r["refused"][4]["why"], "duplicate record for this truck, window and source"]
    assert r["refused"][4]["why"].startswith("a working record needs")
    assert client.post("/v1/blends/solve", headers=ENGINEER, json={"plan_id": str(uuid.uuid4())}).status_code == 404
    assert client.post("/v1/blends/solve", headers=ENGINEER, json={"plan_id": demo["opt"]["result"]["plan_id"]}).json()["code"] == "plan_not_draft"
    assert client.post("/v1/twin/simulate", headers=ENGINEER, json={"plan_ids": [str(uuid.uuid4()), demo["opt"]["result"]["plan_id"]]}).json()["code"] == "plan_not_found"
    assert client.get("/v1/orebody/tiles?bench=9", headers=VIEWER).status_code == 422


def test_roles_and_the_second_person(client, demo, seeded):
    assert client.get("/v1/fleet").status_code == 401 and client.get("/v1/fleet", headers=VIEWER).status_code == 200
    for path in ("/v1/telemetry", "/v1/dispatch/optimize", "/v1/blends/solve", "/v1/twin/simulate"):
        assert client.post(path, headers=VIEWER, json={}).status_code == 403, path
    assert client.post("/v1/mine:advance", headers=ENGINEER, json={"minutes": 30}).status_code == 403 and client.get("/v1/audit", headers=ENGINEER).status_code == 403
    opt = client.post("/v1/dispatch/optimize", headers=SUPER, json={"horizon_h": 2}).json()           # a supervisor optimises ...
    while opt.get("status") in ("queued", "running"):
        jobs.drain()
        opt = client.get(opt["status_url"], headers=SUPER).json()
    pid = opt["result"]["plan_id"]
    assert client.post(f"/v1/dispatch/plans/{pid}/propose", headers=SUPER, json={}).json()["code"] == "policy_not_met"      # no blend, no twin evidence
    with db.tx() as c:                                                                                # (evidence waived here to reach the approval rule)
        c.execute("UPDATE dispatch_plan SET plan = jsonb_set(plan, '{reclaim}', '{\"mode\": \"schedule\", \"hours\": []}') WHERE id = %s", [pid])
    sim = demo["twin"]["result"]["simulation_id"]
    assert client.post(f"/v1/dispatch/plans/{pid}/propose", headers=SUPER, json={"simulation_id": sim}).json()["code"] == "simulation_does_not_cover_plan"
    did = uuid.uuid4()
    with db.tx() as c:                                                                                # the supervisor's own proposal, recorded as the endpoint would
        c.execute("UPDATE dispatch_plan SET status = 'proposed' WHERE id = %s", [pid])
        c.execute("""INSERT INTO decision_record (id, tenant_id, subject_type, subject_id, decision_type, model_versions, inputs_hash, result, proposed_by)
                     VALUES (%s,%s,'dispatch_plan',%s,'dispatch','{}','x','{}',%s)""", [did, seeded["mine"], pid, uuid.uuid5(seeded["mine"], "shift_supervisor")])
    assert client.post(f"/v1/decisions/{did}/approve", headers=SUPER).json()["code"] == "proposer_cannot_approve"          # ... and cannot approve its own
    assert client.post(f"/v1/decisions/{demo['prop']['decision_id']}/approve", headers=SUPER).json()["code"] == "already_decided"


def test_another_operator_sees_nothing(client, demo, seeded):
    assert client.get("/v1/mine/overview", headers=OTHER).json()["code"] == "no_mine"
    assert client.get("/v1/orebody/tiles?bench=3", headers=bearer("other", "viewer")).json()["code"] == "no_mine"
    for table in ("mine", "bench", "block", "site_node", "haul_road", "vehicle", "shovel", "stockpile", "assay", "haul_event", "truck_telemetry", "plant_feed",
                  "equipment_alert", "dispatch_plan", "blend_plan", "simulation_run", "decision_record", "model_artifacts", "model_runs"):
        assert one(f"SELECT count(*) AS n FROM {table}", tenant=seeded["other"])["n"] == 0 < one(f"SELECT count(*) AS n FROM {table}", tenant=seeded["mine"])["n"], table
    with pytest.raises(Exception, match="row-level security"), db.tx(seeded["other"]) as c:
        c.execute("INSERT INTO equipment_alert (id, tenant_id, truck, kind, raised_at) VALUES (%s,%s,'T01','anomaly',now())", [uuid.uuid4(), seeded["mine"]])
    with pytest.raises(Exception, match="permission denied"), db.tx(seeded["other"]) as c:
        c.execute("SELECT count(*) FROM truck_telemetry_2026_10")                  # a partition is only reachable through the parent's policy


def test_idempotent_writes(client, demo):
    body = {"simulation_id": demo["twin"]["result"]["simulation_id"]}
    again = client.post(f"/v1/dispatch/plans/{demo['opt']['result']['plan_id']}/propose", headers={**ENGINEER, "Idempotency-Key": "demo-1:prop"}, json=body)
    assert again.status_code == 201 and again.headers["Idempotent-Replay"] == "true" and again.json()["decision_id"] == demo["prop"]["decision_id"]
    assert client.post(f"/v1/dispatch/plans/{demo['opt']['result']['plan_id']}/propose", headers={**ENGINEER, "Idempotency-Key": "demo-1:prop"}, json={}).json()["code"] == "idempotency_key_reused"
    assert client.post("/v1/mine:load", headers=SUPER, json={"seed": 9}).json()["code"] == "mine_exists"
