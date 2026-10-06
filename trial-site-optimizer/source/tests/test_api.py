"""Integration, end-to-end and security tests against a real Postgres."""
import json
import re
import uuid

import pytest

from core import db, jobs, scenario
from trials import world

from .conftest import bearer

DIRECTOR, ANALYST, VIEWER = bearer("net", "study_director"), bearer("net", "feasibility_analyst"), bearer("net", "viewer")
OTHER = bearer("other", "study_director")
SMALL = "5.1 Inclusion criteria\n1. Age ≥ 18 years at the time of signing informed consent.\n2. Documented diagnosis of stage IV NSCLC.\n\n5.2 Exclusion criteria\n1. Known history of HIV infection.\n"


def test_nothing_works_before_a_network_is_loaded(client):
    assert client.get("/v1/network/overview", headers=VIEWER).json()["code"] == "no_network"
    assert client.post("/v1/studies/parse", headers=ANALYST, json={"external_ref": "X-1", "text": SMALL}).json()["code"] == "no_network"


@pytest.fixture(scope="module")
def demo(client):
    results, _ = scenario.run(client, drain=jobs.drain)
    return results


def one(sql, params=(), tenant=None):
    with db.tx(tenant) as c:
        return c.execute(sql, params).fetchone()


def test_demo_journey(demo):
    load = demo["load"]["result"]
    assert load["sites"] == 120 and load["feed"]["records_received"] == load["feed"]["tokens"] > 30000 and load["feed"]["events_refused"]
    assert load["models"]["enrolment"]["mae"] < load["models"]["enrolment"]["naive_mae"] and one("SELECT count(*) AS n FROM model_artifacts WHERE approved")["n"] == 2
    assert len(demo["ov"]["sites"]) == 120 and demo["ov"]["network"]["feed"]["dropped_at_the_door"][0] == "mrn"
    p = demo["parse"]
    assert p["counts"] == {"parsed": 16, "review": 2, "manual": 4} and [q["ref"] for q in p["review_queue"]] == ["I4", "E2"]
    assert p["text_sha256"] == __import__("hashlib").sha256(world.catalogue_protocol("ONC-LUNG-301")["text"].encode()).hexdigest()   # scenario.json carries the generator's text
    assert demo["badedit"]["code"] == "invalid_review" and "a unit slip?" in demo["badedit"]["detail"]
    rv = demo["review"]
    assert rv["status"] == "approved" and rv["stats"]["acceptance_rate"] == 1.0 and rv["stats"]["edited"] == 2 and rv["stats"]["accepted_unchanged"] == 16
    m = demo["match"]["result"]
    assert m["records"] == m["eligible"] + m["potential"] + m["ineligible"] and m["eligible"] >= 1 and m["potential"] > m["eligible"]
    f = demo["funnel"]
    assert all(a["remaining"] >= b["remaining"] for a, b in zip(f["steps"], f["steps"][1:])) and abs(f["expected_eligible"] - m["expected_eligible"]) < 0.5
    for k in ("x_el", "x_io", "x_lab"):
        assert demo[k]["reproduces_stored_decision"] and demo[k]["lineage_verified"], k
        assert not re.search(r"\d{4}-\d\d-\d\d", json.dumps(demo[k]["timeline"])), k
    assert demo["x_el"]["status"] == "eligible" and demo["x_io"]["failed"] == ["E2"]
    e2 = next(t for t in demo["x_io"]["trace"] if t["ref"] == "E2")["rules"][0]
    assert e2["value"] is True and all(r["end"] is None or r["end"] >= -182 for r in e2["evidence"]["regimens"]) and e2["evidence"]["regimens"][0]["class"] in ("anti-PD-1", "anti-PD-L1")
    i7 = next(t for t in demo["x_lab"]["trace"] if t["ref"] == "I7")
    assert i7["satisfied"] is None and any("in the last 28 days" in (r["evidence"].get("why") or "") for r in i7["rules"])
    s = demo["score"]["result"]
    assert s["sites"] == 120 and s["naive_all_sites"] > s["expected_enrolled_all_sites"] and len(s["excluded"]) >= 1
    assert one("SELECT count(*) AS n FROM model_runs WHERE model_name = %s AND inputs_hash ~ '^[0-9a-f]{16}$'", ["poisson-gamma-weibull-1"])["n"] == 120
    o = demo["opt"]["result"]
    milp, hist, greedy = o["compared"]["milp"], o["compared"]["top_by_history"], o["compared"]["greedy_value_per_dollar"]
    assert o["solver"]["status"] == "optimal" and milp["count"] == 20 and milp["expected_cost"] <= 2_400_000 and milp["academic"] >= 3 and max(milp["regions"].values()) <= 6
    assert not set(milp["sites"]) & set(o["constraints"]["excluded_by_policy"]) and milp["expected_evaluable"] >= greedy["expected_evaluable"] > hist["expected_evaluable"]
    assert demo["self"]["code"] == "forbidden" and demo["approve"]["status"] == "approved"
    adv = demo["adv"]["result"]
    assert adv["plan"]["sites"] == 20 and adv["plan"]["evaluable"] > adv["simulation_truth"]["baseline_top_by_history"]["evaluable"]
    assert adv["plan"]["enrolled"] == adv["plan"]["cumulative_enrolled"][-1] and len(adv["per_site"]) == 20
    acts = {e["action"] for e in demo["audit"]["events"]}
    assert demo["audit"]["chain_valid"] and {"network.loaded", "study.parsed", "criterion.edited", "criteria.approved", "match.evaluated", "export.created",
                                               "sites.scored", "portfolio.proposed", "portfolio.approved", "study.enrolment_simulated"} <= acts


def test_zero_phi_in_the_store_and_the_exports(client, demo):
    """Every identifier the feeds sent (MRN, birth date, dates of care, the free-text note) is absent from the stored tokens,
    the explanations and the analytics exports, and small cells are suppressed."""
    net = world.network(7)
    mrns = {p["record"]["mrn"] for p in net["patients"]}
    assert all(re.fullmatch(r"\d{11}", m) for m in mrns)
    sid = demo["parse"]["study_id"]
    with db.tx() as c:
        stored = [r["t"] for r in c.execute("SELECT token || ' ' || sex || ' ' || age_band || ' ' || distance_band || ' ' || timeline::text AS t FROM patient_token")]
    outgoing = [json.dumps(demo["export"]), client.get(f"/v1/studies/{sid}/export?format=csv", headers=ANALYST).text] + [json.dumps(demo[k]) for k in ("x_el", "x_io", "x_lab")]
    blob = "\n".join(stored + outgoing)
    assert len(stored) == len(mrns) and not re.search(r"\b(19|20)\d\d-\d\d-\d\d", blob.replace(demo["x_el"]["snapshot_date"], ""))   # no birth date, no date of care
    assert not set(re.findall(r"(?<![0-9a-f])\d{11}(?![0-9a-f])", blob)) & mrns and "Seen in clinic" not in blob
    rows = demo["export"]["rows"]
    assert all(r["patients"] == "<11" or r["patients"] >= 11 for r in rows) and demo["export"]["suppressed_cells"] > 0
    assert set(rows[0]) == {"site", "age_band", "status", "patients", "expected_eligible"} and not any(demo["export"]["scan"][k] for k in PHI_KEYS)


PHI_KEYS = ("calendar date", "patient token or long hex", "MRN-like number")


def test_validation(client, demo):
    sid = demo["parse"]["study_id"]
    assert client.post("/v1/studies/parse", headers=ANALYST, json={"external_ref": "X-EMPTY", "text": "Nothing numbered here at all, just prose about a study."}).json()["code"] == "no_criteria_found"
    assert client.post("/v1/studies/parse", headers=ANALYST, json={"external_ref": "ONC-LUNG-301", "text": SMALL}).json()["code"] == "study_exists"
    assert client.post("/v1/studies/parse", headers=ANALYST, json={"external_ref": "bad ref!", "text": SMALL}).status_code == 422
    assert client.post(f"/v1/studies/{sid}/review", headers=DIRECTOR, json={"decisions": []}).json()["code"] == "criteria_frozen"
    small = client.post("/v1/studies/parse", headers=ANALYST, json={"external_ref": "X-SMALL", "text": SMALL}).json()
    assert small["counts"] == {"parsed": 3, "review": 0, "manual": 0}
    bad = client.post(f"/v1/studies/{small['study_id']}/review", headers=DIRECTOR, json={"decisions": [
        {"ref": "I1", "action": "edit", "rules": [{"field": "manual", "topic": "x"}]}, {"ref": "E9", "action": "accept"},
        {"ref": "I2", "action": "edit", "rules": [{"field": "diagnosis", "code": "LUNG"}]}]}).json()
    assert bad["code"] == "invalid_review" and set(json.loads(bad["detail"])) == {"I1", "E9", "I2"}
    assert client.post("/v1/match/evaluate", headers=ANALYST, json={"study_id": small["study_id"]}).json()["code"] == "criteria_not_approved"
    part = client.post(f"/v1/studies/{small['study_id']}/review", headers=DIRECTOR, json={"decisions": [{"ref": "I1", "action": "accept"}]}).json()
    assert part["status"] == "in_review" and part["open"] == ["I2", "E1"]
    assert client.post("/v1/sites/score", headers=ANALYST, json={"study_id": small["study_id"]}).json()["code"] == "not_matched"
    assert client.post("/v1/portfolios/optimize", headers=ANALYST, json={"study_id": small["study_id"], "budget_usd": 1e6}).json()["code"] == "not_scored"
    assert client.post("/v1/network:advance", headers=DIRECTOR, json={"study_id": small["study_id"]}).json()["code"] == "not_a_simulated_protocol"
    job = client.post("/v1/portfolios/optimize", headers=ANALYST, json={"study_id": sid, "budget_usd": 10, "n_sites": 20}).json()
    jobs.drain()
    assert client.get(f"/v1/jobs/{job['job_id']}", headers=ANALYST).json()["result"]["status"] == "infeasible"
    assert client.get(f"/v1/matches/{uuid.uuid4()}/explanation", headers=ANALYST).status_code == 404 and client.get("/v1/sites/S-999", headers=VIEWER).status_code == 404
    assert client.get("/v1/sites/S-001", headers=VIEWER).json()["investigators"] and client.post("/v1/sites/score", headers=ANALYST, json={"study_id": sid, "horizon_months": 3}).status_code == 422


def test_roles_and_the_second_person(client, demo):
    sid = demo["parse"]["study_id"]
    assert client.get("/v1/network/overview").status_code == 401 and client.get("/v1/network/overview", headers={"Authorization": "Bearer nope"}).status_code == 401
    for path, body in (("/v1/studies/parse", {}), ("/v1/match/evaluate", {}), ("/v1/sites/score", {}), ("/v1/portfolios/optimize", {})):
        assert client.post(path, headers=VIEWER, json=body).status_code == 403, path
    assert client.get(f"/v1/matches/{demo['m_el']['items'][0]['match_id']}/explanation", headers=VIEWER).status_code == 403      # patient-level detail is not for viewers
    assert client.get(f"/v1/studies/{sid}/export", headers=VIEWER).status_code == 403 and client.get(f"/v1/studies/{sid}/funnel", headers=VIEWER).status_code == 200
    assert client.post(f"/v1/studies/{sid}/review", headers=ANALYST, json={}).status_code == 403 and client.post("/v1/network:load", headers=ANALYST, json={}).status_code == 403
    assert client.get("/v1/audit", headers=ANALYST).status_code == 403
    job = client.post("/v1/portfolios/optimize", headers=DIRECTOR, json={"study_id": sid, "budget_usd": 2_000_000, "n_sites": 15}).json()     # a director proposes ...
    jobs.drain()
    plan = client.get(f"/v1/jobs/{job['job_id']}", headers=DIRECTOR).json()["result"]["plan_id"]
    assert client.post(f"/v1/portfolios/{plan}/approve", headers=DIRECTOR, json={}).json()["code"] == "proposer_cannot_approve"           # ... and cannot approve it
    assert client.post(f"/v1/portfolios/{demo['opt']['result']['plan_id']}/approve", headers=DIRECTOR, json={}).json()["code"] == "already_decided"


def test_another_sponsor_sees_nothing(client, demo, seeded):
    assert client.get("/v1/network/overview", headers=OTHER).json()["code"] == "no_network"
    assert client.get(f"/v1/matches/{demo['m_el']['items'][0]['match_id']}/explanation", headers=OTHER).status_code == 404
    assert client.get(f"/v1/studies/{demo['parse']['study_id']}/funnel", headers=OTHER).status_code == 404
    for table in ("network", "site", "investigator", "site_metric", "enrollee_history", "patient_token", "study", "criterion", "eligibility_event",
                  "population_bucket", "site_score", "portfolio_plan", "study_run", "model_artifacts", "model_runs"):
        assert one(f"SELECT count(*) AS n FROM {table}", tenant=seeded["other"])["n"] == 0 < one(f"SELECT count(*) AS n FROM {table}", tenant=seeded["net"])["n"], table
    with pytest.raises(Exception, match="row-level security"), db.tx(seeded["other"]) as c:
        c.execute("INSERT INTO study (id, tenant_id, external_ref, protocol_text, text_sha256, parser_version, created_by) VALUES (%s,%s,'X','x','x','x',%s)",
                  [uuid.uuid4(), seeded["net"], uuid.uuid4()])


def test_idempotent_writes(client, demo):
    body = scenario.load()["steps"][1]["calls"][0]["body"]
    again = client.post("/v1/studies/parse", headers={**ANALYST, "Idempotency-Key": "demo-1:parse"}, json=body)
    assert again.status_code == 201 and again.headers["Idempotent-Replay"] == "true" and again.json()["study_id"] == demo["parse"]["study_id"]
    assert client.post("/v1/studies/parse", headers={**ANALYST, "Idempotency-Key": "demo-1:parse"}, json={**body, "name": "changed"}).json()["code"] == "idempotency_key_reused"
    assert client.post("/v1/network:load", headers=DIRECTOR, json={"seed": 9}).json()["code"] == "network_exists"
