"""Integration, end-to-end and security tests against a real Postgres."""
import datetime
import uuid

import pytest

from core import db, jobs, scenario

from .conftest import bearer

LEAD, ENGINEER, VIEWER, OTHER = bearer("acme", "finops_lead"), bearer("acme", "engineer"), bearer("acme", "viewer"), bearer("other", "finops_lead")


def test_nothing_works_before_the_estate_starts(client):
    assert client.get("/v1/estate/overview", headers=VIEWER).json()["code"] == "no_estate"
    body = {"provider": "aws", "external_ref": "418295730016", "name": "x", "credential_ref": "arn:aws:iam::418295730016:role/r"}
    assert client.post("/v1/accounts/connect", headers=LEAD, json=body).json()["code"] == "no_estate"


def one(sql, params=(), tenant=None):
    with db.tx(tenant) as c:
        return c.execute(sql, params).fetchone()


@pytest.fixture(scope="module")
def demo(client):
    first, _ = scenario.run(client, drain=jobs.drain, upto=6)          # up to the approved pull request and portfolio
    cr = first["pr"]["change_request_id"]
    with db.tx() as c:
        rows = c.execute("""SELECT x.from_config, x.to_config, r.attributes, r.status FROM recommendation x JOIN resource r ON r.id = x.resource_id
                             WHERE x.id = ANY((SELECT recommendation_ids FROM change_request WHERE id = %s)::uuid[])""", [cr]).fetchall()
        bought = c.execute("SELECT count(*) AS n FROM commitment WHERE status = 'active'").fetchone()["n"]
    untouched = all(r["status"] == "running" and (r["attributes"].get("size_index") == r["from_config"].get("size") if "size" in r["from_config"] else
                                                  r["attributes"].get("min_nodes") == r["from_config"].get("min_nodes") if "min_nodes" in r["from_config"] else True) for r in rows)
    results, _ = scenario.run(client, drain=jobs.drain)                 # steps 1-6 replay by Idempotency-Key; step 7 runs
    results["_approved_but_untouched"] = untouched and bought == 0 and len(rows) == first["pr"]["summary"]["changes"]
    results["_first"] = first
    return results


def test_demo_journey(demo):
    assert len(demo["sim"]["accounts"]) == 6 and demo["bad"]["code"] == "secret_not_accepted"
    synced = [demo[f"c{i}"]["result"] for i in range(1, 7)]
    assert {s["provider"] for s in synced} == {"aws", "azure", "gcp"} and sum(s["resources"] for s in synced) > 240 and all(s["days"] == ["2026-08-10", "2026-10-04"] for s in synced)
    assert one("SELECT count(*) AS n FROM cloud_account WHERE credential_ref ~ 'AKIA'")["n"] == 0
    assert all(a["fresh"] for a in demo["acc"]["items"]) and len(demo["ov0"]["daily"]) == 56
    d = demo["explain0"]["drivers"]
    assert abs(d["usage"] + d["configuration"] + d["rate"] + d["new_resources"] + d["removed_resources"] - demo["explain0"]["change"]) < 0.05
    assert demo["top"]["items"][0]["kind"] == "pool" and demo["res0"]["hourly"]["forecast"]["p90"]
    rec = demo["rec"]["result"]
    assert rec["open_monthly_savings"] > 10000 and rec["baseline"]["recommendations"] > rec["recommendations"] and rec["baseline"]["expected_breaches"] > 20
    assert rec["risk_model"]["holdout"]["auc"] > 0.9 > rec["risk_model"]["holdout"]["auc_env_kind_rule"] + 0.2
    assert one("SELECT count(*) AS n FROM recommendation WHERE inputs_hash !~ '^[0-9a-f]{16}$' OR model_versions->>'risk' IS NULL")["n"] == 0
    assert one("SELECT count(*) AS n FROM model_run")["n"] >= rec["recommendations"]
    short = one("SELECT count(*) AS n, bool_or(x.reason LIKE '%%days of history%%') AS why FROM recommendation x JOIN resource r ON r.id = x.resource_id WHERE x.action = 'review'")
    assert short["n"] >= 1 and short["why"]
    spot = demo["res1"]
    assert not [x for x in spot["recommendations"] if x["status"] == "open"] and max(spot["hourly"]["cpu_util"]) > 0.8      # the rule would cut it; its peaks say no
    port = demo["port"]["result"]
    cost = port["expected_cost"]
    assert port["solver"]["optimal"] and cost["optimised"]["total"] < cost["baseline"]["total"] < cost["none"]["total"] and cost["baseline"]["unused"] > 3 * cost["optimised"]["unused"]
    plans = {p["plan"]: p for p in demo["simr"]["result"]["plans"]}
    assert plans["slo_aware"]["expected_breaches"] < 1 < 20 < plans["naive_average"]["expected_breaches"]
    assert plans["aggressive"]["monthly_savings"] > plans["slo_aware"]["monthly_savings"] and plans["aggressive"]["expected_breaches"] > plans["slo_aware"]["expected_breaches"]
    pr = demo["pr"]
    assert pr["status"] == "draft" and pr["infrastructure_mutated"] is False
    assert pr["summary"]["changes"] == sum(v["count"] for k, v in rec["by_status_action"].items() if k.startswith("open:")) == len(pr["changes"])
    diffs = [d for repo in pr["files"].values() for d in repo.values()]
    assert diffs and all(line[:1] in "-+ @" for d in diffs for line in d.splitlines()) and any('-  instance_type = "m6i.8xlarge"' in d for d in diffs)
    assert demo["direct"]["code"] == "direct_mutation_disabled" and demo["_first"]["self"]["code"] == "proposer_cannot_approve"
    assert demo["self"]["code"] == "already_decided"                    # on the second pass the lead has already opened it
    assert demo["approve"]["status"] == "opened" and demo["capprove"]["status"] == "approved" and demo["_approved_but_untouched"]
    adv = demo["adv"]["result"]
    truth = adv["simulation_truth"]["true_savings_by_change_request"][pr["change_request_id"]]
    v = adv["verified"][0]
    assert abs(v["estimate"] - truth) / truth < 0.05                     # the blueprint's bar: attribution error under 5%
    assert abs(v["baselines"]["before_after"] - truth) / truth > 0.2 and v["slo_breaches"] == 0 and abs(v["reconciliation"]["difference"]) < 0.005
    assert abs(v["commitment_savings_measured"] - adv["simulation_truth"]["true_commitment_savings"]) < 1.0
    assert demo["ver"]["items"][0]["resources"] and demo["ver"]["items"][0]["estimate"] == v["estimate"]
    d1 = demo["explain1"]["drivers"]
    assert d1["configuration"] < 0 and d1["rate"] < 0 and demo["explain1"]["change"] < 0
    resized = one("""SELECT r.attributes->>'size_index' AS now, x.to_config->>'size' AS want FROM recommendation x JOIN resource r ON r.id = x.resource_id
                      WHERE x.action = 'resize' AND x.status = 'applied' LIMIT 1""")
    assert resized["now"] == resized["want"]
    assert demo["audit"]["chain_valid"] and {"account.synced", "recommendations.ran", "commitments.proposed", "commitments.approved", "simulation.ran", "change_request.proposed",
                                             "change_request.opened", "simulator.advanced", "savings.verified"} <= {e["action"] for e in demo["audit"]["events"]}


def test_validation(client, demo):
    post = lambda body: client.post("/v1/accounts/connect", headers=LEAD, json={"provider": "aws", "name": "x", **body}).json()      # noqa: E731
    assert post({"external_ref": "123456", "credential_ref": "arn:aws:iam::123456:role/r"})["code"] == "bad_external_ref"
    assert post({"external_ref": "418295730016", "credential_ref": "arn:aws:iam::418295730027:role/finops"})["code"] == "credential_account_mismatch"
    assert post({"external_ref": "999999999999", "credential_ref": "arn:aws:iam::999999999999:role/finops"})["code"] == "account_not_reachable"
    assert post({"external_ref": "418295730016", "credential_ref": "http://169.254.169.254/latest/meta-data/iam"})["code"] == "bad_credential_ref"
    assert post({"external_ref": "418295730016", "credential_ref": "arn:aws:iam::418295730016:role/finops", "secret_access_key": "x"})["code"] == "validation_failed"
    assert post({"external_ref": "418295730016", "credential_ref": "arn:aws:iam::418295730016:role/finops"})["code"] == "already_connected"
    adv = lambda body: client.post("/v1/simulator:advance", headers=LEAD, json=body).json()      # noqa: E731
    assert adv({"days": 3, "merge_change_requests": [str(uuid.uuid4())]})["code"] == "change_request_not_open"
    assert adv({"days": 3, "merge_change_requests": [demo["pr"]["change_request_id"]]})["code"] == "change_request_not_open"       # already merged
    assert adv({"days": 3, "purchase_portfolios": [demo["port"]["result"]["portfolio_id"]]})["code"] == "portfolio_not_approved"    # already bought
    assert adv({"days": 2, "apply_after_days": 2})["code"] == "apply_outside_window" and adv({"days": 0})["code"] == "validation_failed"
    assert client.get("/v1/costs/explain?end=2026-08-12&days=7", headers=VIEWER).json()["code"] == "outside_history"
    applied = one("SELECT id FROM recommendation WHERE status = 'applied' LIMIT 1")["id"]
    pr = lambda ids: client.post("/v1/iac/pull-request", headers=ENGINEER, json={"recommendation_ids": ids}).json()      # noqa: E731
    assert pr([str(applied)])["code"] == "recommendation_not_open" and pr([str(uuid.uuid4())])["code"] == "recommendation_not_found"
    assert client.post(f"/v1/change-requests/{uuid.uuid4()}/approve", headers=LEAD).status_code == 404
    assert client.get(f"/v1/resources/{uuid.uuid4()}", headers=VIEWER).status_code == 404 and client.get("/v1/simulations", headers=VIEWER).status_code == 405


def test_roles_and_the_second_person(client, demo):
    assert client.get("/v1/estate/overview").status_code == 401 and client.get("/v1/estate/overview", headers=VIEWER).status_code == 200
    for path in ("/v1/recommendations/run", "/v1/simulations", "/v1/commitments/optimize", "/v1/iac/pull-request"):
        assert client.post(path, headers=VIEWER, json={}).status_code == 403, path
    for path in ("/v1/accounts/connect", "/v1/simulator:advance", "/v1/simulator:start", f"/v1/commitments/{uuid.uuid4()}/approve"):
        assert client.post(path, headers=ENGINEER, json={}).status_code == 403, path
    assert client.get("/v1/audit", headers=ENGINEER).status_code == 403
    job = client.post("/v1/commitments/optimize", headers=LEAD, json={"horizon_weeks": 4, "budget_per_month": 20000}).json()      # a lead proposes ...
    jobs.drain()
    res = client.get(job["status_url"], headers=LEAD).json()["result"]
    assert res["monthly_fees"] <= 20000 + 1e-6
    assert client.post(f"/v1/commitments/{res['portfolio_id']}/approve", headers=LEAD).json()["code"] == "proposer_cannot_approve"   # ... and cannot approve
    assert client.post(f"/v1/commitments/{demo['port']['result']['portfolio_id']}/approve", headers=LEAD).json()["code"] == "already_decided"
    assert client.post(f"/v1/change-requests/{demo['pr']['change_request_id']}/approve", headers=LEAD).json()["code"] == "already_decided"


def test_another_company_sees_nothing(client, demo, seeded):
    assert client.get("/v1/estate/overview", headers=OTHER).json()["code"] == "no_estate"
    assert client.post("/v1/simulator:start", headers=OTHER, json={"seed": 9}).status_code == 201
    assert client.get(f"/v1/resources/{demo['top']['items'][0]['id']}", headers=OTHER).status_code == 404
    assert client.get(f"/v1/change-requests/{demo['pr']['change_request_id']}", headers=OTHER).status_code == 404
    assert client.get("/v1/savings/verified", headers=OTHER).json()["items"] == []
    for table in ("cloud_account", "resource", "resource_metric", "cost_line", "recommendation_run", "recommendation", "commitment_portfolio", "commitment",
                  "simulation", "change_request", "savings_measurement", "model_artifact", "model_run"):
        assert one(f"SELECT count(*) AS n FROM {table}", tenant=seeded["other"])["n"] == 0 < one(f"SELECT count(*) AS n FROM {table}", tenant=seeded["acme"])["n"], table
    with pytest.raises(Exception, match="row-level security"), db.tx(seeded["other"]) as c:
        c.execute("INSERT INTO simulation (id, tenant_id, request, result, created_by) VALUES (%s,%s,'{}','{}',%s)", [uuid.uuid4(), seeded["acme"], uuid.uuid4()])


def test_idempotent_writes(client, demo):
    body = {"title": "Rightsize idle and oversized resources (FinOps, October)"}
    again = client.post("/v1/iac/pull-request", headers={**ENGINEER, "Idempotency-Key": "demo-1:pr"}, json=body)
    assert again.status_code == 201 and again.headers["Idempotent-Replay"] == "true" and again.json()["change_request_id"] == demo["pr"]["change_request_id"]
    assert client.post("/v1/iac/pull-request", headers={**ENGINEER, "Idempotency-Key": "demo-1:pr"}, json={"title": "something else"}).json()["code"] == "idempotency_key_reused"
    assert client.post("/v1/simulator:start", headers=LEAD, json={"seed": 3}).json()["code"] == "estate_exists"
    assert one("SELECT count(*) AS n FROM change_request")["n"] == 1


def test_stale_inventory_becomes_a_review_task(client, demo):
    acct = one("SELECT id FROM cloud_account WHERE external_ref = '418295730016'")["id"]
    with db.tx() as c:
        c.execute("UPDATE cloud_account SET last_sync_at = %s WHERE id = %s", [datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1), acct])
    assert not [a for a in client.get("/v1/accounts", headers=VIEWER).json()["items"] if a["id"] == str(acct)][0]["fresh"]
    client.post("/v1/recommendations/run", headers=ENGINEER, json={"note": "after the replay"})
    jobs.drain()
    with db.tx() as c:
        rows = c.execute("""SELECT x.status, x.reason FROM recommendation x JOIN resource r ON r.id = x.resource_id
                             WHERE r.cloud_account_id = %s AND x.status IN ('open', 'review') AND x.action <> 'review'""", [acct]).fetchall()
    assert rows and all(r["status"] == "review" and "minutes old" in r["reason"] for r in rows)
