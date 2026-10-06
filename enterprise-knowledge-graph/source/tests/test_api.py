"""Integration, end-to-end and security tests against a real Postgres."""
import json
import uuid

import pytest

from core import db, jobs, scenario

from .conftest import bearer

STEWARD, ANALYST, VIEWER, OTHER = bearer("halden", "steward"), bearer("halden", "analyst"), bearer("halden", "viewer"), bearer("other", "steward")


def test_nothing_works_before_a_corpus_is_loaded(client):
    assert client.get("/v1/overview", headers=VIEWER).json()["code"] == "no_corpus"
    assert client.post("/v1/connectors/sync", headers=STEWARD, json={"mode": "full"}).json()["code"] == "no_corpus"
    assert client.post("/v1/answers", headers=VIEWER, json={"question": "who owns ledger-api?"}).json()["code"] == "no_corpus"


@pytest.fixture(scope="module")
def demo(client):
    results, _ = scenario.run(client, drain=jobs.drain)
    return results


def one(sql, params=(), tenant=None):
    with db.tx(tenant) as c:
        return c.execute(sql, params).fetchone()


def test_demo_journey(demo):
    load, sync = demo["load"]["result"], demo["sync"]["result"]
    m = load["models"]["extraction"]
    assert load["people"] == 106 and len(load["sources"]) == 6 and m["model"]["precision"] > m["rules"]["precision"] and load["models"]["linking"]["precision"] > 0.99
    assert sync["objects_changed"] == sum(s["objects_waiting"] for s in load["sources"]) and sync["mentions_abstained"] > 0 and sync["merge_suggestions_new"] == 2
    assert one("SELECT count(*) AS n FROM model_runs")["n"] == 2 * (sync["objects_changed"] + demo["sync2"]["result"]["objects_changed"]) and one("SELECT count(*) AS n FROM model_runs WHERE inputs_hash !~ '^[0-9a-f]{16}$'")["n"] == 0
    assert [o["you"]["containers"] for o in (demo["ov0"], demo["ov_a"], demo["ov_v"])] == [31, 17, 22] and demo["ov_v"]["view"]["facts"] < demo["ov0"]["view"]["facts"]
    assert not any(c["container"].startswith(("wiki:PROC", "crm:contracts", "chat:#vendor-eval")) for s in demo["ov_v"]["sources"] for c in s["readable_containers"])
    assert {a["alias"] for a in demo["res"]["same_name_different_entities"]} and demo["res"]["queue"][0]["status"] == "suggested"
    assert demo["self"]["code"] == "forbidden" and demo["approve"]["status"] == "approved" and demo["approve"]["moved"]["mentions"] > 10
    assert {"Data Platform", "Analytics Engineering"} <= {a["alias"] for a in demo["team"]["aliases"]}
    ask = demo["ask"]
    assert ask["sentences"][0]["text"].startswith("Ember Observability was selected") and ask["verification"]["coverage"] == 1.0 and len(ask["sentences"]) == 7
    assert any("rejected because" in s["text"] for s in ask["sentences"]) and any(r["ranks"].get("graph") for r in demo["find"]["results"])
    assert demo["adv"]["result"]["simulation_truth"]["told"][0]["service"] == "rate-limiter" and demo["sync2"]["result"]["mode"] == "incremental"
    s2 = demo["sync2"]["result"]
    assert 0 < s2["objects_changed"] < 30 and s2["seconds_from_request"] < 300 and s2["systems"]["hr"]["changed"] == 0
    own = demo["own"]
    assert own["sentences"][0]["text"] == "rate-limiter is owned by Messaging (since 2026-05-02)." and own["verification"]["coverage"] == 1.0
    assert any("service overview" in s["text"] and "Search & Discovery" in s["text"] for s in own["sentences"])            # the stale page, named and outvoted
    assert any("INC-9" in s["text"] for s in own["sentences"])                                                          # the failing incident the sync just brought in
    assert demo["then"]["sentences"][0]["text"] == "On 2026-03-15, rate-limiter was owned by Search & Discovery."
    assert [f["subject"]["name"] for f in demo["svc"]["timeline"]] == ["Search & Discovery", "Messaging"]
    assert demo["prov"]["fact"]["predicate"] == "SELECTED" and {e["source"]["container"] for e in demo["prov"]["evidence"]} >= {"chat:#vendor-eval-observability"}
    assert demo["prov2"]["contradicting"] and demo["prov2"]["contradicting"][0]["source"]["title"] == "rate-limiter service overview"
    viewer = demo["ask_viewer"]
    assert len(viewer["sentences"]) == 2 and viewer["verification"]["coverage"] == 1.0 and {s["container"] for s in viewer["sources"]} == {"chat:#eng-decisions"}
    assert demo["price_viewer"]["abstained"] and demo["price_analyst"]["sentences"][0]["text"] == "The Ember Observability contract is worth $455,000 a year."
    assert "455,000" not in json.dumps(demo["price_viewer"]) and "breach" not in json.dumps(demo["find_viewer"]["results"]).lower()
    assert demo["prov_viewer"]["code"] == "fact_not_found"
    assert len(demo["graph_viewer"]["nodes"]) < len(demo["graph_analyst"]["nodes"])
    suite = demo["suite"]["result"]
    assert suite["leaks"] == 0 and suite["probes"] > 5000 and suite["non_interference"]["failed"] == 0 and suite["filter_off"]["leaks"] > suite["filter_off"]["probes"] / 2
    assert one("SELECT count(*) AS n FROM query_audit")["n"] >= 15 and one("SELECT count(*) AS n FROM embedding")["n"] > 0
    assert demo["audit"]["chain_valid"] and {"corpus.loaded", "connectors.synced", "merge.proposed", "merge.approved", "simulator.advanced", "security.suite"} <= {e["action"] for e in demo["audit"]["events"]}


def test_validation(client, demo):
    assert client.post("/v1/connectors/sync", headers=STEWARD, json={"mode": "sometimes"}).status_code == 422
    assert client.post("/v1/connectors/sync", headers=STEWARD, json={"systems": ["sharepoint"]}).status_code == 422
    assert client.post("/v1/simulator:advance", headers=STEWARD, json={"days": 1, "inject": {"kind": "service_failure", "service": "no-such-api"}}).json()["code"] == "unknown_service"
    assert client.post("/v1/simulator:advance", headers=STEWARD, json={"days": 0}).status_code == 422
    assert client.post("/v1/search", headers=VIEWER, json={"query": "x"}).status_code == 422
    assert client.post("/v1/answers", headers=VIEWER, json={"question": "q" * 501}).status_code == 422
    assert client.post("/v1/graph/query", headers=VIEWER, json={"depth": 1}).json()["code"] == "entity_required"
    assert client.post("/v1/graph/query", headers=VIEWER, json={"name": "nothing like this anywhere"}).status_code == 404
    keep = demo["team"]["id"]
    assert client.post("/v1/merges", headers=ANALYST, json={"keep_id": keep, "merge_id": keep}).json()["code"] == "same_entity"
    person = demo["prov"]["evidence"][0]["resolution"][0]["entity"] if demo["prov"]["evidence"][0]["resolution"] else None
    vendor = demo["ask"]["entities"][0]["id"]
    assert client.post("/v1/merges", headers=ANALYST, json={"keep_id": keep, "merge_id": vendor}).json()["code"] == "type_mismatch"
    assert client.post("/v1/merges", headers=ANALYST, json={"keep_id": keep, "merge_id": demo["prop"]["merge"]["id"]}).json()["code"] in ("already_merged", "entity_not_found")
    assert client.get(f"/v1/entities/{uuid.uuid4()}", headers=VIEWER).status_code == 404 and client.get("/v1/entities/not-a-uuid", headers=VIEWER).status_code == 422
    assert client.get(f"/v1/facts/{uuid.uuid4()}/provenance", headers=VIEWER).json()["code"] == "fact_not_found"
    assert client.get(f"/v1/entities/{demo['prop']['merge']['id']}", headers=ANALYST).json()["merged_from"] == demo["prop"]["merge"]["id"]     # an old id finds its merged entity
    assert person is None or client.get(f"/v1/entities/{person}", headers=ANALYST).status_code == 200


def test_roles_and_the_second_person(client, demo):
    assert client.get("/v1/overview").status_code == 401 and client.get("/v1/overview", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.post("/v1/connectors/sync", headers=VIEWER, json={}).status_code == 403 and client.post("/v1/corpus:load", headers=ANALYST, json={}).status_code == 403
    assert client.post("/v1/security/suite", headers=ANALYST).status_code == 403 and client.get("/v1/audit", headers=ANALYST).status_code == 403
    q = client.get("/v1/resolution", headers=STEWARD).json()["queue"]
    other = next(x for x in q if x["status"] == "suggested")                      # the second rename, still a suggestion
    assert client.post("/v1/merges", headers=VIEWER, json={"keep_id": other["keep"]["id"], "merge_id": other["merge"]["id"]}).status_code == 403
    prop = client.post("/v1/merges", headers=STEWARD, json={"keep_id": other["keep"]["id"], "merge_id": other["merge"]["id"], "reason": "renamed"}).json()
    assert prop["status"] == "proposed"
    assert client.post(f"/v1/merges/{prop['merge_id']}/approve", headers=STEWARD).json()["code"] == "proposer_cannot_approve"           # a steward proposes ...
    assert client.post(f"/v1/merges/{prop['merge_id']}/approve", headers=ANALYST).status_code == 403                                     # ... an analyst may not decide
    assert client.post(f"/v1/merges/{demo['prop']['merge_id']}/approve", headers=STEWARD).json()["code"] == "not_proposed"


def test_permissions_hold_through_the_api(client, demo):
    """What the analyst sees from procurement, the engineer cannot reach by any endpoint, and gets the same answer as for nothing."""
    restricted = [f for f in demo["ask"]["facts"] if f["predicate"] in ("CONSIDERED", "REJECTED", "DECIDED_BY")]
    assert restricted
    for f in restricted:
        assert client.get(f"/v1/facts/{f['id']}/provenance", headers=ANALYST).status_code == 200
        r = client.get(f"/v1/facts/{f['id']}/provenance", headers=VIEWER)
        assert r.status_code == 404 and r.json() == client.get(f"/v1/facts/{uuid.uuid4()}/provenance", headers=VIEWER).json()
    rejected = {f["object"]["id"]: f["object"]["name"] for f in restricted if f["predicate"] == "CONSIDERED"}
    for eid, name in rejected.items():
        assert client.get(f"/v1/entities/{eid}", headers=ANALYST).status_code == 200 and client.get(f"/v1/entities/{eid}", headers=VIEWER).status_code == 404
        for body in ({"question": f"Why was {name} rejected?"}, {"question": f"How much does the {name} contract cost?"}):
            a = client.post("/v1/answers", headers=VIEWER, json=body).json()
            assert not any(s["facts"] for s in a["sentences"]) and eid not in json.dumps(a)
        s = client.post("/v1/search", headers=VIEWER, json={"query": f"{name} rejected security review pricing", "k": 20}).json()
        assert not any(r["source"]["container"].startswith(("wiki:PROC", "wiki:SEC", "chat:#vendor-eval", "crm:contracts", "tickets:PROCURE")) for r in s["results"])
        assert client.post("/v1/graph/query", headers=VIEWER, json={"entity_id": eid}).status_code == 404
    found = client.get("/v1/entities", headers=VIEWER, params={"q": next(iter(rejected.values()))}).json()["items"]
    assert not any(i["id"] in rejected for i in found)


def test_another_tenant_sees_nothing(client, demo, seeded):
    assert client.get("/v1/overview", headers=OTHER).json()["code"] == "no_corpus"
    assert client.get(f"/v1/entities/{demo['team']['id']}", headers=OTHER).json()["code"] == "no_corpus"
    tables = ("corpora", "source_system", "source_object", "principal", "permission_edge", "document_chunk", "entity", "entity_alias", "mention", "relationship",
              "temporal_fact", "evidence", "embedding", "query_audit", "merge_proposal", "sync_runs", "model_artifacts", "model_runs")
    for table in tables:
        assert one(f"SELECT count(*) AS n FROM {table}", tenant=seeded["halden"])["n"] > 0, table
        mine = one(f"SELECT count(*) AS n FROM {table}", tenant=seeded["other"])["n"]
        assert mine == (3 if table == "principal" else 0), table                  # the other tenant's three API users, nothing else
    with pytest.raises(Exception, match="row-level security"), db.tx(seeded["other"]) as c:
        c.execute("INSERT INTO entity (id, tenant_id, type, canonical_key, canonical_name, anchored) VALUES (%s,%s,'team','x','x',false)", [uuid.uuid4(), seeded["halden"]])


def test_idempotent_writes_and_incremental_sync(client, demo):
    again = client.post("/v1/answers", headers={**ANALYST, "Idempotency-Key": "demo-1:ask"}, json={"question": demo["ask"]["question"]})
    assert again.status_code == 200 and again.headers["Idempotent-Replay"] == "true" and again.json()["sentences"] == demo["ask"]["sentences"]
    assert client.post("/v1/answers", headers={**ANALYST, "Idempotency-Key": "demo-1:ask"}, json={"question": "something else"}).json()["code"] == "idempotency_key_reused"
    assert client.post("/v1/corpus:load", headers=STEWARD, json={"seed": 9}).json()["code"] == "corpus_exists"
    r = client.post("/v1/connectors/sync", headers=STEWARD, json={"mode": "incremental"}).json()
    jobs.drain()
    res = client.get(r["status_url"], headers=STEWARD).json()["result"]
    assert res["objects_changed"] == sum(s["changed"] for s in res["systems"].values()) and all(s["changed"] == s["fetched"] - s["unchanged"] for s in res["systems"].values())
