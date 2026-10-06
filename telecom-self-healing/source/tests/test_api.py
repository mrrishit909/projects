"""Integration, end-to-end and security tests against a real Postgres."""
import uuid

import pytest

from core import db, jobs, scenario

from .conftest import bearer

MANAGER, ENGINEER, VIEWER, OTHER = bearer("metro", "noc_manager"), bearer("metro", "noc_engineer"), bearer("metro", "viewer"), bearer("other", "noc_manager")


def test_nothing_works_before_a_network_is_loaded(client):
    assert client.get("/v1/network/overview", headers=VIEWER).json()["code"] == "no_network"
    assert client.post("/v1/telemetry/batch", headers=ENGINEER, json={"interval": "2026-10-05T14:00:00Z"}).json()["code"] == "no_network"


@pytest.fixture(scope="module")
def demo(client):
    results, _ = scenario.run(client, drain=jobs.drain)
    return results


def one(sql, params=(), tenant=None):
    with db.tx(tenant) as c:
        return c.execute(sql, params).fetchone()


def test_demo_journey(demo):
    load = demo["load"]["result"]
    assert load["sites"] == 44 and load["cells"] == 264 and load["clock"].startswith("2026-10-05T14:00")
    m = load["models"]
    assert m["anomaly-detector"]["model"]["f1"] > m["anomaly-detector"]["static"]["f1"] and m["traffic-forecaster"]["wape"] < m["traffic-forecaster"]["baseline_wape"]
    rc = m["alarm-correlation"]["root_cause"]
    assert rc["top3"] / rc["incidents_with_ticket"] > 0.9 > rc["baseline_top3"] / rc["incidents_with_ticket"] and m["alarm-correlation"]["fault_ratio"] > 20
    assert not [i for i in demo["ov0"]["open_incidents"] if i["alarm_count"] >= 3]          # the history is over before the demo starts
    adv = demo["adv"]["result"]
    assert [x["element"] for x in adv["simulation_truth"]["told"]] == ["L-S08-AGG-NE", "S10-B-L"] and adv["processing_ms"]["p95"] < 3000
    corr = demo["corr"]["result"]
    storm, ho = corr["top_incidents"][:2]
    assert corr["raw_alarms"] >= 300 and corr["reduction_ratio"] > 20 and corr["baselines"]["dedup_by_element_and_type"] > 3 * corr["incidents"]
    assert storm["root"] == "L-S08-AGG-NE" and storm["kind"] == "transport" and storm["alarms_in_window"] >= 300 and storm["elements"] >= 20
    assert ho["root"] == "S10-B-L" and ho["kind"] == "handover" and "S10-B-L" not in ho["baseline_most_alarms"]
    assert ho["ranking"][0]["evidence"]["config_change_at"] is not None
    probe = demo["probe"]
    assert probe["accepted"] == ["S11-A-N", "S05-A-N"] and [r["why"] for r in probe["refused"]] == ["unknown element", "prb_util = 1.7 is outside 0..1"]
    assert probe["alarms_accepted"][0]["incident_id"] == storm["incident_id"] and [a["anomalous"] for a in probe["anomaly"]] == [True, False]
    assert demo["fc"]["over_envelope"][0] == "L-S08-AGG-NE" and demo["fc"]["peaks"][0]["peak"] > 1.0
    rec1, rec2 = demo["rec1"]["result"], demo["rec2"]["result"]
    assert rec1["kind"] == "reroute" and [a["site"] for a in rec1["actions"]] == ["S10", "S11"] and rec1["inside_envelope"] and rec1["best"]["peak"] <= 0.75
    assert all("S09" not in [a["site"] for a in c["actions"]] for c in rec1["candidates"] if c["feasible"])
    assert rec2["kind"] == "rollback" and rec2["actions"][0]["to"] == "v41"
    assert not demo["naive"]["result"]["inside_envelope"] and demo["naive"]["result"]["violations"][0]["rule"] == "protected_sites"
    assert demo["bad"]["code"] == "outside_policy_envelope" and demo["self"]["status"] == 403
    assert demo["approve"]["status"] == "applied" and len(demo["approve"]["applied"]) == 3
    applied_t = one("SELECT applied_t FROM change_plan WHERE id = %s", [demo["plan"]["change_plan_id"]])["applied_t"]
    after = [x for x in demo["link1"]["series"] if x["t"] >= applied_t]
    assert len(after) == 24 and max(x["util"] for x in after) <= 0.8                                         # the busy hour stayed inside the envelope
    assert demo["cell1"]["series"][-1]["kpis"][5] > 95 and set(one("SELECT rerouted FROM networks")["rerouted"]) == {"S10", "S11"}
    assert one("SELECT count(*) AS n FROM configuration WHERE change_plan_id IS NOT NULL")["n"] == 3
    assert one("SELECT count(*) AS n FROM model_runs WHERE inputs_hash !~ '^[0-9a-f]{16}$'")["n"] == 0 and one("SELECT count(*) AS n FROM model_runs")["n"] >= 36
    assert demo["audit"]["chain_valid"] and {"network.loaded", "network.advanced", "incidents.correlated", "telemetry.ingested", "recommendation.built",
                                             "twin.simulated", "change.proposed", "change.approved", "change.applied"} <= {e["action"] for e in demo["audit"]["events"]}


def test_validation(client, demo):
    adv = lambda body: client.post("/v1/network:advance", headers=MANAGER, json=body)      # noqa: E731
    assert adv({"intervals": 1, "inject": [{"kind": "backhaul_degradation", "element": "L-S01-AGG-NE"}]}).json()["code"] == "fault_does_not_fit_element"
    assert adv({"intervals": 1, "inject": [{"kind": "sleeping_cell", "element": "S99-A-L"}]}).json()["code"] == "fault_does_not_fit_element"
    assert adv({"intervals": 0}).status_code == 422 and adv({"intervals": 1, "inject": [{"kind": "meteor", "element": "S01-A-L"}]}).status_code == 422
    batch = lambda **kw: client.post("/v1/telemetry/batch", headers=ENGINEER, json={"interval": "2026-10-05T22:00:00Z", **kw}).json()   # noqa: E731
    assert batch(interval="2026-10-05T22:07:00Z")["code"] == "interval_not_aligned" and batch(interval="2026-10-09T00:00:00Z")["code"] == "interval_ahead_of_clock"
    assert batch(interval="2026-10-01T00:00:00Z")["code"] == "interval_too_old"
    r = batch(samples=[{"element": "L-S01-AGG-NE", "kpis": {"util": 0.5}}], alarms=[{"element": "S01-A-L", "type": "SOLAR_FLARE", "severity": "minor"},
                                                                                       {"element": "S01-A-L", "type": "VSWR_HIGH", "severity": "minor", "related": "S99-A-L"}])
    dup = client.post("/v1/telemetry/batch", headers=ENGINEER, json={"interval": demo["adv"]["result"]["last_interval"], "samples": [{"element": "S11-A-N", "kpis": {
        k: 0.5 for k in ("dl_mbps", "prb_util", "users", "latency_ms", "loss_pct", "ho_success_pct", "drop_pct", "available")}}]}).json()
    assert dup["refused"] == [{"element": "S11-A-N", "why": "duplicate sample for this interval and source"}]
    assert r["refused"][0]["why"].startswith("a link sample needs exactly") and [a["why"] for a in r["alarms_refused"]] == ["unknown alarm type", "unknown related cell"]
    assert client.post("/v1/twin/simulate", headers=ENGINEER, json={"changes": [{"type": "reroute_site", "site": "S08"}]}).json()["code"] == "bad_change"
    assert client.post("/v1/recommendations", headers=ENGINEER, json={"incident_id": str(uuid.uuid4())}).status_code == 404
    assert client.post("/v1/change-plans", headers=ENGINEER, json={}).json()["code"] == "nothing_to_change"
    assert client.get("/v1/cells/S99-A-L/kpis", headers=VIEWER).status_code == 404 and client.get("/v1/links/L-NOPE/kpis", headers=VIEWER).status_code == 404
    assert client.get(f"/v1/incidents/{uuid.uuid4()}", headers=VIEWER).status_code == 404


def test_roles_and_the_second_person(client, demo):
    assert client.get("/v1/network/topology").status_code == 401 and client.get("/v1/network/topology", headers=VIEWER).status_code == 200
    for path in ("/v1/telemetry/batch", "/v1/incidents/correlate", "/v1/recommendations", "/v1/twin/simulate", "/v1/change-plans"):
        assert client.post(path, headers=VIEWER, json={}).status_code == 403, path
    assert client.post("/v1/network:advance", headers=ENGINEER, json={"intervals": 1}).status_code == 403
    assert client.post("/v1/network:load", headers=ENGINEER, json={}).status_code == 403 and client.get("/v1/audit", headers=ENGINEER).status_code == 403
    prop = client.post("/v1/change-plans", headers=MANAGER, json={"recommendation_ids": [demo["rec2"]["result"]["recommendation_id"]]}).json()   # a manager proposes ...
    assert client.post(f"/v1/changes/{prop['change_plan_id']}/approve", headers=MANAGER).json()["code"] == "proposer_cannot_approve"           # ... and cannot approve
    assert client.post(f"/v1/changes/{demo['plan']['change_plan_id']}/approve", headers=MANAGER).json()["code"] == "already_decided"
    rej = client.post(f"/v1/changes/{prop['change_plan_id']}/approve?decision=rejected", headers=bearer("metro", "noc_manager"))
    assert rej.json()["code"] == "proposer_cannot_approve"


def test_another_operator_sees_nothing(client, demo, seeded):
    assert client.get("/v1/network/overview", headers=OTHER).json()["code"] == "no_network"
    assert client.get(f"/v1/incidents/{demo['corr']['result']['top_incidents'][0]['incident_id']}", headers=bearer("other", "viewer")).status_code == 404
    for table in ("networks", "device", "site", "sector", "cell", "link", "topology_edge", "metric_sample", "alarm", "incident", "configuration",
                  "policy_envelope", "recommendation", "twin_run", "change_plan", "model_artifacts", "model_runs"):
        assert one(f"SELECT count(*) AS n FROM {table}", tenant=seeded["other"])["n"] == 0 < one(f"SELECT count(*) AS n FROM {table}", tenant=seeded["metro"])["n"], table
    with pytest.raises(Exception, match="row-level security"), db.tx(seeded["other"]) as c:
        c.execute("INSERT INTO alarm (id, tenant_id, element_id, t, raised_at, type, severity) VALUES (%s,%s,'S01-A-L',1,now(),'VSWR_HIGH','minor')",
                  [uuid.uuid4(), seeded["metro"]])
    with pytest.raises(Exception, match="permission denied"), db.tx(seeded["other"]) as c:
        c.execute("SELECT count(*) FROM metric_sample_2026_10")                  # a partition is only reachable through the parent's policy


def test_idempotent_writes(client, demo):
    body = {"recommendation_ids": [demo["rec1"]["result"]["recommendation_id"], demo["rec2"]["result"]["recommendation_id"]]}
    again = client.post("/v1/change-plans", headers={**ENGINEER, "Idempotency-Key": "demo-1:plan"}, json=body)
    assert again.status_code == 201 and again.headers["Idempotent-Replay"] == "true" and again.json()["change_plan_id"] == demo["plan"]["change_plan_id"]
    assert client.post("/v1/change-plans", headers={**ENGINEER, "Idempotency-Key": "demo-1:plan"}, json={"recommendation_ids": []}).json()["code"] == "idempotency_key_reused"
    assert client.post("/v1/network:load", headers=MANAGER, json={"seed": 9}).json()["code"] == "network_exists"
