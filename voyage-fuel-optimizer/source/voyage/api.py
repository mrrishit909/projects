"""Public API (modular monolith). Blueprint services map to: vessel-ingest (fleet, noon reports, the reporting gateway),
weather-ocean (forecasts from the provider and their snapshots), performance-model (per-vessel fuel models and hull
fouling), route-optimizer (time-dependent A* on the forecast), speed-optimizer (dynamic programming against the berth
window), port-intelligence (berth line-ups), bunker-planner (MILP) and voyage-monitor (the advance job: storms on the
route, congestion, ETA risk, variance and the voyage report). Not built: Kafka, PostGIS, xarray, a deck.gl map; see the README.

    uvicorn voyage.api:app          python -m core.jobs voyage.api      # the worker
"""
import datetime
import math
import uuid
from typing import Literal

import numpy as np
from fastapi import Depends, Header, Query
from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, model_validator

from core import audit, db, jobs
from core.app import Ctx, Problem, create_app, run

from . import engine, world

READ = {"fleet:read", "jobs:read"}
PLAN = READ | {"voyages:create", "routes:optimize", "speed:optimize", "bunker:plan", "scenarios:run", "plans:propose", "plans:approve", "reports:ingest"}
PERMISSIONS = {"viewer": READ, "master": PLAN, "operator": PLAN | {"simulator:control", "audit:read"}}
app = create_app("voyage-fuel-optimizer", PERMISSIONS)
auth = app.state.auth
IdemKey = Header(None, alias="Idempotency-Key")
START = datetime.datetime(2026, 10, 6, 0, 0, tzinfo=datetime.UTC)
HISTORY_DAYS = 365
STORM_EVENT_HS = 6.0            # the monitor raises an event when the forecast puts the remaining track in seas above this
CONGESTION_EVENT_H = 6.0        # ... or the port's earliest berth is this much later than the plan's P50 arrival
MAP = {"res": 1.5, "lat0": 30.0, "lon0": -78.0, "nlat": 21, "nlon": 57}


def at(hours):
    return START + datetime.timedelta(hours=float(hours))


def hours_of(ts):
    return (ts - START).total_seconds() / 3600


def worker_ctx(job):
    return Ctx(job["tenant_id"], uuid.UUID(job["payload"]["actor_id"]), "worker", "system")


def fleet(c):
    f = c.execute("SELECT * FROM fleets").fetchone()
    if not f:
        raise Problem(409, "no_fleet", "load the fleet first: POST /v1/fleet:load")
    return f


def true_vessel(f, ref):
    """The generator's ship (the simulator only: planners never see these parameters)."""
    return next(v for v in world.fleet(f["model_seed"]) if v["ref"] == ref)


def model_of(c, f, vessel_ref):
    r = c.execute("SELECT artifact FROM model_artifacts WHERE name = %s AND version = %s", [f"fuel-model/{vessel_ref}", version(f)]).fetchone()
    return r["artifact"]


def version(f):
    return f"fleet-{str(f['id'])[:8]}-1"


def days_fn(vessel_row):
    last = vessel_row["metadata"]["last_hull_cleaning_h"]
    return lambda t: (np.asarray(t, float) - last) / 24.0


def particulars(vessel_row):
    return {**vessel_row["metadata"], "ref": vessel_row["external_ref"]}


def terms_of(v):
    t = v["attributes"]["terms"]
    return {"hire_usd_day": t["hire_usd_day"], "fuel_usd_t": t["fuel_usd_t"], "ets_usd_t": t["ets_usd_t"], "ets_share": t["ets_share"],
            "late_usd_h": t["late_usd_h"], "window_open_h": hours_of(datetime.datetime.fromisoformat(t["window_open"])),
            "window_close_h": hours_of(datetime.datetime.fromisoformat(t["window_close"])), "eta_tolerance_h": t["eta_tolerance_h"]}


def storms_told(f):
    return [x for x in f["told"] if x.get("kind") == "storm"]


def congestion_told(f):
    return [x for x in f["told"] if x.get("kind") == "congestion"]


def forecast_view(f, issued, member=0):
    """The weather provider's forecast issued at `issued` (weather-ocean). Derived from the simulated ocean with errors that
    grow with lead time; it cannot know storms that form after its horizon."""
    return world.Weather(f["model_seed"], storms_told(f), issued=issued, member=member)


def berth_estimate(c, f, port, now_h):
    """Port intelligence: the latest line-up the port published, stored, and its earliest berth (None = on arrival)."""
    lu = world.lineup(f["model_seed"], port, now_h, congestion_told(f))
    c.execute("INSERT INTO port_call (id, tenant_id, port, kind, reported_at, ships_waiting, earliest_berth_at, detail) VALUES (%s,%s,%s,'lineup',%s,%s,%s,%s)",
              [uuid.uuid4(), f["tenant_id"], port, at(now_h), lu["ships_waiting"], at(lu["earliest_berth_h"]) if lu["earliest_berth_h"] else None, Jsonb({})])
    return lu


def snapshot(c, f, issued, valid_hours):
    """Store the forecast's sea state on the map grid at some valid times (weather_cell) and return them."""
    wx = forecast_view(f, issued)
    la = MAP["lat0"] + MAP["res"] * np.arange(MAP["nlat"])
    lo = MAP["lon0"] + MAP["res"] * np.arange(MAP["nlon"])
    out = []
    for vh in valid_hours:
        w = wx.at(la[:, None], lo[None, :], vh)
        hs = np.where(world.is_land(la[:, None], lo[None, :]), -1, np.rint(w["hs"] * 10)).astype(int).ravel()
        storms = wx.storms(vh)
        c.execute("""INSERT INTO weather_cell (tenant_id, issued_at, valid_at, res_deg, lat0, lon0, nlat, nlon, hs_dm, storms)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (tenant_id, issued_at, valid_at) DO NOTHING""",
                  [f["tenant_id"], at(issued), at(vh), MAP["res"], MAP["lat0"], MAP["lon0"], MAP["nlat"], MAP["nlon"], [int(x) for x in hs], Jsonb(storms)])
        out.append({"issued_at": at(issued), "valid_at": at(vh), **MAP, "hs_dm": [int(x) for x in hs], "storms": storms})
    return out


def log_run(c, tenant, name, subject, inputs, result, ver):
    h = engine.feature_hash(inputs)
    c.execute("INSERT INTO model_runs (tenant_id, model_name, version, subject, inputs_hash, result) VALUES (%s,%s,%s,%s,%s,%s)",
              [tenant, name, ver, subject, h, Jsonb(jsonable_encoder(result))])
    return h


# --- the fleet and its history --------------------------------------------------------------------------------------------------
class LoadIn(BaseModel):
    seed: int = Field(7, ge=1, le=10 ** 6)


@app.post("/v1/fleet:load", status_code=202, tags=["fleet"], summary="(+) Load the synthetic fleet: six container ships with a year at sea each (voyages, noon reports, AIS positions), fit and register a fuel model per vessel and report it against the sea-trial curve")
def load_fleet(body: LoadIn, ctx: Ctx = Depends(auth("simulator:control")), idem: str | None = IdemKey):
    def work(c):
        if c.execute("SELECT 1 FROM fleets").fetchone():
            raise Problem(409, "fleet_exists", "this tenant already has a fleet; `make reset` for a fresh demo")
        return 202, jobs.enqueue(c, ctx, "fleet.load", body.model_dump())
    return run(ctx, idem, body, work)


@jobs.handler("fleet.load")
def load_job(c, job):
    t, seed = job["tenant_id"], job["payload"]["seed"]
    fid = uuid.uuid5(t, "fleet")
    vessels = world.fleet(seed)
    hist = world.history(seed, vessels, HISTORY_DAYS, 0.0)
    c.execute("INSERT INTO fleets (id, tenant_id, name, model_seed, clock_h) VALUES (%s,%s,'Northline Atlantic Service',%s,0)", [fid, t, seed])
    f = {"id": fid, "tenant_id": t, "model_seed": seed}
    vid, vrows = {}, []
    for v in vessels:
        tr = v["true"]
        last = tr["recleaned_at"] if tr["recleaned_at"] is not None else tr["cleaned_at"]
        meta = {k: v[k] for k in ("design_speed", "service_speed", "mcr_kw", "dwt", "teu", "tank_t", "sea_trial")}
        meta.update(last_hull_cleaning_h=last, hull_cleanings_h=[x for x in (tr["cleaned_at"], tr["recleaned_at"]) if x is not None])
        vid[v["ref"]] = uuid.uuid5(t, "vessel:" + v["ref"])
        vrows.append((vid[v["ref"]], t, v["ref"], v["name"], Jsonb(meta)))
    db.load(c, "vessel", ["vessel_id", "tenant_id", "external_ref", "name", "metadata"], vrows)
    voy, pos, noon = [], [], []
    for h in hist:
        voy_id = uuid.uuid5(t, h["ref"])
        voy.append((voy_id, t, vid[h["vessel"]], h["ref"], "completed", h["orig"], h["dest"], at(h["dep_h"]),
                    Jsonb({"load_disp": round(h["disp"], 3), "distance_nm": round(h["distance_nm"], 1)}), Jsonb({"arrival_at": at(h["arr_h"]).isoformat(), "fuel_t": round(h["fuel_t"], 1)})))
        for p in world.ais(h["track"], seed, h["ref"], every=6):
            pos.append((t, voy_id, at(p["t"]), p["lat"], p["lon"], p["sog"], p["course"]))
        for r in h["noon"]:
            noon.append((t, vid[h["vessel"]], voy_id, at(r["t"]), r["hours"], r["stw"], r["sog"], r["distance_nm"], r["fuel_t"], r["hs_obs"], r["wave_sector"],
                         r["head_wind_obs"], r["disp"], r["days_clean"], r["lat"], r["lon"], "noon"))
    db.load(c, "voyage", ["voyage_id", "tenant_id", "vessel_id", "ref", "status", "orig", "dest", "departure_at", "attributes", "state"], voy)
    db.load(c, "position", ["tenant_id", "voyage_id", "at", "lat", "lon", "sog", "course"], pos)
    db.load(c, "fuel_sample", ["tenant_id", "vessel_id", "voyage_id", "at", "hours", "stw", "sog", "distance_nm", "fuel_t", "hs_obs", "wave_sector",
                               "head_wind_obs", "disp", "days_clean", "lat", "lon", "source"], noon)
    ver = version(f)
    summary = []
    for v in vessels:
        reps = [r for h in hist if h["vessel"] == v["ref"] for r in h["noon"]]
        m = engine.fit_fuel_model(v, reps, 0.0)
        snap = f"noon reports {len(reps)} from {at(-24 * HISTORY_DAYS).date()} to {at(0).date()}, last {engine.HOLDOUT_DAYS} days held out, seed {seed}"
        c.execute("""INSERT INTO model_artifacts (tenant_id, name, version, data_snapshot, feature_schema, metrics, artifact, approved)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,true)""", [t, f"fuel-model/{v['ref']}", ver, snap, Jsonb(engine.FEATURES),
                                                             Jsonb({**m["metrics"], "fouling_now_pct": m["fouling_now_pct"]}), Jsonb(m)])
        summary.append({"vessel": v["ref"], "name": v["name"], "noon_reports": len(reps), **m["metrics"], "fouling_now_pct": m["fouling_now_pct"],
                        "days_since_cleaning": m["days_clean_now"]})
        # every stored report scored with its vessel's model
        preds = [(at(r["t"]), float(engine.predict_tpd(m, *engine.report_inputs(r))) * r["hours"] / 24) for r in reps]
        c.execute("CREATE TEMP TABLE _p (at timestamptz, p real) ON COMMIT DROP")
        db.copy(c, "_p", ["at", "p"], preds)
        c.execute("UPDATE fuel_sample s SET predicted_t = _p.p FROM _p WHERE s.vessel_id = %s AND s.at = _p.at", [vid[v["ref"]]])
        c.execute("DROP TABLE _p")
    audit.record(c, worker_ctx(job), "fleet.loaded", "fleet", fid, {"vessels": len(vessels), "voyages": len(hist), "noon_reports": len(noon), "model_version": ver})
    return {"fleet_id": fid, "vessels": len(vessels), "voyages": len(hist), "noon_reports": len(noon), "positions": len(pos), "history_days": HISTORY_DAYS,
            "clock": at(0), "model_version": ver, "models": summary,
            "how": "each vessel's model is scored on its last 60 days of noon reports after fitting on the ten months before, then refitted on the whole year"}


@app.get("/v1/fleet", tags=["fleet"], summary="(+) The command centre: vessels with their fuel models against the sea-trial curve and hull fouling, voyages under way, open events, the clock")
def fleet_overview(ctx: Ctx = Depends(auth("fleet:read"))):
    with db.tx(ctx.tenant_id) as c:
        f = fleet(c)
        vs = c.execute("SELECT * FROM vessel ORDER BY external_ref").fetchall()
        arts = {r["name"].split("/")[1]: r for r in c.execute("SELECT name, version, data_snapshot, metrics, approved FROM model_artifacts WHERE version = %s", [version(f)])}
        stats = {r["vessel_id"]: r for r in c.execute("""SELECT vessel_id, count(*) AS voyages, sum((state->>'fuel_t')::float8) AS fuel_t
                                                            FROM voyage WHERE status = 'completed' GROUP BY tenant_id, vessel_id""")}
        live = c.execute("""SELECT voyage_id, ref, status, orig, dest, v.external_ref AS vessel, notified_eta_at FROM voyage y JOIN vessel v USING (vessel_id)
                             WHERE status IN ('planned', 'underway') ORDER BY departure_at""").fetchall()
        events = c.execute("SELECT kind, count(*) AS n FROM voyage_event WHERE status = 'open' GROUP BY kind").fetchall()
    out = []
    for v in vs:
        a = arts.get(v["external_ref"])
        md = v["metadata"]
        out.append({"ref": v["external_ref"], "name": v["name"], "teu": md["teu"], "dwt": md["dwt"], "design_speed": md["design_speed"], "service_speed": md["service_speed"],
                    "mcr_kw": md["mcr_kw"], "voyages_last_year": stats.get(v["vessel_id"], {}).get("voyages", 0),
                    "fuel_last_year_t": round(stats.get(v["vessel_id"], {}).get("fuel_t") or 0), "model": a and {"version": a["version"], **a["metrics"]},
                    "days_since_hull_cleaning": round(f["clock_h"] / 24 - md["last_hull_cleaning_h"] / 24, 1)})
    return jsonable_encoder({"fleet": f["name"], "clock": at(f["clock_h"]), "vessels": out, "voyages_live": live, "open_events": events, "model_version": version(f)})


@app.get("/v1/vessels/{ref}/performance", tags=["fleet"], summary="(+) A vessel's fuel against speed: its noon reports, the fitted model and the sea-trial curve, and the hull-fouling estimate")
def performance(ref: str, days: int = Query(120, ge=10, le=365), ctx: Ctx = Depends(auth("fleet:read"))):
    with db.tx(ctx.tenant_id) as c:
        f = fleet(c)
        v = c.execute("SELECT * FROM vessel WHERE external_ref = %s", [ref]).fetchone()
        if not v:
            raise Problem(404, "vessel_not_found")
        m = model_of(c, f, ref)
        reps = c.execute("""SELECT at, hours, stw, fuel_t, hs_obs, wave_sector, head_wind_obs, disp, days_clean, predicted_t, source FROM fuel_sample
                             WHERE vessel_id = %s AND at >= %s ORDER BY at""", [v["vessel_id"], at(f["clock_h"] - 24 * days)]).fetchall()
    p = particulars(v)
    days_now = f["clock_h"] / 24 - p["last_hull_cleaning_h"] / 24
    sp = np.arange(11.0, p["design_speed"] + 0.01, 0.5)
    curve = [{"speed": float(s), "sea_trial_tpd": round(float(engine.sea_trial_tpd(p, s)), 1), "model_calm_today_tpd": round(float(engine.predict_tpd(m, s, 0, 0, 0, 0.85, days_now)), 1),
              "model_calm_clean_tpd": round(float(engine.predict_tpd(m, s, 0, 0, 0, 0.85, 0)), 1)} for s in sp]
    pts = [{"at": r["at"], "speed": r["stw"], "fuel_tpd": round(r["fuel_t"] * 24 / r["hours"], 1), "predicted_tpd": round((r["predicted_t"] or 0) * 24 / r["hours"], 1),
            "sea_trial_tpd": round(float(engine.sea_trial_tpd(p, r["stw"])), 1), "hs": r["hs_obs"], "source": r["source"]} for r in reps]
    return jsonable_encoder({"vessel": ref, "name": v["name"], "model": {"version": version(f), "name": engine.FUEL_VERSION, **m["metrics"]},
                             "fouling_now_pct": engine.fouling_pct(m, p, days_now), "days_since_hull_cleaning": round(days_now, 1),
                             "service_speed": p["service_speed"], "curve": curve, "reports": pts,
                             "how": "fuel per day from noon reports: speed cubed and its neighbours scaled by displacement, the same times days since cleaning (fouling), "
                                    "wave height squared by heading and apparent head wind, fitted by non-negative least squares"})


# --- vessel-ingest: the reporting gateway --------------------------------------------------------------------------------------------
class ReportIn(BaseModel):
    vessel: str
    at: datetime.datetime
    hours: float = Field(gt=0, le=30)
    stw: float = Field(ge=0, le=30)
    fuel_t: float = Field(gt=0, le=500)
    hs_obs: float = Field(ge=0, le=20)
    wave_sector: int = Field(ge=0, le=4)
    head_wind_obs: float = Field(ge=-60, le=60)
    disp: float = Field(ge=0.4, le=1.1)


class ReportsIn(BaseModel):
    reports: list[ReportIn] = Field(min_length=1, max_length=200)


@app.post("/v1/noon-reports", status_code=201, tags=["vessel-ingest"], summary="(+) Noon reports from ships through the gateway. Each is validated on its own and checked against its vessel's fuel model: a figure the model cannot explain (more than 35% off) is refused with the reason rather than learned from")
def ingest_reports(body: ReportsIn, ctx: Ctx = Depends(auth("reports:ingest")), idem: str | None = IdemKey):
    def work(c):
        f = fleet(c)
        vs = {r["external_ref"]: r for r in c.execute("SELECT * FROM vessel")}
        accepted, refused = [], []
        for r in body.reports:
            v = vs.get(r.vessel)
            if not v:
                refused.append({"vessel": r.vessel, "at": r.at, "why": "unknown vessel"})
                continue
            if hours_of(r.at) > f["clock_h"] + 1:
                refused.append({"vessel": r.vessel, "at": r.at, "why": "report from the future"})
                continue
            if c.execute("SELECT 1 FROM fuel_sample WHERE vessel_id = %s AND at = %s", [v["vessel_id"], r.at]).fetchone():
                refused.append({"vessel": r.vessel, "at": r.at, "why": "duplicate report for this vessel and time"})
                continue
            m = model_of(c, f, r.vessel)
            days = (hours_of(r.at) - v["metadata"]["last_hull_cleaning_h"]) / 24
            inp = {"stw": r.stw, "hs_obs": r.hs_obs, "wave_sector": r.wave_sector, "head_wind_obs": r.head_wind_obs, "disp": r.disp, "days_clean": days}
            pred = float(engine.predict_tpd(m, *engine.report_inputs(inp))) * r.hours / 24
            ratio = r.fuel_t / pred
            h = log_run(c, ctx.tenant_id, engine.FUEL_VERSION, f"report:{r.vessel}:{r.at.isoformat()}", inp, {"predicted_t": round(pred, 2)}, version(f))
            if abs(ratio - 1) > 0.35:
                refused.append({"vessel": r.vessel, "at": r.at, "why": f"fuel {r.fuel_t:g} t is {ratio:.1f}x what the model expects ({pred:.1f} t) at {r.stw:g} kn in "
                                                                    f"{r.hs_obs:g} m seas: check the meter reading", "inputs_hash": h})
                continue
            c.execute("""INSERT INTO fuel_sample (tenant_id, vessel_id, at, hours, stw, fuel_t, hs_obs, wave_sector, head_wind_obs, disp, days_clean, source, predicted_t)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'gateway',%s)""",
                      [ctx.tenant_id, v["vessel_id"], r.at, r.hours, r.stw, r.fuel_t, r.hs_obs, r.wave_sector, r.head_wind_obs, r.disp, days, pred])
            accepted.append({"vessel": r.vessel, "at": r.at, "fuel_t": r.fuel_t, "predicted_t": round(pred, 2), "error_pct": round(100 * (ratio - 1), 1), "inputs_hash": h})
        audit.record(c, ctx, "reports.ingested", "fuel_sample", ",".join(a["vessel"] for a in accepted) or "-", {"accepted": len(accepted), "refused": len(refused)})
        return 201, {"accepted": accepted, "refused": refused}
    return run(ctx, idem, body, work)


# --- voyages --------------------------------------------------------------------------------------------------------------------------
class TermsIn(BaseModel):
    hire_usd_day: float = Field(28000, gt=0, le=300000)
    fuel_usd_t: float = Field(620, gt=0, le=3000)
    ets_usd_t: float = Field(80, ge=0, le=500, description="carbon allowance price, USD per t CO2")
    ets_share: float = Field(0.5, ge=0, le=1, description="share of the voyage's CO2 the EU ETS covers (0.5 into or out of the EU)")
    window_open: datetime.datetime
    window_close: datetime.datetime
    late_usd_h: float = Field(3000, ge=0, le=100000)
    eta_tolerance_h: float = Field(12, gt=0, le=72, description="an ETA change beyond this needs the charterer told, so a second person approves it")

    @model_validator(mode="after")
    def window(self):
        if self.window_close <= self.window_open:
            raise ValueError("the berth window must close after it opens")
        return self


class VoyageIn(BaseModel):
    vessel: str
    orig: str
    dest: str
    load: float = Field(0.9, ge=0.5, le=1.0, description="displacement as a fraction of design")
    terms: TermsIn


@app.post("/v1/voyages", status_code=201, tags=["voyages"], summary="Create a voyage: vessel, ports, load and the charter terms (hire, berth window, late penalty, ETA tolerance, fuel and carbon prices). It departs at the current clock")
def create_voyage(body: VoyageIn, ctx: Ctx = Depends(auth("voyages:create")), idem: str | None = IdemKey):
    def work(c):
        f = fleet(c)
        v = c.execute("SELECT * FROM vessel WHERE external_ref = %s", [body.vessel]).fetchone()
        if not v:
            raise Problem(404, "vessel_not_found", body.vessel)
        for p in (body.orig, body.dest):
            if p not in world.PORTS:
                raise Problem(422, "unknown_port", f"{p}: ports are {', '.join(world.PORTS)}")
        if world.PORTS[body.orig][1] == world.PORTS[body.dest][1]:
            raise Problem(422, "not_an_ocean_passage", "the ports must be on opposite sides of the Atlantic")
        if hours_of(body.terms.window_open) < f["clock_h"] + 24 * 4:
            raise Problem(422, "window_unreachable", "the berth window opens less than four days after departure")
        if c.execute("SELECT 1 FROM voyage WHERE vessel_id = %s AND status IN ('planned', 'underway')", [v["vessel_id"]]).fetchone():
            raise Problem(409, "vessel_busy", f"{body.vessel} already has a voyage planned or under way")
        n = c.execute("SELECT count(*) AS n FROM voyage WHERE status <> 'completed'").fetchone()["n"]
        ref = f"NAS-{at(f['clock_h']).strftime('%y%m')}-{n + 1:03d}"
        vid = uuid.uuid4()
        attrs = {"terms": body.terms.model_dump(mode="json"), "load_disp": body.load,
                 "distance_shortest_nm": round(world.Path(*world.passage(body.orig, body.dest)).length, 1)}
        c.execute("""INSERT INTO voyage (voyage_id, tenant_id, vessel_id, ref, status, orig, dest, departure_at, attributes, state)
                     VALUES (%s,%s,%s,%s,'planned',%s,%s,%s,%s,%s)""",
                  [vid, ctx.tenant_id, v["vessel_id"], ref, body.orig, body.dest, at(f["clock_h"]), Jsonb(attrs), Jsonb({"t": f["clock_h"], "fuel_t": 0.0})])
        audit.record(c, ctx, "voyage.created", "voyage", vid, {"ref": ref, "vessel": body.vessel, "orig": body.orig, "dest": body.dest})
        return 201, {"voyage_id": vid, "ref": ref, "vessel": body.vessel, "name": v["name"], "orig": body.orig, "dest": body.dest, "departure_at": at(f["clock_h"]),
                     "status": "planned", **attrs}
    return run(ctx, idem, body, work)


def voyage_row(c, voyage_id):
    v = c.execute("""SELECT y.*, v.external_ref AS vessel_ref, v.name AS vessel_name, v.metadata AS vessel_meta FROM voyage y JOIN vessel v USING (vessel_id)
                      WHERE voyage_id = %s""", [voyage_id]).fetchone()
    if not v:
        raise Problem(404, "voyage_not_found")
    return v


def vessel_like(v):
    return {"external_ref": v["vessel_ref"], "metadata": v["vessel_meta"]}


def start_of(v):
    """Where a new plan for this voyage starts: the departure pilot station, or the ship's position at sea."""
    s = v["state"]
    if v["status"] == "underway":
        return (s["lat"], s["lon"]), s["t"]
    return None, s["t"]


# --- route-optimizer ------------------------------------------------------------------------------------------------------------------
class RouteIn(BaseModel):
    voyage_id: uuid.UUID
    speed_kn: float | None = Field(None, ge=engine.V_MIN, le=25, description="speed order to route at (default: the speed that lands mid-window on the shortest route)")


def _open(c, voyage_id):
    v = voyage_row(c, voyage_id)
    if v["status"] not in ("planned", "underway"):
        raise Problem(409, "voyage_closed", f"this voyage is {v['status']}")
    return v


@app.post("/v1/routes/optimize", status_code=202, tags=["routes"], summary="Weather routing: time-dependent A* over the 0.5-degree ocean grid with the latest forecast (waves, wind, currents) and the vessel's fuel model, against the shortest sea route at the same speed order. Returns both routes, their forecast fuel, time and heavy weather, the solve time and the forecast map")
def route_optimize(body: RouteIn, ctx: Ctx = Depends(auth("routes:optimize")), idem: str | None = IdemKey):
    def work(c):
        fleet(c)
        v = _open(c, body.voyage_id)
        if body.speed_kn and body.speed_kn > v["vessel_meta"]["design_speed"]:
            raise Problem(422, "speed_above_design", f"design speed is {v['vessel_meta']['design_speed']} kn")
        return 202, jobs.enqueue(c, ctx, "route.optimize", body.model_dump(mode="json"))
    return run(ctx, idem, body, work)


def store_route(c, tenant, voyage_id, kind, issued, t0, speed, nodes, path, info, actor, ver):
    rid = uuid.uuid4()
    inputs = {"voyage": str(voyage_id), "issued": issued, "t0": t0, "speed": speed, "kind": kind, "start": [float(path.lat[0]), float(path.lon[0])]}
    h = engine.feature_hash(inputs)
    c.execute("""INSERT INTO route_plan (id, tenant_id, voyage_id, kind, forecast_issued_at, start_at, speed_kn, path, nodes, distance_nm, solve_s, expanded, model_version, inputs_hash, created_by)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
              [rid, tenant, voyage_id, kind, at(issued), at(t0), speed, Jsonb([[round(float(a), 4), round(float(b), 4)] for a, b in zip(path.lat, path.lon)]),
               [int(n) for n in nodes], path.length, info and info.get("seconds"), info and info.get("expanded"), f"{engine.ROUTE_VERSION}/{ver}", h, actor])
    c.execute("INSERT INTO model_runs (tenant_id, model_name, version, subject, inputs_hash, result) VALUES (%s,%s,%s,%s,%s,%s)",
              [tenant, engine.ROUTE_VERSION, ver, f"route_plan:{rid}", h, Jsonb({"distance_nm": round(path.length, 1), "solve_s": info and info.get("seconds")})])
    return rid


def coarse(path, every=4):
    idx = list(range(0, len(path.lat), every)) + [len(path.lat) - 1]
    return [[round(float(path.lat[i]), 3), round(float(path.lon[i]), 3)] for i in sorted(set(idx))]


def track_summary(track, hs=STORM_EVENT_HS):
    if not track:
        return {"max_hs": 0.0, "heavy_h": 0.0, "max_hs_at": None, "max_hs_pos": None}
    worst = max(track, key=lambda h: h["hs"])
    return {"max_hs": round(worst["hs"], 1), "heavy_h": round(sum(h["hours"] for h in track if h["hs"] > hs), 1), "max_hs_at": at(worst["t"]),
            "max_hs_pos": [round(worst["lat"], 2), round(worst["lon"], 2)]}


@jobs.handler("route.optimize")
def route_job(c, job):
    p = job["payload"]
    f = fleet(c)
    v = _open(c, p["voyage_id"])
    vs = vessel_like(v)
    m = model_of(c, f, v["vessel_ref"])
    terms = terms_of(v)
    start, t0 = start_of(v)
    issued = f["clock_h"]
    disp, days_at = v["attributes"]["load_disp"], days_fn(vs)
    g = world.grid()
    s_node = g.node(*(start if start else world.PORTS[v["orig"]][2]))
    goal = g.node(*world.PORTS[v["dest"]][2])
    if p.get("speed_kn"):
        speed = float(p["speed_kn"])
    else:
        dist = world.Path(*world.passage(v["orig"], v["dest"], world.shortest_sea_route(s_node, goal), start=start)).length
        mid = (terms["window_open_h"] + terms["window_close_h"]) / 2
        speed = float(np.clip(round(4 * dist / max(mid - t0, 24)) / 4, engine.V_MIN, v["vessel_meta"]["design_speed"] - 1))
    fc = forecast_view(f, issued)
    gf = engine.GridForecast(fc, issued, 24 * 18)
    ch = engine.choose_route(m, fc, gf, t0, s_node, goal, speed, terms, disp, days_at, v["orig"], v["dest"], start)
    if ch is None:
        raise Problem(422, "no_safe_route", "every way out is closed by seas above the limit")
    out, ids = [], {}
    for kind in ("optimized", "shortest"):
        e = ch["evals"][kind]
        P = e["path"]
        ids[kind] = store_route(c, f["tenant_id"], v["voyage_id"], kind, issued, t0, speed, e["route"]["nodes"], P, e["route"], uuid.UUID(p["actor_id"]), version(f))
        o = engine.outcome(terms, t0, e["arrival_h"], e["fuel_t"], t0, engine.anchor_tph_model(m))
        out.append({"kind": kind, "route_plan_id": ids[kind], "distance_nm": round(P.length, 1), "hours": round(e["arrival_h"] - t0, 1), "arrival_at": at(e["arrival_h"]),
                    "fuel_t": round(e["fuel_t"], 1), "cost_usd": round(float(o["cost_usd"])), **track_summary(e["track"]), "path": coarse(P)})
    opt = ch["info"]
    worst = max(out, key=lambda r: r["max_hs"])
    valid = [issued + 24 * k for k in range(0, 11)]
    maps = snapshot(c, f, issued, valid)
    focus = hours_of(worst["max_hs_at"]) if worst["max_hs_at"] else issued + 96
    shown = min(maps, key=lambda mp: abs(hours_of(mp["valid_at"]) - focus))
    audit.record(c, worker_ctx(job), "route.optimized", "route_plan", ids[ch["chosen"]], {"voyage": v["ref"], "speed_kn": speed, "solve_s": opt["seconds"], "chosen": ch["chosen"]})
    return {"voyage_id": v["voyage_id"], "route_plan_id": ids[ch["chosen"]], "chosen": ch["chosen"], "optimized_route_plan_id": ids["optimized"],
            "shortest_route_plan_id": ids["shortest"], "speed_kn": speed, "forecast_issued_at": at(issued),
            "solve_s": opt["seconds"], "expanded_nodes": opt["expanded"], "grid_nodes": g.n, "routes": out, "map": shown,
            "how": "time-dependent A*: each edge costs the fuel model's burn in the forecast waves and wind at the hour the ship would be there, with the current along it, "
                   "plus hire and a heavy-weather charge; edges into seas above 7 m are closed. Both routes are then sailed through the forecast hour by hour and the cheaper is kept",
            "model_version": f"{engine.ROUTE_VERSION}/{version(f)}"}


# --- speed-optimizer ------------------------------------------------------------------------------------------------------------------
class SpeedIn(BaseModel):
    route_plan_id: uuid.UUID
    label: str = Field("optimized speed", min_length=1, max_length=80)


@app.post("/v1/speed/optimize", status_code=202, tags=["speed"], summary="Speed along a route: dynamic programming over arrival time, leg by leg in 0.25-knot steps, minimising fuel, carbon, hire, waiting at anchor and late penalties against the berth window and the port's earliest berth. The plan keeps its P90 arrival (from the forecast ensemble) inside the window. Returns a candidate plan with its ETA band and its comparison with constant service speed")
def speed_optimize(body: SpeedIn, ctx: Ctx = Depends(auth("speed:optimize")), idem: str | None = IdemKey):
    def work(c):
        fleet(c)
        r = c.execute("SELECT * FROM route_plan WHERE id = %s", [body.route_plan_id]).fetchone()
        if not r:
            raise Problem(404, "route_plan_not_found")
        _open(c, r["voyage_id"])
        return 202, jobs.enqueue(c, ctx, "speed.optimize", body.model_dump(mode="json"))
    return run(ctx, idem, body, work)


def within_terms(v, terms, eta, berth_h):
    """A plan is inside the charter terms if its P90 arrival is inside the window (or before the port's earliest berth) and,
    once an ETA has been given, its P50 moves less than the tolerance from it."""
    limit = max(terms["window_close_h"], berth_h)
    if eta["p90"] > limit + 0.5:
        return False, f"P90 arrival {at(eta['p90']):%d %b %H:%M} is after the window closes ({at(limit):%d %b %H:%M})"
    if v["notified_eta_at"] is not None:
        moved = eta["p50"] - hours_of(v["notified_eta_at"])
        if abs(moved) > terms["eta_tolerance_h"]:
            return False, f"ETA moves {moved:+.0f} h from the {at(hours_of(v['notified_eta_at'])):%d %b %H:%M} given to the charterer (tolerance {terms['eta_tolerance_h']:g} h)"
    return True, "inside the charter terms"


def store_plan(c, f, v, rid, label, res, berth_h, actor):
    terms = terms_of(v)
    ok, why = within_terms(v, terms, res["arrival"], berth_h)
    pid = uuid.uuid4()
    det = [[round(h["t"], 2), round(h["s"], 1), round(h["cmd"], 2), round(h["stw"], 2), round(h["hs"], 2), round(h["g"], 3), round(h["head_ms"], 2),
            round(h["fuel_t"], 4), round(h["hours"], 3), round(h["lat"], 3), round(h["lon"], 3)] for h in res["det_track"]]
    inputs = {"route": str(rid), "issued": res["t0"], "legs": res["legs"], "berth": berth_h}
    h = engine.feature_hash(inputs)
    exp = {k: round(x, 2) for k, x in res["expected"].items()}
    c.execute("""INSERT INTO speed_plan (id, tenant_id, voyage_id, route_plan_id, label, legs, eta, fuel, expected, det_track, berth_estimate_at, within_terms, why,
                                         model_version, inputs_hash, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
              [pid, f["tenant_id"], v["voyage_id"], rid, label, Jsonb(res["legs"]), Jsonb(res["arrival"]), Jsonb(res["fuel"]), Jsonb(exp), Jsonb(det),
               at(berth_h), ok, why, f"{engine.SPEED_VERSION}+{engine.ETA_VERSION}/{version(f)}", h, actor])
    c.execute("INSERT INTO model_runs (tenant_id, model_name, version, subject, inputs_hash, result) VALUES (%s,%s,%s,%s,%s,%s)",
              [f["tenant_id"], engine.ETA_VERSION, version(f), f"speed_plan:{pid}", h, Jsonb({"eta_p50": res["arrival"]["p50"], "eta_p90": res["arrival"]["p90"], "fuel_p50": res["fuel"]["p50"]})])
    return pid, ok, why


def plan_view(res, terms, t_ref, notified_h=None):
    """A plan as the UI and the scenario table show it."""
    e, fu, x = res["arrival"], res["fuel"], res["expected"]
    legs, prev, prof = res["legs"], 0.0, []
    for end, sp in legs:
        prof.append({"from_nm": round(prev), "to_nm": round(end), "speed_kn": sp})
        prev = end
    trk = res["det_track"]
    return {"eta": {k: at(val) for k, val in e.items()}, "eta_hours": {k: round(val - t_ref, 1) for k, val in e.items()},
            "eta_change_h": round(e["p50"] - notified_h, 1) if notified_h is not None else None,
            "fuel_t": {k: round(val, 1) for k, val in fu.items()}, "co2_t": round(x["co2_t"], 1), "expected_cost_usd": round(x["cost_usd"]),
            "cost_breakdown_usd": {"fuel": round(x["fuel_usd"]), "carbon": round(x["carbon_usd"]), "hire": round(x["hire_usd"]), "late_penalty": round(x["late_usd"])},
            "expected_wait_h": round(x["wait_h"], 1), "expected_late_h": round(x["late_h"], 1), "p_late": round(res["p_late"], 3),
            "window": {"open": at(terms["window_open_h"]), "close": at(terms["window_close_h"])}, "berth_estimate": at(res["berth_h"]),
            "distance_nm": round(res["path"].length, 1), "mean_speed_kn": round(res["path"].length / max(1e-6, e["p50"] - t_ref), 2),
            "profile": prof, "path": coarse(res["path"]), **track_summary(trk),
            "speed_by_hour": [[round(h["t"] - t_ref, 1), round(h["cmd"], 2), round(h["stw"], 2), round(h["hs"], 1)] for h in trk[::3]],
            "eta_samples_h": [round(float(a) - t_ref, 1) for a in np.sort(res["arrivals"])]}


@jobs.handler("speed.optimize")
def speed_job(c, job):
    p = job["payload"]
    f = fleet(c)
    r = c.execute("SELECT * FROM route_plan WHERE id = %s", [p["route_plan_id"]]).fetchone()
    v = _open(c, r["voyage_id"])
    vs = vessel_like(v)
    m = model_of(c, f, v["vessel_ref"])
    terms = terms_of(v)
    start, t0 = start_of(v)
    if abs(hours_of(r["start_at"]) - t0) > 1e-6:
        raise Problem(409, "route_stale", "the ship has moved since this route was solved; solve it again")
    issued = f["clock_h"]
    lu = berth_estimate(c, f, v["dest"], issued)
    berth_h = lu["earliest_berth_h"] or t0
    disp, days_at = v["attributes"]["load_disp"], days_fn(vs)
    part = particulars(vs)
    seed = f["model_seed"]
    told = storms_told(f)
    res = engine.plan(m, part, seed, told, issued, t0, v["orig"], v["dest"], terms, berth_h, disp, days_at, start=start, route="path", path_pts=r["path"])
    svc = engine.plan(m, part, seed, told, issued, t0, v["orig"], v["dest"], terms, berth_h, disp, days_at, start=start, route="path", path_pts=r["path"],
                      speed=part["service_speed"])
    pid, ok, why = store_plan(c, f, v, r["id"], p["label"], res, berth_h, uuid.UUID(p["actor_id"]))
    notified = hours_of(v["notified_eta_at"]) if v["notified_eta_at"] else None
    audit.record(c, worker_ctx(job), "speed.optimized", "speed_plan", pid, {"voyage": v["ref"], "eta_p50": at(res["arrival"]["p50"]).isoformat(), "within_terms": ok})
    return {"speed_plan_id": pid, "voyage_id": v["voyage_id"], "route_plan_id": r["id"], "status": "candidate", "within_terms": ok, "why": why,
            "plan": plan_view(res, terms, t0, notified), "service_speed": {"speed_kn": part["service_speed"], **plan_view(svc, terms, t0, notified)},
            "deadline_tightening": [{"deadline": at(x["deadline_h"]) if x["deadline_h"] else None, "p90": at(x["p90_h"])} for x in res["tries"]],
            "port_lineup": {"port": v["dest"], "ships_waiting": lu["ships_waiting"], "earliest_berth": at(lu["earliest_berth_h"]) if lu["earliest_berth_h"] else None},
            "solve_s": res["speed_seconds"], "members": engine.MEMBERS, "model_version": f"{engine.SPEED_VERSION}+{engine.ETA_VERSION}/{version(f)}",
            "how": "speed orders are engine settings: in weather the ship slows rather than burning more; the band sails the plan through 24 forecast members, "
                   "each with storms of its own beyond the forecast horizon and the fuel model's own error"}


# --- plans: activation and approval -----------------------------------------------------------------------------------------------
def activate(c, f, v, plan, actor, how):
    t = f["clock_h"]
    c.execute("UPDATE speed_plan SET status = 'superseded' WHERE voyage_id = %s AND status = 'active'", [v["voyage_id"]])
    c.execute("UPDATE speed_plan SET status = 'active', activated_at = %s WHERE id = %s", [at(t), plan["id"]])
    st = dict(v["state"], plan_id=str(plan["id"]), s=0.0, t=t)
    notified = at(plan["eta"]["p50"])
    c.execute("UPDATE voyage SET active_plan_id = %s, notified_eta_at = %s, state = %s WHERE voyage_id = %s",
              [plan["id"], notified, Jsonb(jsonable_encoder(st)), v["voyage_id"]])
    c.execute("INSERT INTO voyage_event (id, tenant_id, voyage_id, kind, at, detail, status) VALUES (%s,%s,%s,'plan_activated',%s,%s,'info')",
              [uuid.uuid4(), f["tenant_id"], v["voyage_id"], at(t), Jsonb({"plan": str(plan["id"]), "label": plan["label"], "eta_p50": at(plan["eta"]["p50"]).isoformat(), "how": how})])


@app.post("/v1/plans/{plan_id}/activate", tags=["plans"], summary="(+) Put a candidate plan into effect. Inside the charter terms it is activated at once; a plan that moves the ETA beyond the tolerance, or risks arriving after the window, becomes a proposal that a second person (master or operator, not the proposer) must approve")
def activate_plan(plan_id: uuid.UUID, ctx: Ctx = Depends(auth("plans:propose")), idem: str | None = IdemKey):
    def work(c):
        f = fleet(c)
        plan = c.execute("SELECT * FROM speed_plan WHERE id = %s FOR UPDATE", [plan_id]).fetchone()
        if not plan:
            raise Problem(404, "plan_not_found")
        if plan["status"] != "candidate":
            raise Problem(409, "not_a_candidate", f"this plan is {plan['status']}")
        v = _open(c, plan["voyage_id"])
        if abs(plan["det_track"][0][0] - f["clock_h"]) > 1e-6 if plan["det_track"] else True:
            raise Problem(409, "plan_stale", "the ship has moved since this plan was made; plan again")
        if plan["within_terms"]:
            activate(c, f, v, plan, ctx.actor_id, "inside the charter terms: activated without approval")
            audit.record(c, ctx, "plan.activated", "speed_plan", plan_id, {"voyage": v["ref"], "within_terms": True, "eta_p50": at(plan["eta"]["p50"]).isoformat()})
            return 200, {"plan_id": plan_id, "status": "active", "eta_p50": at(plan["eta"]["p50"]), "why": plan["why"]}
        did = uuid.uuid4()
        notified = hours_of(v["notified_eta_at"]) if v["notified_eta_at"] else None
        rationale = {"label": plan["label"], "why": plan["why"], "eta_p50_new": at(plan["eta"]["p50"]).isoformat(), "eta_p90_new": at(plan["eta"]["p90"]).isoformat(),
                     "eta_notified": v["notified_eta_at"].isoformat() if v["notified_eta_at"] else None,
                     "eta_change_h": round(plan["eta"]["p50"] - notified, 1) if notified is not None else None,
                     "expected_cost_usd": plan["expected"]["cost_usd"], "fuel_p50_t": plan["fuel"]["p50"]}
        c.execute("UPDATE speed_plan SET status = 'proposed' WHERE id = %s", [plan_id])
        c.execute("INSERT INTO decisions (id, tenant_id, voyage_id, speed_plan_id, kind, rationale, proposed_by) VALUES (%s,%s,%s,%s,'plan_change',%s,%s)",
                  [did, ctx.tenant_id, v["voyage_id"], plan_id, Jsonb(rationale), ctx.actor_id])
        audit.record(c, ctx, "plan.proposed", "decision", did, {"voyage": v["ref"], "plan": str(plan_id), "why": plan["why"]})
        return 200, {"plan_id": plan_id, "status": "awaiting_approval", "decision_id": did, "rationale": rationale}
    return run(ctx, idem, {"plan_id": str(plan_id)}, work)


@app.post("/v1/decisions/{decision_id}/approve", tags=["plans"], summary="(+) The master or operator approves or rejects a proposed plan change; the proposer cannot. On approval the plan is activated, the charterer's ETA is updated and the ship sails it")
def approve(decision_id: uuid.UUID, decision: Literal["approved", "rejected"] = "approved", ctx: Ctx = Depends(auth("plans:approve")), idem: str | None = IdemKey):
    def work(c):
        f = fleet(c)
        d = c.execute("SELECT * FROM decisions WHERE id = %s FOR UPDATE", [decision_id]).fetchone()
        if not d:
            raise Problem(404, "decision_not_found")
        if d["status"] != "proposed":
            raise Problem(409, "already_decided", f"this decision is {d['status']}")
        if d["proposed_by"] == ctx.actor_id:
            raise Problem(403, "proposer_cannot_approve", "a plan change beyond the charter terms needs a second person")
        plan = c.execute("SELECT * FROM speed_plan WHERE id = %s", [d["speed_plan_id"]]).fetchone()
        v = _open(c, d["voyage_id"])
        if decision == "approved" and abs(plan["det_track"][0][0] - f["clock_h"]) > 1e-6:
            raise Problem(409, "plan_stale", "the ship has moved since this plan was made; plan again")
        c.execute("UPDATE decisions SET status = %s, decided_by = %s, decided_at = now() WHERE id = %s", [decision, ctx.actor_id, decision_id])
        if decision == "approved":
            activate(c, f, v, plan, ctx.actor_id, f"approved by {ctx.role}: {plan['why']}")
        else:
            c.execute("UPDATE speed_plan SET status = 'rejected' WHERE id = %s", [plan["id"]])
        audit.record(c, ctx, f"plan.{decision}", "decision", decision_id, {"voyage": v["ref"], "plan": str(plan["id"]), "by_role": ctx.role})
        return 200, {"decision_id": decision_id, "status": decision, "plan_id": plan["id"], "plan_status": "active" if decision == "approved" else "rejected",
                     "eta_notified": at(plan["eta"]["p50"]) if decision == "approved" else v["notified_eta_at"]}
    return run(ctx, idem, {"decision": decision}, work)


# --- bunker-planner -----------------------------------------------------------------------------------------------------------------------
class CallIn(BaseModel):
    port: str
    price_usd_t: float = Field(gt=0, le=3000)
    fee_usd: float = Field(6000, ge=0, le=100000)


class BunkerIn(BaseModel):
    voyage_id: uuid.UUID
    rob_t: float = Field(ge=0, description="fuel remaining on board now")
    calls: list[CallIn] = Field(default_factory=list, max_length=6, description="this port and the next calls; default: departure, arrival, departure again")
    min_stem_t: float = Field(250, ge=0, le=5000)


PRICES = {"USNYC": 640.0, "USORF": 625.0, "CAHAL": 655.0, "NLRTM": 578.0, "BEANR": 584.0, "FRLEH": 601.0, "DEHAM": 590.0}


@app.post("/v1/bunker/plan", status_code=201, tags=["bunker"], summary="Where and how much to buy over the next calls: a MILP with prices, delivery fees, minimum stems, tank capacity and a reserve from the active plan's P90 fuel, against topping up at every call")
def bunker(body: BunkerIn, ctx: Ctx = Depends(auth("bunker:plan")), idem: str | None = IdemKey):
    def work(c):
        f = fleet(c)
        v = _open(c, body.voyage_id)
        if not v["active_plan_id"]:
            raise Problem(409, "no_active_plan", "activate a plan first: the bunker plan uses its fuel band")
        cap = v["vessel_meta"]["tank_t"]
        if body.rob_t > cap:
            raise Problem(422, "rob_above_capacity", f"tank capacity is {cap} t")
        plan = c.execute("SELECT * FROM speed_plan WHERE id = %s", [v["active_plan_id"]]).fetchone()
        calls = [x.model_dump() for x in body.calls] or [{"port": v["orig"], "price_usd_t": PRICES[v["orig"]], "fee_usd": 6000.0},
                                                         {"port": v["dest"], "price_usd_t": PRICES[v["dest"]], "fee_usd": 6000.0},
                                                         {"port": v["orig"], "price_usd_t": PRICES[v["orig"]], "fee_usd": 6000.0}]
        for x in calls:
            if x["port"] not in world.PORTS:
                raise Problem(422, "unknown_port", x["port"])
        days = (plan["eta"]["p50"] - plan["det_track"][0][0]) / 24
        leg = {"p50": plan["fuel"]["p50"], "p90": plan["fuel"]["p90"], "days": days}
        legs = [leg] + [{"p50": leg["p50"] * (1.08 if i % 2 == 0 else 1.0), "p90": leg["p90"] * (1.08 if i % 2 == 0 else 1.0), "days": days} for i in range(len(calls) - 1)]
        res = engine.bunker_plan([{"port": x["port"], "price": x["price_usd_t"], "fee": x["fee_usd"]} for x in calls], legs, body.rob_t, cap, body.min_stem_t)
        if res["status"] != "optimal":
            raise Problem(422, "bunker_infeasible", "no plan keeps the reserve within the tank's capacity")
        bid = uuid.uuid4()
        c.execute("""INSERT INTO bunker_plan (id, tenant_id, voyage_id, speed_plan_id, request, plan, cost_usd, baseline_cost_usd, model_version, created_by)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", [bid, ctx.tenant_id, v["voyage_id"], plan["id"], Jsonb(body.model_dump(mode="json")), Jsonb(res),
                                                                 res["cost_usd"], res["baseline_cost_usd"], engine.BUNKER_VERSION, ctx.actor_id])
        audit.record(c, ctx, "bunker.planned", "bunker_plan", bid, {"voyage": v["ref"], "cost_usd": res["cost_usd"], "saving_usd": res["saving_usd"]})
        return 201, {"bunker_plan_id": bid, "voyage_id": v["voyage_id"], "capacity_t": cap, "rob_t": body.rob_t, "legs": [{k: round(x, 1) for k, x in lg.items()} for lg in legs],
                     **res, "model_version": engine.BUNKER_VERSION,
                     "how": "legs after this one are estimated from this plan's fuel (westbound 8% heavier); the reserve on arrival is the leg's P90 over P50 plus three days' burn, "
                            "and the plan must end the horizon with at least what it started with"}
    return run(ctx, idem, body, work)


# --- the simulator moves the ship; the voyage monitor watches ------------------------------------------------------------------------
class StormIn(BaseModel):
    lat: float = Field(ge=30, le=60, description="where the storm centre will be ...")
    lon: float = Field(ge=-76, le=-3)
    in_hours: float = Field(ge=12, le=400, description="... this many hours from now")
    forms_in_hours: float = Field(ge=0, le=400, description="it forms this many hours from now")
    course: float = Field(70, ge=0, lt=360)
    speed_kn: float = Field(20, ge=5, le=40)
    wind_ms: float = Field(30, ge=15, le=45)
    radius_deg: float = Field(4.0, ge=1.5, le=7)
    life_h: float = Field(120, ge=36, le=240)

    @model_validator(mode="after")
    def order(self):
        if self.forms_in_hours >= self.in_hours:
            raise ValueError("the storm must form before it reaches the given position")
        return self


class CongestionIn(BaseModel):
    port: str
    berth_not_before: datetime.datetime
    ships_waiting: int = Field(14, ge=1, le=200)


class InjectIn(BaseModel):
    storm: StormIn | None = None
    congestion: CongestionIn | None = None


class AdvanceIn(BaseModel):
    hours: float = Field(gt=0, le=600)
    inject: InjectIn | None = None


@app.post("/v1/voyages/{voyage_id}:advance", status_code=202, tags=["simulator"], summary="(+) Move the clock: the generator sails the ship on its active plan through the real weather, reporting AIS positions, hourly engine samples and noon reports; then the voyage monitor checks the remaining plan against a fresh forecast and the port line-up. The generator can be told about a storm or port congestion first (the demo's injection); the service sees only forecasts, line-ups and the ship's reports")
def advance(voyage_id: uuid.UUID, body: AdvanceIn, ctx: Ctx = Depends(auth("simulator:control")), idem: str | None = IdemKey):
    def work(c):
        fleet(c)
        v = _open(c, voyage_id)
        if not v["active_plan_id"]:
            raise Problem(409, "no_active_plan", "activate a plan before sailing")
        if body.inject and body.inject.congestion and body.inject.congestion.port not in world.PORTS:
            raise Problem(422, "unknown_port", body.inject.congestion.port)
        return 202, jobs.enqueue(c, ctx, "voyage.advance", {**body.model_dump(mode="json"), "voyage_id": str(voyage_id)})
    return run(ctx, idem, {**body.model_dump(mode="json"), "voyage_id": str(voyage_id)}, work)


def plan_path(plan_row, route_row):
    return world.Path([p[0] for p in route_row["path"]], [p[1] for p in route_row["path"]]), [tuple(x) for x in plan_row["legs"]]


def bridge_obs(seed, ref, h, k):
    """What the bridge records each hour: log speed, metered fuel, the sea by eye, the relative wind, a sector for the sea."""
    rng = np.random.default_rng([seed, 97, world.key(ref), k])
    ang = np.degrees(np.arccos(np.clip(2 * h["g"] - 1, -1, 1)))
    return {"stw": round(h["stw"] + rng.normal(0, 0.1), 2), "fuel_t": round(h["fuel_t"] * float(np.exp(rng.normal(0, 0.02))), 4),
            "hs_obs": round(max(0.0, h["hs"] * float(np.exp(rng.normal(0, 0.12)))) * 2) / 2, "wave_sector": int(min(4, round(ang / 45))),
            "head_wind_obs": round(h["head_ms"] + rng.normal(0, 1.0), 1)}


def monitor(c, f, v, plan, route_row, now, m, terms):
    """The voyage monitor: the remaining plan against a fresh forecast and the port line-up. An event is raised only while
    its condition holds now, and closed when it no longer does."""
    vs = vessel_like(v)
    P, legs = plan_path(plan, route_row)
    lu = berth_estimate(c, f, v["dest"], now)
    berth_h = lu["earliest_berth_h"] or now
    a = engine.assess(m, P, legs, f["model_seed"], storms_told(f), now, now, v["state"]["s"], terms, berth_h, v["attributes"]["load_disp"], days_fn(vs))
    snaps = snapshot(c, f, now, [now + 12 * k for k in range(0, 17)])
    ts = track_summary(a["det_track"])
    raised, current = [], {}
    if ts["max_hs"] > STORM_EVENT_HS:
        near = min(snaps, key=lambda s: abs(hours_of(s["valid_at"]) - hours_of(ts["max_hs_at"])))["storms"]
        current["storm_on_route"] = {"max_hs_m": ts["max_hs"], "worst_at": ts["max_hs_at"].isoformat(), "position": ts["max_hs_pos"], "hours_above_6m": ts["heavy_h"],
                                     "storms_in_forecast": near, "rule": f"forecast seas above {STORM_EVENT_HS:g} m on the remaining planned track"}
    if lu["earliest_berth_h"] and lu["earliest_berth_h"] > a["arrival"]["p50"] + CONGESTION_EVENT_H:
        current["port_congestion"] = {"port": v["dest"], "ships_waiting": lu["ships_waiting"], "earliest_berth": at(lu["earliest_berth_h"]).isoformat(),
                                      "plan_eta_p50": at(a["arrival"]["p50"]).isoformat(), "wait_h": round(lu["earliest_berth_h"] - a["arrival"]["p50"], 1),
                                      "rule": f"the port's earliest berth is more than {CONGESTION_EVENT_H:g} h after the plan's P50 arrival"}
    if a["arrival"]["p90"] > max(terms["window_close_h"], berth_h) + 0.5:
        current["eta_at_risk"] = {"eta_p90": at(a["arrival"]["p90"]).isoformat(), "window_close": at(terms["window_close_h"]).isoformat(), "p_late": round(a["p_late"], 2),
                                  "port_earliest_berth": at(lu["earliest_berth_h"]).isoformat() if lu["earliest_berth_h"] else None,
                                  "rule": "the plan's P90 arrival is after both the window's close and the port's earliest berth (late hours the ship would be charged for)"}
    for kind in ("storm_on_route", "port_congestion", "eta_at_risk"):
        openev = c.execute("SELECT id FROM voyage_event WHERE voyage_id = %s AND kind = %s AND status = 'open'", [v["voyage_id"], kind]).fetchone()
        if kind in current and not openev:
            eid = uuid.uuid4()
            c.execute("INSERT INTO voyage_event (id, tenant_id, voyage_id, kind, at, detail) VALUES (%s,%s,%s,%s,%s,%s)",
                      [eid, f["tenant_id"], v["voyage_id"], kind, at(now), Jsonb(current[kind])])
            raised.append({"id": eid, "kind": kind, **current[kind]})
        elif kind in current and openev:
            c.execute("UPDATE voyage_event SET detail = %s WHERE id = %s", [Jsonb(current[kind]), openev["id"]])
        elif openev:
            c.execute("UPDATE voyage_event SET status = 'closed' WHERE id = %s", [openev["id"]])
    eta = {"p10": at(a["arrival"]["p10"]), "p50": at(a["arrival"]["p50"]), "p90": at(a["arrival"]["p90"]), "fuel_remaining_p50_t": round(a["fuel"]["p50"], 1),
           "assessed_at": at(now), "map_valid_at": ts["max_hs_at"] or at(now + 48)}
    return raised, eta, lu


@jobs.handler("voyage.advance")
def advance_job(c, job):
    """Sail in daily steps. After each day the monitor reads a fresh forecast and the port's line-up and raises (or closes)
    events; it changes nothing itself: a change of plan is a person's decision."""
    p = job["payload"]
    f = fleet(c)
    v = _open(c, p["voyage_id"])
    now0 = f["clock_h"]
    told = list(f["told"])
    inj = p.get("inject") or {}
    new_told = []
    if inj.get("storm"):
        s_ = inj["storm"]
        st_ = world.storm_across(s_["lat"], s_["lon"], now0 + s_["in_hours"], now0 + s_["forms_in_hours"], s_["course"], s_["speed_kn"], s_["wind_ms"], s_["radius_deg"],
                                 s_["life_h"], sid=f"told-{len(told) + 1}")
        new_told.append({**st_, "kind": "storm"})
    if inj.get("congestion"):
        cg = inj["congestion"]
        new_told.append({"kind": "congestion", "port": cg["port"], "known_from_h": now0, "berth_from_h": hours_of(datetime.datetime.fromisoformat(cg["berth_not_before"])),
                         "ships_waiting": cg["ships_waiting"]})
    told += new_told
    c.execute("UPDATE fleets SET told = %s", [Jsonb(told)])
    f = dict(f, told=told)
    seed = f["model_seed"]
    vt = true_vessel(f, v["vessel_ref"])
    disp = v["attributes"]["load_disp"]
    truth = world.Weather(seed, [x for x in told if x["kind"] == "storm"])
    m = model_of(c, f, v["vessel_ref"])
    terms = terms_of(v)
    actor = uuid.UUID(p["actor_id"])
    dep_h = hours_of(v["departure_at"])
    now, left = now0, float(p["hours"])
    raised, eta, lu, metered, sailed_nm = [], None, None, 0.0, 0.0
    arrived = False
    while left > 1e-9:
        v = voyage_row(c, v["voyage_id"])
        st = dict(v["state"])
        plan = c.execute("SELECT * FROM speed_plan WHERE id = %s", [v["active_plan_id"]]).fetchone()
        route_row = c.execute("SELECT * FROM route_plan WHERE id = %s", [plan["route_plan_id"]]).fetchone()
        P, legs = plan_path(plan, route_row)
        chunk = min(24.0, left)
        run_ = world.sail(vt, P, legs, truth, now, disp, s0=st.get("s", 0.0), hours=chunk)
        eng, pos = [], []
        for h in run_["track"]:
            ob = bridge_obs(seed, v["ref"], h, int(round((h["t"] - dep_h) * 1000)))
            eng.append((f["tenant_id"], v["voyage_id"], at(h["t"]), h["hours"], ob["stw"], round(h["power_kw"]), ob["fuel_t"], ob["hs_obs"], ob["wave_sector"], ob["head_wind_obs"]))
        for a_ in world.ais(run_["track"], seed, f"{v['ref']}:{int(now)}"):
            pos.append((f["tenant_id"], v["voyage_id"], at(a_["t"]), a_["lat"], a_["lon"], a_["sog"], a_["course"]))
        db.load(c, "engine_sample", ["tenant_id", "voyage_id", "at", "hours", "stw", "power_kw", "fuel_t", "hs_obs", "wave_sector", "head_wind_obs"], eng)
        db.load(c, "position", ["tenant_id", "voyage_id", "at", "lat", "lon", "sog", "course"], pos)
        burned = sum(e[6] for e in eng)
        metered += burned
        sailed_nm += run_["s"] - st.get("s", 0.0)
        lat, lon, _ = P.at(run_["s"])
        st.update(s=run_["s"], t=run_["t"], lat=float(lat), lon=float(lon), fuel_t=round(st.get("fuel_t", 0.0) + burned, 2))
        c.execute("UPDATE voyage SET status = 'underway', state = %s, observed_at = %s WHERE voyage_id = %s", [Jsonb(jsonable_encoder(st)), at(run_["t"]), v["voyage_id"]])
        if run_["arrived"]:
            arrived, now = True, run_["t"]
            break
        now += chunk
        left -= chunk
        c.execute("UPDATE fleets SET clock_h = %s", [now])
        f = dict(f, clock_h=now)
        v = voyage_row(c, v["voyage_id"])
        r_, eta, lu = monitor(c, f, v, plan, route_row, now, m, terms)
        raised += [dict(x, at=at(now)) for x in r_]
        st = dict(v["state"], eta=jsonable_encoder(eta))
        c.execute("UPDATE voyage SET state = %s WHERE voyage_id = %s", [Jsonb(st), v["voyage_id"]])
    v = voyage_row(c, v["voyage_id"])
    st = dict(v["state"])
    noon = noon_reports(c, f, v, st["t"])
    report, status, new_clock = None, "underway", now
    if arrived:
        arrival = st["t"]
        ready = world.port_ready(v["dest"], arrival, [x for x in told if x["kind"] == "congestion"])
        berth = max(arrival, ready, terms["window_open_h"])
        wait = berth - arrival
        anchor_fuel = wait * world.anchor_tph(vt)
        st.update(arrival_h=arrival, berth_h=berth, port_ready_h=ready if math.isfinite(ready) else None, anchor_fuel_t=round(anchor_fuel, 2),
                  fuel_t=round(st["fuel_t"] + anchor_fuel, 2), eta={"arrived_at": at(arrival).isoformat()})
        for kind, t_, det in (("arrived", arrival, {"pilot_station": world.PORTS[v["dest"]][0], "wait_h": round(wait, 1)}),
                              ("berthed", berth, {"anchor_fuel_t": round(anchor_fuel, 1)})):
            c.execute("INSERT INTO voyage_event (id, tenant_id, voyage_id, kind, at, detail, status) VALUES (%s,%s,%s,%s,%s,%s,'info')",
                      [uuid.uuid4(), f["tenant_id"], v["voyage_id"], kind, at(t_), Jsonb(det)])
            c.execute("INSERT INTO port_call (id, tenant_id, port, voyage_id, kind, reported_at, detail) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                      [uuid.uuid4(), f["tenant_id"], v["dest"], v["voyage_id"], "arrival" if kind == "arrived" else "berth", at(t_), Jsonb(det)])
        c.execute("UPDATE voyage_event SET status = 'closed' WHERE voyage_id = %s AND status = 'open'", [v["voyage_id"]])
        report = voyage_report(c, f, v, vt, m, terms, st, told)
        status, new_clock = "berthed", max(berth, now0)
    c.execute("UPDATE voyage SET status = %s, state = %s, report = %s WHERE voyage_id = %s",
              [status, Jsonb(jsonable_encoder(st)), Jsonb(jsonable_encoder(report)) if report else None, v["voyage_id"]])
    c.execute("UPDATE fleets SET clock_h = %s", [new_clock])
    audit.record(c, worker_ctx(job), "voyage.advanced", "voyage", v["voyage_id"], {"hours": p["hours"], "events": [r["kind"] for r in raised], "arrived": arrived,
                                                                                  "told": [x["kind"] for x in new_told]})
    return {"voyage_id": v["voyage_id"], "from": at(now0), "to": at(new_clock), "hours_sailed": round(st["t"] - now0, 1), "distance_nm": round(sailed_nm, 1),
            "position": [round(st["lat"], 3), round(st["lon"], 3)], "fuel_metered_t": round(metered, 1), "fuel_voyage_t": st["fuel_t"], "noon_reports": noon,
            "arrived": arrived, "events_raised": raised, "eta_now": eta,
            "port_lineup": lu and {**lu, "earliest_berth": at(lu["earliest_berth_h"]) if lu["earliest_berth_h"] else None}, "report": report,
            "simulation_truth": {"told": new_told, "note": "what the generator was told; the planners and the monitor never read this, only forecasts, line-ups and the ship's reports"}}


def noon_reports(c, f, v, t_now):
    """Noon reports for each complete day since departure, from the hourly engine samples (stored, and scored by the model)."""
    dep = v["departure_at"]
    done = c.execute("SELECT count(*) AS n FROM fuel_sample WHERE voyage_id = %s", [v["voyage_id"]]).fetchone()["n"]
    full_days = int((t_now - hours_of(dep)) // 24)
    out = []
    m = model_of(c, f, v["vessel_ref"])
    vs = vessel_like(v)
    last_clean = vs["metadata"]["last_hull_cleaning_h"]
    for d in range(done, full_days):
        rows = c.execute("SELECT * FROM engine_sample WHERE voyage_id = %s AND at >= %s AND at < %s ORDER BY at",
                         [v["voyage_id"], dep + datetime.timedelta(days=d), dep + datetime.timedelta(days=d + 1)]).fetchall()
        if not rows:
            continue
        hrs = sum(r["hours"] for r in rows)
        rep = {"stw": round(sum(r["stw"] * r["hours"] for r in rows) / hrs, 2), "fuel_t": round(sum(r["fuel_t"] for r in rows), 2),
               "hs_obs": round(2 * sum(r["hs_obs"] * r["hours"] for r in rows) / hrs) / 2, "wave_sector": int(round(np.median([r["wave_sector"] for r in rows]))),
               "head_wind_obs": round(sum(r["head_wind_obs"] * r["hours"] for r in rows) / hrs, 1), "disp": v["attributes"]["load_disp"],
               "days_clean": round((hours_of(rows[0]["at"]) - last_clean) / 24, 1)}
        pred = float(engine.predict_tpd(m, *engine.report_inputs(rep))) * hrs / 24
        pos = c.execute("SELECT lat, lon FROM position WHERE voyage_id = %s AND at <= %s ORDER BY at DESC LIMIT 1", [v["voyage_id"], rows[-1]["at"]]).fetchone()
        c.execute("""INSERT INTO fuel_sample (tenant_id, vessel_id, voyage_id, at, hours, stw, fuel_t, hs_obs, wave_sector, head_wind_obs, disp, days_clean, lat, lon, source, predicted_t)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'noon',%s)""",
                  [f["tenant_id"], v["vessel_id"], v["voyage_id"], rows[0]["at"], hrs, rep["stw"], rep["fuel_t"], rep["hs_obs"], rep["wave_sector"], rep["head_wind_obs"],
                   rep["disp"], rep["days_clean"], pos and pos["lat"], pos and pos["lon"], pred])
        out.append({"day": d + 1, **rep, "hours": round(hrs, 1), "predicted_t": round(pred, 2)})
    return out


def voyage_report(c, f, v, vt, m, terms, st, told):
    """At berthing: what the voyage cost, its ETA against the plan's band, and the savings against the weather-normalised
    baseline (the shortest sea route at service speed from the same departure through the same realised weather)."""
    dep = hours_of(v["departure_at"])
    disp = v["attributes"]["load_disp"]
    vs = vessel_like(v)
    part = particulars(vs)
    storms = [x for x in told if x["kind"] == "storm"]
    cong = [x for x in told if x["kind"] == "congestion"]
    ready = st.get("port_ready_h")
    ready = -math.inf if ready is None else ready
    wait = st["berth_h"] - st["arrival_h"]
    actual = engine.outcome(terms, dep, st["arrival_h"], st["fuel_t"] - st["anchor_fuel_t"], ready, st["anchor_fuel_t"] / wait if wait > 0 else 0.0)
    P = world.Path(*world.passage(v["orig"], v["dest"]))
    legs = [(P.length, part["service_speed"])]
    hind = world.Weather(f["model_seed"], storms)                 # reanalysis: the weather that really happened, known after the fact
    Fh = world.Field(P, [hind], dep, dep + P.length / 8 + 72)
    b_arr, b_fuel, b_track = engine.deterministic(m, P, legs, Fh, dep, 0.0, disp, days_fn(vs))
    base_model = engine.outcome(terms, dep, b_arr, b_fuel, world.port_ready(v["dest"], b_arr, cong), engine.anchor_tph_model(m))
    tr = world.sail(vt, P, legs, hind, dep, disp)
    base_truth = engine.outcome(terms, dep, tr["t"], tr["fuel_t"], world.port_ready(v["dest"], tr["t"], cong), world.anchor_tph(vt))
    first = c.execute("SELECT eta, fuel FROM speed_plan WHERE voyage_id = %s AND activated_at IS NOT NULL ORDER BY activated_at LIMIT 1", [v["voyage_id"]]).fetchone()
    approved = c.execute("""SELECT s.label, s.eta FROM decisions d JOIN speed_plan s ON s.id = d.speed_plan_id WHERE d.voyage_id = %s AND d.status = 'approved'
                             ORDER BY d.decided_at DESC LIMIT 1""", [v["voyage_id"]]).fetchone()
    fl = lambda o: {"fuel_t": round(float(o["fuel_t"]), 1), "co2_t": round(float(o["co2_t"]), 1), "cost_usd": round(float(o["cost_usd"])), "wait_h": round(float(o["wait_h"]), 1),  # noqa: E731
                    "late_h": round(float(o["late_h"]), 1), "hire_usd": round(float(o["hire_usd"])), "late_usd": round(float(o["late_usd"])),
                    "berth_at": at(float(o["berth_h"])), "fuel_usd": round(float(o["fuel_usd"])), "carbon_usd": round(float(o["carbon_usd"]))}
    A, Bm, Bt = fl(actual), fl(base_model), fl(base_truth)
    sav = lambda b: {"fuel_t": round(b["fuel_t"] - A["fuel_t"], 1), "fuel_pct": round(100 * (1 - A["fuel_t"] / b["fuel_t"]), 1), "co2_t": round(b["co2_t"] - A["co2_t"], 1),  # noqa: E731
                     "cost_usd": b["cost_usd"] - A["cost_usd"], "cost_pct": round(100 * (1 - A["cost_usd"] / b["cost_usd"]), 1)}
    return {"actual": {**A, "arrival_at": at(st["arrival_h"]), "passage_fuel_t": round(st["fuel_t"] - st["anchor_fuel_t"], 1), "anchor_fuel_t": st["anchor_fuel_t"]},
            "baseline": {"what": f"shortest sea route ({P.length:,.0f} nm) at service speed {part['service_speed']} kn from the same departure, through the same realised weather",
                         "path": coarse(P),
                         "fuel_model_on_reanalysis": {**Bm, "arrival_at": at(b_arr), **track_summary(b_track)}, "simulation_truth": {**Bt, "arrival_at": at(tr["t"]), **track_summary(tr["track"])}},
            "savings_vs_baseline": {"by_fuel_model": sav(Bm), "simulation_truth": sav(Bt)},
            "eta_vs_departure_plan": first and {"p50": at(first["eta"]["p50"]), "p90": at(first["eta"]["p90"]), "actual": at(st["arrival_h"]),
                                                "fuel_p50_t": round(first["fuel"]["p50"], 1)},
            "eta_vs_approved_plan": approved and {"label": approved["label"], "p50": at(approved["eta"]["p50"]), "p90": at(approved["eta"]["p90"]), "actual": at(st["arrival_h"])},
            "eta_notified": v["notified_eta_at"], "port_ready_at": at(ready) if math.isfinite(ready) else None,
            "how": "a real deployment measures the baseline with the vessel's fuel model on reanalysis weather; the simulation truth column re-sails the generator's ship, "
                   "which only a simulator can do, and checks the first"}


# --- reading a voyage -------------------------------------------------------------------------------------------------------------------
@app.get("/v1/voyages/{voyage_id}", tags=["voyages"], summary="(+) A voyage: terms, status, the active plan and its band, the AIS track, noon reports, events, plans, and the voyage report once berthed")
def voyage_detail(voyage_id: uuid.UUID, ctx: Ctx = Depends(auth("fleet:read"))):
    with db.tx(ctx.tenant_id) as c:
        f = fleet(c)
        v = voyage_row(c, voyage_id)
        track = c.execute("SELECT at, lat, lon, sog FROM position WHERE voyage_id = %s ORDER BY at", [voyage_id]).fetchall()
        noon = c.execute("SELECT at, hours, stw, fuel_t, predicted_t, hs_obs, wave_sector FROM fuel_sample WHERE voyage_id = %s ORDER BY at", [voyage_id]).fetchall()
        events = c.execute("SELECT id, kind, at, detail, status FROM voyage_event WHERE voyage_id = %s ORDER BY at, raised_at", [voyage_id]).fetchall()
        plans = c.execute("""SELECT s.id, s.label, s.status, s.eta, s.fuel, s.expected, s.within_terms, s.why, s.activated_at, s.created_at, r.kind AS route_kind, r.distance_nm
                               FROM speed_plan s JOIN route_plan r ON r.id = s.route_plan_id WHERE s.voyage_id = %s ORDER BY s.created_at""", [voyage_id]).fetchall()
        active = None
        if v["active_plan_id"]:
            a = c.execute("SELECT s.legs, s.eta, r.path FROM speed_plan s JOIN route_plan r ON r.id = s.route_plan_id WHERE s.id = %s", [v["active_plan_id"]]).fetchone()
            active = {"id": v["active_plan_id"], "eta": {k: at(x) for k, x in a["eta"].items()}, "path": a["path"][::3] + [a["path"][-1]]}
        mv = (v["state"].get("eta") or {}).get("map_valid_at")
        wc = None
        if v["status"] == "underway":
            wc = c.execute("""SELECT issued_at, valid_at, res_deg, lat0, lon0, nlat, nlon, hs_dm, storms FROM weather_cell
                               WHERE issued_at = (SELECT max(issued_at) FROM weather_cell) ORDER BY abs(extract(epoch FROM valid_at - %s::timestamptz)) LIMIT 1""",
                           [mv or at(f["clock_h"])]).fetchone()
    st = dict(v["state"])
    return jsonable_encoder({"voyage_id": v["voyage_id"], "ref": v["ref"], "vessel": v["vessel_ref"], "vessel_name": v["vessel_name"], "status": v["status"], "orig": v["orig"],
                             "dest": v["dest"], "departure_at": v["departure_at"], "terms": v["attributes"].get("terms"), "load_disp": v["attributes"].get("load_disp"),
                             "notified_eta_at": v["notified_eta_at"], "clock": at(f["clock_h"]), "state": st, "active_plan": active, "track": track[::2] + track[-1:],
                             "noon_reports": noon, "events": events, "plans": plans, "map": wc, "report": v["report"]})


@app.get("/v1/voyages/{voyage_id}/variance", tags=["voyages"], summary="Plan against what happened, hour by hour over the sailed part: fuel variance split into speed (orders and the speed made), weather (the sea met against the forecast's) and model (what the fuel model cannot explain: hull, engine, the model itself), daily rows, and the ETA against what the charterer was told")
def voyage_variance(voyage_id: uuid.UUID, ctx: Ctx = Depends(auth("fleet:read"))):
    with db.tx(ctx.tenant_id) as c:
        f = fleet(c)
        v = voyage_row(c, voyage_id)
        m = model_of(c, f, v["vessel_ref"])
        plans = c.execute("SELECT id, label, det_track, activated_at FROM speed_plan WHERE voyage_id = %s AND activated_at IS NOT NULL ORDER BY activated_at", [voyage_id]).fetchall()
        eng = c.execute("SELECT at, hours, stw, fuel_t, hs_obs, wave_sector, head_wind_obs FROM engine_sample WHERE voyage_id = %s ORDER BY at", [voyage_id]).fetchall()
    if not eng:
        raise Problem(409, "not_sailed_yet", "nothing has been sailed on this voyage yet")
    dep = hours_of(v["departure_at"])
    planned, actual, days = [], [], {}
    for i, pl in enumerate(plans):
        a0 = hours_of(pl["activated_at"])
        a1 = hours_of(plans[i + 1]["activated_at"]) if i + 1 < len(plans) else 1e12
        trk = [r for r in pl["det_track"] if a0 - 1e-6 <= r[0] < a1 - 1e-6]
        act = [e for e in eng if a0 - 1e-6 <= hours_of(e["at"]) < a1 - 1e-6]
        n = min(len(trk), len(act))
        for r, e in zip(trk[:n], act[:n]):
            planned.append({"t": r[0], "stw": r[3], "hs": r[4], "g": r[5], "head_ms": r[6], "hours": r[8], "fuel_t": r[7]})
            g_obs = (1 + np.cos(np.radians(45 * e["wave_sector"]))) / 2
            actual.append({"t": hours_of(e["at"]), "stw": e["stw"], "hs_obs": e["hs_obs"], "g_obs": g_obs, "head_obs": e["head_wind_obs"], "hours": e["hours"], "fuel_t": e["fuel_t"],
                           "plan_s_rate": r[2]})
            d = int((hours_of(e["at"]) - dep) // 24) + 1
            row = days.setdefault(d, {"day": d, "planned_fuel_t": 0.0, "actual_fuel_t": 0.0, "planned_stw": [], "actual_stw": [], "forecast_hs": [], "observed_hs": []})
            row["planned_fuel_t"] += r[7]
            row["actual_fuel_t"] += e["fuel_t"]
            row["planned_stw"].append(r[3]), row["actual_stw"].append(e["stw"]), row["forecast_hs"].append(r[4]), row["observed_hs"].append(e["hs_obs"])
    vs = vessel_like(v)
    split = engine.variance(m, planned, actual, v["attributes"]["load_disp"], days_fn(vs)) if planned else None
    rows = [{"day": d["day"], "planned_fuel_t": round(d["planned_fuel_t"], 1), "actual_fuel_t": round(d["actual_fuel_t"], 1), "planned_stw": round(float(np.mean(d["planned_stw"])), 2),
             "actual_stw": round(float(np.mean(d["actual_stw"])), 2), "forecast_hs": round(float(np.mean(d["forecast_hs"])), 1), "observed_hs": round(float(np.mean(d["observed_hs"])), 1)}
            for d in sorted(days.values(), key=lambda x: x["day"])]
    eta = v["state"].get("eta") or {}
    ref = eta.get("arrived_at") or eta.get("p50")
    return jsonable_encoder({"voyage_id": voyage_id, "hours_compared": len(planned), "fuel": split, "days": rows, "plans_sailed": [{"label": p["label"], "activated_at": p["activated_at"]} for p in plans],
                             "eta": {"notified": v["notified_eta_at"], "now_p50": eta.get("p50"), "now_p90": eta.get("p90"), "arrived_at": eta.get("arrived_at"),
                                     "drift_h": round(hours_of(datetime.datetime.fromisoformat(ref)) - hours_of(v["notified_eta_at"]), 1) if ref and v["notified_eta_at"] else None},
                             "how": "planned fuel is the model on the plan's forecast hour by hour; then the speed made replaces the planned speed, then the bridge's observed sea "
                                    "replaces the forecast's; what is left against the metered fuel is the model's (hull, engine, the model itself)"})


# --- scenarios: alternatives side by side ----------------------------------------------------------------------------------------------------
class AltIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    route: Literal["keep", "optimize"] = "optimize"
    speed: Literal["keep", "optimize", "hold_eta", "service"] = "optimize"


class ScenarioIn(BaseModel):
    voyage_id: uuid.UUID
    alternatives: list[AltIn] = Field(default_factory=list, max_length=5)


DEFAULT_ALTS = [{"name": "Keep the plan", "route": "keep", "speed": "keep"},
                {"name": "Hold the notified ETA", "route": "optimize", "speed": "hold_eta"},
                {"name": "Re-speed on the same route", "route": "keep", "speed": "optimize"},
                {"name": "Re-route and re-speed", "route": "optimize", "speed": "optimize"}]


@app.post("/v1/scenarios", status_code=202, tags=["scenarios"], summary="Compare route and speed alternatives from where the ship is now, with the latest forecast and the port's line-up: ETA band, fuel, CO2, expected cost with its charter penalty, waiting at anchor and the worst sea on the way, side by side. Each becomes a candidate plan that can be activated")
def scenarios(body: ScenarioIn, ctx: Ctx = Depends(auth("scenarios:run")), idem: str | None = IdemKey):
    def work(c):
        fleet(c)
        v = _open(c, body.voyage_id)
        if not v["active_plan_id"] and any(a.route == "keep" or a.speed == "keep" for a in body.alternatives or []):
            raise Problem(422, "nothing_to_keep", "there is no active plan to keep")
        return 202, jobs.enqueue(c, ctx, "scenario.compare", body.model_dump(mode="json"))
    return run(ctx, idem, body, work)


@jobs.handler("scenario.compare")
def scenario_job(c, job):
    p = job["payload"]
    f = fleet(c)
    v = _open(c, p["voyage_id"])
    vs = vessel_like(v)
    m = model_of(c, f, v["vessel_ref"])
    terms = terms_of(v)
    part = particulars(vs)
    start, t0 = start_of(v)
    now = f["clock_h"]
    seed, told = f["model_seed"], storms_told(f)
    lu = berth_estimate(c, f, v["dest"], now)
    berth_h = lu["earliest_berth_h"] or now
    disp, days_at = v["attributes"]["load_disp"], days_fn(vs)
    notified = hours_of(v["notified_eta_at"]) if v["notified_eta_at"] else None
    active = route_row = None
    if v["active_plan_id"]:
        active = c.execute("SELECT * FROM speed_plan WHERE id = %s", [v["active_plan_id"]]).fetchone()
        route_row = c.execute("SELECT * FROM route_plan WHERE id = %s", [active["route_plan_id"]]).fetchone()
    gf = engine.GridForecast(forecast_view(f, now), now, 24 * 18)
    alts = p["alternatives"] or DEFAULT_ALTS
    out, actor = [], uuid.UUID(p["actor_id"])
    for alt in alts:
        if alt["route"] == "keep" and alt["speed"] == "keep":
            P, legs = plan_path(active, route_row)
            res = engine.assess(m, P, legs, seed, told, now, now, v["state"].get("s", 0.0), terms, berth_h, disp, days_at)
            path_nodes, kind = route_row["nodes"], "kept"
            # store the rest of the kept path as its own route so the candidate stands alone
            s0 = v["state"].get("s", 0.0)
            keep_pts = [(float(a), float(b)) for a, b, s in zip(P.lat, P.lon, P.s) if s > s0 + 1e-6]
            la, lo, _ = P.at(s0)
            P2 = world.Path([float(la)] + [x[0] for x in keep_pts], [float(lo)] + [x[1] for x in keep_pts])
            res = dict(res, path=P2, legs=[(max(0.0, e - s0), sp) for e, sp in legs if e > s0 + 1e-6])
            res["det_track"] = [dict(h, s=h["s"] - s0) for h in res["det_track"]]
        else:
            if alt["route"] == "keep":
                P_old, _ = plan_path(active, route_row)
                pts, route, kind = engine.remaining_path(P_old, v["state"].get("s", 0.0)), "path", "kept"
            else:
                pts, route, kind = None, "optimize", "optimized"
            speed = {"optimize": "optimize", "hold_eta": "optimize", "service": part["service_speed"], "keep": "optimize"}[alt["speed"]]
            deadline = notified if alt["speed"] == "hold_eta" and notified else None
            res = engine.plan(m, part, seed, told, now, now, v["orig"], v["dest"], terms, berth_h, disp, days_at, start=start, route=route, path_pts=pts,
                              speed=speed, deadline_h=deadline, gf=gf)
            path_nodes = res["nodes"]
            if alt["speed"] == "hold_eta" and notified:
                res["tries"] = []
        rid = store_route(c, f["tenant_id"], v["voyage_id"], kind, now, now, float(np.mean([s for _, s in res["legs"]])), path_nodes, res["path"], res["route"], actor, version(f))
        pid, ok, why = store_plan(c, f, v, rid, alt["name"], res, berth_h, actor)
        out.append({"name": alt["name"], "route": alt["route"], "speed": alt["speed"], "speed_plan_id": pid, "within_terms": ok, "why": why, **plan_view(res, terms, now, notified)})
    maps = snapshot(c, f, now, [now + 12 * k for k in range(0, 13)])
    worst = max((o for o in out), key=lambda o: o["max_hs"])
    focus = hours_of(worst["max_hs_at"]) if worst["max_hs_at"] else now + 48
    shown = min(maps, key=lambda mp: abs(hours_of(mp["valid_at"]) - focus))
    sid = uuid.uuid4()
    result = {"scenario_id": sid, "voyage_id": v["voyage_id"], "at": at(now), "position": list(start) if start else None, "notified_eta": at(notified) if notified else None,
              "port_lineup": {"port": v["dest"], "ships_waiting": lu["ships_waiting"], "earliest_berth": at(lu["earliest_berth_h"]) if lu["earliest_berth_h"] else None},
              "alternatives": out, "map": shown, "window": {"open": at(terms["window_open_h"]), "close": at(terms["window_close_h"])},
              "how": "every alternative is planned from the ship's position with the forecast issued now and sailed through its 24 members; costs are from now to berthing: "
                     "fuel and carbon (including waiting at anchor), hire, and the late penalty, which does not apply to waiting the port causes"}
    c.execute("INSERT INTO scenarios (id, tenant_id, voyage_id, request, result, created_by) VALUES (%s,%s,%s,%s,%s,%s)",
              [sid, f["tenant_id"], v["voyage_id"], Jsonb(p), Jsonb(jsonable_encoder(result)), actor])
    audit.record(c, worker_ctx(job), "scenario.compared", "scenario", sid, {"voyage": v["ref"], "alternatives": [a["name"] for a in alts]})
    return result


@app.get("/v1/decisions", tags=["plans"], summary="(+) Proposals and decisions")
def decisions(ctx: Ctx = Depends(auth("fleet:read"))):
    with db.tx(ctx.tenant_id) as c:
        return jsonable_encoder({"items": c.execute("SELECT id, voyage_id, speed_plan_id, kind, rationale, status, proposed_by, decided_by, created_at, decided_at FROM decisions ORDER BY created_at DESC").fetchall()})
