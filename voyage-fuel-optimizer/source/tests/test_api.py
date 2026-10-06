"""Integration, end-to-end and security tests against a real Postgres."""
import datetime
import uuid

import pytest

from core import db, jobs, scenario

from .conftest import bearer

OPERATOR, MASTER, VIEWER, OTHER = bearer("northline", "operator"), bearer("northline", "master"), bearer("northline", "viewer"), bearer("other", "operator")


def test_nothing_works_before_a_fleet_is_loaded(client):
    assert client.get("/v1/fleet", headers=VIEWER).json()["code"] == "no_fleet"
    assert client.post("/v1/voyages", headers=OPERATOR, json={"vessel": "V01", "orig": "USNYC", "dest": "NLRTM", "terms": {
        "window_open": "2026-10-14T00:00:00Z", "window_close": "2026-10-15T00:00:00Z"}}).json()["code"] == "no_fleet"


@pytest.fixture(scope="module")
def demo(client):
    results, _ = scenario.run(client, drain=jobs.drain)
    return results


def one(sql, params=(), tenant=None):
    with db.tx(tenant) as c:
        return c.execute(sql, params).fetchone()


def iso(s):
    return datetime.datetime.fromisoformat(s)


def test_demo_journey(demo):
    load = demo["load"]["result"]
    assert load["vessels"] == 6 and load["voyages"] > 150 and load["noon_reports"] > 1500
    assert all(m["mape_pct"] < 7.0 and m["mape_pct"] < m["baseline_mape_pct"] for m in load["models"])
    assert one("SELECT count(*) AS n FROM model_artifacts WHERE approved")["n"] == 6 and one("SELECT count(*) AS n FROM fuel_sample WHERE predicted_t IS NULL")["n"] == 0
    assert demo["perf"]["fouling_now_pct"] > 10 and demo["perf"]["curve"][-1]["model_calm_today_tpd"] > demo["perf"]["curve"][-1]["sea_trial_tpd"]
    assert len(demo["reports"]["accepted"]) == 1 and demo["reports"]["refused"][0]["why"].startswith("fuel 410 t is")
    route = demo["route"]["result"]
    assert route["solve_s"] < 30 and {r["kind"] for r in route["routes"]} == {"optimized", "shortest"}
    sp = demo["speed"]["result"]
    terms = demo["voy"]["terms"]
    assert sp["within_terms"] and iso(sp["plan"]["eta"]["p90"]) <= iso(terms["window_close"]) and sp["plan"]["expected_cost_usd"] < sp["service_speed"]["expected_cost_usd"]
    assert demo["act"]["status"] == "active" and demo["bunker"]["saving_usd"] >= 0
    adv = demo["adv"]["result"]
    assert {e["kind"] for e in adv["events_raised"]} == {"storm_on_route", "port_congestion"} and {t["kind"] for t in adv["simulation_truth"]["told"]} == {"storm", "congestion"}
    assert len(adv["noon_reports"]) == 2 and demo["var1"]["hours_compared"] == 48 and abs(demo["var1"]["fuel"]["variance_t"]) < 5
    alts = {a["name"]: a for a in demo["scen"]["result"]["alternatives"]}
    keep, reroute = alts["Keep the plan"], alts["Re-route and re-speed"]
    assert keep["max_hs"] > 7 > reroute["max_hs"] and reroute["expected_cost_usd"] < keep["expected_cost_usd"] and not reroute["within_terms"]
    assert alts["Hold the notified ETA"]["expected_wait_h"] > reroute["expected_wait_h"]           # keeping the ETA only buys waiting at anchor
    assert demo["prop"]["status"] == "awaiting_approval" and demo["self"]["code"] == "proposer_cannot_approve" and demo["approve"]["plan_status"] == "active"
    assert one("SELECT count(*) AS n FROM model_runs WHERE inputs_hash !~ '^[0-9a-f]{16}$'")["n"] == 0 and one("SELECT count(*) AS n FROM model_runs")["n"] > 10
    rep = demo["adv2"]["result"]["report"]
    assert demo["adv2"]["result"]["arrived"] and demo["voy2"]["status"] == "berthed"
    assert rep["savings_vs_baseline"]["simulation_truth"]["cost_usd"] > 0 and rep["savings_vs_baseline"]["by_fuel_model"]["fuel_t"] > 0
    assert rep["actual"]["late_h"] == 0 and iso(rep["actual"]["arrival_at"]) <= iso(rep["eta_vs_approved_plan"]["p90"])
    assert abs(demo["var2"]["fuel"]["variance_t"]) < 0.05 * demo["var2"]["fuel"]["actual_fuel_t"]
    assert demo["audit"]["chain_valid"] and {"fleet.loaded", "voyage.created", "route.optimized", "speed.optimized", "plan.activated", "bunker.planned", "voyage.advanced",
                                             "scenario.compared", "plan.proposed", "plan.approved"} <= {e["action"] for e in demo["audit"]["events"]}


def new_voyage(client, vessel="V02", open_days=8.0, close_days=10.0, **kw):
    clock = iso(client.get("/v1/fleet", headers=VIEWER).json()["clock"])
    body = {"vessel": vessel, "orig": "USNYC", "dest": "NLRTM", "terms": {"window_open": (clock + datetime.timedelta(days=open_days)).isoformat(),
                                                                       "window_close": (clock + datetime.timedelta(days=close_days)).isoformat()}}
    body.update(kw)
    return client.post("/v1/voyages", headers=OPERATOR, json=body)


def test_validation(client, demo):
    assert new_voyage(client, orig="USNYC", dest="CAHAL").json()["code"] == "not_an_ocean_passage"
    assert new_voyage(client, dest="XXABC").json()["code"] == "unknown_port"
    assert new_voyage(client, vessel="V99").status_code == 404
    assert new_voyage(client, open_days=2, close_days=3).json()["code"] == "window_unreachable"
    assert new_voyage(client, open_days=9, close_days=8).json()["code"] == "validation_failed"
    v = new_voyage(client).json()
    assert v["status"] == "planned" and new_voyage(client).json()["code"] == "vessel_busy"
    assert client.post(f"/v1/voyages/{v['voyage_id']}:advance", headers=OPERATOR, json={"hours": 24}).json()["code"] == "no_active_plan"
    assert client.post("/v1/bunker/plan", headers=OPERATOR, json={"voyage_id": v["voyage_id"], "rob_t": 100}).json()["code"] == "no_active_plan"
    assert client.post("/v1/routes/optimize", headers=OPERATOR, json={"voyage_id": v["voyage_id"], "speed_kn": 24.9}).json()["code"] == "speed_above_design"
    bad_storm = {"hours": 24, "inject": {"storm": {"lat": 45, "lon": -40, "in_hours": 30, "forms_in_hours": 40}}}
    assert client.post(f"/v1/voyages/{v['voyage_id']}:advance", headers=OPERATOR, json=bad_storm).json()["code"] == "validation_failed"
    stale = demo["scen"]["result"]["alternatives"][0]["speed_plan_id"]                         # made two days into a voyage that has since berthed
    assert client.post(f"/v1/plans/{stale}/activate", headers=OPERATOR).json()["code"] == "voyage_closed"
    assert client.post(f"/v1/plans/{uuid.uuid4()}/activate", headers=OPERATOR).status_code == 404
    rep = {"vessel": "V03", "at": "2026-10-05T12:00:00Z", "hours": 24, "stw": 15, "fuel_t": 40, "hs_obs": 2, "wave_sector": 2, "head_wind_obs": 3, "disp": 0.8}
    out = client.post("/v1/noon-reports", headers=MASTER, json={"reports": [dict(rep, vessel="V77"), dict(rep, at="2027-01-01T00:00:00Z"), dict(rep, vessel="V02", at="2026-10-05T12:00:00Z")]}).json()
    assert [r["why"] for r in out["refused"]] == ["unknown vessel", "report from the future", "duplicate report for this vessel and time"]
    assert client.post("/v1/noon-reports", headers=MASTER, json={"reports": [dict(rep, stw=45)]}).json()["code"] == "validation_failed"


def test_roles_and_the_second_person(client, demo):
    assert client.get("/v1/fleet").status_code == 401 and client.get("/v1/fleet", headers=VIEWER).status_code == 200
    for path, body in (("/v1/voyages", {}), ("/v1/routes/optimize", {}), ("/v1/speed/optimize", {}), ("/v1/scenarios", {}), ("/v1/bunker/plan", {}), ("/v1/noon-reports", {})):
        assert client.post(path, headers=VIEWER, json=body).status_code == 403, path
    assert client.post("/v1/fleet:load", headers=MASTER, json={}).status_code == 403 and client.get("/v1/audit", headers=MASTER).status_code == 403
    assert client.post(f"/v1/voyages/{demo['voy']['voyage_id']}:advance", headers=MASTER, json={"hours": 1}).status_code == 403
    assert client.post(f"/v1/decisions/{demo['prop']['decision_id']}/approve", headers=MASTER).json()["code"] == "already_decided"
    # a master's own proposal: planned on a fresh voyage, the master proposes a change beyond the terms and cannot approve it
    v = client.get("/v1/fleet", headers=VIEWER).json()
    live = next(x for x in v["voyages_live"] if x["vessel"] == "V02")
    with db.tx() as c:
        c.execute("UPDATE voyage SET notified_eta_at = departure_at WHERE voyage_id = %s", [live["voyage_id"]])     # an ETA long passed: any plan moves it
    r = client.post("/v1/routes/optimize", headers=MASTER, json={"voyage_id": live["voyage_id"]})
    jobs.drain()
    route = client.get(r.json()["status_url"], headers=MASTER).json()["result"]
    s = client.post("/v1/speed/optimize", headers=MASTER, json={"route_plan_id": route["route_plan_id"]})
    jobs.drain()
    plan = client.get(s.json()["status_url"], headers=MASTER).json()["result"]
    assert not plan["within_terms"] and "ETA moves" in plan["why"]
    prop = client.post(f"/v1/plans/{plan['speed_plan_id']}/activate", headers=MASTER).json()
    assert prop["status"] == "awaiting_approval"
    assert client.post(f"/v1/decisions/{prop['decision_id']}/approve", headers=MASTER).json()["code"] == "proposer_cannot_approve"
    assert client.post(f"/v1/decisions/{prop['decision_id']}/approve?decision=rejected", headers=OPERATOR).json()["plan_status"] == "rejected"


def test_another_operator_sees_nothing(client, demo, seeded):
    assert client.get("/v1/fleet", headers=OTHER).json()["code"] == "no_fleet"
    assert client.get(f"/v1/voyages/{demo['voy']['voyage_id']}", headers=OTHER).json()["code"] == "no_fleet"
    for table in ("fleets", "vessel", "voyage", "position", "engine_sample", "fuel_sample", "weather_cell", "port_call", "route_plan", "speed_plan", "bunker_plan",
                  "voyage_event", "model_artifacts", "model_runs", "decisions", "scenarios"):
        assert one(f"SELECT count(*) AS n FROM {table}", tenant=seeded["other"])["n"] == 0 < one(f"SELECT count(*) AS n FROM {table}", tenant=seeded["northline"])["n"], table
    with pytest.raises(Exception, match="row-level security"), db.tx(seeded["other"]) as c:
        c.execute("INSERT INTO voyage_event (id, tenant_id, voyage_id, kind, at, detail) VALUES (%s,%s,%s,'arrived',now(),'{}')",
                  [uuid.uuid4(), seeded["northline"], demo["voy"]["voyage_id"]])


def test_idempotent_writes(client, demo):
    body = {"voyage_id": demo["voy"]["voyage_id"], "rob_t": 1400}
    again = client.post("/v1/bunker/plan", headers={**OPERATOR, "Idempotency-Key": "demo-1:bunker"}, json=body)
    assert again.status_code == 201 and again.headers["Idempotent-Replay"] == "true" and again.json()["bunker_plan_id"] == demo["bunker"]["bunker_plan_id"]
    assert client.post("/v1/bunker/plan", headers={**OPERATOR, "Idempotency-Key": "demo-1:bunker"}, json={**body, "rob_t": 900}).json()["code"] == "idempotency_key_reused"
    assert client.post("/v1/fleet:load", headers=OPERATOR, json={"seed": 9}).json()["code"] == "fleet_exists"
    assert one("SELECT count(*) AS n FROM bunker_plan")["n"] == 1
