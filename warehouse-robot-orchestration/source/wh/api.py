"""Public API (modular monolith). Blueprint services map to: robot-adapter (telemetry in, robot_state), world-model (zones,
nodes, edges, closures and obstacles), task-planner (tasks, FIFO / greedy / CP-SAT assignment), multi-agent-pathfinder
(prioritized SIPP planning, D* Lite distance fields, local CBS), traffic-control (repairs after events, pause and resume),
battery-planner (chargers, the degradation forecast), simulation (sandbox runs and forward projections) and fleet-api
(fleet state). Not built: ROS2/gRPC/MQTT adapters, Kafka, a WebSocket telemetry feed, RL; see the README.

    uvicorn wh.api:app          python -m core.jobs wh.api      # the worker
"""
import datetime
import functools
import hashlib
import json
import pickle
import uuid
from collections import defaultdict
from typing import Literal

from fastapi import Depends, Header, Query
from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from core import audit, db, jobs
from core.app import Ctx, Problem, create_app, run

from . import engine, world

READ = {"fleet:read", "jobs:read"}
ENGINEER = READ | {"tasks:create", "plans:recompute", "simulations:run", "robots:pause"}
PERMISSIONS = {"viewer": READ, "fleet_engineer": ENGINEER,
               "shift_manager": ENGINEER | {"warehouse:load", "fleet:advance", "decisions:approve", "audit:read"}}
app = create_app("warehouse-robot-orchestration", PERMISSIONS)
auth = app.state.auth
IdemKey = Header(None, alias="Idempotency-Key")
START = datetime.datetime(2026, 10, 5, 16, 0, tzinfo=datetime.UTC)        # simulated second 0: the evening peak begins
ZONE_KIND = {"X": "cross_aisle", "H": "highway", "PARK": "parking", "PACK": "pack"}
_cache = {}


@functools.lru_cache(maxsize=1)
def layout():
    return world.Layout()


def at(seconds):
    return START + datetime.timedelta(seconds=float(seconds))


def worker_ctx(job):
    return Ctx(job["tenant_id"], uuid.UUID(job["payload"]["actor_id"]), "worker", "system")


def warehouse(c, lock=False):
    w = c.execute("SELECT * FROM warehouses" + (" FOR UPDATE" if lock else "")).fetchone()
    if not w:
        raise Problem(409, "no_warehouse", "load a warehouse first: POST /v1/warehouse:load")
    return w


def state(c, lock=False):
    """(row, floor, fleet). Reads share an unpickled copy per state version; writes lock the row and get their own."""
    w = warehouse(c, lock)
    key = (str(w["tenant_id"]), w["state_version"])
    if not lock and key in _cache:
        return w, *_cache[key]
    floor, fleet = pickle.loads(w["world_state"]), pickle.loads(w["fleet_state"])
    if not lock:
        _cache.clear()
        _cache[key] = (floor, fleet)
    return w, floor, fleet


def robot_index(fleet, robot_id):
    r = fleet.index.get(robot_id)
    if r is None:
        raise Problem(404, "robot_not_found")
    return r


def xy(fleet, c):
    return list(fleet.L.xy[c])


def zone_kind(z):
    return "aisle" if "-" in z else ZONE_KIND.get(z, ZONE_KIND.get(z[0]))


def upsert(c, table, cols, key, rows):
    c.execute(f"CREATE TEMP TABLE _up (LIKE {table} INCLUDING DEFAULTS) ON COMMIT DROP")
    db.copy(c, "_up", cols, rows)
    sets = ", ".join(f"{k} = EXCLUDED.{k}" for k in cols if k not in key)
    c.execute(f"INSERT INTO {table} ({', '.join(cols)}) SELECT {', '.join(cols)} FROM _up ON CONFLICT ({', '.join(key)}) DO UPDATE SET {sets}")
    c.execute("DROP TABLE _up")


def persist(c, w, floor, fleet, marks):
    """Write the new state and its read model: robot_state, tasks, plans, assignments, conflicts, events, chargers, zones."""
    t, tid = floor.t, w["tenant_id"]
    c.execute("UPDATE warehouses SET world_state = %s, fleet_state = %s, clock_s = %s, told = %s, wave = %s, state_version = state_version + 1",
              [pickle.dumps(floor, protocol=5), pickle.dumps(fleet, protocol=5), t, Jsonb(floor.told), Jsonb(floor.wave)])
    upsert(c, "robot_state", ["tenant_id", "robot_id", "node", "soc", "soh_est", "status", "task_id", "sim_t", "observed_at"], ["tenant_id", "robot_id"],
           [(tid, fleet.ids[r], fleet.cell[r], round(fleet.soc[r], 5), round(fleet.soh[r], 4), fleet.status[r] if not fleet.waiting[r] else "waiting",
             fleet.task[r], fleet.seen_t[r], at(fleet.seen_t[r])) for r in range(fleet.R)])
    upsert(c, "tasks", ["tenant_id", "id", "pick_node", "location", "priority", "status", "released_s", "due_s", "robot_id", "station",
                        "assigned_s", "picked_s", "done_s", "source", "bumped"], ["tenant_id", "id"],
           [(tid, k, tk["pick"], tk["location"], tk["priority"], tk["status"], tk["released"], tk["due"],
             fleet.ids[tk["robot"]] if tk["robot"] is not None else None, fleet.L.station_names[tk["station"]] if tk["station"] is not None else None,
             tk["assigned_t"], tk["picked_t"], tk["done_t"], tk["source"], tk["bumped"]) for k, tk in fleet.tasks.items()])
    upsert(c, "route_plans", ["tenant_id", "robot_id", "start_s", "path", "legs", "planner"], ["tenant_id", "robot_id"],
           [(tid, fleet.ids[r], max(t, fleet.plan_t0[r]), fleet.plan[r][max(0, t - fleet.plan_t0[r]):][:600] or fleet.plan[r][-1:],
             Jsonb([{k: v for k, v in lg.items()} for lg in fleet.legs[r]]), engine.PLANNER_VERSION) for r in range(fleet.R)])
    db.load(c, "task_assignments", ["tenant_id", "task_id", "robot_id", "station", "policy", "solver_version", "epoch_s", "inputs_hash"],
            [(tid, k, rid, st, pol, engine.VERSIONS.get(pol, pol), et, h) for et, k, rid, st, pol, h in fleet.assign_log[marks["assign"]:]])
    rows = [(tid, r["t"], "replan", [], None, Jsonb({k: v for k, v in r.items() if k != "paths"})) for r in fleet.stats["repairs"][marks["repairs"]:]
            if r["reason"] != "retry"]
    rows += [(tid, v[0], v[1], v[2], v[3], Jsonb({})) for v in floor.violations[marks["violations"]:]]
    db.load(c, "conflicts", ["tenant_id", "sim_t", "kind", "robots", "node", "detail"], rows)
    db.load(c, "world_events", ["tenant_id", "sim_t", "kind", "detail"],
            [(tid, e["t"], e["kind"], Jsonb(e)) for e in fleet.stats["events"][marks["events"]:]])
    for i, name in enumerate(fleet.L.charger_names):
        occ = fleet.occupant[i]
        c.execute("UPDATE chargers SET status = %s, occupant = %s WHERE id = %s", ["up" if fleet.charger_up[i] else "fault", fleet.ids[occ] if occ is not None else None, name])
    closed = sorted(set(fleet.closed.values()))
    c.execute("UPDATE zones SET status = CASE WHEN id = ANY(%s) THEN 'closed' ELSE 'open' END, observed_at = %s WHERE kind = 'aisle' AND (status = 'closed' OR id = ANY(%s))",
              [closed, at(t), closed])


def marks_of(floor, fleet):
    return {"assign": len(fleet.assign_log), "repairs": len(fleet.stats["repairs"]), "violations": len(floor.violations), "events": len(fleet.stats["events"])}


# --- loading the warehouse ------------------------------------------------------------------------------------------------
class LoadIn(BaseModel):
    seed: int = Field(7, ge=1, le=10 ** 6)


@app.post("/v1/warehouse:load", status_code=202, tags=["warehouse"], summary="(+) Load the synthetic warehouse: its graph, 250 robots with vendor profiles and their battery cycle histories; fit and register the battery model against its baseline")
def load_warehouse(body: LoadIn, ctx: Ctx = Depends(auth("warehouse:load")), idem: str | None = IdemKey):
    def work(c):
        if c.execute("SELECT 1 FROM warehouses").fetchone():
            raise Problem(409, "warehouse_exists", "this tenant already has a warehouse; `make reset` for a fresh demo")
        return 202, jobs.enqueue(c, ctx, "warehouse.load", body.model_dump())
    return run(ctx, idem, body, work)


def histories_of(rows):
    out = defaultdict(list)
    for rid, _, day, dod, temp, cap in rows:
        out[rid].append((day, dod, temp, cap))
    return out


@jobs.handler("warehouse.load")
def load_job(c, job):
    t, seed = job["tenant_id"], job["payload"]["seed"]
    wid = uuid.uuid5(t, "warehouse")
    L = world.Layout()
    robots = world.fleet(seed, L)
    rows, soh_true = world.battery_history(seed, robots)
    H = histories_of(rows)
    nominal = {r["id"]: r["capacity_wh"] for r in robots}
    vendor = {r["id"]: r["vendor"] for r in robots}
    age = {r["id"]: r["days"] for r in robots}
    fit = engine.fit_batteries(H, nominal, vendor, age)
    backtest = engine.battery_backtest(H, nominal, vendor, age)
    soh_est = {r: engine.forecast_soh(p, 0) for r, p in fit.items()}
    floor = world.Floor(L, robots, soh_true, seed)
    fleet = engine.Fleet(L, robots, "cpsat", soh_est)
    for i, r in enumerate(robots):
        fleet.soc[i] = r["soc"]
    c.execute("""INSERT INTO warehouses (id, tenant_id, external_ref, name, metadata, seed, world_state, fleet_state)
                 VALUES (%s,%s,'LFC-1','Larkfield Fulfilment Centre',%s,%s,%s,%s)""",
              [wid, t, Jsonb({**L.params, "width": L.W, "height": L.H, "cells": L.n, "pick_cells": len(L.picks), "cell_m": world.CELL_M}), seed,
               pickle.dumps(floor, protocol=5), pickle.dumps(fleet, protocol=5)])
    zones = sorted(set(L.zone))
    db.load(c, "zones", ["tenant_id", "id", "warehouse_id", "kind", "attributes"],
            [(t, z, wid, zone_kind(z), Jsonb({"cells": L.zone.count(z)})) for z in zones])
    db.load(c, "nodes", ["tenant_id", "id", "x", "y", "kind", "zone_id"], [(t, i, x, y, L.kind[i], L.zone[i]) for i, (x, y) in enumerate(L.xy)])
    db.load(c, "edges", ["tenant_id", "src", "dst"], [(t, a, b) for a, b in L.edges()])
    db.load(c, "robots", ["tenant_id", "id", "vendor", "home_node", "capacity_wh", "commissioned_on"],
            [(t, r["id"], r["vendor"], r["home"], r["capacity_wh"], (START - datetime.timedelta(days=r["days"])).date()) for r in robots])
    db.load(c, "chargers", ["tenant_id", "id", "node"], [(t, n, cell) for n, cell in zip(L.charger_names, L.chargers)])
    db.load(c, "battery_cycles", ["tenant_id", "robot_id", "cycle", "ended_at", "dod", "temp_c", "capacity_wh"],
            [(t, rid, k, at(day * 86400), round(dod, 4), round(temp, 2), round(cap, 2)) for rid, k, day, dod, temp, cap in rows])
    version = f"{engine.BATTERY_VERSION}+{str(wid)[:8]}"
    snapshot = f"{len(rows)} cycles of {len(robots)} packs up to {START.date()}, seed {seed}; backtest holds out the last 120 days"
    c.execute("INSERT INTO model_artifacts (tenant_id, name, version, data_snapshot, metrics, artifact, approved) VALUES (%s,'battery-soh',%s,%s,%s,%s,true)",
              [t, version, snapshot, Jsonb(backtest), pickle.dumps(fit)])
    for name, v in (("task-assignment", engine.VERSIONS["cpsat"]), ("multi-agent-planner", engine.PLANNER_VERSION)):
        c.execute("INSERT INTO model_artifacts (tenant_id, name, version, data_snapshot, metrics, approved) VALUES (%s,%s,%s,'none (a solver, not a fitted model)',%s,true)",
                  [t, name, v, Jsonb({"evaluated_by": "python -m wh.evaluate (held-out warehouses and waves)"})])
    db.load(c, "model_runs", ["tenant_id", "model_name", "version", "subject", "inputs_hash", "result"],
            [(t, "battery-soh", version, f"robot:{r}", hashlib.sha256(json.dumps([p["stress_now"], p["age_years"], p["cycles"]]).encode()).hexdigest()[:16],
              Jsonb({"soh": round(soh_est[r], 4), "days_to_eol": engine.days_to_eol(p)})) for r, p in fit.items()])
    persist(c, {"tenant_id": t}, floor, fleet, marks_of(floor, fleet))
    by_vendor = defaultdict(int)
    for r in robots:
        by_vendor[r["vendor"]] += 1
    eol = sorted(((engine.days_to_eol(p), r) for r, p in fit.items() if engine.days_to_eol(p) is not None and engine.days_to_eol(p) <= 180))
    audit.record(c, worker_ctx(job), "warehouse.loaded", "warehouse", wid, {"robots": len(robots), "cells": L.n, "battery_model": version})
    return {"warehouse_id": wid, "cells": L.n, "edges": len(L.edges()), "width_m": round(L.W * world.CELL_M), "depth_m": round(L.H * world.CELL_M),
            "aisles": len(L.aisles), "pick_cells": len(L.picks), "stations": len(L.stations), "chargers": len(L.chargers), "robots": len(robots),
            "robots_by_vendor": dict(sorted(by_vendor.items())), "battery_cycles": len(rows), "battery_model": {"version": version, **backtest},
            "eol_within_180_days": [{"robot": r, "days": d, "soh": round(soh_est[r], 4)} for d, r in eol],
            "soh_mean": round(sum(soh_est.values()) / len(soh_est), 4), "below_low_soc": sum(r["soc"] < engine.LOW_SOC for r in robots)}


# --- the clock moves -----------------------------------------------------------------------------------------------------------
class Inject(BaseModel):
    kind: Literal["aisle_blocked", "charger_fault"]
    zone: str | None = Field(None, description="an aisle, e.g. C-14 (aisle_blocked)")
    charger: str | None = Field(None, description="e.g. CH-05 (charger_fault)")
    after_s: int = Field(0, ge=0, le=900)
    duration_s: int | None = Field(None, ge=1, le=7200, description="omit for the rest of the shift")


class Wave(BaseModel):
    orders_per_hour: int = Field(ge=0, le=20000)


class AdvanceIn(BaseModel):
    seconds: int = Field(ge=1, le=900)
    wave: Wave | None = None
    inject: list[Inject] = Field(default_factory=list, max_length=6)


def check_inject(L, inject, seconds):
    for e in inject:
        if e.kind == "aisle_blocked" and e.zone not in L.aisles:
            raise Problem(422, "unknown_aisle", f"{e.zone!r} is not an aisle")
        if e.kind == "charger_fault" and e.charger not in L.charger_names:
            raise Problem(422, "unknown_charger", f"{e.charger!r} is not a charger")
        if e.after_s >= seconds:
            raise Problem(422, "event_after_window", "after_s must fall inside the window being run")


@app.post("/v1/fleet:advance", status_code=202, tags=["fleet"], summary="(+) Run the floor forward. The generator can be told an order rate and events (an aisle blocked, a charger failing); the orchestrator sees orders, closures and faults only as they happen")
def advance(body: AdvanceIn, ctx: Ctx = Depends(auth("fleet:advance")), idem: str | None = IdemKey):
    def work(c):
        warehouse(c)
        check_inject(layout(), body.inject, body.seconds)
        return 202, jobs.enqueue(c, ctx, "fleet.advance", body.model_dump())
    return run(ctx, idem, body, work)


def tell(floor, inject):
    told = []
    for e in inject:
        ev = {"kind": e["kind"], "at": floor.t + e["after_s"], "until": floor.t + e["after_s"] + e["duration_s"] if e.get("duration_s") else None}
        ev.update({"zone": e["zone"]} if e["kind"] == "aisle_blocked" else {"charger": e["charger"]})
        told.append(ev)
    floor.tell(told)
    return told


@jobs.handler("fleet.advance")
def advance_job(c, job):
    p = job["payload"]
    w, floor, fleet = state(c, lock=True)
    marks = marks_of(floor, fleet)
    if p.get("wave"):
        wid = (floor.wave or {}).get("id", 0) + 1
        floor.set_wave(p["wave"]["orders_per_hour"], wid)
    told = tell(floor, p.get("inject") or [])
    engine.sync(floor, fleet)
    m = engine.simulate(floor, fleet, p["seconds"])                # ends with the fleet's view at the floor's clock
    persist(c, w, floor, fleet, marks)
    events = fleet.stats["events"][marks["events"]:]
    audit.record(c, worker_ctx(job), "fleet.advanced", "warehouse", w["id"],
                 {"seconds": p["seconds"], "to_s": floor.t, "completed": m["orders_completed"], "collisions": m["collisions"], "events": len(events)})
    return {**m, "clock": at(floor.t), "events": events, "chargers": charger_view(fleet),
            "simulation_truth": {"told": told, "wave": floor.wave, "note": "what the generator was told; the planner never reads this"}}


# --- fleet state, map ------------------------------------------------------------------------------------------------------------
def charger_view(fleet):
    queue = sorted((r for r in range(fleet.R) if fleet.status[r] == "charge_wait"), key=lambda r: fleet.soc[r])
    return {"chargers": [{"id": n, "xy": xy(fleet, cell), "status": "up" if fleet.charger_up[i] else "fault",
                          "occupant": fleet.ids[fleet.occupant[i]] if fleet.occupant[i] is not None else None,
                          "incoming": fleet.ids[fleet.target[i]] if fleet.target[i] is not None else None}
                         for i, (n, cell) in enumerate(zip(fleet.L.charger_names, fleet.L.chargers))],
            "queue": [{"robot": fleet.ids[r], "soc": round(fleet.soc[r], 3)} for r in queue]}


def kpis(fleet, t, window=300):
    tasks = fleet.tasks.values()
    done = [tk for tk in tasks if tk["status"] == "done"]
    recent = [tk for tk in done if tk["done_t"] > t - window]
    return {"orders": len(fleet.tasks), "completed": len(done), "on_time": sum(tk["done_t"] <= tk["due"] for tk in done),
            "sla_hit_rate": round(sum(tk["done_t"] <= tk["due"] for tk in done) / len(done), 4) if done else None,
            "throughput_last_5min_per_hour": round(len(recent) * 3600 / min(window, max(1, t))),
            "open": sum(tk["status"] == "open" for tk in tasks), "in_progress": sum(tk["status"] in ("assigned", "picked") for tk in tasks),
            "held": sum(tk["status"] == "held" for tk in tasks), "overdue": sum(tk["status"] != "done" and tk["due"] < t for tk in tasks)}


@app.get("/v1/fleet/state", tags=["fleet"], summary="Every robot's cell, status, charge and task; chargers and their queue; closed aisles; order KPIs; telemetry freshness; and the robots standing in the busiest aisle cells")
def fleet_state(ctx: Ctx = Depends(auth("fleet:read"))):
    with db.tx(ctx.tenant_id) as c:
        w, floor, fleet = state(c)
    t, L = floor.t, fleet.L
    robots = [{"id": fleet.ids[r], "xy": xy(fleet, fleet.cell[r]), "status": "waiting" if fleet.waiting[r] else fleet.status[r],
               "soc": round(fleet.soc[r], 3), "soh": round(fleet.soh[r], 3), "task": fleet.task[r], "vendor": fleet.vendor[r]} for r in range(fleet.R)]
    counts = defaultdict(int)
    for x in robots:
        counts[x["status"]] += 1
    busy = []
    for r in range(fleet.R):
        c0 = fleet.cell[r]
        if L.kind[c0] == "aisle" and r not in fleet.paused and fleet.status[r] == "task":
            users = fleet.res.users_after(c0, t, r)
            if users:
                busy.append({"robot": fleet.ids[r], "xy": xy(fleet, c0), "location": L.location(c0), "robots_due_through": len(users)})
    busy.sort(key=lambda b: (-b["robots_due_through"], b["robot"]))
    ages = [t - s for s in fleet.seen_t]
    return jsonable_encoder({"clock_s": t, "clock": at(t), "robots": robots, "status_counts": dict(sorted(counts.items())),
                             "chargers": charger_view(fleet), "closed_aisles": sorted(set(fleet.closed.values())),
                             "paused": [fleet.ids[r] for r in sorted(fleet.paused)], "kpis": kpis(fleet, t), "in_aisles": busy[:8],
                             "telemetry": {"max_age_s": max(ages), "note": "simulated seconds since each robot's last report; the floor reports every second"},
                             "state_version": w["state_version"]})


@app.get("/v1/warehouse/map", tags=["warehouse"], summary="(+) The layout: one character per cell, zones, pack stations and chargers")
def warehouse_map(ctx: Ctx = Depends(auth("fleet:read"))):
    with db.tx(ctx.tenant_id) as c:
        w, floor, fleet = state(c)
    L = fleet.L
    return {"width": L.W, "height": L.H, "cell_m": world.CELL_M, "grid": L.grid(), "legend": {"#": "rack", "a": "aisle (pick faces)", "x": "cross-aisle or highway",
            "l": "parking lane", "b": "robot bay", "c": "charger", "s": "pack station", " ": "wall"},
            "stations": [{"id": n, "xy": xy(fleet, cell)} for n, cell in zip(L.station_names, L.stations)],
            "chargers": [{"id": n, "xy": xy(fleet, cell)} for n, cell in zip(L.charger_names, L.chargers)],
            "aisles": {z: [xy(fleet, cs[0]), xy(fleet, cs[-1])] for z, cs in sorted(L.aisles.items())}, "metadata": w["metadata"]}


# --- tasks from the WMS --------------------------------------------------------------------------------------------------------
class TaskIn(BaseModel):
    id: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")
    location: str = Field(min_length=3, max_length=20, description="aisle and position, e.g. A-14-07")
    priority: Literal["normal", "urgent"] = "normal"
    due_in_s: int | None = Field(None, ge=30, le=86400, description="default: the priority's SLA")


class TasksIn(BaseModel):
    tasks: list[TaskIn] = Field(min_length=1, max_length=50)


@app.post("/v1/tasks", status_code=201, tags=["tasks"], summary="Tasks from the WMS: a pick location, a priority and a due time. Each is validated on its own; accepted tasks join the queue the dispatcher assigns from every few seconds")
def create_tasks(body: TasksIn, ctx: Ctx = Depends(auth("tasks:create")), idem: str | None = IdemKey):
    def work(c):
        w, floor, fleet = state(c, lock=True)
        marks = marks_of(floor, fleet)
        t = engine.sync(floor, fleet)
        accepted, refused = [], []
        for tk in body.tasks:
            cell = fleet.L.cell_of_location(tk.location)
            why = ("task id already exists" if tk.id in fleet.tasks else
                   f"unknown location {tk.location}" if cell is None else None)
            if why:
                refused.append({"id": tk.id, "why": why})
                continue
            sla = tk.due_in_s or (world.SLA_URGENT_S if tk.priority == "urgent" else world.SLA_NORMAL_S)
            fleet.add_task({"id": tk.id, "pick": cell, "priority": tk.priority, "released": t, "due": t + sla}, source="api")
            row = fleet.tasks[tk.id]
            accepted.append({"id": tk.id, "location": tk.location, "priority": tk.priority, "released_s": t, "due_s": t + sla, "status": row["status"],
                             "note": "held: its aisle is closed" if row["status"] == "held" else None})
        if accepted:
            persist(c, w, floor, fleet, marks)
        audit.record(c, ctx, "tasks.created", "task", ",".join(a["id"] for a in accepted) or "-", {"accepted": len(accepted), "refused": refused})
        return 201, {"accepted": accepted, "refused": refused, "clock_s": t}
    return run(ctx, idem, body, work)


@app.get("/v1/tasks", tags=["tasks"], summary="(+) Tasks by status and priority")
def list_tasks(status: Literal["open", "assigned", "picked", "done", "held", "all"] = "all", priority: Literal["normal", "urgent", "all"] = "all",
               limit: int = Query(100, ge=1, le=1000), ctx: Ctx = Depends(auth("fleet:read"))):
    with db.tx(ctx.tenant_id) as c:
        warehouse(c)
        rows = c.execute("""SELECT id, location, priority, status, released_s, due_s, robot_id, station, assigned_s, picked_s, done_s, source, bumped
                              FROM tasks WHERE (%s = 'all' OR status = %s) AND (%s = 'all' OR priority = %s)
                             ORDER BY priority = 'urgent' DESC, released_s DESC, id LIMIT %s""", [status, status, priority, priority, limit]).fetchall()
    return jsonable_encoder({"items": rows})


# --- traffic control: pause and resume -----------------------------------------------------------------------------------------
class PauseIn(BaseModel):
    reason: str = Field("operator stop", min_length=3, max_length=200)


def repair_view(fleet, rec):
    out = {k: v for k, v in rec.items() if k != "paths"}
    if "paths" in rec:
        out["paths"] = {rid: {k: [xy(fleet, c) for c in v] for k, v in p.items()} for rid, p in rec["paths"].items()}
    return out


@app.post("/v1/robots/{robot_id}/pause", tags=["robots"], summary="Stop a robot where it stands. It becomes an obstacle; every robot whose plan crosses its cell is re-planned at once (prioritized, or jointly by CBS when few), and the latency is reported")
def pause(robot_id: str, body: PauseIn, ctx: Ctx = Depends(auth("robots:pause")), idem: str | None = IdemKey):
    def work(c):
        w, floor, fleet = state(c, lock=True)
        r = robot_index(fleet, robot_id)
        if r in fleet.paused:
            raise Problem(409, "already_paused")
        marks = marks_of(floor, fleet)
        t = engine.sync(floor, fleet)
        floor.pause(r)
        rec = fleet.pause(r, t)
        persist(c, w, floor, fleet, marks)
        audit.record(c, ctx, "robot.paused", "robot", robot_id, {"reason": body.reason, "replanned": rec["robots"], "ms": rec["ms"], "method": rec["method"]})
        return 200, {"robot": robot_id, "xy": xy(fleet, fleet.cell[r]), "clock_s": t, "planner": engine.PLANNER_VERSION,
                     "affected": sorted(rec.get("paths", {})), **repair_view(fleet, rec)}
    return run(ctx, idem, body, work)


@app.post("/v1/robots/{robot_id}/resume", tags=["robots"], summary="(+) Release a paused robot; it is re-planned from where it stands")
def resume(robot_id: str, ctx: Ctx = Depends(auth("robots:pause")), idem: str | None = IdemKey):
    def work(c):
        w, floor, fleet = state(c, lock=True)
        r = robot_index(fleet, robot_id)
        if r not in fleet.paused:
            raise Problem(409, "not_paused")
        marks = marks_of(floor, fleet)
        t = engine.sync(floor, fleet)
        floor.pause(r, False)
        rec = fleet.resume(r, t)
        persist(c, w, floor, fleet, marks)
        audit.record(c, ctx, "robot.resumed", "robot", robot_id, {"ms": rec["ms"]})
        return 200, {"robot": robot_id, "clock_s": t, **repair_view(fleet, rec)}
    return run(ctx, idem, {}, work)


@app.get("/v1/robots/{robot_id}", tags=["robots"], summary="(+) One robot: state, the next minute of its plan, its battery's measured capacity and the fade forecast against the baseline")
def robot_detail(robot_id: str, ctx: Ctx = Depends(auth("fleet:read"))):
    with db.tx(ctx.tenant_id) as c:
        w, floor, fleet = state(c)
        r = robot_index(fleet, robot_id)
        cyc = c.execute("SELECT cycle, ended_at, dod, temp_c, capacity_wh FROM battery_cycles WHERE robot_id = %s ORDER BY cycle", [robot_id]).fetchall()
        fit = pickle.loads(c.execute("SELECT artifact FROM model_artifacts WHERE name = 'battery-soh'").fetchone()["artifact"])
    t = floor.t
    nominal = fleet.nominal_wh[r]
    p = fit.get(robot_id)
    hist = [(((x["ended_at"] - START).total_seconds() / 86400), x["dod"], x["temp_c"], x["capacity_wh"]) for x in cyc]
    step = max(1, len(cyc) // 120)
    forecast = [{"day": d, "soh": round(engine.forecast_soh(p, d), 4), "baseline": round(engine.baseline_soh(hist, nominal, d), 4)} for d in range(0, 361, 30)] if p else []
    return jsonable_encoder({"robot": robot_id, "vendor": fleet.vendor[r], "status": "waiting" if fleet.waiting[r] else fleet.status[r], "xy": xy(fleet, fleet.cell[r]),
                             "soc": round(fleet.soc[r], 3), "task": fleet.task[r], "plan_next_60s": [xy(fleet, fleet.expected(r, tt)) for tt in range(t, t + 60)],
                             "legs": [{"kind": lg["kind"], "goal": xy(fleet, lg["goal"]) if lg.get("goal") is not None else None, "arr": lg.get("arr")} for lg in fleet.legs[r]],
                             "battery": {"nominal_wh": nominal, "soh": round(fleet.soh[r], 4), "cycles": len(cyc), "days_to_eol": engine.days_to_eol(p) if p else None,
                                         "measured": [{"day": round(h[0], 1), "soh": round(h[3] / nominal, 4)} for h in hist[::step]], "forecast": forecast,
                                         "model": engine.BATTERY_VERSION}})


@app.get("/v1/batteries", tags=["batteries"], summary="(+) The fleet's state of health, packs forecast to reach end of life (80%), and how the fade model scored against each pack's own trend")
def batteries(horizon_days: int = Query(180, ge=30, le=1000), ctx: Ctx = Depends(auth("fleet:read"))):
    with db.tx(ctx.tenant_id) as c:
        w, floor, fleet = state(c)
        art = c.execute("SELECT version, metrics, artifact, data_snapshot FROM model_artifacts WHERE name = 'battery-soh'").fetchone()
    fit = pickle.loads(art["artifact"])
    rows = []
    for rid, p in fit.items():
        d = engine.days_to_eol(p)
        rows.append({"robot": rid, "vendor": fleet.vendor[fleet.index[rid]], "soh": round(engine.forecast_soh(p, 0), 4),
                     "soh_in_horizon": round(engine.forecast_soh(p, horizon_days), 4), "days_to_eol": d, "cycles": p["cycles"]})
    rows.sort(key=lambda x: x["soh_in_horizon"])
    vendors = defaultdict(list)
    for x in rows:
        vendors[x["vendor"]].append(x["soh"])
    return {"model": art["version"], "data_snapshot": art["data_snapshot"], "backtest": art["metrics"], "horizon_days": horizon_days,
            "eol": [x for x in rows if x["days_to_eol"] is not None and x["days_to_eol"] <= horizon_days],
            "by_vendor": {v: {"packs": len(s), "soh_mean": round(sum(s) / len(s), 4), "soh_min": round(min(s), 4)} for v, s in sorted(vendors.items())},
            "lowest": rows[:12]}


# --- plans: recompute with a person in the loop --------------------------------------------------------------------------------
class RecomputeIn(BaseModel):
    horizon_s: int = Field(240, ge=60, le=600)
    allow_preemption: bool = True


@app.post("/v1/plans/recompute", status_code=202, tags=["plans"], summary="Recompute for the open urgent orders: project the current plan and a preemptive one (robots taken off ordinary picks) forward on a copy of the floor that knows no future orders, compare urgent and bumped orders' completion, recommend one. A plan that takes robots off their tasks becomes a proposal a shift manager must approve")
def recompute(body: RecomputeIn, ctx: Ctx = Depends(auth("plans:recompute")), idem: str | None = IdemKey):
    def work(c):
        warehouse(c)
        return 202, jobs.enqueue(c, ctx, "plans.recompute", body.model_dump())
    return run(ctx, idem, body, work)


def summary(proj, ids):
    rows = [x for x in proj["tasks"] if x["id"] in ids]
    done = [x["done_t"] for x in rows if x["done_t"] is not None]
    return {"on_time": sum(x["on_time"] for x in rows), "of": len(rows), "late_s_total": sum(x["late_by"] for x in rows),
            "last_done_s": max(done) if len(done) == len(rows) and rows else None}


@jobs.handler("plans.recompute")
def recompute_job(c, job):
    p = job["payload"]
    w, floor, fleet = state(c, lock=True)                       # its own copy: sync() moves the fleet's view to the floor's clock
    t = engine.sync(floor, fleet)
    urgent = sorted(k for k, tk in fleet.tasks.items() if tk["priority"] == "urgent" and tk["status"] == "open")
    if not urgent:
        return {"clock_s": t, "urgent_open": [], "recommended": "keep", "needs_approval": False, "note": "no open urgent orders; the current plan stands"}
    t0 = datetime.datetime.now()
    pairs = engine.preemption(fleet, t, urgent) if p["allow_preemption"] else []
    bumped = [b for *_, b in pairs if b]
    keep = engine.project(floor, fleet, p["horizon_s"], urgent + bumped)
    alt = engine.project(floor, fleet, p["horizon_s"], urgent + bumped, change=lambda fl: engine.apply_preemption(fl, t, engine.preemption(fl, t, urgent))) if pairs else None
    ms = round((datetime.datetime.now() - t0).total_seconds() * 1000)
    inputs = hashlib.sha256(json.dumps([t, urgent, [fleet.cell[r] for r in range(fleet.R)]]).encode()).hexdigest()[:16]
    alts = [{"name": "keep the current plan", "kind": "keep", "urgent": summary(keep, urgent), "bumped": summary(keep, bumped), "projection": keep}]
    if alt:
        alts.append({"name": f"preempt: take {len(bumped)} robot{'s' if len(bumped) != 1 else ''} off ordinary picks", "kind": "preempt",
                     "urgent": summary(alt, urgent), "bumped": summary(alt, bumped), "projection": alt,
                     "assignments": [{"robot": fleet.ids[r], "task": k, "station": fleet.L.station_names[s], "bumps": b} for r, k, s, b in pairs]})
    better = alt and (alts[1]["urgent"]["on_time"] > alts[0]["urgent"]["on_time"] or
                      (alts[1]["urgent"]["on_time"] == alts[0]["urgent"]["on_time"] and alts[1]["urgent"]["late_s_total"] + 10 < alts[0]["urgent"]["late_s_total"]))
    rec = alts[1] if better else alts[0]
    needs = bool(better and bumped)
    out = {"clock_s": t, "horizon_s": p["horizon_s"], "urgent_open": urgent, "alternatives": alts, "recommended": rec["kind"], "needs_approval": needs,
           "policy": "a plan that takes robots off their tasks needs a shift manager's approval; the proposer cannot approve it",
           "how": "both alternatives run forward on a copy of the floor with the same planner; the copy knows no future orders or events",
           "solver": engine.VERSIONS["cpsat"], "inputs_hash": inputs, "ms": ms}
    c.execute("INSERT INTO model_runs (tenant_id, model_name, version, subject, inputs_hash, result) VALUES (%s,'preemption',%s,%s,%s,%s)",
              [w["tenant_id"], engine.VERSIONS["cpsat"], f"urgent:{','.join(urgent)}", inputs, Jsonb({"recommended": rec["kind"], "bumped": bumped})])
    if better and not bumped:                                   # better and harmless: bounded automation applies it now
        marks = marks_of(floor, fleet)
        out["applied"] = engine.apply_preemption(fleet, t, [(fleet.index[a["robot"]], a["task"], fleet.L.station_names.index(a["station"]), None) for a in rec["assignments"]])
        persist(c, w, floor, fleet, marks)
    elif needs:
        did = uuid.uuid4()
        c.execute("INSERT INTO decisions (id, tenant_id, kind, proposal, state_version, proposed_by) VALUES (%s,%s,'preemption',%s,%s,%s)",
                  [did, w["tenant_id"], Jsonb(jsonable_encoder({"assignments": rec["assignments"], "urgent": urgent, "bumped": bumped,
                                                                "urgent_on_time": [a["urgent"]["on_time"] for a in alts], "clock_s": t})),
                   w["state_version"], uuid.UUID(p["actor_id"])])
        out["decision_id"] = did
        out["status"] = "proposed"
    audit.record(c, worker_ctx(job), "plan.recomputed", "plan", out.get("decision_id", inputs), {"recommended": rec["kind"], "needs_approval": needs, "urgent": len(urgent)})
    return out


@app.post("/v1/decisions/{decision_id}/approve", tags=["plans"], summary="(+) A shift manager approves or rejects a proposed plan; the proposer cannot. Approval applies it only if the floor has not moved since it was computed")
def approve(decision_id: uuid.UUID, decision: Literal["approved", "rejected"] = "approved", ctx: Ctx = Depends(auth("decisions:approve")), idem: str | None = IdemKey):
    def work(c):
        d = c.execute("SELECT * FROM decisions WHERE id = %s FOR UPDATE", [decision_id]).fetchone()
        if not d:
            raise Problem(404, "decision_not_found")
        if d["status"] != "proposed":
            raise Problem(409, "already_decided", f"this decision is {d['status']}")
        if d["proposed_by"] == ctx.actor_id:
            raise Problem(403, "proposer_cannot_approve", "a plan that takes robots off their tasks needs a second person")
        w, floor, fleet = state(c, lock=True)
        if decision == "approved" and w["state_version"] != d["state_version"]:
            c.execute("UPDATE decisions SET status = 'stale', decided_by = %s, decided_at = now() WHERE id = %s", [ctx.actor_id, decision_id])
            audit.record(c, ctx, "plan.stale", "decision", decision_id, {})
            return 409, {"type": "https://errors.example/plan_stale", "title": "plan stale", "status": 409, "code": "plan_stale",     # committed, not raised
                         "detail": "the floor has moved since this plan was computed; recompute"}
        applied = []
        if decision == "approved":
            marks = marks_of(floor, fleet)
            t = engine.sync(floor, fleet)
            pr = d["proposal"]
            applied = engine.apply_preemption(fleet, t, [(fleet.index[a["robot"]], a["task"], fleet.L.station_names.index(a["station"]), a["bumps"]) for a in pr["assignments"]])
            persist(c, w, floor, fleet, marks)
        c.execute("UPDATE decisions SET status = %s, decided_by = %s, decided_at = now() WHERE id = %s", [decision, ctx.actor_id, decision_id])
        audit.record(c, ctx, f"plan.{decision}", "decision", decision_id, {"applied": len(applied)})
        return 200, {"decision_id": decision_id, "status": decision,
                     "applied": [{"robot": r, "task": k, "bumped": b} for r, k, b in applied]}
    return run(ctx, idem, {"decision": decision}, work)


@app.get("/v1/decisions", tags=["plans"], summary="(+) Proposed and decided plans")
def decisions(ctx: Ctx = Depends(auth("fleet:read"))):
    with db.tx(ctx.tenant_id) as c:
        return jsonable_encoder({"items": c.execute("SELECT id, kind, status, proposed_by, decided_by, created_at, decided_at, proposal FROM decisions ORDER BY created_at DESC").fetchall()})


# --- simulation ------------------------------------------------------------------------------------------------------------------
class SimEvent(BaseModel):
    kind: Literal["aisle_blocked", "charger_fault"]
    zone: str | None = None
    charger: str | None = None
    after_s: int = Field(0, ge=0, le=3600)
    duration_s: int | None = Field(None, ge=1, le=7200)


class SimulationIn(BaseModel):
    seconds: int = Field(420, ge=60, le=1800)
    orders_per_hour: int = Field(9000, ge=0, le=20000)
    policies: list[Literal["fifo", "greedy", "cpsat"]] = Field(default_factory=lambda: ["fifo", "cpsat"], min_length=1, max_length=3)
    events: list[SimEvent] = Field(default_factory=list, max_length=6)
    seed: int | None = Field(None, ge=1, le=10 ** 6, description="default: this warehouse's seed (same layout, robots and order stream)")

    @field_validator("policies")
    @classmethod
    def distinct(cls, v):
        if len(set(v)) != len(v):
            raise ValueError("policies must be distinct")
        return v


@app.post("/v1/simulations", status_code=202, tags=["simulation"], summary="Run the same shift start, order stream and events in a sandbox under each assignment policy (FIFO nearest-free, greedy best-pair, CP-SAT), with the same planner and collision checker, and compare distance, throughput, SLA and collisions")
def simulations(body: SimulationIn, ctx: Ctx = Depends(auth("simulations:run")), idem: str | None = IdemKey):
    def work(c):
        warehouse(c)
        check_inject(layout(), body.events, body.seconds)
        return 202, jobs.enqueue(c, ctx, "simulation.run", body.model_dump())
    return run(ctx, idem, body, work)


@jobs.handler("simulation.run")
def simulation_job(c, job):
    p = job["payload"]
    w = warehouse(c)
    seed = p.get("seed") or w["seed"]
    fit = pickle.loads(c.execute("SELECT artifact FROM model_artifacts WHERE name = 'battery-soh'").fetchone()["artifact"])
    soh_est = {r: engine.forecast_soh(q, 0) for r, q in fit.items()}
    out = {}
    for pol in p["policies"]:
        floor, fleet = engine.new_world(seed, policy=pol, soh_est=soh_est)
        floor.set_wave(p["orders_per_hour"], 1)
        tell(floor, p["events"])
        m = engine.simulate(floor, fleet, p["seconds"])
        out[pol] = {k: v for k, v in m.items() if k not in ("repairs", "violations")}
    base = out.get("fifo")
    comparison = {}
    if base:
        for pol, m in out.items():
            if pol != "fifo" and base["cells_per_order"] and m["cells_per_order"]:
                comparison[pol] = {"distance_per_order_vs_fifo": round(m["cells_per_order"] / base["cells_per_order"] - 1, 4),
                                   "throughput_vs_fifo": round(m["throughput_per_hour"] / max(1, base["throughput_per_hour"]) - 1, 4)}
    sid = uuid.uuid4()
    result = {"simulation_id": sid, "seed": seed, "seconds": p["seconds"], "orders_per_hour": p["orders_per_hour"], "events": p["events"], "policies": out,
              "comparison": comparison, "versions": {**{k: engine.VERSIONS[k] for k in p["policies"]}, "planner": engine.PLANNER_VERSION},
              "how": "each policy runs the same shift start, order stream and events (same seed), with the same planner and collision checker; only the assignment differs"}
    c.execute("INSERT INTO simulation_runs (id, tenant_id, request, result, created_by) VALUES (%s,%s,%s,%s,%s)",
              [sid, w["tenant_id"], Jsonb(p), Jsonb(jsonable_encoder({**result, "policies": {k: {kk: vv for kk, vv in v.items() if kk != "heat"} for k, v in out.items()}})),
               uuid.UUID(p["actor_id"])])
    audit.record(c, worker_ctx(job), "simulation.ran", "simulation_run", sid, {"policies": p["policies"], "seconds": p["seconds"]})
    return result


@app.get("/v1/simulations/{sim_id}", tags=["simulation"], summary="(+) A stored simulation run")
def simulation(sim_id: uuid.UUID, ctx: Ctx = Depends(auth("fleet:read"))):
    with db.tx(ctx.tenant_id) as c:
        row = c.execute("SELECT id, request, result, created_at FROM simulation_runs WHERE id = %s", [sim_id]).fetchone()
    if not row:
        raise Problem(404, "simulation_not_found")
    return jsonable_encoder(row)


@app.get("/v1/conflicts", tags=["fleet"], summary="(+) Conflicts the planner resolved by replanning (with method and latency) and any the collision checker found")
def conflicts(kind: Literal["replan", "violation", "all"] = "all", limit: int = Query(50, ge=1, le=500), ctx: Ctx = Depends(auth("fleet:read"))):
    with db.tx(ctx.tenant_id) as c:
        warehouse(c)
        rows = c.execute("""SELECT sim_t, kind, robots, node, detail FROM conflicts
                             WHERE %s = 'all' OR (%s = 'replan' AND kind = 'replan') OR (%s = 'violation' AND kind <> 'replan')
                             ORDER BY id DESC LIMIT %s""", [kind, kind, kind, limit]).fetchall()
        counts = c.execute("SELECT kind, count(*) AS n FROM conflicts GROUP BY kind").fetchall()
    return jsonable_encoder({"items": rows, "counts": {r["kind"]: r["n"] for r in counts}})
