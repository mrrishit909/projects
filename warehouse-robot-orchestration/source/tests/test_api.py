"""Integration, end-to-end and security tests against a real Postgres."""
import uuid

import pytest

from core import db, jobs, scenario

from .conftest import bearer

MANAGER, ENGINEER, VIEWER, OTHER = bearer("wh", "shift_manager"), bearer("wh", "fleet_engineer"), bearer("wh", "viewer"), bearer("other", "shift_manager")


def test_nothing_works_before_a_warehouse_is_loaded(client):
    assert client.get("/v1/fleet/state", headers=VIEWER).json()["code"] == "no_warehouse"
    assert client.post("/v1/tasks", headers=ENGINEER, json={"tasks": [{"id": "T-1", "location": "A-01-01"}]}).json()["code"] == "no_warehouse"
    assert client.post("/v1/robots/R-001/pause", headers=ENGINEER, json={}).json()["code"] == "no_warehouse"


@pytest.fixture(scope="module")
def demo(client):
    results, _ = scenario.run(client, drain=jobs.drain)
    return results


def one(sql, params=(), tenant=None):
    with db.tx(tenant) as c:
        return c.execute(sql, params).fetchone()


def test_demo_journey(demo):
    load = demo["load"]["result"]
    assert (load["robots"], load["cells"], load["chargers"], load["stations"], load["pick_cells"]) == (250, 3452, 24, 20, 1476)
    assert load["battery_model"]["mae_points"] < load["battery_model"]["baseline_mae_points"] and load["battery_cycles"] > 100000
    assert len(demo["map"]["grid"]) == demo["map"]["height"] and len(demo["fs0"]["robots"]) == 250 and demo["bat"]["eol"]
    adv1 = demo["adv1"]["result"]
    assert adv1["collisions"] == 0 and adv1["robot_steps_checked"] == 300 * 250 and adv1["orders_completed"] > 300 and adv1["simulation_truth"]["wave"]["orders_per_hour"] == 9000
    adv2 = demo["adv2"]["result"]
    closed = [e for e in adv2["events"] if e["kind"] == "aisle_closed"]
    assert [e["zone"] for e in closed] == ["C-14", "B-27"] and all(e["robots"] > 0 for e in closed) and adv2["collisions"] == 0
    assert any(e["kind"] == "charger_fault" and e["charger"] == "CH-05" for e in adv2["events"]) and adv2["held_tasks"] > 0
    assert demo["fs2"]["closed_aisles"] == ["B-27", "C-14"] and next(c for c in demo["fs2"]["chargers"]["chargers"] if c["id"] == "CH-05")["status"] == "fault"
    pause = demo["pause"]
    assert pause["robot"] == demo["fs2"]["in_aisles"][0]["robot"] and pause["robots"] >= 2 and pause["deferred"] >= 1 and pause["waiting"] == 0
    assert demo["adv3"]["result"]["deferred_replans"]["robots"] == pause["deferred"]          # the rest were re-planned at the next epoch
    assert any(p["before"] != p["after"] for p in pause["paths"].values()) and demo["conf"]["counts"]["replan"] >= 3
    assert [a["id"] for a in demo["urgent"]["accepted"]] == [f"EXP-700{i}" for i in range(1, 6)] and demo["urgent"]["refused"] == [{"id": "EXP-7006", "why": "unknown location Z-99-01"}]
    rec = demo["rec"]["result"]
    keep, pre = rec["alternatives"]
    assert rec["needs_approval"] and rec["recommended"] == "preempt" and pre["urgent"]["on_time"] > keep["urgent"]["on_time"] and pre["assignments"]
    assert all(x["on_time"] for x in pre["projection"]["tasks"] if x["priority"] == "normal")      # the bumped orders still make their own SLA
    assert demo["self"]["status"] == 403 and demo["approve"]["status"] == "approved" and len(demo["approve"]["applied"]) == 5
    adv3 = demo["adv3"]["result"]
    urgent = {u["id"]: u for u in adv3["urgent"]}
    assert all(u["status"] == "done" for u in urgent.values()) and sum(u["done_t"] <= u["due"] for u in urgent.values()) >= pre["urgent"]["on_time"] - 1
    assert adv3["collisions"] == 0 and demo["resume"]["waiting"] == 0
    sim = demo["sim"]["result"]
    assert all(m["collisions"] == 0 for m in sim["policies"].values()) and sim["comparison"]["cpsat"]["distance_per_order_vs_fifo"] < -0.10
    assert sim["policies"]["cpsat"]["orders_arrived"] == sim["policies"]["fifo"]["orders_arrived"]            # the same order stream
    assert demo["audit"]["chain_valid"] and {"warehouse.loaded", "fleet.advanced", "robot.paused", "tasks.created", "plan.recomputed", "plan.approved",
                                             "robot.resumed", "simulation.ran"} <= {e["action"] for e in demo["audit"]["events"]}
    assert one("SELECT count(*) AS n FROM model_artifacts WHERE approved")["n"] == 3 and one("SELECT count(*) AS n FROM model_runs WHERE model_name = 'battery-soh'")["n"] >= 230
    assert one("SELECT count(*) AS n FROM conflicts WHERE kind <> 'replan'")["n"] == 0 and one("SELECT count(*) AS n FROM route_plans")["n"] == 250
    assert one("SELECT count(*) AS n FROM task_assignments WHERE inputs_hash !~ '^[0-9a-f]{16}$' AND inputs_hash <> 'preemption'")["n"] == 0
    assert one("SELECT count(*) AS n FROM tasks WHERE status = 'done'")["n"] == one("SELECT count(*) AS n FROM tasks WHERE done_s IS NOT NULL")["n"] > 700
    assert one("SELECT status FROM zones WHERE id = 'C-14'")["status"] == "closed" and one("SELECT max(sim_t) AS t FROM robot_state")["t"] == 690


def test_validation(client, demo):
    adv = lambda body: client.post("/v1/fleet:advance", headers=MANAGER, json=body)          # noqa: E731
    assert adv({"seconds": 0}).status_code == 422 and adv({"seconds": 10, "inject": [{"kind": "aisle_blocked", "zone": "Q-99"}]}).json()["code"] == "unknown_aisle"
    assert adv({"seconds": 10, "inject": [{"kind": "charger_fault", "charger": "CH-99"}]}).json()["code"] == "unknown_charger"
    assert adv({"seconds": 10, "inject": [{"kind": "aisle_blocked", "zone": "A-01", "after_s": 10}]}).json()["code"] == "event_after_window"
    post = lambda tasks: client.post("/v1/tasks", headers=ENGINEER, json={"tasks": tasks})    # noqa: E731
    r = post([{"id": "EXP-7001", "location": "A-01-01"}, {"id": "T-held", "location": "C-14-03"}])
    assert r.json()["refused"] == [{"id": "EXP-7001", "why": "task id already exists"}] and r.json()["accepted"][0]["status"] == "held"
    assert post([{"id": "bad id!", "location": "A-01-01"}]).status_code == 422 and post([]).status_code == 422
    assert client.post("/v1/robots/R-999/pause", headers=ENGINEER, json={}).status_code == 404
    assert client.post("/v1/robots/R-001/resume", headers=ENGINEER).json()["code"] == "not_paused"
    assert client.post("/v1/robots/R-001/pause", headers=ENGINEER, json={"reason": "x"}).status_code == 422
    assert client.post("/v1/simulations", headers=ENGINEER, json={"policies": ["fifo", "fifo"]}).status_code == 422
    assert client.get(f"/v1/simulations/{uuid.uuid4()}", headers=VIEWER).status_code == 404
    assert client.post(f"/v1/decisions/{uuid.uuid4()}/approve", headers=MANAGER).status_code == 404
    rob = client.get("/v1/robots/R-001", headers=VIEWER).json()
    assert len(rob["plan_next_60s"]) == 60 and rob["battery"]["forecast"][0]["soh"] >= rob["battery"]["forecast"][-1]["soh"]


def test_roles_and_the_second_person(client, demo, seeded):
    assert client.get("/v1/fleet/state").status_code == 401 and client.get("/v1/fleet/state", headers=VIEWER).status_code == 200
    for path, body in (("/v1/tasks", {"tasks": []}), ("/v1/plans/recompute", {}), ("/v1/simulations", {}), ("/v1/robots/R-001/pause", {})):
        assert client.post(path, headers=VIEWER, json=body).status_code == 403, path
    assert client.post("/v1/fleet:advance", headers=ENGINEER, json={"seconds": 1}).status_code == 403
    assert client.post("/v1/warehouse:load", headers=ENGINEER, json={}).status_code == 403 and client.get("/v1/audit", headers=ENGINEER).status_code == 403
    assert client.post(f"/v1/decisions/{demo['rec']['result']['decision_id']}/approve", headers=MANAGER).json()["code"] == "already_decided"
    version = one("SELECT state_version FROM warehouses")["state_version"]
    manager_id = uuid.uuid5(seeded["wh"], "shift_manager")
    engineer_id = uuid.uuid5(seeded["wh"], "fleet_engineer")
    own, stale = uuid.uuid4(), uuid.uuid4()
    with db.tx(seeded["wh"]) as c:                                  # a plan the manager proposed, and one computed against an older floor
        c.execute("INSERT INTO decisions (id, tenant_id, kind, proposal, state_version, proposed_by) VALUES (%s,%s,'preemption','{\"assignments\": []}',%s,%s)",
                  [own, seeded["wh"], version, manager_id])
        c.execute("INSERT INTO decisions (id, tenant_id, kind, proposal, state_version, proposed_by) VALUES (%s,%s,'preemption','{\"assignments\": []}',%s,%s)",
                  [stale, seeded["wh"], version - 1, engineer_id])
    assert client.post(f"/v1/decisions/{own}/approve", headers=MANAGER).json()["code"] == "proposer_cannot_approve"
    assert client.post(f"/v1/decisions/{stale}/approve", headers=MANAGER).json()["code"] == "plan_stale"
    assert one("SELECT status FROM decisions WHERE id = %s", [stale])["status"] == "stale"


def test_another_operator_sees_nothing(client, demo, seeded):
    assert client.get("/v1/fleet/state", headers=OTHER).json()["code"] == "no_warehouse"
    assert client.get(f"/v1/simulations/{demo['sim']['result']['simulation_id']}", headers=bearer("other", "viewer")).status_code == 404
    for table in ("warehouses", "zones", "nodes", "edges", "robots", "robot_state", "chargers", "battery_cycles", "tasks", "task_assignments", "route_plans",
                  "conflicts", "world_events", "simulation_runs", "model_artifacts", "model_runs", "decisions"):
        assert one(f"SELECT count(*) AS n FROM {table}", tenant=seeded["other"])["n"] == 0 < one(f"SELECT count(*) AS n FROM {table}", tenant=seeded["wh"])["n"], table
    with pytest.raises(Exception, match="row-level security"), db.tx(seeded["other"]) as c:
        c.execute("INSERT INTO conflicts (tenant_id, sim_t, kind, robots) VALUES (%s, 1, 'vertex', '{}')", [seeded["wh"]])


def test_idempotent_writes(client, demo):
    body = demo_urgent_body()
    again = client.post("/v1/tasks", headers={**ENGINEER, "Idempotency-Key": "demo-1:urgent"}, json=body)
    assert again.status_code == 201 and again.headers["Idempotent-Replay"] == "true" and again.json() == demo["urgent"]
    assert client.post("/v1/tasks", headers={**ENGINEER, "Idempotency-Key": "demo-1:urgent"}, json={"tasks": body["tasks"][:1]}).json()["code"] == "idempotency_key_reused"
    assert client.post("/v1/warehouse:load", headers=MANAGER, json={"seed": 9}).json()["code"] == "warehouse_exists"


def demo_urgent_body():
    step = next(s for s in scenario.load()["steps"] for c in s["calls"] if c["key"] == "urgent")
    return next(c for c in step["calls"] if c["key"] == "urgent")["body"]
