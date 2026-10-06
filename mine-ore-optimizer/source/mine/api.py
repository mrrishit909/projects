"""Public API (modular monolith). Blueprint services map to: geology-model (block model, assays, ore control), grade-estimator
(kriging with uncertainty), fleet-telemetry (the haul log and engine telemetry), maintenance-feed (engine anomalies and
breakdowns), dispatch-optimizer (the dispatch MIP and its baselines), blend-optimizer (hourly reclaim), plant-forecast (mill
throughput) and twin-simulator (the shift re-run under alternative plans). Not built: Kafka, TimescaleDB/ClickHouse, PostGIS,
CesiumJS, PyTorch; see the README.

    uvicorn mine.api:app          python -m core.jobs mine.api      # the worker
"""
import copy
import datetime
import functools
import math
import pickle
import time
import uuid
from typing import Literal

import numpy as np
from fastapi import Depends, Header, Query
from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from core import audit, db, jobs
from core.app import Ctx, Problem, create_app, run

from . import engine, world

READ = {"mine:read", "jobs:read"}
ENGINEER = READ | {"telemetry:ingest", "dispatch:optimize", "blends:solve", "twin:run", "plans:propose"}
PERMISSIONS = {"viewer": READ, "mine_engineer": ENGINEER,
               "shift_supervisor": ENGINEER | {"mine:load", "mine:advance", "decisions:approve", "audit:read"}}
app = create_app("mine-ore-optimizer", PERMISSIONS)
auth = app.state.auth
IdemKey = Header(None, alias="Idempotency-Key")
HISTORY_SHIFTS, TEST_FROM_SHIFT = 14, 10          # one week of day and night shifts; the last four score the models
START = datetime.datetime(2026, 9, 24, 6, 0, tzinfo=datetime.UTC)
PLANT = {"target_cu": world.TARGET_CU, "tol_cu": world.TOL_CU, "window": [round(world.TARGET_CU - world.TOL_CU, 2), round(world.TARGET_CU + world.TOL_CU, 2)],
         "as_limit_ppm": world.AS_LIMIT, "cu_price_usd_t": world.PRICE, "processing_usd_t": world.PROC_COST, "fuel_usd_l": world.FUEL_PRICE,
         "rehandle_usd_t": world.REHANDLE, "bin_t": world.BIN_T, "loader_tph": world.LOADER_TPH, "cutoffs": world.CUTOFF}


def at(minutes):
    return START + datetime.timedelta(minutes=float(minutes))


def minute_of(ts):
    return (ts - START).total_seconds() / 60


def worker_ctx(job):
    return Ctx(job["tenant_id"], uuid.UUID(job["payload"]["actor_id"]), "worker", "system")


def mine_row(c):
    m = c.execute("SELECT * FROM mine").fetchone()
    if not m:
        raise Problem(409, "no_mine", "load a mine first: POST /v1/mine:load")
    return m


@functools.lru_cache(maxsize=4)
def generator(seed):
    return world.make_mine(seed)


@functools.lru_cache(maxsize=16)
def _models(tenant_id, version):
    with db.tx(tenant_id) as c:
        return {r["name"]: pickle.loads(r["artifact"]) for r in c.execute("SELECT name, artifact FROM model_artifacts WHERE version = %s", [version])}


def model_version(m):
    return f"mine-{str(m['id'])[:8]}-1"


_FRESH = {}                       # models trained by a load job that has not committed yet (its own transaction reads them from here)


def models(m):
    key = (str(m["tenant_id"]), model_version(m))
    return _FRESH.get(key) or _models(*key)


def shift_bounds(m):
    s = m["sim_state"]["start"]["shift"]
    return s, s * world.SHIFT_MIN, (s + 1) * world.SHIFT_MIN


# --- the service's view of the mine (from its own tables) -------------------------------------------------------------------
def shovels(c):
    return [{"id": r["id"], "kind": r["kind"], "bench": r["bench"], "rate_tph": r["rate_tph"], "load_min": r["load_min"], "seq": list(r["seq"]),
             "pos": r["pos"], "remaining": r["remaining_t"]} for r in c.execute("SELECT * FROM shovel ORDER BY id")]


def estimates(c, blocks):
    rows = c.execute("SELECT id, est_cu, cu_mu, cu_s, est_as, as_s, est_bwi, cls FROM block WHERE id = ANY(%s)", [list(map(int, blocks))]).fetchall()
    out = {}
    for r in rows:
        cu, s = r["est_cu"], r["cu_s"]
        out[r["id"]] = {"cu": cu, "cu_mu": r["cu_mu"], "cu_s": s, "cu_sd": cu * math.sqrt(math.exp(s * s) - 1), "as": r["est_as"],
                        "as_sd": r["est_as"] * math.sqrt(math.exp(r["as_s"] ** 2) - 1), "bwi": r["est_bwi"], "cls": r["cls"]}
    return out


def ahead(sh, n=60):
    return [b for s in sh for b in s["seq"][s["pos"]:s["pos"] + n]]


def stock(c):
    return {r["id"]: {"tonnes": r["tonnes"], "cu": r["cu"], "cu_sd": r["cu_sd"], "as": r["as_ppm"], "as_sd": r["as_sd"], "bwi": r["bwi"]}
            for r in c.execute("SELECT * FROM stockpile ORDER BY id")}


def bin_now(c):
    r = c.execute("SELECT * FROM plant_feed ORDER BY hour_at DESC LIMIT 1").fetchone()
    if not r:
        return [world.BIN_T / 2, world.TARGET_CU, 200.0, world.MILL_BASE_BWI]
    t = max(0.0, min(world.BIN_T, r["bin_start_t"] + r["delivered_t"] + r["reclaim_t"] - r["processed_t"]))
    return [t, r["feed_cu"] or world.TARGET_CU, r["feed_as"] or 200.0, r["est_bwi"] or world.MILL_BASE_BWI]


def trucks_up(c):
    return [(r["id"], r["last_node"]) for r in c.execute("SELECT id, last_node FROM vehicle WHERE status = 'up' ORDER BY id")]


def travel_for(c, m, sh):
    mm = models(m)
    tr = engine.Travel(mm["cycle-time"], {s["id"]: s["kind"] for s in sh}, {s["id"]: s["load_min"] for s in sh})
    tr.face_shovel = {b: s["id"] for s in sh for b in s["seq"]}
    return tr


def active_plan(c):
    return c.execute("SELECT * FROM dispatch_plan WHERE status = 'active'").fetchone()


def ore_control(c, sh):
    """The current ore-control polygons: every block ahead of each shovel classified on the latest estimate."""
    return {str(r["id"]): r["cls"] for r in c.execute("SELECT id, cls FROM block WHERE id = ANY(%s)", [ahead(sh)])}


def reclaim_for_world(plan, from_min_local):
    """A plan's reclaim schedule (hours from its start) as the generator's local-hour list."""
    rc = plan.get("reclaim", {"mode": "proportional"})
    if rc["mode"] != "schedule":
        return rc
    h0 = int(from_min_local // 60)
    return {"mode": "schedule", "hours": [{}] * h0 + rc["hours"]}


# --- loading the mine ---------------------------------------------------------------------------------------------------------
class LoadIn(BaseModel):
    seed: int = Field(7, ge=1, le=10 ** 6)


@app.post("/v1/mine:load", status_code=202, tags=["mine"], summary="(+) Load the synthetic mine: the block model's survey, exploration and blast-hole assays, a week of shifts (haul log, engine telemetry, plant hours); train and register the models against their baselines; issue the shift's baseline dispatch plan")
def load_mine(body: LoadIn, ctx: Ctx = Depends(auth("mine:load")), idem: str | None = IdemKey):
    def work(c):
        if c.execute("SELECT 1 FROM mine").fetchone():
            raise Problem(409, "mine_exists", "this tenant already has a mine; `make reset` for a fresh demo")
        return 202, jobs.enqueue(c, ctx, "mine.load", body.model_dump())
    return run(ctx, idem, body, work)


def haul_rows(t, events, plan_id=None):
    return [(t, e["truck"], e["shovel"], e["block"], e["cls"], e["dest"], e["from"], e["payload_t"], at(e["dispatched_min"]), at(e["ended_min"]), e["cycle_min"],
             Jsonb({k: e[k] for k in ("empty_min", "queue_load_min", "load_min", "haul_min", "queue_dump_min", "dump_min")}), e["fuel_l"],
             Jsonb({k: e[k] for k in ("queue_at_dispatch", "enroute_at_dispatch", "to_crusher_at_dispatch", "wet")}), plan_id) for e in events]


HAUL_COLS = ["tenant_id", "truck", "shovel", "block", "cls", "dest", "from_node", "payload_t", "dispatched_at", "ended_at", "cycle_min", "segments", "fuel_l", "dispatch_context", "plan_id"]


def event_of(r):
    """A stored haul event back into the shape the models read."""
    return {"truck": r["truck"], "shovel": r["shovel"], "block": r["block"], "dest": r["dest"], "from": r["from_node"], "payload_t": r["payload_t"],
            "cycle_min": r["cycle_min"], "fuel_l": r["fuel_l"], "dispatched_min": minute_of(r["dispatched_at"]), **r["segments"], **r["dispatch_context"]}


TEL_COLS = ["tenant_id", "truck", "at", "source", "state", "duty", "speed_kmh", "payload_t", "loaded_frac", "ambient_c", "coolant_c", "oil_kpa", "exhaust_c", "fuel_lph", "z"]


def tel_row(t, w, source, z):
    return (t, w["truck"], at(w["at_min"]), source, w["state"], *(w.get(k) for k in ("duty", "speed_kmh", "payload_t", "loaded_frac", "ambient_c", "coolant_c", "oil_kpa", "exhaust_c", "fuel_lph")),
            Jsonb({k: round(v, 2) for k, v in z.items()}) if z else None)


def store_estimates(c, gm, version, when):
    pred = gm.predict(np.arange(world.N_BLOCKS))
    cls = engine.classify(pred["cu"])
    c.execute("CREATE TEMP TABLE _est (id int, est_cu float8, cu_mu float8, cu_s float8, est_as float8, as_s float8, est_bwi float8, cls text, p_hg float8) ON COMMIT DROP")
    db.copy(c, "_est", ["id", "est_cu", "cu_mu", "cu_s", "est_as", "as_s", "est_bwi", "cls", "p_hg"],
            ((b, float(pred["cu"][b]), float(pred["cu_mu"][b]), float(pred["cu_s"][b]), float(pred["as"][b]), float(pred["as_s"][b]), float(pred["bwi"][b]), str(cls[b]), float(pred["p_hg"][b]))
             for b in range(world.N_BLOCKS)))
    changed = c.execute("""SELECT b.id, b.cls AS before, e.cls AS after, b.est_cu AS cu_before, e.est_cu AS cu_after FROM block b JOIN _est e ON e.id = b.id
                            WHERE b.cls IS DISTINCT FROM e.cls""").fetchall()
    c.execute("""UPDATE block b SET est_cu = e.est_cu, cu_mu = e.cu_mu, cu_s = e.cu_s, est_as = e.est_as, as_s = e.as_s, est_bwi = e.est_bwi, cls = e.cls,
                        p_hg = e.p_hg, model_version = %s, observed_at = %s FROM _est e WHERE e.id = b.id""", [version, when])
    c.execute("DROP TABLE _est")
    return changed


def assays_of(c):
    return [{"block": r["block"], "kind": r["kind"], "cu": r["cu"], "as": r["as_ppm"], "bwi": r["bwi"]} for r in c.execute("SELECT * FROM assay ORDER BY id")]


def ingest_haul(c, t, events, plan_id=None):
    """The haul log: store it, move the shovels' faces, mark dug blocks, add each stockpiled load at the estimate of its block."""
    if not events:
        return
    db.load(c, "haul_event", HAUL_COLS, haul_rows(t, events, plan_id))
    est = estimates(c, {e["block"] for e in events if e["dest"] in ("hg", "lg")})
    piles = stock(c)
    for e in events:
        if e["dest"] in piles:
            g, p = est[e["block"]], piles[e["dest"]]
            n = p["tonnes"] + e["payload_t"]
            for k, gk in (("cu", "cu"), ("cu_sd", "cu_sd"), ("as", "as"), ("as_sd", "as_sd"), ("bwi", "bwi")):
                p[k] = (p[k] * p["tonnes"] + g[gk] * e["payload_t"]) / n
            p["tonnes"] = n
    for k, p in piles.items():
        c.execute("UPDATE stockpile SET tonnes = %s, cu = %s, cu_sd = %s, as_ppm = %s, as_sd = %s, bwi = %s, updated_at = %s WHERE id = %s",
                  [p["tonnes"], p["cu"], p["cu_sd"], p["as"], p["as_sd"], p["bwi"], at(max(e["ended_min"] for e in events)), k])
    last = {}
    for e in events:
        last[e["truck"]] = e["dest"]
    for tid, node in last.items():
        c.execute("UPDATE vehicle SET last_node = %s WHERE id = %s", [node, tid])
    sync_shovels(c)


def sync_shovels(c):
    """Where each shovel is digging, from the haul log: the furthest block of its sequence it has loaded, and what is left of it."""
    for s in c.execute("SELECT id, seq FROM shovel").fetchall():
        rows = c.execute("SELECT block, sum(payload_t) AS t FROM haul_event WHERE shovel = %s GROUP BY block", [s["id"]]).fetchall()
        if not rows:
            continue
        idx = {b: i for i, b in enumerate(s["seq"])}
        done = {r["block"]: r["t"] for r in rows if r["block"] in idx}
        pos = max(idx[b] for b in done)
        rem = float(np.clip(world.BLOCK_T - done[s["seq"][pos]], 200, world.BLOCK_T))
        c.execute("UPDATE shovel SET pos = %s, remaining_t = %s WHERE id = %s", [pos, rem, s["id"]])
        c.execute("UPDATE block SET status = 'mined' WHERE id = ANY(%s) AND status = 'in_situ'", [s["seq"][:pos]])


def ingest_plant(c, t, hours):
    """Plant hours: stored with the estimator's hardness of what was fed; the reclaim comes off the stockpiles."""
    piles = stock(c)
    for h in hours:
        hs, he = at(h["hour_min"]), at(h["hour_min"] + 60)
        fed = c.execute("""SELECT sum(e.payload_t) AS t, sum(e.payload_t * b.est_bwi) AS bw FROM haul_event e JOIN block b ON b.id = e.block
                            WHERE e.dest = 'crusher' AND e.ended_at >= %s AND e.ended_at < %s""", [hs, he]).fetchone()
        tt, bw = fed["t"] or 0.0, fed["bw"] or 0.0
        for k, v in h.get("reclaim_by_pile", {}).items():
            tt += v
            bw += v * piles[k]["bwi"]
            piles[k]["tonnes"] = max(0.0, piles[k]["tonnes"] - v)
        est_bwi = bw / tt if tt else None
        c.execute("""INSERT INTO plant_feed (tenant_id, hour_at, delivered_t, reclaim_t, reclaim_by_pile, processed_t, bin_start_t, outage_min, feed_cu, feed_as, est_bwi)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                  [t, hs, h["delivered_t"], h["reclaim_t"], Jsonb(h.get("reclaim_by_pile", {})), h["processed_t"], h["bin_start_t"], h["outage_min"], h["feed_cu"], h["feed_as"], est_bwi])
    for k, p in piles.items():
        c.execute("UPDATE stockpile SET tonnes = %s WHERE id = %s", [p["tonnes"], k])


@jobs.handler("mine.load")
def load_job(c, job):
    t0 = time.perf_counter()
    t, seed = job["tenant_id"], job["payload"]["seed"]
    mid = uuid.uuid5(t, "mine")
    gen = world.make_mine(seed)
    hist, st = world.history(gen, HISTORY_SHIFTS)
    version = f"mine-{str(mid)[:8]}-1"
    clock = HISTORY_SHIFTS * world.SHIFT_MIN
    c.execute("INSERT INTO mine (id, tenant_id, name, model_seed, start_at, clock_min, history_shifts, sim_state, plant) VALUES (%s,%s,'Copper Ridge Mine',%s,%s,%s,%s,%s,%s)",
              [mid, t, seed, START, clock, HISTORY_SHIFTS, Jsonb({"start": st, "plans": [], "baseline": []}), Jsonb(PLANT)])
    db.load(c, "bench", ["tenant_id", "k", "floor_rl", "ramp_x", "ramp_y"], [(t, k, world.TOP_RL - (k + 1) * world.BENCH_M, *world.ramp_xy(k)) for k in range(world.NZ)])
    db.load(c, "site_node", ["tenant_id", "id", "x", "y"], [(t, k, x, y) for k, (x, y) in world.NODES.items()])
    roads = [(t, f"RAMP-{k}", f"bench{k}", "exit" if k == 0 else f"bench{k - 1}", "ramp", world.RAMP_LEN, world.RAMP_GRADE) for k in range(world.NZ)]
    roads += [(t, f"EXIT-{d.upper()}", "exit", d, "surface", L, g) for d, (L, g) in world.SURFACE.items()]
    roads += [(t, "EXIT-GOLINE", "exit", "goline", "surface", 120.0, 0.0)]
    db.load(c, "haul_road", ["tenant_id", "id", "from_node", "to_node", "kind", "length_m", "grade"], roads)
    db.load(c, "block", ["tenant_id", "id", "bench", "i", "j"], [(t, b, b // (world.NX * world.NY), b % world.NX, (b // world.NX) % world.NY) for b in range(world.N_BLOCKS)])
    events = [e for r in hist for e in r["haul"]]
    load_min = {s["id"]: float(np.mean([e["load_min"] for e in events if e["shovel"] == s["id"]])) for s in gen["shovels"]}
    db.load(c, "shovel", ["tenant_id", "id", "kind", "bench", "rate_tph", "load_min", "seq", "pos", "remaining_t"],
            [(t, s["id"], s["kind"], s["bench"], s["rate_tph"], load_min[s["id"]], s["seq"], 0, world.BLOCK_T) for s in gen["shovels"]])
    db.load(c, "vehicle", ["tenant_id", "id", "model", "payload_t", "age_h", "status"],
            [(t, tr["id"], tr["model"], tr["payload_t"], tr["age_h"], "up" if st["down_until"].get(tr["id"], -1) <= clock else "down") for tr in gen["trucks"]])
    # assays: the exploration programme, and every blast assayed up to the one each shovel is digging
    samples = world.drill_holes(gen)
    arows = [(t, f"{s['hole']}-{world.block_ijk(s['block'])[2]}", s["hole"], "exploration", s["block"], s["cu"], s["as"], s["bwi"], START - datetime.timedelta(days=60)) for s in samples]
    for sid, blocks in world.blasts_assayed(gen, st).items():
        for b in blocks:
            a = world.blast_assay(gen, b)
            samples.append(a)
            arows.append((t, a["hole"], a["hole"], "blasthole", b, a["cu"], a["as"], a["bwi"], at(clock - 60)))
    db.load(c, "assay", ["tenant_id", "id", "hole", "kind", "block", "cu", "as_ppm", "bwi", "received_at"], arows)
    gm = engine.GradeModel([s for s in samples if s["kind"] == "exploration"])
    held = np.setdiff1d(np.arange(world.N_BLOCKS), [s["block"] for s in samples if s["kind"] == "exploration"])
    expl = [s for s in samples if s["kind"] == "exploration"]
    pv = gm.predict(held)
    truth = gen["cu"][held]          # scored against the generator only here, at registration: the service never stores it
    grade_metrics = {"model": engine.score_grade(truth, pv["cu"], pv["p10"], pv["p90"]), "idw": engine.score_grade(truth, engine.idw(expl, held)),
                     "nearest_hole": engine.score_grade(truth, engine.nearest_hole(expl, held)), "exploration_composites": len(expl), "kernel": str(gm.kernels["cu"])}
    gm.condition(samples)
    store_estimates(c, gm, version, at(clock))
    # stockpiles: the survey the mine started with, then the history's loads at their estimates
    survey = world.stock_survey(gen, world.initial_state(gen))
    db.load(c, "stockpile", ["tenant_id", "id", "tonnes", "cu", "cu_sd", "as_ppm", "as_sd", "bwi"],
            [(t, k, v["tonnes"], v["cu"], v["cu_sd"], v["as"], v["as_sd"], v["bwi"]) for k, v in survey.items()])
    for r in hist:
        ingest_haul(c, t, r["haul"])
        ingest_plant(c, t, r["plant"])
    c.execute("UPDATE vehicle SET status_at = %s", [at(clock)])
    # models trained on the first ten shifts, scored on the last four
    kinds, ages = {s["id"]: s["kind"] for s in gen["shovels"]}, {tr["id"]: tr["age_h"] for tr in gen["trucks"]}
    test = np.array([e["dispatched_min"] >= TEST_FROM_SHIFT * world.SHIFT_MIN for e in events])
    cyc, cyc_m = engine.train_cycle(events, kinds, ages, test)
    fuel, fuel_m = engine.train_fuel(events, test)
    windows = sorted((w for r in hist for w in r["telemetry"]), key=lambda w: (w["truck"], w["at_min"]))
    downs = [b for r in hist for b in r["breakdowns"]]
    split = TEST_FROM_SHIFT * world.SHIFT_MIN
    anomaly = engine.train_anomaly([w for w in windows if w["at_min"] < split], [b for b in downs if b["at_min"] < split])
    tw, tb = [w for w in windows if w["at_min"] >= split], [b for b in downs if b["at_min"] >= split]
    anom_m = {"model": engine.score_alarms(engine.alarms(anomaly, tw), tb, tw), "static_thresholds": engine.score_alarms(engine.alarms(anomaly, tw, "static"), tb, tw),
              "z_alarm": engine.Z_ALARM, "persist_windows": engine.PERSIST, "static": engine.STATIC}
    zs = engine.health_scores(anomaly, windows)
    db.load(c, "truck_telemetry", TEL_COLS, [tel_row(t, w, "fleet", z) for w, z in zip(windows, zs)])
    for tid, amin, sensor, val in engine.alarms(anomaly, windows):
        c.execute("INSERT INTO equipment_alert (id, tenant_id, truck, kind, sensor, value, raised_at, detail, status) VALUES (%s,%s,%s,'anomaly',%s,%s,%s,%s,'closed')",
                  [uuid.uuid4(), t, tid, sensor, val, at(amin), Jsonb({"rule": "history"})])
    for b in downs:
        c.execute("INSERT INTO equipment_alert (id, tenant_id, truck, kind, raised_at, detail, status) VALUES (%s,%s,%s,'breakdown',%s,%s,'closed')",
                  [uuid.uuid4(), t, b["truck"], at(b["at_min"]), Jsonb({"failure": b["failure"], "repaired": True})])
    prow = plant_rows(c)
    ptest = np.array([r["hour_min"] >= split for r in prow])
    plant_model, plant_m = engine.train_plant(prow, ptest)
    snapshot = f"shifts 0-{HISTORY_SHIFTS - 1} (train < {TEST_FROM_SHIFT}), {len(events)} haul cycles, {len(windows)} telemetry windows, seed {seed}"
    for name, obj, metrics in (("grade-estimator", gm.kernels, grade_metrics), ("cycle-time", cyc, cyc_m), ("fuel", fuel, fuel_m),
                               ("engine-anomaly", anomaly, anom_m), ("plant-forecast", plant_model, plant_m)):
        c.execute("INSERT INTO model_artifacts (tenant_id, name, version, data_snapshot, metrics, artifact, approved) VALUES (%s,%s,%s,%s,%s,%s,true)",
                  [t, name, version, snapshot, Jsonb(metrics), pickle.dumps(obj)])
    _models.cache_clear()
    m = mine_row(c)
    _FRESH[(str(t), version)] = {"grade-estimator": gm.kernels, "cycle-time": cyc, "fuel": fuel, "engine-anomaly": anomaly, "plant-forecast": plant_model}
    plan = baseline_plan(c, m)
    pid = uuid.uuid4()
    c.execute("""INSERT INTO dispatch_plan (id, tenant_id, kind, status, plan, summary, inputs_hash, model_versions, effective_from_min, created_by)
                 VALUES (%s,%s,'baseline','active',%s,%s,%s,%s,%s,%s)""",
              [pid, t, Jsonb(plan), Jsonb({"trucks": plan["trucks"], "rule": "match-factor split, cut-off routing, proportional reclaim"}),
               engine.feature_hash(plan["trucks"]), Jsonb({"grade": version}), clock, uuid.UUID(job["payload"]["actor_id"])])
    local = clock - HISTORY_SHIFTS * world.SHIFT_MIN
    c.execute("UPDATE mine SET sim_state = jsonb_set(jsonb_set(sim_state, '{plans}', %s), '{baseline}', %s)", [Jsonb([[local, plan]]), Jsonb([[local, plan]])])
    _FRESH.clear()
    audit.record(c, worker_ctx(job), "mine.loaded", "mine", mid, {"shifts": HISTORY_SHIFTS, "cycles": len(events), "model_version": version})
    hp = [h for r in hist for h in r["plant"]]
    return {"mine_id": mid, "blocks": world.N_BLOCKS, "benches": world.NZ, "block_t": world.BLOCK_T, "shovels": len(gen["shovels"]), "trucks": len(gen["trucks"]),
            "trucks_up": c.execute("SELECT count(*) AS n FROM vehicle WHERE status = 'up'").fetchone()["n"], "assays": len(samples),
            "exploration_composites": len(expl), "blast_holes": len(samples) - len(expl), "history_shifts": HISTORY_SHIFTS, "haul_cycles": len(events),
            "telemetry_windows": len(windows), "plant_hours": len(hp), "tonnes_moved": round(sum(e["payload_t"] for e in events)),
            "tonnes_milled": round(sum(h["processed_t"] for h in hp)), "history_breakdowns": len(downs), "clock": at(clock),
            "models": {"version": version, "grade": grade_metrics, "cycle_time": cyc_m, "fuel": fuel_m, "anomaly": anom_m, "plant": plant_m},
            "baseline_plan_id": pid, "plant": PLANT, "load_seconds": round(time.perf_counter() - t0, 1)}


def plant_rows(c):
    rows = c.execute("SELECT * FROM plant_feed ORDER BY hour_at").fetchall()
    bw = engine.smooth_bwi([r["est_bwi"] or world.MILL_BASE_BWI for r in rows])
    return [{"hour_min": minute_of(r["hour_at"]), "feed_tph": r["delivered_t"] + r["reclaim_t"], "bin_start_t": r["bin_start_t"], "bwi_s": b,
             "processed_t": r["processed_t"]} for r, b in zip(rows, bw)]


def baseline_plan(c, m):
    """The shift's plan as the mine makes it without the optimiser: trucks split by what each shovel needs, cut-off routing."""
    sh = shovels(c)
    up = [tid for tid, _ in trucks_up(c)]
    est = estimates(c, ahead(sh))
    mm = models(m)
    inp = engine.dispatch_inputs(sh, est, travel_for(c, m, sh), mm["fuel"], [{"shovel": None, "trucks": up}], stock(c), 12)
    plan = engine.heuristic_dispatch(inp)
    plan["block_class"] = ore_control(c, sh)
    return plan


# --- the clock moves -------------------------------------------------------------------------------------------------------------
class Zone(BaseModel):
    ahead_of: Literal["S1", "S2", "S3", "S4", "S5", "S6"]
    radius_m: float = Field(45.0, ge=15, le=120)
    factor: float = Field(0.3, gt=0, lt=1, description="true grade multiplied by this inside the zone")
    assays_after_min: float = Field(150.0, ge=0, le=720, description="the lab returns the blast's assays this many minutes into the advance")


class Breakdown(BaseModel):
    truck: str = Field(pattern=r"^T\d{2}$")
    after_min: float = Field(ge=0, le=720)
    failure: Literal["tyre", "cooling", "oil", "electrical"]


class Inject(BaseModel):
    low_grade_zone: Zone | None = None
    breakdowns: list[Breakdown] = Field(default_factory=list, max_length=10)


class AdvanceIn(BaseModel):
    minutes: int = Field(ge=10, le=720)
    inject: Inject | None = None


@app.post("/v1/mine:advance", status_code=202, tags=["mine"], summary="(+) Run the shift forward under the active plan. The generator can be told about a low-grade zone or truck breakdowns (the demo's injection); the service sees only the haul log, telemetry, plant hours and assays, never the telling")
def advance(body: AdvanceIn, ctx: Ctx = Depends(auth("mine:advance")), idem: str | None = IdemKey):
    def work(c):
        m = mine_row(c)
        s1 = (m["sim_state"]["start"]["shift"] + 1) * world.SHIFT_MIN
        if m["clock_min"] >= s1 - 1e-6:
            raise Problem(409, "shift_over", "this slice runs one shift after the history; `make reset` to run the demo again")
        if m["clock_min"] + body.minutes > s1 + 1e-6:
            raise Problem(422, "past_shift_end", f"{s1 - m['clock_min']:.0f} minutes are left in this shift")
        up = {tid for tid, _ in trucks_up(c)}
        for b in (body.inject.breakdowns if body.inject else []):
            if b.truck not in up:
                raise Problem(422, "truck_not_working", f"{b.truck} is not working this shift")
            if b.after_min >= body.minutes:
                raise Problem(422, "breakdown_after_advance", f"{b.truck}: after_min must fall inside the {body.minutes} minutes")
        return 202, jobs.enqueue(c, ctx, "mine.advance", {**body.model_dump(), "from_min": m["clock_min"]})
    return run(ctx, idem, body, work)


def ingest_telemetry(c, m, rows, source):
    """Fleet telemetry: store each window with the anomaly detector's deviations; an alert when a truck runs two windows in a
    row more than 4 sd off its normal in a harmful direction; a breakdown when a working truck reports down."""
    t = m["tenant_id"]
    mm = models(m)
    rows = sorted(rows, key=lambda w: (w["truck"], w["at_min"]))
    zs = engine.health_scores(mm["engine-anomaly"], rows)
    db.load(c, "truck_telemetry", TEL_COLS, [tel_row(t, w, source, z) for w, z in zip(rows, zs)])
    raised = []
    by = {}
    for w, z in zip(rows, zs):
        by.setdefault(w["truck"], []).append((w, z))
    for tid, ws in by.items():
        prev = c.execute("SELECT state, z FROM truck_telemetry WHERE truck = %s AND at < %s ORDER BY at DESC LIMIT 1", [tid, at(ws[0][0]["at_min"])]).fetchone()
        run_ = 1 if prev and prev["z"] and max(prev["z"].values()) > engine.Z_ALARM else 0
        was_working = bool(prev and prev["state"] != "down")
        for w, z in ws:
            if w["state"] == "down":
                if was_working:
                    early = c.execute("""SELECT raised_at, sensor, value FROM equipment_alert WHERE truck = %s AND kind = 'anomaly' AND status = 'open'
                                          ORDER BY raised_at LIMIT 1""", [tid]).fetchone()
                    lead = round(w["at_min"] - minute_of(early["raised_at"])) if early else None
                    aid = uuid.uuid4()
                    c.execute("INSERT INTO equipment_alert (id, tenant_id, truck, kind, raised_at, detail) VALUES (%s,%s,%s,'breakdown',%s,%s)",
                              [aid, t, tid, at(w["at_min"]), Jsonb({"reported_by": "telemetry: truck down", "anomaly_alert_lead_min": lead,
                                                                    "anomaly_sensor": early["sensor"] if early else None})])
                    c.execute("UPDATE vehicle SET status = 'down', status_at = %s WHERE id = %s", [at(w["at_min"]), tid])
                    raised.append({"kind": "breakdown", "truck": tid, "at": at(w["at_min"]), "anomaly_alert_lead_min": lead})
                was_working, run_ = False, 0
                continue
            was_working = True
            if not z:
                continue
            s = max(z, key=z.get)
            run_ = run_ + 1 if z[s] > engine.Z_ALARM else 0
            if run_ >= engine.PERSIST and not c.execute("SELECT 1 FROM equipment_alert WHERE truck = %s AND kind = 'anomaly' AND status = 'open'", [tid]).fetchone():
                aid = uuid.uuid4()
                c.execute("INSERT INTO equipment_alert (id, tenant_id, truck, kind, sensor, value, raised_at, detail) VALUES (%s,%s,%s,'anomaly',%s,%s,%s,%s)",
                          [aid, t, tid, s, round(z[s], 1), at(w["at_min"]), Jsonb({"reading": w[s], "z": {k: round(v, 1) for k, v in z.items()},
                                                                                     "rule": f"{engine.PERSIST} windows in a row above {engine.Z_ALARM} sd in the harmful direction",
                                                                                     "static_threshold_crossed": (w[s] - engine.STATIC[s]) * dict(engine.SENSORS)[s] > 0})])
                raised.append({"kind": "anomaly", "truck": tid, "sensor": s, "z": round(z[s], 1), "reading": w[s], "at": at(w["at_min"])})
    runs = [(engine.ANOMALY_VERSION, f"truck:{w['truck']}:{w['at_min']:.0f}", engine.feature_hash([w.get(k) for k in ("duty", "ambient_c", "payload_t", "coolant_c", "oil_kpa", "exhaust_c")]),
             Jsonb({"max_z": round(max(z.values()), 2)})) for w, z in zip(rows, zs) if z]
    db.load(c, "model_runs", ["tenant_id", "model_name", "version", "subject", "inputs_hash", "result"], [(t, n, model_version(m), s, h, r) for n, s, h, r in runs])
    return raised


@jobs.handler("mine.advance")
def advance_job(c, job):
    p = job["payload"]
    m = mine_row(c)
    t = m["tenant_id"]
    gen = generator(m["model_seed"])
    shift, s0, s1 = shift_bounds(m)
    sim = m["sim_state"]
    start = sim["start"]
    a, b = p["from_min"] - s0, p["from_min"] - s0 + p["minutes"]
    told = list(m["told"])
    inj = p.get("inject") or {}
    if inj.get("low_grade_zone"):
        z = inj["low_grade_zone"]
        zone = world.zone_ahead_of(gen, start, z["ahead_of"], z["radius_m"], z["factor"])
        zone["assays_at_min"] = a + z["assays_after_min"]
        told.append(zone)
    for bd in inj.get("breakdowns", []):
        told.append({"kind": "breakdown", "shift": shift, "truck": bd["truck"], "at_min": a + bd["after_min"], "failure": bd["failure"]})
    plans = [(mm_, pl) for mm_, pl in sim["plans"]]
    active = active_plan(c)
    out = world.run_shift(gen, start, plans, told, until=b, natural=False)
    s0abs = s0
    haul = [e for e in out["haul"] if a <= e["ended_min"] - s0abs < b]
    plant = [h for h in out["plant"] if a <= h["hour_min"] - s0abs < b]
    tel = [w for w in out["telemetry"] if a <= w["at_min"] - s0abs < b]
    assays = world.assays_due(gen, start, told, a, b)
    ingest_haul(c, t, haul, active["id"] if active else None)
    ingest_plant(c, t, plant)
    alerts = ingest_telemetry(c, m, tel, "fleet")
    changed, reest = [], None
    if assays:
        db.load(c, "assay", ["tenant_id", "id", "hole", "kind", "block", "cu", "as_ppm", "bwi", "received_at"],
                [(t, f"{x['hole']}-{shift}", x["hole"], "blasthole", x["block"], x["cu"], x["as"], x["bwi"], at(x["at_min"])) for x in assays])
        mm = models(m)
        t_ = time.perf_counter()
        gm = engine.GradeModel.from_kernels(mm["grade-estimator"], assays_of(c))
        changed = store_estimates(c, gm, model_version(m), at(s0 + b))
        reest = {"assays": len(assays), "blocks_reclassified": len(changed), "seconds": round(time.perf_counter() - t_, 1),
                 "by_change": {f"{k[0]}->{k[1]}": v for k, v in _count((r["before"], r["after"]) for r in changed).items()}}
        c.execute("INSERT INTO model_runs (tenant_id, model_name, version, subject, inputs_hash, result) VALUES (%s,%s,%s,%s,%s,%s)",
                  [t, engine.GRADE_VERSION, model_version(m), f"reestimate:{shift}:{b:.0f}", engine.feature_hash([x["block"] for x in assays]), Jsonb(reest)])
    sh = shovels(c)
    if changed:                                      # ore control re-issues its polygons; every plan in force picks them up
        classes = ore_control(c, sh)
        for key in ("plans", "baseline"):
            last = copy.deepcopy(sim[key][-1][1])
            last["block_class"] = classes
            sim[key].append([b, last])
        if active:
            c.execute("UPDATE dispatch_plan SET plan = jsonb_set(plan, '{block_class}', %s) WHERE id = %s", [Jsonb(classes), active["id"]])
    c.execute("UPDATE mine SET clock_min = %s, told = %s, sim_state = %s", [s0 + b, Jsonb(told), Jsonb(sim)])
    audit.record(c, worker_ctx(job), "mine.advanced", "mine", m["id"], {"minutes": p["minutes"], "cycles": len(haul), "alerts": len(alerts), "assays": len(assays)})
    hours = [{"hour": at(h["hour_min"]), "delivered_t": h["delivered_t"], "reclaim_t": h["reclaim_t"], "processed_t": h["processed_t"], "feed_cu": h["feed_cu"], "feed_as": h["feed_as"]} for h in plant]
    res = {"from": at(p["from_min"]), "to": at(s0 + b), "cycles": len(haul), "moved_t": round(sum(e["payload_t"] for e in haul)),
           "by_dest_t": {d: round(sum(e["payload_t"] for e in haul if e["dest"] == d)) for d in world.DESTS}, "fuel_l": round(sum(e["fuel_l"] for e in haul)),
           "plant_hours": hours, "alerts": alerts, "assays_received": [{"block": x["block"], "cu": x["cu"], "at": at(x["at_min"])} for x in assays],
           "reestimate": reest, "trucks_up": len(trucks_up(c)),
           "simulation_truth": {"told": [x for x in told if x not in m["told"]], "note": "what the generator was told; the analysis never reads this"}}
    if s0 + b >= s1 - 1e-6 and sim["plans"] != sim["baseline"]:
        res["simulation_truth"]["shift_outcome"] = shift_truth(gen, start, sim, told, b)
    return res


def _count(it):
    out = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return out


def shift_truth(gen, start, sim, told, until):
    """At the end of a shift in which a plan replaced the baseline: the generator re-runs the same shift with the baseline plan kept,
    on the same random draws, and reports both from the moment the plans diverged (simulation truth, never read by the analysis)."""
    split = min(mm for mm, pl in sim["plans"] if [mm, pl] not in sim["baseline"])
    out = {}
    for name, plans in (("approved_plan", sim["plans"]), ("baseline_plan", sim["baseline"])):
        before = world.run_shift(gen, start, plans, told, until=split, natural=False, record=False)["end_state"]
        r = world.run_shift(gen, start, plans, told, until=until, natural=False)
        t0 = start["shift"] * world.SHIFT_MIN
        haul = [e for e in r["haul"] if e["ended_min"] - t0 >= split]
        plant = [h for h in r["plant"] if h["hour_min"] - t0 >= split]
        out[name] = engine.shift_value(plant, haul, before["stock"], r["end_state"]["stock"], before["bin"], r["end_state"]["bin"])
    out["from_minute_of_shift"] = split
    out["difference"] = {k: round(out["approved_plan"][k] - out["baseline_plan"][k], 1) for k in out["approved_plan"] if k != "hours"}
    return out


# --- telemetry from outside the dispatch system --------------------------------------------------------------------------------
class TelemetryIn(BaseModel):
    truck: str
    at: datetime.datetime
    state: Literal["working", "idle", "down"]
    duty: float | None = Field(None, ge=0, le=1)
    speed_kmh: float | None = Field(None, ge=0, le=80)
    payload_t: float | None = Field(None, ge=0, le=320)
    loaded_frac: float | None = Field(None, ge=0, le=1)
    ambient_c: float | None = Field(None, ge=-40, le=60)
    coolant_c: float | None = None
    oil_kpa: float | None = None
    exhaust_c: float | None = None
    fuel_lph: float | None = Field(None, ge=0, le=600)


class TelemetryBatch(BaseModel):
    source: str = Field("oem", pattern=r"^[a-z0-9_-]{2,20}$")
    records: list[TelemetryIn] = Field(min_length=1, max_length=2000)


RANGES = {"coolant_c": (-20, 140), "oil_kpa": (0, 1000), "exhaust_c": (-20, 1000)}


@app.post("/v1/telemetry", status_code=201, tags=["fleet"], summary="Engine telemetry from an OEM feed or a probe: 10-minute summaries per truck. Each record is validated on its own (known truck, aligned window, not ahead of the clock or a day old, sensors in range, no duplicate per source); accepted records are scored by the anomaly detector like the fleet's own")
def telemetry(body: TelemetryBatch, ctx: Ctx = Depends(auth("telemetry:ingest")), idem: str | None = IdemKey):
    def work(c):
        m = mine_row(c)
        known = {r["id"] for r in c.execute("SELECT id FROM vehicle")}
        accepted, refused, seen = [], [], set()
        for r in body.records:
            mn = minute_of(r.at)
            why = None
            if r.truck not in known:
                why = "unknown truck"
            elif abs(mn - round(mn / 10) * 10) > 1e-6:
                why = "at must be on a 10-minute boundary"
            elif mn > m["clock_min"] + 1e-6:
                why = "ahead of the mine clock"
            elif mn < m["clock_min"] - 24 * 60:
                why = "older than a day"
            elif r.state == "working" and any(getattr(r, k) is None for k in ("duty", "ambient_c", "payload_t", "speed_kmh", "coolant_c", "oil_kpa", "exhaust_c")):
                why = "a working record needs duty, ambient_c, payload_t, speed_kmh, coolant_c, oil_kpa and exhaust_c"
            elif bad := [k for k, (lo, hi) in RANGES.items() if getattr(r, k) is not None and not lo <= getattr(r, k) <= hi]:
                why = f"{bad[0]} = {getattr(r, bad[0])} is outside {RANGES[bad[0]][0]}..{RANGES[bad[0]][1]}"
            elif (r.truck, mn) in seen or c.execute("SELECT 1 FROM truck_telemetry WHERE truck = %s AND at = %s AND source = %s", [r.truck, r.at, body.source]).fetchone():
                why = "duplicate record for this truck, window and source"
            if why:
                refused.append({"truck": r.truck, "at": r.at, "why": why})
                continue
            seen.add((r.truck, mn))
            accepted.append({**r.model_dump(exclude={"at"}), "at_min": mn})
        alerts = ingest_telemetry(c, m, accepted, body.source) if accepted else []
        scored = []
        if accepted:
            for r in c.execute("SELECT truck, at, z FROM truck_telemetry WHERE source = %s AND (truck, at) IN (SELECT * FROM unnest(%s::text[], %s::timestamptz[]))",
                               [body.source, [a["truck"] for a in accepted], [at(a["at_min"]) for a in accepted]]):
                scored.append({"truck": r["truck"], "at": r["at"], "z": r["z"]})
        audit.record(c, ctx, "telemetry.ingested", "telemetry", body.source, {"accepted": len(accepted), "refused": len(refused), "alerts": len(alerts)})
        return 201, {"accepted": len(accepted), "scored": scored, "refused": refused, "alerts": alerts, "model": engine.ANOMALY_VERSION}
    return run(ctx, idem, body, work)


# --- reading the mine ---------------------------------------------------------------------------------------------------------
@app.get("/v1/mine/overview", tags=["mine"], summary="(+) The command centre: clock, fleet, plant by hour against the grade window, stockpiles, open alerts, the plan in force, the models")
def overview(hours: int = Query(12, ge=1, le=96), ctx: Ctx = Depends(auth("mine:read"))):
    with db.tx(ctx.tenant_id) as c:
        m = mine_row(c)
        plant = c.execute("SELECT * FROM plant_feed WHERE hour_at >= %s ORDER BY hour_at", [at(m["clock_min"] - hours * 60)]).fetchall()
        fleet = c.execute("SELECT status, count(*) AS n FROM vehicle GROUP BY status").fetchall()
        alerts = c.execute("SELECT id, truck, kind, sensor, value, raised_at, detail FROM equipment_alert WHERE status = 'open' ORDER BY raised_at").fetchall()
        plan = active_plan(c)
        models_ = c.execute("SELECT name, version, data_snapshot, metrics FROM model_artifacts ORDER BY name").fetchall()
        moved = c.execute("SELECT dest, sum(payload_t) AS t FROM haul_event WHERE ended_at >= %s GROUP BY dest", [at(m["clock_min"] - hours * 60)]).fetchall()
        shift, s0, _ = shift_bounds(m)
        piles = {k: {kk: round(v, 4) for kk, v in s.items()} for k, s in stock(c).items()}
    return jsonable_encoder({"clock": at(m["clock_min"]), "shift": shift, "minute_of_shift": m["clock_min"] - s0, "plant": PLANT,
                             "plant_hours": plant, "fleet": {r["status"]: r["n"] for r in fleet}, "open_alerts": alerts, "stockpiles": piles,
                             "moved_t": {r["dest"]: round(r["t"]) for r in moved}, "active_plan": {"id": plan["id"], "kind": plan["kind"], "summary": plan["summary"]} if plan else None,
                             "models": models_})


@app.get("/v1/orebody/tiles", tags=["geology"], summary="One bench of the block model as a grid: estimated grade, its 80% interval, the probability of high grade, the ore-control class and whether it is dug; the assays on the bench, the shovels' faces and blasts, and the ramp")
def tiles(bench: int = Query(..., ge=0, le=world.NZ - 1), ctx: Ctx = Depends(auth("mine:read"))):
    with db.tx(ctx.tenant_id) as c:
        m = mine_row(c)
        rows = c.execute("SELECT id, i, j, est_cu, cu_mu, cu_s, cls, p_hg, status, model_version, observed_at FROM block WHERE bench = %s ORDER BY j, i", [bench]).fetchall()
        assays = c.execute("SELECT a.block, a.kind, a.cu, a.received_at FROM assay a WHERE a.block / %s = %s ORDER BY a.received_at", [world.NX * world.NY, bench]).fetchall()
        sh = [s for s in shovels(c) if s["bench"] == bench]
        b0 = c.execute("SELECT * FROM bench WHERE k = %s", [bench]).fetchone()
    grid = {"nx": world.NX, "ny": world.NY, "block_m": world.BLOCK_M, "cu": [], "p10": [], "p90": [], "cls": [], "p_hg": [], "mined": []}
    for r in rows:
        grid["cu"].append(round(r["est_cu"], 3))
        grid["p10"].append(round(math.exp(r["cu_mu"] - 1.2816 * r["cu_s"]), 3))
        grid["p90"].append(round(math.exp(r["cu_mu"] + 1.2816 * r["cu_s"]), 3))
        grid["cls"].append(r["cls"])
        grid["p_hg"].append(round(r["p_hg"], 2))
        grid["mined"].append(1 if r["status"] == "mined" else 0)
    faces = []
    for s in sh:
        face = s["seq"][min(s["pos"], len(s["seq"]) - 1)]
        nxt = s["seq"][s["pos"]:s["pos"] + 24]
        faces.append({"shovel": s["id"], "kind": s["kind"], "face": face, "face_ij": world.block_ijk(face)[:2], "next": [world.block_ijk(b)[:2] for b in nxt],
                      "next_cu": [grid["cu"][world.block_ijk(b)[1] * world.NX + world.block_ijk(b)[0]] for b in nxt],
                      "next_cls": [grid["cls"][world.block_ijk(b)[1] * world.NX + world.block_ijk(b)[0]] for b in nxt]})
    return jsonable_encoder({"bench": bench, "floor_rl": b0["floor_rl"], "ramp": [b0["ramp_x"], b0["ramp_y"]], "grid": grid, "shovels": faces,
                             "assays": [{"ij": world.block_ijk(a["block"])[:2], "kind": a["kind"], "cu": a["cu"], "received_at": a["received_at"]} for a in assays],
                             "model_version": rows[0]["model_version"], "estimated_at": max(r["observed_at"] for r in rows), "cutoffs": world.CUTOFF,
                             "clock": at(m["clock_min"]), "how": "Gaussian-process (kriging) estimate of log-grade from drill and blast-hole assays; the interval is the posterior's 10th to 90th percentile"})


@app.get("/v1/fleet", tags=["fleet"], summary="(+) Every truck: status, where the active plan sends it, its last cycles and its engine against its own normal; open maintenance alerts with the anomaly's lead over the breakdown")
def fleet(ctx: Ctx = Depends(auth("mine:read"))):
    with db.tx(ctx.tenant_id) as c:
        m = mine_row(c)
        plan = active_plan(c)
        assign = (plan["plan"].get("assign") or {}) if plan else {}
        trucks = c.execute("SELECT * FROM vehicle ORDER BY id").fetchall()
        out = []
        since = at(m["clock_min"] - 240)
        for v in trucks:
            tel = c.execute("""SELECT at, state, duty, coolant_c, oil_kpa, exhaust_c, z FROM truck_telemetry WHERE truck = %s AND source = 'fleet' AND at >= %s ORDER BY at""",
                            [v["id"], since]).fetchall()
            cyc = c.execute("SELECT count(*) AS n, avg(cycle_min) AS cm, sum(payload_t) AS t FROM haul_event WHERE truck = %s AND ended_at >= %s", [v["id"], since]).fetchone()
            out.append({"truck": v["id"], "status": v["status"], "status_at": v["status_at"], "age_h": v["age_h"], "assigned": assign.get(v["id"]), "last_node": v["last_node"],
                        "cycles_4h": cyc["n"], "mean_cycle_min": round(cyc["cm"], 1) if cyc["cm"] else None, "moved_t_4h": round(cyc["t"] or 0),
                        "engine": [{"at": r["at"], "state": r["state"], "coolant_c": r["coolant_c"], "oil_kpa": r["oil_kpa"], "max_z": round(max(r["z"].values()), 1) if r["z"] else None,
                                    "worst": max(r["z"], key=r["z"].get) if r["z"] else None} for r in tel]})
        alerts = c.execute("SELECT * FROM equipment_alert WHERE status = 'open' ORDER BY raised_at").fetchall()
        metrics = c.execute("SELECT metrics FROM model_artifacts WHERE name = 'engine-anomaly' AND version = %s", [model_version(m)]).fetchone()["metrics"]
    return jsonable_encoder({"clock": at(m["clock_min"]), "trucks": out, "alerts": alerts, "detector": {"model": engine.ANOMALY_VERSION, **metrics}})


# --- dispatch ---------------------------------------------------------------------------------------------------------------
class OptimizeIn(BaseModel):
    horizon_h: float | None = Field(None, gt=0, le=12, description="default: the rest of the shift")
    confidence_z: float = Field(1.0, ge=0, le=3, description="the grade window and arsenic limit are held at estimate +- z sd")
    time_limit_s: float = Field(10.0, gt=0, le=60)


@app.post("/v1/dispatch/optimize", status_code=202, tags=["dispatch"], summary="202 + job: the dispatch MIP over the trucks that are up, from where they are: trucks and a target rate per shovel, where each shovel's high- and low-grade ore goes, stockpile reclaim, the plant's grade window and arsenic limit; returns a draft plan with its objective, optimality gap and solve time, beside the plan in force")
def optimize(body: OptimizeIn, ctx: Ctx = Depends(auth("dispatch:optimize")), idem: str | None = IdemKey):
    def work(c):
        m = mine_row(c)
        if not trucks_up(c):
            raise Problem(409, "no_trucks", "no truck is up")
        return 202, jobs.enqueue(c, ctx, "dispatch.optimize", {**body.model_dump(), "clock": m["clock_min"]})
    return run(ctx, idem, body, work)


@jobs.handler("dispatch.optimize")
def optimize_job(c, job):
    p = job["payload"]
    m = mine_row(c)
    _, s0, s1 = shift_bounds(m)
    H = p["horizon_h"] or (s1 - m["clock_min"]) / 60
    sh = shovels(c)
    est = estimates(c, ahead(sh))
    active = active_plan(c)
    up = [tid for tid, _ in trucks_up(c)]
    assign = active["plan"].get("assign", {}) if active else {}
    groups = {}
    for tid in up:
        groups.setdefault(assign.get(tid), []).append(tid)
    mm = models(m)
    inp = engine.dispatch_inputs(sh, est, travel_for(c, m, sh), mm["fuel"], [{"shovel": k, "trucks": v} for k, v in sorted(groups.items(), key=str)], stock(c), H)
    kept = {tid: assign[tid] for tid in up if assign.get(tid)}
    inp["waste_tph_min"] = engine.waste_floor(inp, kept) if active and active["plan"]["mode"] == "fixed" else None
    res = engine.optimize_dispatch(inp, p["time_limit_s"], p["confidence_z"])
    classes = ore_control(c, sh)
    plan = {"mode": "fixed", "targets": res["targets"], "assign": res["assign"], "trucks": res["trucks"], "route": res["route"], "block_class": classes,
            "reclaim": {"mode": "proportional"}, "reclaim_tph": res["reclaim_tph"]}
    # the plan in force as it stands now (its trucks less those that broke down), for comparison
    base_trucks = {}
    for tid, sid in kept.items():
        base_trucks[sid] = base_trucks.get(sid, 0) + 1
    base_rates = {k: round(v, 1) for k, v in engine.plan_rates_fixed(inp, kept).items()}
    pid = uuid.uuid4()
    h = engine.feature_hash({"inp": [(s["id"], s["mix"], s["src"]) for s in inp["shovels"]], "trucks": up, "stock": inp["stock"]})
    versions = {"dispatch": engine.DISPATCH_VERSION, "cycle_time": engine.CYCLE_VERSION, "grade": model_version(m), "solver": res["solver"]}
    summary = {k: res[k] for k in ("objective_per_h", "bound_per_h", "gap", "solve_ms", "variables", "constraints", "slack", "z", "trucks_available")}
    c.execute("""INSERT INTO dispatch_plan (id, tenant_id, kind, status, plan, summary, inputs_hash, model_versions, created_by)
                 VALUES (%s,%s,'optimized','draft',%s,%s,%s,%s,%s)""", [pid, m["tenant_id"], Jsonb(plan), Jsonb(summary), h, Jsonb(versions), uuid.UUID(p["actor_id"])])
    c.execute("INSERT INTO model_runs (tenant_id, model_name, version, subject, inputs_hash, result) VALUES (%s,%s,%s,%s,%s,%s)",
              [m["tenant_id"], engine.DISPATCH_VERSION, model_version(m), f"plan:{pid}", h, Jsonb(summary)])
    audit.record(c, worker_ctx(job), "dispatch.optimized", "dispatch_plan", pid, {"objective_per_h": res["objective_per_h"], "gap": res["gap"], "solve_ms": res["solve_ms"]})
    rows = []
    for x in inp["shovels"]:
        sid = x["id"]
        rows.append({"shovel": sid, "mix": {k: round(v, 2) for k, v in x["mix"].items()},
                     "grade": {k: {"cu": round(v[0], 3), "cu_sd": round(v[1], 3), "as": round(v[2]), "bwi": round(v[4], 1)} for k, v in x["src"].items()},
                     "baseline": {"trucks": base_trucks.get(sid, 0), "expected_tph": base_rates[sid], "route": active["plan"]["route"][sid] if active else None},
                     "optimized": {"trucks": res["trucks"][sid], "target_tph": res["targets"][sid], "route": res["route"][sid]},
                     "travel_min": {k: round(v, 1) for k, v in x["travel"].items()}})
    return {"plan_id": pid, "status": "draft", "horizon_h": round(H, 2), "trucks_up": len(up), "shovels": rows, "reclaim_tph": res["reclaim_tph"],
            "mill_tph": round(inp["mill_tph"]), "waste_tph_floor": round(inp["waste_tph_min"] or 0), **summary, "inputs_hash": h, "model_versions": versions, "reassigned_trucks": sum(1 for tid in up if res["assign"].get(tid) != assign.get(tid)),
            "how": "trucks are counted per shovel they are on (identical trucks in the same place are interchangeable), so the MIP is exact for the fleet; shovel output follows a finite-source queue on the cycle-time model's travel times"}


class BlendIn(BaseModel):
    plan_id: uuid.UUID
    hours: int = Field(8, ge=1, le=12)
    confidence_z: float = Field(1.28, ge=0, le=3)


@app.post("/v1/blends/solve", status_code=202, tags=["blend"], summary="202 + job: the hour-by-hour crusher blend for a plan: loader reclaim from each stockpile in whole loads and how much of each pit source to feed, inside the grade window and under the arsenic limit with the estimates' spread; beside the proportional blend on the same pit feed. The schedule becomes the plan's reclaim")
def blend(body: BlendIn, ctx: Ctx = Depends(auth("blends:solve")), idem: str | None = IdemKey):
    def work(c):
        mine_row(c)
        pl = c.execute("SELECT status FROM dispatch_plan WHERE id = %s", [body.plan_id]).fetchone()
        if not pl:
            raise Problem(404, "plan_not_found")
        if pl["status"] != "draft":
            raise Problem(409, "plan_not_draft", f"this plan is {pl['status']}; a blend attaches to a draft")
        return 202, jobs.enqueue(c, ctx, "blend.solve", body.model_dump(mode="json"))
    return run(ctx, idem, body, work)


def plan_rates(c, m, plan, sh, est):
    """Expected dig rate per shovel under a plan: its targets, or for fixed assignments the queueing curve at the trucks it has."""
    if plan["mode"] == "targets":
        return plan["targets"]
    up = {tid for tid, _ in trucks_up(c)}
    n = {}
    for tid, sid in plan["assign"].items():
        if tid in up:
            n[sid] = n.get(sid, 0) + 1
    tr = travel_for(c, m, sh)
    out = {}
    for s in sh:
        blocks = engine.horizon_blocks(s["seq"], s["pos"], s["remaining"], s["rate_tph"], 4)
        face = s["seq"][min(s["pos"], len(s["seq"]) - 1)]
        tot = sum(t for _, t in blocks) or 1
        mix_t = sum(t * sum(tr.split(d, face, d, s["id"])) for b, t in blocks for d in [{"HG": "crusher", "LG": "lg", "W": "dump"}[est[b]["cls"]]]) / tot
        k = n.get(s["id"], 0)
        out[s["id"]] = engine.shovel_curve(mix_t, s["load_min"], s["rate_tph"], max(k, 1))[k]
    return out


@jobs.handler("blend.solve")
def blend_job(c, job):
    p = job["payload"]
    m = mine_row(c)
    pl = c.execute("SELECT * FROM dispatch_plan WHERE id = %s", [p["plan_id"]]).fetchone()
    sh = shovels(c)
    est = estimates(c, ahead(sh, 80))
    plan = pl["plan"]
    pit = engine.pit_feed_by_hour(sh, plan_rates(c, m, plan, sh, est), plan["route"], est, p["hours"])
    st = stock(c)
    mill = []
    for h in pit:
        t = sum(v[0] for v in h.values())
        bw = sum(v[0] * v[5] for v in h.values()) / t if t else np.mean([s["bwi"] for s in st.values()])
        mill.append(world.mill_tph(bw))
    res = engine.solve_blend(pit, st, mill, z=p["confidence_z"])
    base = engine.proportional_blend(pit, st, mill)
    lo, hi = PLANT["window"]

    def inside(hours, key="cu"):
        return sum(1 for h in hours if h["cu"] is not None and lo <= h["cu"] <= hi)

    def band_inside(hours):
        return sum(1 for h in hours if h["cu_band"] and lo <= h["cu_band"][0] and h["cu_band"][1] <= hi and h["as_high"] <= world.AS_LIMIT)
    bid = uuid.uuid4()
    params = {"hours": p["hours"], "z": p["confidence_z"], "window": PLANT["window"], "as_limit": world.AS_LIMIT, "unit_t": 50, "min_tph_per_pile": 300}
    c.execute("INSERT INTO blend_plan (id, tenant_id, dispatch_plan_id, hours, baseline, params, objective, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
              [bid, m["tenant_id"], pl["id"], Jsonb(res["hours"]), Jsonb(base["hours"]), Jsonb(params), res["objective"], uuid.UUID(p["actor_id"])])
    sched = [{k: v for k, v in h["reclaim_tph"].items() if v > 0} for h in res["hours"]]
    c.execute("UPDATE dispatch_plan SET plan = jsonb_set(plan, '{reclaim}', %s), summary = jsonb_set(summary, '{blend_plan_id}', %s) WHERE id = %s",
              [Jsonb({"mode": "schedule", "hours": sched}), Jsonb(str(bid)), pl["id"]])
    h = engine.feature_hash({"pit": [{k: v[:2] for k, v in x.items()} for x in pit], "stock": st})
    c.execute("INSERT INTO model_runs (tenant_id, model_name, version, subject, inputs_hash, result) VALUES (%s,%s,%s,%s,%s,%s)",
              [m["tenant_id"], engine.BLEND_VERSION, model_version(m), f"blend:{bid}", h, Jsonb({"objective": res["objective"], "gap": res["gap"]})])
    audit.record(c, worker_ctx(job), "blend.solved", "blend_plan", bid, {"plan": str(pl["id"]), "hours": p["hours"]})
    return {"blend_plan_id": bid, "plan_id": pl["id"], "hours": res["hours"], "baseline_hours": base["hours"], "window": PLANT["window"], "as_limit": world.AS_LIMIT,
            "z": p["confidence_z"], "hours_inside": inside(res["hours"]), "hours_inside_with_spread": band_inside(res["hours"]),
            "baseline_hours_inside": inside(base["hours"]), "baseline_hours_inside_with_spread": band_inside(base["hours"]),
            "reclaim_t": {k: sum(x["reclaim_tph"][k] for x in res["hours"]) for k in st}, "baseline_reclaim_t": {k: sum(x["reclaim_tph"][k] for x in base["hours"]) for k in st},
            "stockpiles": {k: {kk: round(v, 3) for kk, v in s.items()} for k, s in st.items()}, "objective": res["objective"], "gap": res["gap"], "solve_ms": res["solve_ms"],
            "inputs_hash": h, "model": engine.BLEND_VERSION}


# --- the twin ---------------------------------------------------------------------------------------------------------------
class TwinIn(BaseModel):
    plan_ids: list[uuid.UUID] = Field(min_length=2, max_length=4, description="the first is the reference (usually the plan in force)")
    replications: int = Field(20, ge=2, le=100)
    minutes: int | None = Field(None, ge=30, le=720, description="default: the rest of the shift")


@app.post("/v1/twin/simulate", status_code=202, tags=["twin"], summary="202 + job: re-run the rest of the shift in the service's own simulation under each plan, with the cycle-time model's travel times, queues at the shovels and the crusher, block grades drawn from the estimator, and the same random draws for every plan; production, fuel, revenue and the economic objective with their spread and the paired difference")
def twin(body: TwinIn, ctx: Ctx = Depends(auth("twin:run")), idem: str | None = IdemKey):
    def work(c):
        mine_row(c)
        found = {r["id"] for r in c.execute("SELECT id FROM dispatch_plan WHERE id = ANY(%s)", [body.plan_ids])}
        if missing := [str(x) for x in body.plan_ids if x not in found]:
            raise Problem(404, "plan_not_found", ", ".join(missing))
        return 202, jobs.enqueue(c, ctx, "twin.simulate", body.model_dump(mode="json"))
    return run(ctx, idem, body, work)


def twin_ctx(c, m, minutes):
    sh = shovels(c)
    est = estimates(c, ahead(sh, 80))
    mm = models(m)
    tr = travel_for(c, m, sh)
    coef = mm["fuel"]
    st = stock(c)
    return {"minutes": int(minutes), "trucks": trucks_up(c), "shovels": sh, "est": est, "travel_split": lambda frm, face, dest: tr.split(frm, face, dest, tr.face_shovel.get(int(face))),
            "fuel": lambda frm, face, dest, payload, idle: engine.fuel_litres(coef, frm, face, dest, payload, idle), "resid_sd": mm["cycle-time"].resid_sd_,
            "stock": {k: [v["tonnes"], v["cu"], v["as"], v["bwi"]] for k, v in st.items()}, "bin": bin_now(c)}


@jobs.handler("twin.simulate")
def twin_job(c, job):
    p = job["payload"]
    m = mine_row(c)
    _, s0, s1 = shift_bounds(m)
    minutes = p["minutes"] or int(round(s1 - m["clock_min"]))
    rows = {str(r["id"]): r for r in c.execute("SELECT * FROM dispatch_plan WHERE id = ANY(%s)", [p["plan_ids"]])}
    sh = shovels(c)
    classes = ore_control(c, sh)
    plans, names = {}, {}
    for pid in p["plan_ids"]:
        r = rows[pid]
        pl = copy.deepcopy(r["plan"])
        pl["block_class"] = classes                      # both run on today's ore control
        name = f"{r['kind']} ({r['status']})"
        names[name] = pid
        plans[name] = pl
    t_ = time.perf_counter()
    res = engine.twin(twin_ctx(c, m, minutes), plans, reps=p["replications"], seed=int(m["model_seed"]) * 1000 + int(m["clock_min"]))
    sid = uuid.uuid4()
    result = {"simulation_id": sid, "minutes": minutes, "from": at(m["clock_min"]), "replications": p["replications"], "plans": {n: {"plan_id": names[n], **v} for n, v in res.items()},
              "reference": next(iter(plans)), "seconds": round(time.perf_counter() - t_, 1), "model": engine.TWIN_VERSION, "window": PLANT["window"],
              "how": "each replication draws block grades from the estimator's posterior, cycle noise from the cycle-time model's residuals and loading times once, and every plan runs on those same draws; differences are paired"}
    c.execute("INSERT INTO simulation_run (id, tenant_id, request, result, created_by) VALUES (%s,%s,%s,%s,%s)",
              [sid, m["tenant_id"], Jsonb(p), Jsonb(jsonable_encoder(result)), uuid.UUID(p["actor_id"])])
    c.execute("INSERT INTO model_runs (tenant_id, model_name, version, subject, inputs_hash, result) VALUES (%s,%s,%s,%s,%s,%s)",
              [m["tenant_id"], engine.TWIN_VERSION, model_version(m), f"simulation:{sid}", engine.feature_hash(p["plan_ids"]), Jsonb({"replications": p["replications"]})])
    audit.record(c, worker_ctx(job), "twin.simulated", "simulation_run", sid, {"plans": p["plan_ids"], "replications": p["replications"]})
    return result


# --- decisions -------------------------------------------------------------------------------------------------------------------
class ProposeIn(BaseModel):
    simulation_id: uuid.UUID | None = Field(None, description="the twin run that is the evidence")


@app.post("/v1/dispatch/plans/{plan_id}/propose", status_code=201, tags=["decisions"], summary="(+) Propose a draft plan for dispatch, with its twin run as evidence. Policy: the plan must carry a blend schedule and the twin must show it no worse than the plan in force. A proposal changes nothing until a shift supervisor who did not propose it approves")
def propose(plan_id: uuid.UUID, body: ProposeIn, ctx: Ctx = Depends(auth("plans:propose")), idem: str | None = IdemKey):
    def work(c):
        m = mine_row(c)
        pl = c.execute("SELECT * FROM dispatch_plan WHERE id = %s FOR UPDATE", [plan_id]).fetchone()
        if not pl:
            raise Problem(404, "plan_not_found")
        if pl["status"] != "draft":
            raise Problem(409, "plan_not_draft", f"this plan is {pl['status']}")
        checks = {"blend_schedule": pl["plan"].get("reclaim", {}).get("mode") == "schedule"}
        evidence = None
        if body.simulation_id:
            sim = c.execute("SELECT result FROM simulation_run WHERE id = %s", [body.simulation_id]).fetchone()
            if not sim:
                raise Problem(404, "simulation_not_found")
            mine_ = next((v for v in sim["result"]["plans"].values() if v["plan_id"] == str(plan_id)), None)
            if not mine_ or not any(k.startswith("vs_") for k in mine_):
                raise Problem(422, "simulation_does_not_cover_plan", "the twin run must compare this plan with the plan in force")
            diff = next(v for k, v in mine_.items() if k.startswith("vs_"))
            evidence = {"simulation_id": str(body.simulation_id), "net_value_usd": diff["net_value_usd"], "moved_t": diff["moved_t"], "fuel_l": diff["fuel_l"],
                        "revenue_usd": diff["revenue_usd"], "hours_in_window": diff["hours_in_window"]}
            checks["twin_not_worse"] = diff["net_value_usd"]["mean"] >= 0
        else:
            checks["twin_not_worse"] = False
        if not all(checks.values()):
            raise Problem(422, "policy_not_met", ", ".join(k for k, v in checks.items() if not v) + " failed")
        did = uuid.uuid4()
        c.execute("""INSERT INTO decision_record (id, tenant_id, subject_type, subject_id, decision_type, model_versions, inputs_hash, result, confidence, policy_state, proposed_by)
                     VALUES (%s,%s,'dispatch_plan',%s,'dispatch',%s,%s,%s,%s,%s,%s)""",
                  [did, ctx.tenant_id, plan_id, Jsonb(pl["model_versions"]), pl["inputs_hash"], Jsonb({"summary": pl["summary"], "evidence": evidence}),
                   evidence["net_value_usd"]["better_in"] if evidence else None, Jsonb(checks), ctx.actor_id])
        c.execute("UPDATE dispatch_plan SET status = 'proposed' WHERE id = %s", [plan_id])
        audit.record(c, ctx, "plan.proposed", "decision", did, {"plan": str(plan_id), "checks": checks})
        return 201, {"decision_id": did, "plan_id": plan_id, "status": "proposed", "policy_checks": checks, "evidence": evidence, "clock": at(m["clock_min"])}
    return run(ctx, idem, body, work)


@app.post("/v1/decisions/{decision_id}/approve", tags=["decisions"], summary="(+) A shift supervisor approves or rejects a proposed plan; the proposer cannot. On approval the plan is dispatched from the current minute and the plan it replaces is superseded")
def approve(decision_id: uuid.UUID, decision: Literal["approved", "rejected"] = "approved", ctx: Ctx = Depends(auth("decisions:approve")), idem: str | None = IdemKey):
    def work(c):
        m = mine_row(c)
        d = c.execute("SELECT * FROM decision_record WHERE id = %s FOR UPDATE", [decision_id]).fetchone()
        if not d:
            raise Problem(404, "decision_not_found")
        if d["status"] != "proposed":
            raise Problem(409, "already_decided", f"this decision is {d['status']}")
        if d["proposed_by"] == ctx.actor_id:
            raise Problem(403, "proposer_cannot_approve", "a dispatch plan needs a second person")
        c.execute("UPDATE decision_record SET status = %s, decided_by = %s, decided_at = now() WHERE id = %s", [decision, ctx.actor_id, decision_id])
        out = {"decision_id": decision_id, "status": decision, "plan_id": d["subject_id"]}
        if decision == "approved":
            old = active_plan(c)
            c.execute("UPDATE dispatch_plan SET status = 'superseded' WHERE status = 'active'")
            c.execute("UPDATE dispatch_plan SET status = 'active', effective_from_min = %s WHERE id = %s", [m["clock_min"], d["subject_id"]])
            pl = c.execute("SELECT plan FROM dispatch_plan WHERE id = %s", [d["subject_id"]]).fetchone()["plan"]
            _, s0, _ = shift_bounds(m)
            local = m["clock_min"] - s0
            sim = m["sim_state"]
            gp = copy.deepcopy(pl)
            gp["reclaim"] = reclaim_for_world(pl, local)
            sim["plans"].append([local, gp])                 # the dispatch system now runs this plan
            c.execute("UPDATE mine SET sim_state = %s", [Jsonb(sim)])
            out.update(active_from=at(m["clock_min"]), superseded=old["id"] if old else None)
        else:
            c.execute("UPDATE dispatch_plan SET status = 'rejected' WHERE id = %s", [d["subject_id"]])
        audit.record(c, ctx, f"plan.{decision}", "decision", decision_id, {"plan": str(d["subject_id"])})
        return 200, out
    return run(ctx, idem, {"decision": decision}, work)


@app.get("/v1/dispatch/plans", tags=["dispatch"], summary="(+) Dispatch plans: the one in force, drafts, proposals, superseded")
def plans(status: Literal["active", "draft", "proposed", "superseded", "rejected", "all"] = "all", ctx: Ctx = Depends(auth("mine:read"))):
    with db.tx(ctx.tenant_id) as c:
        mine_row(c)
        rows = c.execute("SELECT * FROM dispatch_plan WHERE %s = 'all' OR status = %s ORDER BY created_at", [status, status]).fetchall()
    for r in rows:
        r["plan"] = {k: v for k, v in r["plan"].items() if k != "block_class"}
    return jsonable_encoder({"items": rows})


# --- plant ---------------------------------------------------------------------------------------------------------------------
@app.get("/v1/plant/forecast", tags=["plant"], summary="Mill throughput and feed grade, hour by hour, under a plan (default: the one in force): the plan's pit feed and reclaim, the estimated hardness, the bin; the throughput model against the trailing 12-hour mean")
def plant_forecast(hours: int = Query(8, ge=1, le=12), plan_id: uuid.UUID | None = None, ctx: Ctx = Depends(auth("mine:read"))):
    with db.tx(ctx.tenant_id) as c:
        m = mine_row(c)
        pl = c.execute("SELECT * FROM dispatch_plan WHERE id = %s", [plan_id]).fetchone() if plan_id else active_plan(c)
        if not pl:
            raise Problem(404, "plan_not_found")
        sh = shovels(c)
        est = estimates(c, ahead(sh, 80))
        plan = pl["plan"]
        pit = engine.pit_feed_by_hour(sh, plan_rates(c, m, plan, sh, est), plan["route"], est, hours)
        st = stock(c)
        binv = bin_now(c)
        mm = models(m)
        hist = c.execute("SELECT processed_t, hour_at FROM plant_feed ORDER BY hour_at DESC LIMIT 12").fetchall()
        trailing = float(np.mean([r["processed_t"] for r in hist])) if hist else None
        rc = plan.get("reclaim", {"mode": "proportional"})
        tot = sum(s["tonnes"] for s in st.values())
        out, b = [], binv[0]
        prior = plant_rows(c)
        bws = prior[-1]["bwi_s"] if prior else world.MILL_BASE_BWI
        for h, ph in enumerate(pit):
            pit_t = sum(v[0] for v in ph.values())
            bw = sum(v[0] * v[5] for v in ph.values()) / pit_t if pit_t else float(np.mean([s["bwi"] for s in st.values()]))
            cap = world.mill_tph(bw)
            overflow = any(r.get("HG") == "crusher|hg" for r in plan["route"].values())
            take = {k: v[0] * (min(1.0, cap / pit_t) if overflow and pit_t > cap else 1.0) for k, v in ph.items()}
            pit_t = sum(take.values())
            if rc["mode"] == "schedule":
                rec = rc["hours"][h] if h < len(rc["hours"]) else {}
            else:
                room = max(0.0, cap - pit_t)
                rec = {k: min(world.LOADER_TPH, room) * s["tonnes"] / tot for k, s in st.items()}
            g = engine.blend_grade(ph, take, st, rec, 1.28)
            feed = pit_t + sum(rec.values())
            bws = engine.smooth_bwi([g["bwi"] or bw], bws)[0]
            pred = engine.predict_plant(mm["plant-forecast"], b + feed, bws)
            b = float(np.clip(b + feed - pred, 0, world.BIN_T))
            out.append({"hour": at(m["clock_min"] + 60 * h), "pit_feed_tph": round(pit_t), "reclaim_tph": {k: round(v) for k, v in rec.items()}, "est_bwi": g["bwi"],
                        "forecast_tph": round(pred), "baseline_tph": round(trailing) if trailing else None, "feed_cu": g["cu"], "feed_cu_band": g["cu_band"], "feed_as": g["as"],
                        "inside_window": g["cu"] is not None and PLANT["window"][0] <= g["cu"] <= PLANT["window"][1]})
        h_ = engine.feature_hash([[o["pit_feed_tph"], o["est_bwi"]] for o in out])
        c.execute("INSERT INTO model_runs (tenant_id, model_name, version, subject, inputs_hash, result) VALUES (%s,%s,%s,%s,%s,%s)",
                  [m["tenant_id"], engine.PLANT_VERSION, model_version(m), f"forecast:{pl['id']}", h_, Jsonb({"hours": hours, "mean_tph": round(float(np.mean([o["forecast_tph"] for o in out])))})])
        metrics = c.execute("SELECT metrics FROM model_artifacts WHERE name = 'plant-forecast' AND version = %s", [model_version(m)]).fetchone()["metrics"]
        recent = c.execute("SELECT hour_at, processed_t, feed_cu, feed_as, delivered_t, reclaim_t FROM plant_feed ORDER BY hour_at DESC LIMIT 12").fetchall()
    return jsonable_encoder({"plan_id": pl["id"], "plan_kind": pl["kind"], "plan_status": pl["status"], "hours": out, "recent": list(reversed(recent)), "window": PLANT["window"],
                             "as_limit": world.AS_LIMIT, "model": engine.PLANT_VERSION, "version": model_version(m), "inputs_hash": h_, "test_metrics": metrics,
                             "mean_forecast_tph": round(float(np.mean([o["forecast_tph"] for o in out]))), "hours_inside_window": sum(o["inside_window"] for o in out)})


@app.get("/v1/decisions", tags=["decisions"], summary="(+) Proposals and decisions")
def decisions(ctx: Ctx = Depends(auth("mine:read"))):
    with db.tx(ctx.tenant_id) as c:
        return jsonable_encoder({"items": c.execute("SELECT id, subject_type, subject_id, status, policy_state, proposed_by, decided_by, created_at, decided_at FROM decision_record ORDER BY created_at DESC").fetchall()})
