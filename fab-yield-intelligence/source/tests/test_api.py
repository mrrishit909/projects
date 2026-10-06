"""Integration, end-to-end and security tests against a real Postgres."""
import uuid

import pytest

from core import db, jobs, scenario

from .conftest import bearer

MANAGER, ENGINEER, VIEWER, OTHER = bearer("fab", "yield_manager"), bearer("fab", "process_engineer"), bearer("fab", "viewer"), bearer("other", "yield_manager")


def test_nothing_works_before_a_fab_is_loaded(client):
    assert client.get("/v1/fab/overview", headers=VIEWER).json()["code"] == "no_fab"
    assert client.post("/v1/lots/ingest", headers=ENGINEER, json={"lots": [{"lot": "X-1", "product": "P1", "wafers": [{"slot": 1, "steps": [], "die_bins": "1"}]}]}).json()["code"] == "no_fab"


@pytest.fixture(scope="module")
def demo(client):
    results, _ = scenario.run(client, drain=jobs.drain)
    return results


def one(sql, params=(), tenant=None):
    with db.tx(tenant) as c:
        return c.execute(sql, params).fetchone()


def test_demo_journey(demo):
    load = demo["load"]["result"]
    assert load["lots"] == 448 and load["wafers"] == 11200 and load["chambers"] == 27 and load["dies_per_wafer"] == 540
    m = load["models"]
    assert m["classifier"]["macro_f1"] > m["classifier"]["baseline_macro_f1"] and m["yield"]["mae_pp"] < m["yield"]["baseline_mae_pp"] and m["yield"]["mae_pp"] < 2.5
    assert m["pattern_to_step_prior"]["edge-ring"]["etch"] > 0.8
    assert one("SELECT count(*) AS n FROM model_artifacts WHERE approved")["n"] == 3 and one("SELECT count(*) AS n FROM wafers WHERE pattern IS NULL")["n"] == 0
    assert demo["map0"]["model_version"] and len(demo["map0"]["dies"]) == 540 and len({(d[0], d[1]) for d in demo["map0"]["dies"]}) == 540
    assert all(not ch["alarms_at_lots"] for ch in demo["tool0"]["chambers"])
    adv = demo["adv"]["result"]
    raised = [(lot["index"], a["kind"], a.get("chamber") or a.get("pattern")) for lot in adv["lots"] for a in lot["alerts_raised"]]
    drift = [r for r in raised if r[1] == "drift"]
    first_edge = min(lot["index"] for lot in adv["lots"] if lot["patterns"].get("edge-ring"))
    assert drift == [(453, "drift", "ETCH-03/B")] and drift[0][0] < first_edge                 # the sensor told us before the wafers did
    assert any(r[1:] == ("excursion", "edge-ring") for r in raised) and adv["simulation_truth"]["told"][0]["chamber"] == "ETCH-03/B"
    assert demo["ingest"]["accepted"][0]["lot"] == "EXT-PARTNER-0412" and demo["ingest"]["refused"][0]["why"] == "slot 1: unknown chamber ETCH-09/A for etch"
    rc = demo["rc"]["result"]
    assert rc["top"]["chamber"] == "ETCH-03/B" and rc["top"]["confidence"] > 0.9 and rc["top"]["evidence"]["sensor_change_point"] and rc["top"]["evidence"]["affected_rate_elsewhere_in_step"] < 0.05
    assert rc["exposed_since_lot"] == 453 and 3.0 < rc["estimated_drift"]["deviation"] < 4.5 and demo["map1"]["pattern"] == "edge-ring"
    assert one("SELECT count(*) AS n FROM model_runs")["n"] >= 2 * 40 * 25 and one("SELECT count(*) AS n FROM model_runs WHERE inputs_hash !~ '^[0-9a-f]{16}$'")["n"] == 0
    assert demo["self"]["status"] == 403 and demo["approve"]["status"] == "approved" and demo["approve"]["chamber_on_hold"] == "ETCH-03/B"
    assert one("SELECT count(*) AS n FROM lots WHERE status = 'quarantined'")["n"] == len(rc["exposed_lots"]) and one("SELECT status FROM chambers WHERE id = 'ETCH-03/B'")["status"] == "hold"
    cf = demo["cf"]["result"]
    offset, route = cf["alternatives"]
    assert cf["reproduces_actual"] and route["pattern_wafers_counterfactual"] == 0 and route["mean_yield_counterfactual"] > offset["mean_yield_counterfactual"] > offset["mean_yield_actual"]
    assert offset["pattern_wafers_counterfactual"] > 0                                          # a fixed offset over-cools the early lots
    assert "ETCH-03/B" not in {w["route"]["etch"] for lot in demo["adv2"]["result"]["lots"] for w in client_lot(lot["lot"])}
    assert demo["audit"]["chain_valid"] and {"fab.loaded", "fab.advanced", "lots.ingested", "root_cause.ranked", "quarantine.proposed", "quarantine.approved", "scenario.counterfactual"} <= {e["action"] for e in demo["audit"]["events"]}


def client_lot(lot_id):
    with db.tx() as c:
        return c.execute("""SELECT w.slot, jsonb_object_agg(p.step, p.chamber_id) AS route FROM wafers w JOIN process_events p ON p.wafer_id = w.id
                             WHERE w.lot_id = %s GROUP BY w.id, w.slot""", [lot_id]).fetchall()


def test_validation(client, demo):
    lot = lambda **kw: {"lots": [{"lot": "EXT-T-1", "product": "P1", "wafers": [{"slot": 1, "steps": [{"step": s, "chamber": c, "recipe": "r", "sensors": dict.fromkeys(k, 1.0)} for s, c, k in STEPS], "die_bins": "1" * 540}], **kw}]}  # noqa: E731
    post = lambda body: client.post("/v1/lots/ingest", headers=ENGINEER, json=body).json()      # noqa: E731
    assert post(lot())["accepted"][0]["lot"] == "EXT-T-1" and post(lot())["refused"][0]["why"] == "lot already ingested"
    bad_bins = lot(lot="EXT-T-2"); bad_bins["lots"][0]["wafers"][0]["die_bins"] = "1" * 539
    assert post(bad_bins)["refused"][0]["why"].startswith("slot 1: die_bins must be 540 digits")
    held = lot(lot="EXT-T-3"); held["lots"][0]["wafers"][0]["steps"][1]["chamber"] = "ETCH-03/B"
    assert post(held)["refused"][0]["why"] == "slot 1: chamber ETCH-03/B is on hold"
    sensors = lot(lot="EXT-T-4"); sensors["lots"][0]["wafers"][0]["steps"][0]["sensors"] = {"focus_nm": 1.0}
    assert "needs sensors" in post(sensors)["refused"][0]["why"]
    order = lot(lot="EXT-T-5"); order["lots"][0]["wafers"][0]["steps"].reverse()
    assert post(order)["refused"][0]["why"].startswith("slot 1: steps must be")
    assert client.post("/v1/fab:advance", headers=MANAGER, json={"lots": 2, "inject": {"kind": "cmp_pad_wear", "chamber": "ETCH-01/A", "rate_per_lot": 0.1, "max": 0.4}}).json()["code"] == "fault_does_not_fit_chamber"
    assert client.post("/v1/fab:advance", headers=MANAGER, json={"lots": 0}).status_code == 422
    drift = client.get("/v1/alerts?kind=all", headers=VIEWER).json()["items"]
    assert client.post("/v1/analysis/root-cause", headers=ENGINEER, json={"alert_id": next(a["id"] for a in drift if a["kind"] == "drift")}).json()["code"] == "not_an_excursion"
    assert client.post("/v1/analysis/root-cause", headers=ENGINEER, json={"alert_id": str(uuid.uuid4())}).status_code == 404
    assert client.post("/v1/scenarios/counterfactual", headers=ENGINEER, json={"case_id": demo["rc"]["result"]["case_id"], "alternatives": [{"name": "x", "adjust": {"ETCH-01/A": {"bogus": 1}}}]}).json()["code"] == "bad_adjustment"
    assert client.get("/v1/wafers/" + str(uuid.uuid4()) + "/map", headers=VIEWER).status_code == 404 and client.get("/v1/tools/NOPE/health", headers=VIEWER).status_code == 404


STEPS = [("litho", "LITHO-01/A", ["focus_nm", "dose_mj"]), ("etch", "ETCH-01/A", ["temp_c", "pressure_mt", "rf_w"]), ("depo", "DEPO-01/A", ["flow_sccm", "temp_c"]),
         ("cmp", "CMP-01/A", ["pressure_psi", "speed_rpm"]), ("implant", "IMPLANT-01/A", ["dose_pct", "energy_kev"])]


def test_roles_and_the_second_person(client, demo):
    assert client.get("/v1/fab/overview").status_code == 401 and client.get("/v1/fab/overview", headers=VIEWER).status_code == 200
    for path, body in (("/v1/lots/ingest", {"lots": []}), ("/v1/analysis/root-cause", {}), ("/v1/scenarios/counterfactual", {}), ("/v1/models/yield/predict", {})):
        assert client.post(path, headers=VIEWER, json=body).status_code == 403, path
    assert client.post("/v1/fab:advance", headers=ENGINEER, json={"lots": 1}).status_code == 403 and client.post("/v1/fab:load", headers=ENGINEER, json={}).status_code == 403
    assert client.get("/v1/audit", headers=ENGINEER).status_code == 403
    prop = client.post(f"/v1/cases/{demo['rc']['result']['case_id']}/quarantine", headers=MANAGER, json={"hold_chamber": False}).json()      # a manager proposes ...
    assert client.post(f"/v1/decisions/{prop['decision_id']}/approve", headers=MANAGER).json()["code"] == "proposer_cannot_approve"         # ... and cannot approve
    assert client.post(f"/v1/decisions/{demo['prop']['decision_id']}/approve", headers=MANAGER).json()["code"] == "already_decided"


def test_another_fab_sees_nothing(client, demo, seeded):
    assert client.get("/v1/fab/overview", headers=OTHER).json()["code"] == "no_fab"
    assert client.get(f"/v1/wafers/{demo['map1']['wafer_id']}/map", headers=bearer("other", "viewer")).status_code == 404
    for table in ("fabs", "tools", "chambers", "lots", "wafers", "process_events", "model_artifacts", "model_runs", "alerts", "root_cause_cases", "decisions", "scenarios"):
        assert one(f"SELECT count(*) AS n FROM {table}", tenant=seeded["other"])["n"] == 0 < one(f"SELECT count(*) AS n FROM {table}", tenant=seeded["fab"])["n"], table
    with pytest.raises(Exception, match="row-level security"), db.tx(seeded["other"]) as c:
        c.execute("INSERT INTO alerts (id, tenant_id, kind, first_lot, detail) VALUES (%s,%s,'drift',1,'{}')", [uuid.uuid4(), seeded["fab"]])


def test_idempotent_writes(client, demo):
    body = {"hold_chamber": True}
    again = client.post(f"/v1/cases/{demo['rc']['result']['case_id']}/quarantine", headers={**ENGINEER, "Idempotency-Key": "demo-1:prop"}, json=body)
    assert again.status_code == 201 and again.headers["Idempotent-Replay"] == "true" and again.json()["decision_id"] == demo["prop"]["decision_id"]
    assert client.post(f"/v1/cases/{demo['rc']['result']['case_id']}/quarantine", headers={**ENGINEER, "Idempotency-Key": "demo-1:prop"}, json={"hold_chamber": False}).json()["code"] == "idempotency_key_reused"
    assert client.post("/v1/fab:load", headers=MANAGER, json={"seed": 9}).json()["code"] == "fab_exists"
