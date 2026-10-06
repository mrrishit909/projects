"""Integration, end-to-end and security tests against a real Postgres. The demo scenario runs with 80,000 invoice lines
instead of two million (the steps, checks and shapes are the same; the recorded demo has the full volume)."""
import uuid

import psycopg
import pytest

from core import db, jobs, scenario

from .conftest import bearer

LEAD, ANALYST, VIEWER, OTHER = bearer("meridale", "lead"), bearer("meridale", "analyst"), bearer("meridale", "viewer"), bearer("other", "lead")
LINES = 80_000


def test_nothing_works_before_a_company_is_loaded(client):
    assert client.get("/v1/overview", headers=VIEWER).json()["code"] == "no_company"
    assert client.post("/v1/activities/import", headers=ANALYST, json={"connector": {"transactions": 5000}}).json()["code"] == "no_company"


@pytest.fixture(scope="module")
def demo(client):
    sc = scenario.load()
    sc["steps"][1]["calls"][0]["body"]["connector"]["transactions"] = LINES
    results, _ = scenario.run(client, sc, drain=jobs.drain)
    return results


def one(sql, params=(), tenant=None):
    with db.tx(tenant) as c:
        return c.execute(sql, params).fetchone()


def test_demo_journey(demo):
    m = demo["load"]["result"]["models"]
    cc, sm = m["category_classifier"], m["supplier_matcher"]
    assert cc["spend_weighted_accuracy"] > cc["baseline"]["spend_weighted_accuracy"] and cc["orphan_rate"] < cc["baseline"]["orphan_rate"]
    assert sm["check"]["f1"] > sm["check_fuzzy_baseline"]["f1"] > sm["check_exact_baseline"]["f1"]
    imp = demo["imp"]["result"]
    assert imp["ap"]["read"] > LINES and imp["ap"]["duplicates_dropped"] > 0 and imp["ap"]["stored"] == one("SELECT count(*) AS n FROM activity WHERE kind = 'ap' AND batch_id = %s", [imp["batch_id"]])["n"]
    assert set(imp["ap"]["rejected_by_reason"]) == {"unknown_currency", "unknown_vendor", "outside_reporting_year"} and imp["ap"]["currency_aliases_normalised"] > 0
    assert imp["freight"]["stored"] == 40000 and imp["utility"]["duplicates_dropped"] == 1 and imp["disclosures_received"] > 10
    mp = imp["mapping"]
    assert mp["orphan_rate"] < 0.01 < mp["rules_baseline_orphan_rate"] and mp["review_tasks"] == one("SELECT count(*) AS n FROM review_task WHERE kind = 'category'")["n"]
    rows = demo["rows"]
    assert [a["currency"] for a in rows["accepted"]] == ["GBP", "GBP"] and rows["accepted"][0]["category"] == "steel_metals" and rows["refused"][0]["why"] == "unknown currency 'GPB'"
    res = demo["res"]["result"]
    truth = res["simulation_truth"]
    assert res["suppliers"] < 0.6 * res["vendor_records"] and truth["resolver"]["f1"] > truth["fuzzy_name_baseline"]["f1"] > truth["exact_name_baseline"]["f1"]
    assert len(demo["sup"]["records"]) >= 3 and len({r["subsidiary"] for r in demo["sup"]["records"]}) >= 3
    ext = demo["ext"]["result"]
    assert len(ext["accepted"]) >= 10 and any("implausible" in r["reasons"][0] for r in ext["review"]) and any("boundary incomplete" in r["reasons"][0] for r in ext["review"])
    assert demo["fv"]["version_status"] == "draft" and len(demo["fv"]["added"]) == len(ext["accepted"])
    assert demo["self"]["status"] == 403 and demo["adopt"]["status"] == "approved" and demo["adopt"]["version"]["status"] == "frozen"
    calc = demo["calc"]["result"]
    assert calc["factor_version"] == "EF-2025.1-S1" and calc["lineage_coverage"] == 1.0 and calc["lines_with_complete_lineage"] == calc["lines_carrying_co2e"] > LINES
    assert calc["orphans"]["rate"] < 0.01 and calc["by_method"]["supplier-specific"]["lines"] > 0 and calc["by_method"]["covered"]["t"] == 0
    assert one("SELECT count(*) AS n FROM calculation_lineage WHERE calculation_id = %s", [calc["calculation_id"]])["n"] == calc["lines"]
    u = demo["inv"]["total_t"]
    assert u["p2_5"] < u["t"] < u["p97_5"] and demo["inv"]["scope3_t"]["t"] > 10 * demo["inv"]["scope2_t"]["t"]
    rep = demo["rep"]["result"]
    assert rep["identical"] and rep["inputs_unchanged"] and rep["compare_with"]["lines_changed"] == calc["by_method"]["supplier-specific"]["lines"]
    lin = demo["lin"]
    assert lin["arithmetic"]["matches"] and lin["source"]["record"].startswith(lin["source"]["subsidiary"]) and lin["mapping"]["model_call"]["inputs_hash"] == lin["mapping"]["input_hash"]
    assert lin["other_records_of_this_supplier"] and lin["factor_version"]["status"] == "frozen" and lin["factor"]["version"] == "EF-2025.1-S1"
    eng = demo["eng"]
    assert len(eng["items"]) == 20 and eng["network_edges"] > 0 and any(i["via"] for i in eng["items"])
    sc = demo["sc"]["result"]
    assert sc["results"]["total"]["change"]["p97_5"] < 0 and sc["results"]["s3:4"]["change"]["t"] < 0 and sc["freight"]["tonnes_shifted"] > 0
    assert sc["recalculation"]["activity_lines"] > LINES and len(sc["suppliers"]) == 20
    assert all(demo["pub"]["checks"][k]["ok"] for k in ("lineage_coverage", "orphan_rate", "reproduced")) and demo["approve"]["published"]
    assert len(demo["export"]["sha256"]) == 64 and demo["export"]["report"]["approval"]["decided_by"] != demo["export"]["report"]["approval"]["proposed_by"]
    actions = {e["action"] for e in demo["audit"]["events"]}
    assert demo["audit"]["chain_valid"] and {"company.loaded", "activities.imported", "suppliers.resolved", "documents.extracted", "factor_version.proposed",
                                            "adopt_factor_version.approved", "calculation.run", "calculation.reproduced", "scenario.run",
                                            "publish_inventory.approved", "report.exported"} <= actions
    assert one("SELECT count(*) AS n FROM model_runs WHERE model_name = 'category-tfidf-lr-1'")["n"] == mp["distinct_inputs_classified"] + 2


def test_validation(client, demo):
    calc = demo["calc"]["result"]["calculation_id"]
    row = {"subsidiary": "MDG-GB", "vendor_ref": "MDG-GB-V00045", "invoice": "T-1", "line": 1, "period": "2025-05-01", "description": "x", "gl_code": "5100", "amount": 10.0, "currency": "GBP"}
    r = client.post("/v1/activities/import", headers=ANALYST, json={"rows": [row, row, {**row, "invoice": "T-2", "vendor_ref": "MDG-GB-V99999"}, {**row, "invoice": "T-3", "period": "2024-05-01"},
                                                                            {**row, "invoice": "PAPER-0007"}, {**row, "invoice": "T-4", "amount": 0}, {**row, "invoice": "T-5", "subsidiary": "MDG-ZZ"}]}).json()
    assert [x["why"] for x in r["refused"]] == ["duplicate in this upload", "vendor MDG-GB-V99999 is not in the vendor master", "period 2024-05-01 is outside the reporting year 2025",
                                                "already imported", "amount is zero", "unknown subsidiary"] and len(r["accepted"]) == 1
    assert client.post("/v1/activities/import", headers=ANALYST, json={}).json()["code"] == "one_source"
    assert client.post("/v1/activities/import", headers=ANALYST, json={"rows": [{**row, "gl_code": "51"}]}).json()["code"] == "validation_failed"
    assert client.post("/v1/calculations", headers=ANALYST, json={"factor_version": "EF-1999.1"}).status_code == 404
    assert client.post("/v1/scenarios", headers=ANALYST, json={"name": "x"}).json()["code"] == "nothing_to_change"
    assert client.post("/v1/scenarios", headers=ANALYST, json={"name": "x", "supplier_decarbonisation": {"reduction": 0.2}}).json()["code"] == "pick_suppliers"
    assert client.post("/v1/factor-versions", headers=ANALYST, json={"id": "EF-2025.1-S1", "based_on": "EF-2025.1"}).json()["code"] == "version_exists"
    assert client.get(f"/v1/calculations/{calc}/lineage?activity_id=999999999", headers=VIEWER).status_code == 404
    assert client.get(f"/v1/suppliers/{uuid.uuid4()}", headers=VIEWER).status_code == 404


def test_frozen_factors_and_policy_checks(client, demo, seeded):
    with pytest.raises(psycopg.errors.RaiseException, match="frozen"), db.tx(seeded["meridale"]) as c:
        c.execute("UPDATE emission_factor SET value = value * 0.5 WHERE version = 'EF-2025.1-S1'")
    with pytest.raises(psycopg.errors.RaiseException, match="frozen"), db.tx(seeded["meridale"]) as c:
        c.execute("UPDATE factor_version SET status = 'draft' WHERE id = 'EF-2025.1'")
    # a draft version cannot be calculated with, and a calculation nobody reproduced cannot be proposed for publication
    prop = client.post("/v1/factor-versions", headers=ANALYST, json={"id": "EF-2025.1-S2", "based_on": "EF-2025.1"}).json()
    assert client.post("/v1/calculations", headers=ANALYST, json={"factor_version": "EF-2025.1-S2"}).json()["code"] == "version_not_frozen"
    assert client.post(f"/v1/decisions/{prop['decision_id']}/approve?decision=rejected", headers=LEAD).json()["status"] == "rejected"
    assert one("SELECT count(*) AS n FROM emission_factor WHERE version = 'EF-2025.1-S2'")["n"] == 0
    r = client.post("/v1/calculations", headers=ANALYST, json={"factor_version": "EF-2024.2"}).json()
    jobs.drain()
    old = client.get(r["status_url"], headers=ANALYST).json()["result"]
    assert old["result_hash"] != demo["calc"]["result"]["result_hash"] and old["lineage_coverage"] == 1.0
    assert client.post(f"/v1/calculations/{old['calculation_id']}/publish", headers=ANALYST, json={}).json()["code"] == "policy_failed"
    assert client.post("/v1/reports/export", headers=ANALYST, json={"calculation_id": old["calculation_id"]}).json()["code"] == "not_published"


def test_roles_and_the_second_person(client, demo):
    assert client.get("/v1/overview").status_code == 401 and client.get("/v1/overview", headers=VIEWER).status_code == 200
    for path, body in (("/v1/activities/import", {"rows": []}), ("/v1/suppliers/resolve", {}), ("/v1/calculations", {}), ("/v1/scenarios", {"name": "x"}), ("/v1/reports/export", {})):
        assert client.post(path, headers=VIEWER, json=body).status_code == 403, path
    assert client.post("/v1/company:load", headers=ANALYST, json={}).status_code == 403 and client.get("/v1/audit", headers=ANALYST).status_code == 403
    calc = demo["calc"]["result"]["calculation_id"]
    r = client.post("/v1/calculations", headers=ANALYST, json={}).json()
    jobs.drain()
    new = client.get(r["status_url"], headers=ANALYST).json()["result"]
    rep = client.post(f"/v1/calculations/{new['calculation_id']}:reproduce", headers=LEAD, json={}).json()
    jobs.drain()
    assert client.get(rep["status_url"], headers=LEAD).json()["result"]["identical"]
    prop = client.post(f"/v1/calculations/{new['calculation_id']}/publish", headers=LEAD, json={}).json()           # a lead proposes ...
    assert client.post(f"/v1/decisions/{prop['decision_id']}/approve", headers=LEAD).json()["code"] == "proposer_cannot_approve"   # ... and cannot approve
    assert client.post(f"/v1/decisions/{demo['pub']['decision_id']}/approve", headers=LEAD).json()["code"] == "already_decided"
    assert client.post(f"/v1/calculations/{calc}/publish", headers=ANALYST, json={}).json()["code"] == "already_published"


def test_another_company_sees_nothing(client, demo, seeded):
    calc = demo["calc"]["result"]["calculation_id"]
    assert client.get("/v1/overview", headers=OTHER).json()["code"] == "no_company"
    assert client.get(f"/v1/calculations/{calc}/lineage", headers=bearer("other", "viewer")).status_code == 404
    assert client.get(f"/v1/suppliers/{demo['res']['result']['examples'][0]['supplier_id']}", headers=bearer("other", "viewer")).status_code == 404
    assert client.get("/v1/inventory/scope3", headers=bearer("other", "viewer")).json()["code"] == "no_company"
    for table in ("organization", "facility", "supplier", "supplier_alias", "import_batch", "activity", "factor_version", "emission_factor", "calculation",
                  "calculation_lineage", "scenario", "assurance_evidence", "decision_record", "review_task", "model_artifacts", "model_runs"):
        assert one(f"SELECT count(*) AS n FROM {table}", tenant=seeded["other"])["n"] == 0 < one(f"SELECT count(*) AS n FROM {table}", tenant=seeded["meridale"])["n"], table
    with pytest.raises(Exception, match="row-level security"), db.tx(seeded["other"]) as c:
        c.execute("INSERT INTO review_task (tenant_id, id, kind, subject, detail) VALUES (%s,%s,'category','x','{}')", [seeded["meridale"], uuid.uuid4()])


def test_idempotent_writes(client, demo):
    body = demo_rows_body()
    again = client.post("/v1/activities/import", headers={**ANALYST, "Idempotency-Key": "demo-1:rows"}, json=body)
    assert again.status_code == 201 and again.headers["Idempotent-Replay"] == "true" and again.json()["batch_id"] == demo["rows"]["batch_id"]
    assert client.post("/v1/activities/import", headers={**ANALYST, "Idempotency-Key": "demo-1:rows"}, json={"rows": body["rows"][:1]}).json()["code"] == "idempotency_key_reused"
    assert client.post("/v1/company:load", headers=LEAD, json={"seed": 9}).json()["code"] == "company_exists"
    fresh = client.post("/v1/activities/import", headers=ANALYST, json=body).json()                    # the same lines again without the key: the data refuses them
    assert [x["why"] for x in fresh["refused"]] == ["already imported", "already imported", "unknown currency 'GPB'"]


def demo_rows_body():
    return scenario.load()["steps"][1]["calls"][1]["body"]
