"""Public API (modular monolith). Blueprint services map to: equipment-gateway and wafer-lineage (lot ingest, lots, wafers,
process events), feature-pipeline (map features, sensor deviations from qualified chamber baselines), defect-vision (the
wafer-map pattern classifier), yield-forecast (yield before test), root-cause-graph (commonality across shared chambers,
change-point evidence, pattern-to-step priors), experiment-service (counterfactual re-runs) and alert-service (drift and
excursion alerts). Not built: inspection imagery, a CNN, Kafka/Flink/ClickHouse; see the README.

    uvicorn fab.api:app          python -m core.jobs fab.api      # the worker
"""
import datetime
import functools
import pickle
import uuid
from typing import Literal

import numpy as np
from fastapi import Depends, Header, Query
from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from core import audit, db, jobs
from core.app import Ctx, Problem, create_app, run

from . import engine, world

READ = {"fab:read", "jobs:read"}
ENGINEER = READ | {"lots:ingest", "analysis:run", "scenarios:run", "decisions:propose", "models:predict"}
PERMISSIONS = {"viewer": READ, "process_engineer": ENGINEER,
               "yield_manager": ENGINEER | {"fab:load", "fab:advance", "decisions:approve", "audit:read"}}
app = create_app("fab-yield-intelligence", PERMISSIONS)
auth = app.state.auth
IdemKey = Header(None, alias="Idempotency-Key")
START = datetime.datetime(2026, 8, 3, 0, 0, tzinfo=datetime.UTC)
HISTORY_LOTS, HISTORY_FAULTS, TEST_FROM = 448, 14, 336      # eight weeks of history; the last two score the models
DIE_VALUE = 42.0                                             # dollars per good die, for the counterfactual's value line
EXCURSION_WINDOW, EXCURSION_MIN = 8, 8                       # an excursion alert: >= 8 wafers with one pattern in the last 8 lots


def at(hours):
    return START + datetime.timedelta(hours=float(hours))


def worker_ctx(job):
    return Ctx(job["tenant_id"], uuid.UUID(job["payload"]["actor_id"]), "worker", "system")


def fab(c):
    f = c.execute("SELECT * FROM fabs").fetchone()
    if not f:
        raise Problem(409, "no_fab", "load a fab first: POST /v1/fab:load")
    return f


@functools.lru_cache(maxsize=16)
def _models(tenant_id, version):
    with db.tx(tenant_id) as c:
        rows = {r["name"]: pickle.loads(r["artifact"]) for r in c.execute("SELECT name, artifact FROM model_artifacts WHERE version = %s", [version])}
    return rows


def models(c, f):
    m = _models(str(f["tenant_id"]), model_version(f))
    m["baselines"] = {r["id"]: r["baseline"] for r in c.execute("SELECT id, baseline FROM chambers")}
    return m


def model_version(f):
    return f"fab-{str(f['id'])[:8]}-1"


# --- loading the fab ---------------------------------------------------------------------------------------------------
class LoadIn(BaseModel):
    seed: int = Field(7, ge=1, le=10 ** 6)


@app.post("/v1/fab:load", status_code=202, tags=["fab"], summary="(+) Load the synthetic fab: eight weeks of lots with their sensors and test maps, engineers' pattern labels on the history, chamber baselines from the qualification week; train and register the models and report them against their baselines")
def load_fab(body: LoadIn, ctx: Ctx = Depends(auth("fab:load")), idem: str | None = IdemKey):
    def work(c):
        if c.execute("SELECT 1 FROM fabs").fetchone():
            raise Problem(409, "fab_exists", "this tenant already has a fab; `make reset` for a fresh demo")
        return 202, jobs.enqueue(c, ctx, "fab.load", body.model_dump())
    return run(ctx, idem, body, work)


def lot_rows(t, lots, source="equipment"):
    lot_r, wafer_r, ev_r, recs = [], [], [], []
    for lot in lots:
        lot_r.append((t, lot["lot"], lot["index"], lot["product"], at(lot["start_h"]), "active", source))
        for w in lot["wafers"]:
            wid = uuid.uuid5(t, f"{lot['lot']}:{w['slot']}")
            wafer_r.append([wid, t, lot["lot"], w["slot"], [int(b) for b in w["bins"]], w["yield"], w.get("truth_pattern") if source == "history" else None])
            for st in w["steps"]:
                ev_r.append((t, wid, st["step"], st["chamber"], st["recipe"], at(st["at_h"]), Jsonb(st["sensors"])))
            recs.append({"id": wid, "lot_index": lot["index"], "lot": lot["lot"], "product": lot["product"], "steps": w["steps"], "bins": w["bins"], "yield": w["yield"]})
    return lot_r, wafer_r, ev_r, recs


def store(c, t, lots, source):
    lot_r, wafer_r, ev_r, recs = lot_rows(t, lots, source)
    db.load(c, "lots", ["tenant_id", "id", "lot_index", "product", "started_at", "status", "source"], lot_r)
    db.load(c, "wafers", ["id", "tenant_id", "lot_id", "slot", "die_bins", "yield", "label"], wafer_r)
    db.load(c, "process_events", ["tenant_id", "wafer_id", "step", "chamber_id", "recipe_id", "at", "sensors"], ev_r)
    return recs


def score(c, m, version, recs, log=True):
    """Classify each wafer's map and predict its yield from its sensors; store both, log every inference."""
    if not recs:
        return []
    X = np.array([engine.map_features(r["bins"]) for r in recs])
    pats, confs = engine.classify(m["wafer-pattern-classifier"], X)
    Xy = np.array([engine.yield_features(r["steps"], m["baselines"], r["product"]) for r in recs])
    pred = np.clip(m["yield-predictor"].predict(Xy), 0, 1)
    c.execute("CREATE TEMP TABLE _score (id uuid, pattern text, conf float8, py float8) ON COMMIT DROP")
    db.copy(c, "_score", ["id", "pattern", "conf", "py"], [(r["id"], p, cf, float(py)) for r, p, cf, py in zip(recs, pats, confs, pred)])
    c.execute("UPDATE wafers w SET pattern = s.pattern, pattern_conf = s.conf, predicted_yield = s.py, model_version = %s FROM _score s WHERE w.id = s.id", [version])
    c.execute("DROP TABLE _score")
    if log:
        runs = []
        for r, p, cf, py, x, xy in zip(recs, pats, confs, pred, X, Xy):
            runs.append((r["tenant_id"], engine.CLASSIFIER_VERSION, version, f"wafer:{r['id']}", engine.feature_hash(x), Jsonb({"pattern": p, "confidence": cf})))
            runs.append((r["tenant_id"], engine.YIELD_VERSION, version, f"wafer:{r['id']}", engine.feature_hash(xy), Jsonb({"predicted_yield": round(float(py), 4)})))
        db.load(c, "model_runs", ["tenant_id", "model_name", "version", "subject", "inputs_hash", "result"], runs)
    return list(zip(pats, confs, pred))


@jobs.handler("fab.load")
def load_job(c, job):
    t, seed = job["tenant_id"], job["payload"]["seed"]
    fid = uuid.uuid5(t, "fab")
    faults = world.random_faults(seed, HISTORY_LOTS, HISTORY_FAULTS)
    lots = world.run(seed, 0, HISTORY_LOTS, faults)
    c.execute("INSERT INTO fabs (id, tenant_id, name, model_seed, next_lot, told, qualification_lots) VALUES (%s,%s,'Northgate Fab 2',%s,%s,%s,%s)",
              [fid, t, seed, HISTORY_LOTS, Jsonb(faults), world.QUALIFICATION_LOTS])
    db.load(c, "tools", ["tenant_id", "id", "step"], sorted({(t, tool, s) for _, tool, s in world.CHAMBERS}))
    recipes = [(t, f"{s.upper()}-{p}-R3", s, p, Jsonb({k: v[0][p] for k, v in world.SENSORS[s].items()})) for s in world.STEPS for p in world.PRODUCTS]
    db.load(c, "recipes", ["tenant_id", "id", "step", "product", "setpoints"], recipes)
    recs = store(c, t, lots, "history")
    for r, lot_w in zip(recs, (w for lot in lots for w in lot["wafers"])):
        r["label"] = lot_w["truth_pattern"]                  # engineers labelled the history's maps
    fitted = engine.fit(recs, TEST_FROM)
    db.load(c, "chambers", ["tenant_id", "id", "tool_id", "step", "status", "baseline"],
            [(t, ch, tool, s, "up", Jsonb(fitted["baselines"][ch])) for ch, tool, s in world.CHAMBERS])
    version = f"fab-{str(fid)[:8]}-1"
    snapshot = f"lots 0-{HISTORY_LOTS - 1} (train < {TEST_FROM}), {len(recs)} wafers, seed {seed}"
    for name, obj, metrics in (("wafer-pattern-classifier", fitted["classifier"], fitted["metrics"]["classifier"]),
                               ("yield-predictor", fitted["yield"], fitted["metrics"]["yield"]),
                               ("root-cause-priors", fitted["priors"], {"pattern_to_step": fitted["priors"]})):
        c.execute("INSERT INTO model_artifacts (tenant_id, name, version, data_snapshot, metrics, artifact, approved) VALUES (%s,%s,%s,%s,%s,%s,true)",
                  [t, name, version, snapshot, Jsonb(metrics), pickle.dumps(obj)])
    m = {"wafer-pattern-classifier": fitted["classifier"], "yield-predictor": fitted["yield"], "baselines": fitted["baselines"]}
    for r in recs:
        r["tenant_id"] = t
    score(c, m, version, recs, log=False)
    out = {"fab_id": fid, "lots": HISTORY_LOTS, "wafers": len(recs), "process_events": len(recs) * len(world.STEPS), "die_measurements": len(recs) * world.N_DIES,
           "tools": len({tool for _, tool, _ in world.CHAMBERS}), "chambers": len(world.CHAMBERS), "dies_per_wafer": world.N_DIES,
           "clock": at(HISTORY_LOTS * 24 / world.LOTS_PER_DAY), "models": {"version": version, **fitted["metrics"], "pattern_to_step_prior": fitted["priors"]},
           "history_excursions": len(faults)}
    audit.record(c, worker_ctx(job), "fab.loaded", "fab", fid, {"lots": HISTORY_LOTS, "wafers": len(recs), "model_version": version})
    return out


# --- the clock moves ----------------------------------------------------------------------------------------------------
class Inject(BaseModel):
    kind: Literal["etch_temp_drift", "cmp_pad_wear", "litho_focus_drift", "depo_flow_fault", "implant_dose_fault"]
    chamber: str
    after_lots: int = Field(0, ge=0, le=100)
    rate_per_lot: float = Field(gt=0, le=50)
    max: float = Field(gt=0, le=100)

    @field_validator("chamber")
    @classmethod
    def known(cls, v):
        if v not in world.CHAMBER_STEP:
            raise ValueError("unknown chamber")
        return v


class AdvanceIn(BaseModel):
    lots: int = Field(ge=1, le=100)
    inject: Inject | None = None


@app.post("/v1/fab:advance", status_code=202, tags=["fab"], summary="(+) Process more lots. The generator can be told about a fault (the demo's injection); the service sees sensors and test maps, never the telling")
def advance(body: AdvanceIn, ctx: Ctx = Depends(auth("fab:advance")), idem: str | None = IdemKey):
    def work(c):
        f = fab(c)
        if body.inject and world.FAULTS[body.inject.kind][0] != world.CHAMBER_STEP[body.inject.chamber]:
            raise Problem(422, "fault_does_not_fit_chamber", f"{body.inject.kind} happens at {world.FAULTS[body.inject.kind][0]}, not {world.CHAMBER_STEP[body.inject.chamber]}")
        return 202, jobs.enqueue(c, ctx, "fab.advance", {**body.model_dump(), "from_lot": f["next_lot"]})
    return run(ctx, idem, body, work)


def check_alerts(c, f, m, lot_index):
    """After a lot: a change-point on any chamber that ran it, and an excursion if a pattern is piling up."""
    raised = []
    for ch in [r["chamber_id"] for r in c.execute("""SELECT DISTINCT p.chamber_id FROM process_events p JOIN wafers w ON w.id = p.wafer_id
                                                     JOIN lots l ON l.id = w.lot_id WHERE l.lot_index = %s""", [lot_index])]:
        if c.execute("SELECT 1 FROM alerts WHERE kind = 'drift' AND chamber_id = %s AND status = 'open'", [ch]).fetchone():
            continue
        z, lots_of, sensor = chamber_series(c, m, ch, 600)
        new = [i for i in engine.drift_alarms(z) if lots_of[i] == lot_index]
        if new:
            shift = float(np.mean(z[-10:]) * sensor_sd(m, ch, sensor))
            aid = uuid.uuid4()
            c.execute("INSERT INTO alerts (id, tenant_id, kind, chamber_id, first_lot, detail) VALUES (%s,%s,'drift',%s,%s,%s)",
                      [aid, f["tenant_id"], ch, lot_index, Jsonb({"sensor": sensor, "shift": round(shift, 3), "shift_sd": round(float(np.mean(z[-10:])), 1),
                                                                  "rule": "Bayesian online change-point, P(run <= 5) > 0.5 with a shift above 2 sd"})])
            raised.append({"kind": "drift", "chamber": ch, "id": aid})
    recent = c.execute("""SELECT w.pattern, count(*) AS n, count(*) FILTER (WHERE l.lot_index = %s) AS now FROM wafers w JOIN lots l ON l.id = w.lot_id
                           WHERE l.lot_index > %s AND l.lot_index <= %s GROUP BY w.pattern""", [lot_index, lot_index - EXCURSION_WINDOW, lot_index]).fetchall()
    for r in recent:          # still happening (seen in this lot) and piling up
        if r["pattern"] in (*engine.EXCURSION_PATTERNS, "review") and r["n"] >= EXCURSION_MIN and r["now"] and not c.execute(
                "SELECT 1 FROM alerts WHERE kind = 'excursion' AND pattern = %s AND status = 'open'", [r["pattern"]]).fetchone():
            aid = uuid.uuid4()
            c.execute("INSERT INTO alerts (id, tenant_id, kind, pattern, first_lot, detail) VALUES (%s,%s,'excursion',%s,%s,%s)",
                      [aid, f["tenant_id"], r["pattern"], lot_index, Jsonb({"wafers": r["n"], "window_lots": EXCURSION_WINDOW,
                                                                             "rule": f">= {EXCURSION_MIN} wafers classified {r['pattern']} in the last {EXCURSION_WINDOW} lots, including this one"})])
            raised.append({"kind": "excursion", "pattern": r["pattern"], "id": aid})
    return raised


def chamber_series(c, m, ch, last):
    """The chamber's primary sensor over its last runs, in standard deviations from its qualified baseline for each run's product."""
    sensor = world.PRIMARY[world.CHAMBER_STEP[ch]]
    rows = c.execute("""SELECT * FROM (SELECT (p.sensors->>%s)::float8 AS v, l.lot_index, l.product, p.at, w.slot FROM process_events p
                          JOIN wafers w ON w.id = p.wafer_id JOIN lots l ON l.id = w.lot_id
                         WHERE p.chamber_id = %s ORDER BY p.at DESC, w.slot DESC LIMIT %s) x ORDER BY at, slot""", [sensor, ch, last]).fetchall()
    b = m["baselines"][ch]
    return np.array([(r["v"] - b[r["product"]][sensor][0]) / b[r["product"]][sensor][1] for r in rows]), [r["lot_index"] for r in rows], sensor


def sensor_sd(m, ch, sensor):
    return float(np.mean([v[sensor][1] for v in m["baselines"][ch].values()]))


def ingest(c, f, m, lots, source):
    """The equipment gateway's path for every new lot: store, score, then check alerts lot by lot."""
    t, version = f["tenant_id"], model_version(f)
    recs = store(c, t, lots, source)
    for r in recs:
        r["tenant_id"] = t
    scored = score(c, m, version, recs)
    out, k = [], 0
    for lot in lots:
        n = len(lot["wafers"])
        part = scored[k:k + n]
        k += n
        alerts = check_alerts(c, f, m, lot["index"])
        pats = {}
        for p, _, _ in part:
            pats[p] = pats.get(p, 0) + 1
        out.append({"lot": lot["lot"], "index": lot["index"], "product": lot["product"], "wafers": n, "yield": round(float(np.mean([w["yield"] for w in lot["wafers"]])), 4),
                    "predicted_yield": round(float(np.mean([py for _, _, py in part])), 4), "patterns": pats, "alerts_raised": alerts,
                    "route": lot.get("route") or {st["step"]: st["chamber"] for st in lot["wafers"][0]["steps"]}})
    return out


@jobs.handler("fab.advance")
def advance_job(c, job):
    p = job["payload"]
    f = fab(c)
    told = list(f["told"])
    if p.get("inject"):
        inj = p["inject"]
        told.append({"kind": inj["kind"], "chamber": inj["chamber"], "start_lot": p["from_lot"] + inj["after_lots"], "end_lot": None,
                     "rate_per_lot": inj["rate_per_lot"], "max": inj["max"]})
    held = [r["id"] for r in c.execute("SELECT id FROM chambers WHERE status = 'hold' ORDER BY id")]
    lots = world.run(f["model_seed"], p["from_lot"], p["from_lot"] + p["lots"], told, route_around=held[0] if held else None)
    m = models(c, f)
    summary = ingest(c, f, m, lots, "equipment")
    c.execute("UPDATE fabs SET next_lot = %s, told = %s", [p["from_lot"] + p["lots"], Jsonb(told)])
    audit.record(c, worker_ctx(job), "fab.advanced", "fab", f["id"], {"lots": p["lots"], "from_lot": p["from_lot"], "alerts": sum(len(s["alerts_raised"]) for s in summary)})
    return {"from_lot": p["from_lot"], "lots": summary, "clock": at((p["from_lot"] + p["lots"]) * 24 / world.LOTS_PER_DAY),
            "simulation_truth": {"told": told[len(f["told"]):], "held_chambers_routed_around": held,
                                 "note": "what the generator was told; the analysis never reads this"}}


# --- equipment gateway: external lots ------------------------------------------------------------------------------------
class StepIn(BaseModel):
    step: str
    chamber: str
    recipe: str
    sensors: dict[str, float]


class WaferIn(BaseModel):
    slot: int = Field(ge=1, le=25)
    steps: list[StepIn]
    die_bins: str = Field(description=f"one digit per die in the fixed die order ({world.N_DIES} dies)")


class LotIn(BaseModel):
    lot: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")
    product: Literal["P1", "P2"]
    wafers: list[WaferIn] = Field(min_length=1, max_length=25)


class IngestIn(BaseModel):
    lots: list[LotIn] = Field(min_length=1, max_length=50)


def validate_lot(c, lot):
    """-> reason it is refused, or None."""
    if c.execute("SELECT 1 FROM lots WHERE id = %s", [lot.lot]).fetchone():
        return "lot already ingested"
    if len({w.slot for w in lot.wafers}) != len(lot.wafers):
        return "duplicate slot"
    held = {r["id"] for r in c.execute("SELECT id FROM chambers WHERE status = 'hold'")}
    valid_bins = set("".join(str(b) for b in world.BINS.values()))
    for w in lot.wafers:
        if [s.step for s in w.steps] != world.STEPS:
            return f"slot {w.slot}: steps must be {', '.join(world.STEPS)} in order"
        for s in w.steps:
            if world.CHAMBER_STEP.get(s.chamber) != s.step:
                return f"slot {w.slot}: unknown chamber {s.chamber} for {s.step}"
            if s.chamber in held:
                return f"slot {w.slot}: chamber {s.chamber} is on hold"
            if set(s.sensors) != set(world.SENSORS[s.step]):
                return f"slot {w.slot}: {s.step} needs sensors {', '.join(world.SENSORS[s.step])}"
        if len(w.die_bins) != world.N_DIES or not set(w.die_bins) <= valid_bins:
            return f"slot {w.slot}: die_bins must be {world.N_DIES} digits from {''.join(sorted(valid_bins))}"
    return None


@app.post("/v1/lots/ingest", status_code=201, tags=["lots"], summary="Lots from the equipment gateway: per-wafer route with sensor summaries and the die test map. Each lot is validated on its own; accepted lots are classified, yield-scored and checked for alerts like any other")
def ingest_lots(body: IngestIn, ctx: Ctx = Depends(auth("lots:ingest")), idem: str | None = IdemKey):
    def work(c):
        f = fab(c)
        m = models(c, f)
        accepted, refused = [], []
        for lot in body.lots:
            why = validate_lot(c, lot)
            if why:
                refused.append({"lot": lot.lot, "why": why})
                continue
            idx = f["next_lot"] + len(accepted)
            wafers = [{"slot": w.slot, "bins": np.array([int(ch) for ch in w.die_bins], np.int16),
                       "yield": float(np.mean([ch == "1" for ch in w.die_bins])),
                       "steps": [{"step": s.step, "chamber": s.chamber, "recipe": s.recipe, "sensors": s.sensors,
                                  "at_h": idx * 24 / world.LOTS_PER_DAY + k * world.HOURS_PER_STEP} for k, s in enumerate(w.steps)]} for w in lot.wafers]
            accepted.append({"index": idx, "lot": lot.lot, "product": lot.product, "start_h": idx * 24 / world.LOTS_PER_DAY, "wafers": wafers})
        summary = ingest(c, f, m, accepted, "ingest") if accepted else []
        if accepted:
            c.execute("UPDATE fabs SET next_lot = next_lot + %s", [len(accepted)])
        audit.record(c, ctx, "lots.ingested", "lot", ",".join(a["lot"] for a in accepted) or "-", {"accepted": len(accepted), "refused": refused})
        return 201, {"accepted": summary, "refused": refused}
    return run(ctx, idem, body, work)


# --- reading the fab -------------------------------------------------------------------------------------------------------
@app.get("/v1/fab/overview", tags=["fab"], summary="(+) The command centre: yield and patterns by lot, open alerts, chambers on hold, quarantined lots, the models in production")
def overview(last: int = Query(60, ge=5, le=500), ctx: Ctx = Depends(auth("fab:read"))):
    with db.tx(ctx.tenant_id) as c:
        f = fab(c)
        lots = c.execute("""SELECT l.id AS lot, l.lot_index, l.product, l.status, avg(w.yield) AS yield, avg(w.predicted_yield) AS predicted_yield, count(*) AS wafers
                              FROM lots l JOIN wafers w ON w.lot_id = l.id GROUP BY l.tenant_id, l.id ORDER BY l.lot_index DESC LIMIT %s""", [last]).fetchall()
        pats = c.execute("""SELECT l.lot_index, w.pattern, count(*) AS n FROM wafers w JOIN lots l ON l.id = w.lot_id
                             WHERE l.lot_index > %s GROUP BY 1, 2""", [f["next_lot"] - last - 1]).fetchall()
        by = {}
        for r in pats:
            by.setdefault(r["lot_index"], {})[r["pattern"]] = r["n"]
        alerts = c.execute("SELECT id, kind, pattern, chamber_id, first_lot, detail, status, raised_at FROM alerts ORDER BY raised_at DESC LIMIT 20").fetchall()
        held = [r["id"] for r in c.execute("SELECT id FROM chambers WHERE status = 'hold'")]
        q = c.execute("SELECT count(*) AS n FROM lots WHERE status = 'quarantined'").fetchone()["n"]
        models_ = c.execute("SELECT name, version, data_snapshot, metrics, approved FROM model_artifacts ORDER BY name").fetchall()
        hist = c.execute("SELECT avg(yield) AS y FROM wafers w JOIN lots l ON l.id = w.lot_id WHERE l.lot_index < %s", [HISTORY_LOTS]).fetchone()["y"]
    return jsonable_encoder({"lots_processed": f["next_lot"], "clock": at(f["next_lot"] * 24 / world.LOTS_PER_DAY), "history_mean_yield": round(hist, 4),
                             "lots": [{**r, "yield": round(r["yield"], 4), "predicted_yield": round(r["predicted_yield"], 4),
                                       "patterns": by.get(r["lot_index"], {})} for r in reversed(lots)],
                             "open_alerts": [a for a in alerts if a["status"] == "open"], "chambers_on_hold": held, "quarantined_lots": q,
                             "models": [{**m_, "metrics": m_["metrics"] if m_["name"] != "root-cause-priors" else None} for m_ in models_]})


@app.get("/v1/lots/{lot_id}", tags=["lots"], summary="(+) One lot: status, route and every wafer's yield, pattern and confidence")
def lot_detail(lot_id: str, ctx: Ctx = Depends(auth("fab:read"))):
    with db.tx(ctx.tenant_id) as c:
        lot = c.execute("SELECT * FROM lots WHERE id = %s", [lot_id]).fetchone()
        if not lot:
            raise Problem(404, "lot_not_found")
        ws = c.execute("""SELECT w.id, w.slot, w.yield, w.predicted_yield, w.pattern, w.pattern_conf, w.label,
                                 jsonb_object_agg(p.step, p.chamber_id) AS route
                            FROM wafers w JOIN process_events p ON p.wafer_id = w.id WHERE w.lot_id = %s GROUP BY w.id ORDER BY w.slot""", [lot_id]).fetchall()
    return jsonable_encoder({**lot, "wafers": ws})


@app.get("/v1/wafers/{wafer_id}/map", tags=["wafers"], summary="A wafer's die map (x, y, test bin), the classifier's call with its confidence and model version, and the route that made it")
def wafer_map(wafer_id: uuid.UUID, ctx: Ctx = Depends(auth("fab:read"))):
    with db.tx(ctx.tenant_id) as c:
        w = c.execute("SELECT * FROM wafers WHERE id = %s", [wafer_id]).fetchone()
        if not w:
            raise Problem(404, "wafer_not_found")
        steps = c.execute("SELECT step, chamber_id, recipe_id, at, sensors FROM process_events WHERE wafer_id = %s ORDER BY at", [wafer_id]).fetchall()
    return jsonable_encoder({"wafer_id": w["id"], "lot": w["lot_id"], "slot": w["slot"], "yield": round(w["yield"], 4), "predicted_yield": w["predicted_yield"],
                             "pattern": w["pattern"], "confidence": w["pattern_conf"], "label": w["label"], "model_version": w["model_version"],
                             "bins_legend": {str(v): k for k, v in world.BINS.items()},
                             "dies": [[int(x), int(y), int(b)] for x, y, b in zip(world.DIE_X, world.DIE_Y, w["die_bins"])], "route": steps})


@app.get("/v1/tools/{tool_id}/health", tags=["tools"], summary="A tool's chambers: status, qualified baseline, the primary sensor's recent runs as deviations, the change-point probability and alarms, open alerts")
def tool_health(tool_id: str, runs: int = Query(300, ge=20, le=2000), ctx: Ctx = Depends(auth("fab:read"))):
    with db.tx(ctx.tenant_id) as c:
        f = fab(c)
        chs = c.execute("SELECT * FROM chambers WHERE tool_id = %s ORDER BY id", [tool_id]).fetchall()
        if not chs:
            raise Problem(404, "tool_not_found")
        m = models(c, f)
        out = []
        for ch in chs:
            z, lots_of, sensor = chamber_series(c, m, ch["id"], runs)
            cp, mean = engine.bocpd(z)
            alarms = engine.drift_alarms(z)
            sd = sensor_sd(m, ch["id"], sensor)
            step = max(1, len(z) // 150)
            out.append({"chamber": ch["id"], "status": ch["status"], "sensor": sensor,
                        "baseline": {p: {"median": round(v[sensor][0], 3), "sd": round(v[sensor][1], 4)} for p, v in sorted(ch["baseline"].items())},
                        "series": [{"lot": lots_of[i], "deviation_sd": round(float(z[i]), 2), "change_point_prob": round(float(cp[i]), 3)} for i in range(0, len(z), step)],
                        "alarms_at_lots": sorted({lots_of[i] for i in alarms}), "current_shift": round(float(np.mean(z[-10:]) * sd), 3) if len(z) else 0,
                        "open_alerts": c.execute("SELECT id, kind, first_lot, detail FROM alerts WHERE chamber_id = %s AND status = 'open'", [ch["id"]]).fetchall()})
    return jsonable_encoder({"tool": tool_id, "step": chs[0]["step"], "chambers": out})


@app.get("/v1/alerts", tags=["alerts"], summary="(+) Alerts, newest first")
def alerts(status: Literal["open", "closed", "all"] = "open", kind: Literal["excursion", "drift", "all"] = "all", ctx: Ctx = Depends(auth("fab:read"))):
    with db.tx(ctx.tenant_id) as c:
        rows = c.execute("""SELECT * FROM alerts WHERE (%s = 'all' OR status = %s) AND (%s = 'all' OR kind = %s)
                             ORDER BY raised_at DESC, first_lot DESC""", [status, status, kind, kind]).fetchall()
    return jsonable_encoder({"items": rows})


# --- analysis -------------------------------------------------------------------------------------------------------------
class RootCauseIn(BaseModel):
    alert_id: uuid.UUID
    lookback_lots: int = Field(6, ge=0, le=60)


@app.post("/v1/analysis/root-cause", status_code=202, tags=["analysis"], summary="Rank every chamber for an excursion: commonality with the affected wafers within each step, change-points on the chamber's sensor, and how often the pattern came from that step in the history. Returns the evidence, a confidence, the lots exposed and the chamber's estimated drift")
def root_cause(body: RootCauseIn, ctx: Ctx = Depends(auth("analysis:run")), idem: str | None = IdemKey):
    def work(c):
        fab(c)
        a = c.execute("SELECT * FROM alerts WHERE id = %s", [body.alert_id]).fetchone()
        if not a:
            raise Problem(404, "alert_not_found")
        if a["kind"] != "excursion":
            raise Problem(422, "not_an_excursion", "root cause runs on an excursion alert (a pattern); drift alerts are evidence for it")
        return 202, jobs.enqueue(c, ctx, "analysis.root_cause", {**body.model_dump(mode="json")})
    return run(ctx, idem, body, work)


@jobs.handler("analysis.root_cause")
def root_cause_job(c, job):
    p = job["payload"]
    f = fab(c)
    m = models(c, f)
    a = c.execute("SELECT * FROM alerts WHERE id = %s", [p["alert_id"]]).fetchone()
    lo, hi = a["first_lot"] - EXCURSION_WINDOW - p["lookback_lots"], f["next_lot"] - 1
    rows = c.execute("""SELECT w.id, w.pattern, w.yield, l.lot_index, l.id AS lot, jsonb_object_agg(e.step, e.chamber_id) AS route
                          FROM wafers w JOIN lots l ON l.id = w.lot_id JOIN process_events e ON e.wafer_id = w.id
                         WHERE l.lot_index BETWEEN %s AND %s GROUP BY w.id, l.lot_index, l.id ORDER BY l.lot_index, w.slot""", [lo, hi]).fetchall()
    ws = [{"affected": r["pattern"] == a["pattern"], "route": r["route"]} for r in rows]
    drifting = {r["chamber_id"] for r in c.execute("SELECT chamber_id FROM alerts WHERE kind = 'drift' AND first_lot BETWEEN %s AND %s", [lo - 12, hi])}
    ranking = engine.root_cause(ws, a["pattern"], m["root-cause-priors"], drifting)
    top = ranking[0]
    since = c.execute("SELECT min(first_lot) AS l FROM alerts WHERE kind = 'drift' AND chamber_id = %s", [top["chamber"]]).fetchone()["l"]
    if since is None:
        since = min([r["lot_index"] for r in rows if r["pattern"] == a["pattern"] and r["route"][top["step"]] == top["chamber"]] or [lo])
    exposed = sorted({r["lot"] for r in rows if r["lot_index"] >= since and r["route"][top["step"]] == top["chamber"]})
    z, _, sensor = chamber_series(c, m, top["chamber"], 25)
    sd = sensor_sd(m, top["chamber"], sensor)
    drift = {"chamber": top["chamber"], "sensor": sensor, "deviation": round(float(np.median(z) * sd), 3), "over_runs": len(z),
             "suggested_recipe_offset": {sensor: round(-float(np.median(z) * sd), 3)}}
    cid = uuid.uuid4()
    versions = {"classifier": engine.CLASSIFIER_VERSION, "priors": model_version(f), "ranking": "commonality+changepoint+prior-1"}
    c.execute("""INSERT INTO root_cause_cases (id, tenant_id, alert_id, pattern, window_lots, ranking, top_chamber, confidence, affected_lots, estimated_drift, model_versions, created_by)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
              [cid, f["tenant_id"], a["id"], a["pattern"], [lo, hi], Jsonb(ranking), top["chamber"], top["confidence"], exposed, Jsonb(drift), Jsonb(versions), uuid.UUID(p["actor_id"])])
    audit.record(c, worker_ctx(job), "root_cause.ranked", "root_cause_case", cid, {"alert": str(a["id"]), "top": top["chamber"], "confidence": top["confidence"]})
    return {"case_id": cid, "pattern": a["pattern"], "window_lots": [lo, hi], "wafers_in_window": len(ws), "affected_wafers": sum(w["affected"] for w in ws),
            "ranking": ranking[:8], "top": top, "drifting_chambers": sorted(drifting), "exposed_since_lot": since, "exposed_lots": exposed,
            "estimated_drift": drift, "model_versions": versions,
            "example_wafer": next((r["id"] for r in reversed(rows) if r["pattern"] == a["pattern"] and r["route"][top["step"]] == top["chamber"]), None),
            "how": "commonality is computed within each step, so a chamber is compared with the other chambers that could have run the same wafers"}


class QuarantineIn(BaseModel):
    hold_chamber: bool = True


@app.post("/v1/cases/{case_id}/quarantine", status_code=201, tags=["decisions"], summary="(+) Propose a quarantine of the lots exposed to the top-ranked chamber (and a hold on the chamber). A proposal changes nothing until a yield manager who did not propose it approves")
def propose_quarantine(case_id: uuid.UUID, body: QuarantineIn, ctx: Ctx = Depends(auth("decisions:propose")), idem: str | None = IdemKey):
    def work(c):
        case = c.execute("SELECT * FROM root_cause_cases WHERE id = %s", [case_id]).fetchone()
        if not case:
            raise Problem(404, "case_not_found")
        lots = c.execute("""SELECT l.id, avg(w.yield) AS y, avg(w.predicted_yield) AS py, count(*) FILTER (WHERE w.pattern = %s) AS hit
                              FROM lots l JOIN wafers w ON w.lot_id = l.id WHERE l.id = ANY(%s) AND l.status = 'active' GROUP BY l.tenant_id, l.id ORDER BY l.id""",
                         [case["pattern"], case["affected_lots"]]).fetchall()
        did = uuid.uuid4()
        rationale = {"pattern": case["pattern"], "top_chamber": case["top_chamber"], "confidence": case["confidence"],
                     "lots": [{"lot": r["id"], "yield": round(r["y"], 4), "predicted_yield": round(r["py"], 4), "wafers_with_pattern": r["hit"]} for r in lots],
                     "estimated_drift": case["estimated_drift"]}
        c.execute("""INSERT INTO decisions (id, tenant_id, case_id, kind, lots, hold_chamber, rationale, proposed_by) VALUES (%s,%s,%s,'quarantine',%s,%s,%s,%s)""",
                  [did, ctx.tenant_id, case_id, [r["id"] for r in lots], case["top_chamber"] if body.hold_chamber else None, Jsonb(rationale), ctx.actor_id])
        audit.record(c, ctx, "quarantine.proposed", "decision", did, {"lots": len(lots), "hold": case["top_chamber"] if body.hold_chamber else None})
        return 201, {"decision_id": did, "status": "proposed", "lots": [r["id"] for r in lots], "hold_chamber": case["top_chamber"] if body.hold_chamber else None, "rationale": rationale}
    return run(ctx, idem, body, work)


@app.post("/v1/decisions/{decision_id}/approve", tags=["decisions"], summary="(+) A yield manager approves or rejects a proposed quarantine; the proposer cannot. On approval the lots are quarantined and the chamber is put on hold (new lots are routed around it)")
def approve(decision_id: uuid.UUID, decision: Literal["approved", "rejected"] = "approved", ctx: Ctx = Depends(auth("decisions:approve")), idem: str | None = IdemKey):
    def work(c):
        d = c.execute("SELECT * FROM decisions WHERE id = %s FOR UPDATE", [decision_id]).fetchone()
        if not d:
            raise Problem(404, "decision_not_found")
        if d["status"] != "proposed":
            raise Problem(409, "already_decided", f"this decision is {d['status']}")
        if d["proposed_by"] == ctx.actor_id:
            raise Problem(403, "proposer_cannot_approve", "a quarantine needs a second person")
        c.execute("UPDATE decisions SET status = %s, decided_by = %s, decided_at = now() WHERE id = %s", [decision, ctx.actor_id, decision_id])
        if decision == "approved":
            c.execute("UPDATE lots SET status = 'quarantined' WHERE id = ANY(%s)", [d["lots"]])
            if d["hold_chamber"]:
                c.execute("UPDATE chambers SET status = 'hold' WHERE id = %s", [d["hold_chamber"]])
        audit.record(c, ctx, f"quarantine.{decision}", "decision", decision_id, {"lots": len(d["lots"]), "hold": d["hold_chamber"]})
        return 200, {"decision_id": decision_id, "status": decision, "quarantined_lots": d["lots"] if decision == "approved" else [],
                     "chamber_on_hold": d["hold_chamber"] if decision == "approved" else None}
    return run(ctx, idem, {"decision": decision}, work)


@app.get("/v1/decisions", tags=["decisions"], summary="(+) Proposals and decisions")
def decisions(ctx: Ctx = Depends(auth("fab:read"))):
    with db.tx(ctx.tenant_id) as c:
        return jsonable_encoder({"items": c.execute("SELECT id, case_id, kind, lots, hold_chamber, status, proposed_by, decided_by, created_at, decided_at FROM decisions ORDER BY created_at DESC").fetchall()})


# --- what-if ---------------------------------------------------------------------------------------------------------------
class Alternative(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    adjust: dict[str, dict[str, float]] | None = Field(None, description="{chamber: {sensor: setpoint offset}}, a recipe change")
    route_around: str | None = Field(None, description="a chamber taken offline; its wafers go to the tool's other chambers")


class CounterfactualIn(BaseModel):
    case_id: uuid.UUID
    alternatives: list[Alternative] = Field(default_factory=list, max_length=4)


@app.post("/v1/scenarios/counterfactual", status_code=202, tags=["scenarios"], summary="Re-run the exposed lots with a recipe change or with the chamber routed around, wafer by wafer with the same randomness, and compare yield, patterns and good dies with what happened. Default alternatives: the recipe offset the case suggests, and routing around the chamber")
def counterfactual(body: CounterfactualIn, ctx: Ctx = Depends(auth("scenarios:run")), idem: str | None = IdemKey):
    def work(c):
        fab(c)
        if not c.execute("SELECT 1 FROM root_cause_cases WHERE id = %s", [body.case_id]).fetchone():
            raise Problem(404, "case_not_found")
        for alt in body.alternatives:
            for ch, sens in (alt.adjust or {}).items():
                if ch not in world.CHAMBER_STEP or not set(sens) <= set(world.SENSORS[world.CHAMBER_STEP[ch]]):
                    raise Problem(422, "bad_adjustment", f"{ch}: unknown chamber or sensor")
            if alt.route_around and alt.route_around not in world.CHAMBER_STEP:
                raise Problem(422, "bad_route", "unknown chamber")
        return 202, jobs.enqueue(c, ctx, "scenario.counterfactual", body.model_dump(mode="json"))
    return run(ctx, idem, body, work)


@jobs.handler("scenario.counterfactual")
def counterfactual_job(c, job):
    p = job["payload"]
    f = fab(c)
    m = models(c, f)
    case = c.execute("SELECT * FROM root_cause_cases WHERE id = %s", [p["case_id"]]).fetchone()
    idx = {r["lot_index"]: r["id"] for r in c.execute("SELECT id, lot_index FROM lots WHERE id = ANY(%s) AND source = 'equipment'", [case["affected_lots"]])}
    alts = p["alternatives"] or [
        {"name": "recipe offset " + ", ".join(f"{k} {v:+.2f}" for k, v in case["estimated_drift"]["suggested_recipe_offset"].items()), "adjust": {case["top_chamber"]: case["estimated_drift"]["suggested_recipe_offset"]}, "route_around": None},
        {"name": f"route around {case['top_chamber']}", "adjust": None, "route_around": case["top_chamber"]}]
    told = list(f["told"])
    held = None                                              # re-run as the lots actually ran (no hold existed then)
    actual = {r["lot_index"]: r for r in c.execute("""SELECT l.lot_index, avg(w.yield) AS y, count(*) AS n, sum(w.yield) AS good_frac,
                                                             count(*) FILTER (WHERE w.pattern = %s) AS hit
                                                        FROM lots l JOIN wafers w ON w.lot_id = l.id WHERE l.lot_index = ANY(%s) GROUP BY l.lot_index""",
                                                     [case["pattern"], list(idx)])}
    lo, hi = min(idx), max(idx) + 1

    def rerun(adjust=None, route_around=held):
        lots = world.run(f["model_seed"], lo, hi, told, adjust=adjust, route_around=route_around, only=set(idx))
        X = np.array([engine.map_features(w["bins"]) for lot in lots for w in lot["wafers"]])
        pats, _ = engine.classify(m["wafer-pattern-classifier"], X)
        out, k = {}, 0
        for lot in lots:
            n = len(lot["wafers"])
            out[lot["index"]] = {"yield": float(np.mean([w["yield"] for w in lot["wafers"]])), "hit": sum(pp == case["pattern"] for pp in pats[k:k + n])}
            k += n
        return out
    check = rerun()
    reproduces = all(abs(check[i]["yield"] - actual[i]["y"]) < 1e-9 for i in idx)
    results = []
    for alt in alts:
        cf = rerun(alt.get("adjust"), alt.get("route_around"))
        per = [{"lot": idx[i], "actual_yield": round(actual[i]["y"], 4), "counterfactual_yield": round(cf[i]["yield"], 4),
                "actual_pattern_wafers": actual[i]["hit"], "counterfactual_pattern_wafers": cf[i]["hit"]} for i in sorted(idx)]
        dies = sum((cf[i]["yield"] - actual[i]["y"]) * actual[i]["n"] * world.N_DIES for i in idx)
        results.append({"name": alt["name"], "adjust": alt.get("adjust"), "route_around": alt.get("route_around"),
                        "mean_yield_actual": round(float(np.mean([actual[i]["y"] for i in idx])), 4), "mean_yield_counterfactual": round(float(np.mean([cf[i]["yield"] for i in idx])), 4),
                        "pattern_wafers_actual": sum(actual[i]["hit"] for i in idx), "pattern_wafers_counterfactual": sum(cf[i]["hit"] for i in idx),
                        "good_dies_recovered": int(round(dies)), "value_recovered_usd": round(dies * DIE_VALUE), "by_lot": per})
    sid = uuid.uuid4()
    result = {"scenario_id": sid, "case_id": case["id"], "lots": len(idx), "wafers": sum(actual[i]["n"] for i in idx), "reproduces_actual": reproduces, "alternatives": results,
              "die_value_usd": DIE_VALUE,
              "how": "the generator re-runs each exposed lot with the same per-wafer randomness, so each wafer is compared with itself; the counterfactual is only as good as the generator's physics, which here is the truth"}
    c.execute("INSERT INTO scenarios (id, tenant_id, case_id, request, result, created_by) VALUES (%s,%s,%s,%s,%s,%s)",
              [sid, f["tenant_id"], case["id"], Jsonb(p), Jsonb(jsonable_encoder(result)), uuid.UUID(p["actor_id"])])
    audit.record(c, worker_ctx(job), "scenario.counterfactual", "scenario", sid, {"case": str(case["id"]), "alternatives": [a["name"] for a in alts]})
    return result


class PredictIn(BaseModel):
    lot_id: str


@app.post("/v1/models/yield/predict", tags=["models"], summary="Predict each wafer's yield in a lot from its process sensors, before test; returns the model version and the hash of each input, and logs every call")
def predict(body: PredictIn, ctx: Ctx = Depends(auth("models:predict"))):
    with db.tx(ctx.tenant_id) as c:
        f = fab(c)
        m = models(c, f)
        lot = c.execute("SELECT * FROM lots WHERE id = %s", [body.lot_id]).fetchone()
        if not lot:
            raise Problem(404, "lot_not_found")
        rows = c.execute("""SELECT w.id, w.slot, w.yield, jsonb_agg(jsonb_build_object('step', p.step, 'chamber', p.chamber_id, 'sensors', p.sensors)) AS steps
                              FROM wafers w JOIN process_events p ON p.wafer_id = w.id WHERE w.lot_id = %s GROUP BY w.id ORDER BY w.slot""", [body.lot_id]).fetchall()
        X = np.array([engine.yield_features(r["steps"], m["baselines"], lot["product"]) for r in rows])
        pred = np.clip(m["yield-predictor"].predict(X), 0, 1)
        out = []
        for r, x, py in zip(rows, X, pred):
            h = engine.feature_hash(x)
            c.execute("INSERT INTO model_runs (tenant_id, model_name, version, subject, inputs_hash, result) VALUES (%s,%s,%s,%s,%s,%s)",
                      [ctx.tenant_id, engine.YIELD_VERSION, model_version(f), f"wafer:{r['id']}", h, Jsonb({"predicted_yield": round(float(py), 4)})])
            out.append({"wafer_id": r["id"], "slot": r["slot"], "predicted_yield": round(float(py), 4), "actual_yield": round(r["yield"], 4), "inputs_hash": h})
        metrics = c.execute("SELECT metrics FROM model_artifacts WHERE name = 'yield-predictor' AND version = %s", [model_version(f)]).fetchone()["metrics"]
    return jsonable_encoder({"lot": body.lot_id, "model": engine.YIELD_VERSION, "version": model_version(f), "test_mae_pp": metrics["mae_pp"],
                             "baseline_mae_pp": metrics["baseline_mae_pp"], "wafers": out,
                             "mean_predicted": round(float(pred.mean()), 4), "mean_actual": round(float(np.mean([w["actual_yield"] for w in out])), 4)})
