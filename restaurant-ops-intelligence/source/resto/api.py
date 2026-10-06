"""Public API (modular monolith). Blueprint services map to: pos-ingest (sales by 15-minute slot, the ticket ingest API),
demand-forecast (the hierarchical forecast and its refresh), prep-planner (prep plans from forecast quantiles, with the
staffing curve the labor-interface would hand to scheduling), inventory-engine (lots, counts, base-stock orders, backup
orders, the approval rule), waste-predictor (the spoilage hazard on every open lot), margin-intelligence (the food-cost
bridge and promotion economics) and shrinkage-detection (actual against theoretical usage). Not built: Kafka, ClickHouse,
a labor scheduler, a POS connector; see the README.

    uvicorn resto.api:app          python -m core.jobs resto.api      # the worker
"""
import datetime
import functools
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

from . import engine as E
from . import world as W

READ = {"chain:read", "jobs:read"}
PLANNER = READ | {"sales:ingest", "forecast:refresh", "prep:plan", "orders:recommend", "outcomes:run"}
PERMISSIONS = {"viewer": READ, "planner": PLANNER,
               "store_manager": PLANNER | {"chain:load", "chain:advance", "decisions:approve", "audit:read"}}
app = create_app("restaurant-ops-intelligence", PERMISSIONS)
auth = app.state.auth
IdemKey = Header(None, alias="Idempotency-Key")
START = datetime.date(2026, 8, 3)                 # a Monday; day 0 of the chain's history
HISTORY_DAYS, VALIDATE_FROM = 56, 42               # eight weeks of history; the last two score the models
Q_PREP, Q_ING = 0.9, 0.95                          # chosen on a tuning chain (seed 11) the demo and the evaluation never use
CHAIN_NAME = "Verde Grill"


def date_of(day):
    return START + datetime.timedelta(days=int(day))


def day_of(d):
    return (d - START).days


def slot_time(s):
    return f"{W.OPEN_HOUR + s // 4:02d}:{15 * (s % 4):02d}"


def worker_ctx(job):
    return Ctx(job["tenant_id"], uuid.UUID(job["payload"]["actor_id"]), "worker", "system")


def chain(c):
    f = c.execute("SELECT id, tenant_id, name, model_seed, start_date, next_day, told, model_version, snapshot FROM chains").fetchone()
    if not f:
        raise Problem(409, "no_chain", "load a chain first: POST /v1/chain:load")
    return f


def meta(c):
    rows = c.execute("SELECT id, idx, name, region, format, metadata FROM locations ORDER BY idx").fetchall()
    return {"L": len(rows), "ids": [r["id"] for r in rows], "names": [r["name"] for r in rows], "region_name": [r["region"] for r in rows],
            "region": np.array([W.REGIONS.index(r["region"]) for r in rows]), "format": np.array([W.FORMATS.index(r["format"]) for r in rows]),
            "xy": [r["metadata"].get("xy") for r in rows], "idx": {r["id"]: r["idx"] for r in rows}}


@functools.lru_cache(maxsize=8)
def _models(tenant_id, version):
    with db.tx(tenant_id) as c:
        return {r["name"]: pickle.loads(r["artifact"]) for r in c.execute("SELECT name, artifact FROM model_artifacts WHERE version = %s", [version])}


def models(f):
    return _models(str(f["tenant_id"]), f["model_version"])


def system_policy(m):
    return E.SystemPolicy(m["demand-forecast"], raw_ratio=m["consumption"]["raw"], comp_ratio=None, hazard=m["spoilage-hazard"],
                          q_ing=Q_ING, q_prep=Q_PREP)


def log_run(c, t, name, version, subject, inputs_hash, result):
    c.execute("INSERT INTO model_runs (tenant_id, model_name, version, subject, inputs_hash, result) VALUES (%s,%s,%s,%s,%s,%s)",
              [t, name, version, subject, inputs_hash, Jsonb(jsonable_encoder(result))])


# --- what the service knows, as arrays -----------------------------------------------------------------------------------
class DbObs:
    """The planner's view at the close of `day`, read from the tables (the same interface as world.Obs, which the
    simulated days use): counts and lot checks, usage history, kitchen run-outs, the order pipeline with the suppliers'
    notices applied, cooler temperatures and the calendar."""

    def __init__(self, c, f, mt, day, lookback=21):
        L = mt["L"]
        self.day, self.L, self.lunch_sales = day, L, None
        self.ch = {"L": L, "region": mt["region"]}
        lo, hi = date_of(day - lookback), date_of(day)
        idx = mt["idx"]
        ii = {k: n for n, k in enumerate(W.ING)}
        cc = {k: n for n, k in enumerate(W.COMP)}
        it = {k: n for n, k in enumerate(W.ITEM)}
        self.use, self.ing_out, self.comp_use, self.comp_out = {}, {}, {}, {}
        cnt = {}
        for r in c.execute("""SELECT location_id, ingredient_id, business_date, counted, received, actual_use FROM inventory_counts
                               WHERE business_date BETWEEN %s AND %s""", [date_of(day - lookback - 1), hi]):
            dd = day_of(r["business_date"])
            for key, v in (("count", r["counted"]), ("recv", r["received"]), ("use", r["actual_use"])):
                cnt.setdefault((key, dd), np.zeros((L, W.N_ING)))[idx[r["location_id"]], ii[r["ingredient_id"]]] = v
        for dd in range(day - lookback, day + 1):
            if ("count", dd) in cnt:
                self.use[dd] = cnt[("use", dd)]
                prev = cnt.get(("count", dd - 1), cnt[("count", dd)])
                self.ing_out[dd] = cnt[("count", dd)] < 0.03 * np.maximum(prev + cnt[("recv", dd)], 1e-9)
        self.count = cnt.get(("count", day), np.zeros((L, W.N_ING)))
        for dd in range(day - lookback, day + 1):
            self.comp_use[dd] = np.zeros((L, W.N_COMP, 2))
            self.comp_out[dd] = np.zeros((L, W.N_COMP, 2), bool)
        win = np.zeros((2, W.SLOTS))
        win[0, :20], win[1, 20:] = 1, 1
        for r in c.execute("SELECT location_id, item_id, business_date, dine_in, delivery FROM sales WHERE business_date BETWEEN %s AND %s", [lo, hi]):
            units = (np.asarray(r["dine_in"]) + np.asarray(r["delivery"])) @ win.T                # [2] lunch, dinner
            self.comp_use[day_of(r["business_date"])][idx[r["location_id"]]] += np.outer(W.ITEM_COMP[it[r["item_id"]]], units)
        maxp = (W.ITEM_COMP * 1.2).max(0)
        for r in c.execute("""SELECT location_id, business_date, prep_window, component_id, done_qty, discarded, topups FROM prep_tasks
                               WHERE status = 'done' AND business_date BETWEEN %s AND %s""", [lo, hi]):
            k = cc[r["component_id"]]
            w = 1 if (r["prep_window"] == "dinner" or not W.WINDOW_COMP[k]) else 0
            self.comp_out[day_of(r["business_date"])][idx[r["location_id"]], k, w] |= bool((r["done_qty"] or 0) > 0 and ((r["discarded"] or 0) < maxp[k] or (r["topups"] or 0) > 0))
        self.lots = np.zeros((L, W.N_ING, W.AGES))
        for r in c.execute("SELECT location_id, ingredient_id, received_on, qty_on_hand FROM inventory_lots WHERE status = 'open'"):
            a = min(day - day_of(r["received_on"]), W.AGES - 1)
            if a >= 0:
                self.lots[idx[r["location_id"]], ii[r["ingredient_id"]], a] += r["qty_on_hand"]
        row = c.execute("SELECT array_agg(cooler_c ORDER BY l.idx) AS t FROM conditions k JOIN locations l ON l.id = k.location_id WHERE k.business_date = %s", [hi]).fetchone()
        self.temp = np.array(row["t"] if row and row["t"] else [3.5] * L, float)
        self.pipeline = []
        for r in c.execute("""SELECT supplier, ingredient_id, location_id, coalesce(eta, due_on) AS eta, qty FROM supplier_orders
                               WHERE placed AND delivered_on IS NULL"""):
            q = np.zeros((L, W.N_ING))
            q[idx[r["location_id"]], ii[r["ingredient_id"]]] = r["qty"]
            self.pipeline.append({"supplier": r["supplier"], "due": day_of(r["eta"]), "qty": q, "delayed": 1})
        self.delays = [n["detail"] | {"due": day_of(datetime.date.fromisoformat(n["detail"]["due_on"]))}
                       for n in c.execute("SELECT detail FROM notices WHERE kind = 'supplier_delay'")]
        self._cond = {}
        for r in c.execute("""SELECT location_id, business_date, rain_forecast, event FROM conditions WHERE business_date BETWEEN %s AND %s""",
                           [date_of(day + 1), date_of(day + 7)]):
            d_ = day_of(r["business_date"])
            rain, ev = self._cond.setdefault(d_, (np.zeros((L, W.SLOTS)), np.zeros((L, W.SLOTS), bool)))
            if r["rain_forecast"] is not None:
                rain[idx[r["location_id"]]] = r["rain_forecast"]
            if r["event"]:
                ev[idx[r["location_id"]], list(W.EVENT_SLOTS)] = True
        self.promos = c.execute("SELECT item_id, discount, starts_on, ends_on, regions FROM promotions").fetchall()
        self.region_name = np.array(mt["region_name"])

    def discounts(self, day):
        out = np.zeros((self.L, W.N_ITEM))
        for p in self.promos:
            if p["starts_on"] <= date_of(day) < p["ends_on"]:
                out[np.isin(self.region_name, p["regions"]), W.ITEM.index(p["item_id"])] = p["discount"]
        return out

    def conditions(self, day):
        rain, ev = self._cond.get(day, (np.zeros((self.L, W.SLOTS)), np.zeros((self.L, W.SLOTS), bool)))
        return (rain if day - self.day <= 2 else np.zeros((self.L, W.SLOTS))), ev, self.discounts(day)


# --- writing what happened --------------------------------------------------------------------------------------------------
def write_days(c, t, mt, recs, plans=None):
    """Store the days the generator just played: sales, conditions, counts, lots, waste, prep logs, deliveries."""
    ids = mt["ids"]
    sales, cond, counts, waste, preps = [], [], [], [], []
    plans = plans or {}
    for r in recs:
        d, bd = r["day"], date_of(r["day"])
        sold = r["sold"]
        for l in range(mt["L"]):
            for i in range(W.N_ITEM):
                units = int(sold[l, i].sum())
                out = np.nonzero(r["unavailable"][l, i])[0]
                if units or len(out):
                    sales.append((t, ids[l], W.ITEM[i], bd, sold[l, i, 0].tolist(), sold[l, i, 1].tolist(), out.tolist(), units,
                                  round(float(r["revenue"][l, i]), 2), float(r["discount"][l, i])))
            cond.append((t, ids[l], bd, [round(float(x), 3) for x in r["rain"][l]], float(round(r["temp"][l], 2))))
        theo = r["sold"].sum((2, 3)) @ W.ITEM_THEORETICAL_RAW + r["prep_discard"].sum(2) @ W.RAW_PER_COMP
        prev = r.get("prev_count")
        for l, i in np.ndindex(mt["L"], W.N_ING):
            use = float(prev[l, i] + r["received"][l, i] - r["count"][l, i] - r["lot_waste"][l, i].sum()) if prev is not None else 0.0
            counts.append((t, ids[l], W.ING[i], bd, float(r["count"][l, i]), float(r["received"][l, i]), float(r["lot_waste"][l, i].sum()), use, float(theo[l, i])))
        for l, k, w in zip(*np.nonzero(r["prep_discard"] > 1e-6)):
            waste.append((t, ids[l], bd, "component", W.COMP[k], None, round(float(r["prep_discard"][l, k, w]), 3), "prep_discard",
                          round(float(r["prep_discard"][l, k, w] * W.COMP_COST[k]), 2)))
        for l, i, rd, status, q in r["closures"]:
            if status in ("spoiled", "expired") and q > 0:
                waste.append((t, ids[l], bd, "ingredient", W.ING[i], f"{ids[l]}:{W.ING[i]}:{date_of(rd)}", round(q, 3), status, round(q * W.COST[i], 2)))
        planned = plans.get(d)
        for l, k in np.ndindex(mt["L"], W.N_COMP):
            for w in (0, 1):
                made = r["prepped"][l, k, w]
                if W.WINDOW_COMP[k] or w == 0:
                    disc = r["prep_discard"][l, k, w] if W.WINDOW_COMP[k] else r["prep_discard"][l, k].sum()
                    made = made if W.WINDOW_COMP[k] else r["prepped"][l, k].sum()
                    tops = int(r["topups"][l, k, w] if W.WINDOW_COMP[k] else r["topups"][l, k].sum())
                    if made > 0 or r["prep_plan"][l, k, w] > 0:
                        preps.append((l, k, w, float(r["prep_plan"][l, k, w]), float(made), float(disc), tops))
        if planned:
            c.execute("UPDATE prep_tasks SET status = 'superseded' WHERE plan_id = %s AND status = 'planned' AND prep_window = 'dinner'", [planned])
        rows = []
        for l, k, w, qty, made, disc, tops in preps:
            win = "lunch" if w == 0 else "dinner"
            if planned and w == 0:
                c.execute("""UPDATE prep_tasks SET status = 'done', done_qty = %s, discarded = %s, topups = %s
                              WHERE plan_id = %s AND location_id = %s AND component_id = %s AND prep_window = 'lunch'""",
                          [round(made, 3), round(disc, 3), tops, planned, ids[l], W.COMP[k]])
            else:
                rows.append((t, ids[l], bd, win, W.COMP[k], round(qty, 3), datetime.time(10, 45) if w == 0 else datetime.time(16, 45),
                             round(qty * W.LABOR_MIN[k], 1), Jsonb({"planned_by": "kitchen par sheet" if not plans else "planner, 15:00 update" if w else "planner"}),
                             "done", round(made, 3), round(disc, 3), tops))
        preps = []
        if rows:
            db.load(c, "prep_tasks", ["tenant_id", "location_id", "business_date", "prep_window", "component_id", "qty", "ready_by", "labor_min",
                                      "evidence", "status", "done_qty", "discarded", "topups"], rows)
        # deliveries and lots
        c.execute("UPDATE supplier_orders SET delivered_on = %s WHERE placed AND delivered_on IS NULL AND coalesce(eta, due_on) = %s", [bd, bd])
        new = [(t, f"{ids[l]}:{W.ING[i]}:{bd}", ids[l], W.ING[i], bd, date_of(d + int(min(W.SHELF[i], 3650)) - 1), float(r["received"][l, i]), float(r["received"][l, i]), "open")
               for l, i in zip(*np.nonzero(r["received"] > 0))]
        if new:
            db.load(c, "inventory_lots", ["tenant_id", "id", "location_id", "ingredient_id", "received_on", "expires_on", "qty_received", "qty_on_hand", "status"], new)
        closed = [(f"{ids[l]}:{W.ING[i]}:{date_of(rd)}", status, bd) for l, i, rd, status, q in r["closures"]]
        if closed:
            c.execute("CREATE TEMP TABLE _closed (id text, status text, closed_on date) ON COMMIT DROP")
            db.copy(c, "_closed", ["id", "status", "closed_on"], closed)
            c.execute("UPDATE inventory_lots l SET status = x.status, closed_on = x.closed_on, qty_on_hand = 0 FROM _closed x WHERE l.id = x.id AND l.status = 'open'")
            c.execute("DROP TABLE _closed")
        if r["rain_forecast_next"] is not None:
            for k, fc in enumerate(r["rain_forecast_next"], 1):
                for l in range(mt["L"]):
                    cond.append((t, ids[l], date_of(d + k), None, None, [round(float(x), 3) for x in fc[l]]))
    # sales: upsert, adding to slots already there (tickets the ingest API took for the same day)
    c.execute("CREATE TEMP TABLE _sales (LIKE sales INCLUDING DEFAULTS) ON COMMIT DROP")
    db.copy(c, "_sales", ["tenant_id", "location_id", "item_id", "business_date", "dine_in", "delivery", "unavailable", "units", "revenue", "discount"], sales)
    c.execute("""INSERT INTO sales SELECT * FROM _sales ON CONFLICT (tenant_id, location_id, item_id, business_date) DO UPDATE SET
                   dine_in = add_slots(sales.dine_in, EXCLUDED.dine_in), delivery = add_slots(sales.delivery, EXCLUDED.delivery),
                   unavailable = EXCLUDED.unavailable, units = sales.units + EXCLUDED.units, revenue = sales.revenue + EXCLUDED.revenue""")
    c.execute("DROP TABLE _sales")
    obs_rows = [x for x in cond if len(x) == 5]
    fc_rows = [x for x in cond if len(x) == 6]
    c.execute("CREATE TEMP TABLE _cond (location_id text, business_date date, rain real[], cooler_c real, rain_forecast real[]) ON COMMIT DROP")
    db.copy(c, "_cond", ["location_id", "business_date", "rain", "cooler_c", "rain_forecast"],
            [(x[1], x[2], x[3], x[4], None) for x in obs_rows] + [(x[1], x[2], None, None, x[5]) for x in fc_rows])
    c.execute("""INSERT INTO conditions (tenant_id, location_id, business_date, rain, cooler_c, rain_forecast)
                 SELECT %s, location_id, business_date, max(rain), max(cooler_c), max(rain_forecast) FROM _cond GROUP BY location_id, business_date
                 ON CONFLICT (tenant_id, location_id, business_date) DO UPDATE SET rain = coalesce(EXCLUDED.rain, conditions.rain),
                   cooler_c = coalesce(EXCLUDED.cooler_c, conditions.cooler_c), rain_forecast = coalesce(EXCLUDED.rain_forecast, conditions.rain_forecast)""", [t])
    c.execute("DROP TABLE _cond")
    db.load(c, "inventory_counts", ["tenant_id", "location_id", "ingredient_id", "business_date", "counted", "received", "lot_waste", "actual_use", "theoretical_use"], counts)
    if waste:
        db.load(c, "waste_events", ["tenant_id", "location_id", "business_date", "kind", "ref_id", "lot_id", "qty", "reason", "cost"], waste)
    # the closing lot check on the last day: what is left on every open lot
    last = recs[-1]
    upd = []
    for l, i in zip(*np.nonzero(last["received"] >= 0)):
        for a in range(W.AGES):
            q = last["lots"][l, i, a]
            if q > 1e-9:
                upd.append((f"{ids[l]}:{W.ING[i]}:{date_of(last['day'] - a)}", round(float(q), 3)))
    c.execute("CREATE TEMP TABLE _oh (id text, q double precision) ON COMMIT DROP")
    db.copy(c, "_oh", ["id", "q"], upd)
    c.execute("UPDATE inventory_lots l SET qty_on_hand = coalesce(x.q, 0) FROM inventory_lots l2 LEFT JOIN _oh x ON x.id = l2.id WHERE l.id = l2.id AND l.status = 'open'")
    c.execute("DROP TABLE _oh")


def order_lines(c, t, mt, orders, ordered_on, source, rec_id=None, status_of=None, evidence_of=None, placed=False, delays=()):
    """Store order lines (one per store and ingredient with a quantity or a par)."""
    rows = []
    for o in orders:
        prem = W.SUPPLIERS[o["supplier"]][2]
        par = o.get("par", np.zeros_like(o["qty"]))
        for l, i in zip(*np.nonzero((o["qty"] > 0) | (par > 0))):
            late = W.expected_delay({"L": mt["L"], "region": mt["region"]}, o, delays)
            eta = o["due"] + (int(late[l]) if np.ndim(late) else int(late))
            st = status_of(o, l, i) if status_of else "auto_approved"
            rows.append((uuid.uuid4(), t, mt["ids"][l], o["supplier"], W.ING[i], date_of(ordered_on), date_of(o["due"]), date_of(eta) if eta != o["due"] else None,
                         float(o["qty"][l, i]), float(par[l, i]), round(float(W.COST[i] * prem), 3), st, source, rec_id,
                         Jsonb(evidence_of(o, l, i) if evidence_of else {}), placed))
    if rows:
        db.load(c, "supplier_orders", ["id", "tenant_id", "location_id", "supplier", "ingredient_id", "ordered_on", "due_on", "eta", "qty", "par_qty",
                                       "unit_cost", "status", "source", "recommendation_id", "evidence", "placed"], rows)
    return rows


# --- loading the chain --------------------------------------------------------------------------------------------------------
class LoadIn(BaseModel):
    seed: int = Field(7, ge=1, le=10 ** 6)


@app.post("/v1/chain:load", status_code=202, tags=["chain"], summary="(+) Load the synthetic chain: 50 stores and eight weeks of history run the way the chain always ran (par prep, par orders); train and register the demand forecast, the consumption model and the spoilage hazard, each scored against its baseline")
def load_chain(body: LoadIn, ctx: Ctx = Depends(auth("chain:load")), idem: str | None = IdemKey):
    def work(c):
        if c.execute("SELECT 1 FROM chains").fetchone():
            raise Problem(409, "chain_exists", "this tenant already has a chain; `make reset` for a fresh demo")
        return 202, jobs.enqueue(c, ctx, "chain.load", body.model_dump())
    return run(ctx, idem, body, work)


def fit_all(ch, recs, st):
    """Everything the service trains from its history; metrics on the last two weeks from a fit to the first six."""
    h_all = E.history_arrays(recs, ch)
    h_tr = E.history_arrays(recs[:VALIDATE_FROM], ch)
    val = E.DemandModel().fit(h_tr)
    test = recs[VALIDATE_FROM:]
    y = np.stack([r["sold"].sum(2) for r in test], 2).astype(float)                     # what the POS saw (the service has no truth)
    ok = np.stack([~r["unavailable"] for r in test], 2)
    mu_c = np.stack([val.mean(r["day"], r["rain"], W.event_mask(ch, r["day"]), r["discount"]) for r in test], 3)   # [L, I, C, D, S]
    lo, hi = E.slot_interval(val, mu_c)
    mu = mu_c.sum(2)
    R = list(W.LUNCH_RUSH)
    sel = ok[..., R]
    Y = np.stack([r["sold"] for r in recs], 3).astype(float)
    bins, q = E.seasonal_naive(Y[:, :, :, :VALIDATE_FROM], None)
    fc = Y.sum(2)[:, :, VALIDATE_FROM - 7:HISTORY_DAYS - 7]
    nlo, nhi = E.naive_interval(fc, bins, q)
    yr, mr, fr = y[..., R][sel], mu[..., R][sel], fc[..., R][sel]
    demand_metrics = {"lunch_slot_wape": round(float(np.abs(yr - mr).sum() / yr.sum()), 3), "baseline_lunch_slot_wape": round(float(np.abs(yr - fr).sum() / yr.sum()), 3),
                      "lunch_slot_pit_coverage_90": round(float(E.pit_coverage(val, mu_c, y)[..., R][sel].mean()), 3),
                      "lunch_slot_interval_coverage_90": round(float(((yr >= lo[..., R][sel]) & (yr <= hi[..., R][sel])).mean()), 3),
                      "baseline_lunch_slot_interval_coverage_90": round(float(((yr >= nlo[..., R][sel]) & (yr <= nhi[..., R][sel])).mean()), 3),
                      "scored_on": "sales in the lunch rush of the last two weeks, slots not 86'd; the evaluation scores against true demand"}
    lw = E.window_interval(val, mu_c[..., R])
    yl = y[..., R].sum(-1)
    okl = sel.all(-1)
    demand_metrics["item_lunch_coverage_90"] = round(float(((yl >= lw[0]) & (yl <= lw[1]))[okl].mean()), 3)
    model = E.DemandModel().fit(h_all)
    theo = np.stack([r["sold"].sum((2, 3)) @ W.ITEM_THEORETICAL_RAW + r["prep_discard"].sum(2) @ W.RAW_PER_COMP for r in recs])
    act = np.stack([st["use"][r["day"]] for r in recs])
    raw_ratio, chain_ratio = E.usage_ratios(theo[:VALIDATE_FROM], act[:VALIDATE_FROM])
    t_te, a_te = theo[VALIDATE_FROM:].sum(0), act[VALIDATE_FROM:].sum(0)
    cons_metrics = {"usage_wape": round(float(np.abs(a_te - t_te * raw_ratio).sum() / a_te.sum()), 4), "baseline_recipes_only_wape": round(float(np.abs(a_te - t_te).sum() / a_te.sum()), 4),
                    "chain_ratio": {W.ING[i]: round(float(v), 3) for i, v in enumerate(chain_ratio)}}
    raw_ratio, chain_ratio = E.usage_ratios(theo, act)
    lots = lot_list(recs)
    temps = np.stack([r["temp"] for r in recs], 1)
    rows, rdays = E.lot_days(lots, temps, HISTORY_DAYS, with_day=True)
    tr = rdays < VALIDATE_FROM
    hz_val = E.HazardModel().fit(rows[tr, 1].astype(int), rows[tr, 2], rows[tr, 3], rows[tr, 4])
    hz_metrics = E.evaluate_hazard(hz_val, rows[~tr])
    hz = E.HazardModel().fit(rows[:, 1].astype(int), rows[:, 2], rows[:, 3], rows[:, 4])
    return {"demand": model, "demand_metrics": {**demand_metrics, **model.summary()}, "consumption": {"raw": raw_ratio, "chain": chain_ratio},
            "consumption_metrics": cons_metrics, "hazard": hz, "hazard_metrics": hz_metrics, "theo": theo, "act": act}


def lot_list(recs):
    closed = {}
    for r in recs:
        for l, i, rd, status, q in r["closures"]:
            closed[(l, i, rd)] = (r["day"], status)
    return [(l, i, r["day"], *closed.get((l, i, r["day"]), (None, "open"))) for r in recs for l, i in zip(*np.nonzero(r["received"] > 0))]


@jobs.handler("chain.load")
def load_job(c, job):
    t, seed = job["tenant_id"], job["payload"]["seed"]
    t0 = time.perf_counter()
    ch = W.chain(seed)
    st, recs = W.run(ch, W.initial_state(ch), 0, HISTORY_DAYS, W.UsualPractice(), last_orders=False)
    prev = W.initial_state(ch)["count"]
    for r in recs:                                                                       # yesterday's count, for the usage column
        r["prev_count"], prev = prev, r["count"]
    fitted = fit_all(ch, recs, st)
    fid = uuid.uuid5(t, "chain")
    version = f"resto-{str(fid)[:8]}-1"
    c.execute("""INSERT INTO chains (id, tenant_id, name, model_seed, start_date, next_day, told, sim_state, model_version)
                 VALUES (%s,%s,%s,%s,%s,%s,'[]',%s,%s)""", [fid, t, CHAIN_NAME, seed, START, HISTORY_DAYS, pickle.dumps(st), version])
    ids = W.store_ids(ch["L"])
    db.load(c, "locations", ["tenant_id", "id", "idx", "name", "region", "format", "metadata"],
            [(t, ids[l], l, ch["names"][l], W.REGIONS[ch["region"][l]], W.FORMATS[ch["format"][l]], Jsonb({"xy": [round(float(v), 3) for v in ch["xy"][l]]})) for l in range(ch["L"])])
    db.load(c, "menu_items", ["tenant_id", "id", "status", "price", "attributes"],
            [(t, n, "active", W.PRICE[i], Jsonb({"recipe_food_cost": round(float(W.ITEM_FOOD_COST[i]), 2)})) for i, n in enumerate(W.ITEM)])
    db.load(c, "ingredients", ["tenant_id", "id", "unit", "unit_cost", "shelf_life_days", "supplier", "case_size", "storage"],
            [(t, n, *W.INGREDIENTS[n][:2], W.INGREDIENTS[n][2], W.INGREDIENTS[n][3], W.INGREDIENTS[n][4], W.INGREDIENTS[n][5]) for n in W.ING])
    db.load(c, "components", ["tenant_id", "id", "unit", "hold", "labor_min_per_unit"], [(t, n, v[0], v[1], v[3]) for n, v in W.COMPONENTS.items()])
    rec_rows = [(t, "item", n, "component" if k in W.COMPONENTS else "ingredient", k, q) for n, v in W.ITEMS.items() for k, q in v[3].items()]
    rec_rows += [(t, "component", n, "ingredient", k, q) for n, v in W.COMPONENTS.items() for k, q in v[2].items()]
    db.load(c, "recipes", ["tenant_id", "parent_kind", "parent_id", "input_kind", "input_id", "qty"], rec_rows)
    db.load(c, "promotions", ["tenant_id", "id", "item_id", "discount", "starts_on", "ends_on", "regions"],
            [(t, p["id"], p["item"], p["discount"], date_of(p["start"]), date_of(p["end"]), p["regions"]) for p in ch["promos"]])
    ev = [(t, ids[l], date_of(d), "local event 17:00-21:00") for l, d in zip(*np.nonzero(ch["events"]))]
    db.load(c, "conditions", ["tenant_id", "location_id", "business_date", "event"], ev)
    write_days(c, t, meta(c), recs)
    pend = [p for p in st["pipeline"] if p["due"] >= HISTORY_DAYS]
    mt = meta(c)
    for p in pend:
        order_lines(c, t, mt, [{"supplier": p["supplier"], "due": p["due"], "qty": p["qty"]}], p["ordered_on"], "history",
                    status_of=lambda *_: "placed", placed=True)
    snapshot = f"days 0-{HISTORY_DAYS - 1} (scored on {VALIDATE_FROM}-{HISTORY_DAYS - 1} from a fit to 0-{VALIDATE_FROM - 1}), seed {seed}"
    for name, obj, metrics in (("demand-forecast", fitted["demand"], fitted["demand_metrics"]),
                               ("consumption", fitted["consumption"], fitted["consumption_metrics"]),
                               ("spoilage-hazard", fitted["hazard"], fitted["hazard_metrics"])):
        c.execute("INSERT INTO model_artifacts (tenant_id, name, version, data_snapshot, metrics, artifact, approved) VALUES (%s,%s,%s,%s,%s,%s,true)",
                  [t, name, version, snapshot, Jsonb(jsonable_encoder(metrics)), pickle.dumps(obj)])
    scan, base = E.shrinkage_scan(fitted["theo"], fitted["act"])
    for l in np.nonzero(scan["flags"].any(1))[0]:
        c.execute("INSERT INTO alerts (id, tenant_id, kind, location_id, detail, raised_on) VALUES (%s,%s,'shrinkage',%s,%s,%s)",
                  [uuid.uuid4(), t, ids[l], Jsonb(shrink_detail(scan, l)), date_of(HISTORY_DAYS - 1)])
    m = metrics_summary(recs)
    audit.record(c, worker_ctx(job), "chain.loaded", "chain", fid, {"days": HISTORY_DAYS, "stores": ch["L"], "model_version": version})
    return {"chain_id": fid, "name": CHAIN_NAME, "stores": ch["L"], "regions": len(W.REGIONS), "menu_items": W.N_ITEM, "ingredients": W.N_ING, "components": W.N_COMP,
            "days": HISTORY_DAYS, "from": date_of(0), "to": date_of(HISTORY_DAYS - 1), "sales_rows": c.execute("SELECT count(*) AS n FROM sales").fetchone()["n"],
            "units_sold": int(sum(r["sold"].sum() for r in recs)), "slot_counts": int(ch["L"] * W.N_ITEM * 2 * W.SLOTS * HISTORY_DAYS),
            "lots": len(lot_list(recs)), "history": m, "shrinkage_flags": int(scan["flags"].any(1).sum()), "threshold_flags": int(base.any(1).sum()),
            "models": {"version": version, "demand": fitted["demand_metrics"], "consumption": fitted["consumption_metrics"], "hazard": fitted["hazard_metrics"]},
            "seconds": round(time.perf_counter() - t0, 1)}


def metrics_summary(recs):
    """What the service can see about some days: sales, waste it logged, purchases, item-slots 86'd."""
    sold = sum(r["sold"].sum() for r in recs)
    waste = sum((r["prep_discard"].sum(2) @ W.COMP_COST).sum() + (r["lot_waste"].sum(2) @ W.COST).sum() for r in recs)
    purchases = sum(float((q * W.COST).sum()) * W.SUPPLIERS[s][2] for r in recs for s, q in r["received_by"].items())
    return {"units_sold": int(sold), "revenue_usd": round(float(sum(r["revenue"].sum() for r in recs)), 2), "waste_usd": round(float(waste), 2),
            "purchases_usd": round(float(purchases), 2), "waste_pct_of_purchases": round(float(waste / max(purchases, 1)), 4),
            "item_slots_86d": int(sum(r["unavailable"].sum() for r in recs)), "store_days": len(recs) * recs[0]["sold"].shape[0]}


def shrink_detail(scan, l):
    f = np.nonzero(scan["flags"][l])[0]
    return {"class": E.classify_shrinkage(scan, l), "ingredients": [{"ingredient": W.ING[i], "variance_pct": round(100 * float(scan["variance"][l, i]), 1),
                                                                      "chain_norm_pct": round(100 * float(scan["chain_norm"][i]), 1), "z": round(float(scan["z"][l, i]), 1),
                                                                      "follows_sales": round(float(scan["corr"][l, i]), 2)} for i in f]}


# --- the clock moves -----------------------------------------------------------------------------------------------------------
class Inject(BaseModel):
    kind: Literal["supplier_delay", "rainstorm"]
    regions: list[Literal["Harbor", "Uptown", "Riverside", "Midtown", "Lakeside"]] = Field(min_length=1, max_length=5)
    supplier: Literal["produce", "protein", "broadline"] | None = None
    days: int = Field(1, ge=1, le=3, description="supplier_delay: how late the truck is")
    from_hour: float = Field(11, ge=10, le=21)
    to_hour: float = Field(15, ge=10.25, le=22)
    intensity: float = Field(0.9, gt=0, le=1)


class AdvanceIn(BaseModel):
    days: int = Field(ge=0, le=7, description="0: only tell the generator (the notices arrive tonight)")
    inject: list[Inject] = Field(default_factory=list, max_length=4)


@app.post("/v1/chain:advance", status_code=202, tags=["chain"], summary="(+) Run business days. The generator can be told about tomorrow first (a supplier's late truck, a rainstorm); the service then receives what a real chain would (the supplier's delay notice, the weather service's forecast), never the telling. Days run on the plans in force: tonight's approved orders, the active prep plan, and the planner unattended inside its limits")
def advance(body: AdvanceIn, ctx: Ctx = Depends(auth("chain:advance")), idem: str | None = IdemKey):
    def work(c):
        f = chain(c)
        for inj in body.inject:
            if inj.kind == "supplier_delay" and not inj.supplier:
                raise Problem(422, "supplier_required", "a supplier delay names the supplier")
            if inj.kind == "rainstorm" and inj.to_hour <= inj.from_hour:
                raise Problem(422, "bad_window", "the storm must end after it starts")
            if inj.kind == "supplier_delay" and (f["next_day"]) % 7 not in W.SUPPLIERS[inj.supplier][1]:
                raise Problem(422, "no_delivery_tomorrow", f"{inj.supplier} does not deliver on {date_of(f['next_day']).strftime('%A')}")
        if f["next_day"] + body.days > 80:
            raise Problem(422, "beyond_calendar", "the demo chain's calendar ends at day 80")
        return 202, jobs.enqueue(c, ctx, "chain.advance", body.model_dump())
    return run(ctx, idem, body, work)


def tonight_orders(c, f, mt, m, ctx_id):
    """The orders placed at tonight's close: the planner's recommendation as approved (lines still awaiting approval or
    rejected go at the usual par), or, with no recommendation, the planner unattended inside its limit."""
    d = f["next_day"] - 1
    lines = c.execute("""SELECT id, supplier, ingredient_id, location_id, due_on, qty, par_qty, status FROM supplier_orders
                          WHERE ordered_on = %s AND NOT placed AND status <> 'superseded'""", [date_of(d)]).fetchall()
    if not lines:
        obs = DbObs(c, f, mt, d)
        orders = E.Bounded(system_policy(m), W.UsualPractice()).order(obs.ch, d, obs)
        order_lines(c, f["tenant_id"], mt, orders, d, "auto", status_of=lambda o, l, i: "auto_approved" if o["auto"][l, i] else "fallback_par", delays=obs.delays)
        lines = c.execute("""SELECT id, supplier, ingredient_id, location_id, due_on, qty, par_qty, status FROM supplier_orders
                              WHERE ordered_on = %s AND NOT placed AND status <> 'superseded'""", [date_of(d)]).fetchall()
    pend = {}
    for r in lines:
        q = r["qty"] if r["status"] in ("auto_approved", "approved") else (r["par_qty"] or 0.0)
        if r["status"] == "proposed":
            c.execute("UPDATE supplier_orders SET status = 'fallback_par' WHERE id = %s", [r["id"]])
        key = (r["supplier"], day_of(r["due_on"]))
        pend.setdefault(key, np.zeros((mt["L"], W.N_ING)))[mt["idx"][r["location_id"]], W.ING.index(r["ingredient_id"])] += q
    c.execute("UPDATE supplier_orders SET placed = true WHERE ordered_on = %s AND status <> 'superseded'", [date_of(d)])
    c.execute("UPDATE supplier_orders SET qty = par_qty WHERE ordered_on = %s AND status IN ('fallback_par', 'rejected')", [date_of(d)])
    return [{"id": f"{d}-{s}-{due}", "supplier": s, "due": due, "ordered_on": d, "qty": q} for (s, due), q in sorted(pend.items())]


@jobs.handler("chain.advance")
def advance_job(c, job):
    p = job["payload"]
    f = chain(c)
    t, d0 = f["tenant_id"], f["next_day"]
    mt = meta(c)
    told = list(f["told"])
    new = []
    for inj in p["inject"]:
        if inj["kind"] == "rainstorm":
            e = {"kind": "rainstorm", "day": d0, "from_hour": inj["from_hour"], "to_hour": inj["to_hour"], "intensity": inj["intensity"], "regions": inj["regions"]}
        else:
            e = {"kind": "supplier_delay", "supplier": inj["supplier"], "due": d0, "days": inj["days"], "regions": inj["regions"]}
        told.append(e)
        new.append(e)
    ch = W.apply_told(W.chain(f["model_seed"]), told)
    for e in new:                                       # what reaches the service: the notices, not the telling
        if e["kind"] == "rainstorm":
            fc = W.rain_forecast(ch, d0)
            for l in np.nonzero(np.isin(np.array(mt["region_name"]), e["regions"]))[0]:
                c.execute("UPDATE conditions SET rain_forecast = %s WHERE location_id = %s AND business_date = %s", [[round(float(x), 3) for x in fc[l]], mt["ids"][l], date_of(d0)])
            c.execute("INSERT INTO notices (id, tenant_id, kind, received_on, detail) VALUES (%s,%s,'weather_forecast',%s,%s)",
                      [uuid.uuid4(), t, date_of(d0 - 1), Jsonb({"for": str(date_of(d0)), "regions": e["regions"], "from": slot_time(int((e["from_hour"] - 10) * 4)),
                                                               "to": slot_time(int((e["to_hour"] - 10) * 4)), "intensity": round(e["intensity"], 2),
                                                               "text": f"Heavy rain {e['from_hour']:g}:00-{e['to_hour']:g}:00 in {', '.join(e['regions'])}"})])
        else:
            c.execute("INSERT INTO notices (id, tenant_id, kind, received_on, detail) VALUES (%s,%s,'supplier_delay',%s,%s)",
                      [uuid.uuid4(), t, date_of(d0 - 1), Jsonb({"supplier": e["supplier"], "due_on": str(date_of(d0)), "days": e["days"], "regions": e["regions"],
                                                               "arrives": str(date_of(d0 + e["days"])),
                                                               "text": f"{e['supplier'].title()} deliveries due {date_of(d0):%a %d %b} to {', '.join(e['regions'])} arrive {date_of(d0 + e['days']):%a %d %b}"})])
            stores = [mt["ids"][l] for l in np.nonzero(np.isin(np.array(mt["region_name"]), e["regions"]))[0]]
            c.execute("UPDATE supplier_orders SET eta = %s WHERE supplier = %s AND due_on = %s AND location_id = ANY(%s)", [date_of(d0 + e["days"]), e["supplier"], date_of(d0), stores])
    c.execute("UPDATE chains SET told = %s", [Jsonb(told)])
    truth = {"told": new, "note": "what the generator was told; the analysis never reads this"}
    if not p["days"]:
        audit.record(c, worker_ctx(job), "chain.told", "chain", f["id"], {"events": [e["kind"] for e in new]})
        notices = c.execute("SELECT kind, received_on, detail FROM notices ORDER BY created_at DESC LIMIT %s", [len(new)]).fetchall()
        return {"days": 0, "notices": notices, "simulation_truth": truth}
    m = models(f)
    raw = c.execute("SELECT sim_state FROM chains").fetchone()["sim_state"]
    st = pickle.loads(raw)
    pending = tonight_orders(c, f, mt, m, job["payload"]["actor_id"])
    plans = {day_of(r["business_date"]): r["id"] for r in c.execute("SELECT id, business_date FROM prep_plans WHERE status = 'active' AND business_date >= %s", [date_of(d0)])}
    preps = plan_arrays(c, mt, plans)
    policy = E.WithPlans(E.Bounded(system_policy(m), W.UsualPractice()), preps)
    st2, recs = W.run(ch, st, d0, d0 + p["days"], policy, told, pending, last_orders=False)   # tonight's orders are the planner's
    prev = st["count"]
    for r in recs:
        r["prev_count"], prev = prev, r["count"]
    write_days(c, t, mt, recs, plans)
    for r in recs:
        if r["orders"]:
            order_lines(c, t, mt, r["orders"], r["day"], "auto", status_of=lambda o, l, i: "auto_approved" if o["auto"][l, i] else "fallback_par",
                        placed=True, delays=W.delays_known(ch, told, r["day"]))
    tm = W.metrics(recs)
    snap = {"from_day": d0, "days": p["days"], "pending": [{**x, "qty": x["qty"].tolist()} for x in pending], "plans": {str(k): str(v) for k, v in plans.items()}, "told": told,
            "actual": {"waste_usd": tm["waste_usd"], "lost_units": tm["lost_units"], "units_sold": int(sum(r["sold"].sum() for r in recs))}}
    c.execute("UPDATE chains SET next_day = %s, sim_state = %s, snapshot = %s, snapshot_state = %s",
              [d0 + p["days"], pickle.dumps(st2), Jsonb(snap), raw])
    for r in recs:
        log_run(c, t, E.PLANNER_VERSION, f["model_version"], f"chain:{date_of(r['day'])}", E.feature_hash(r["prep_plan"]),
                {"prep_plan_kg": round(float(r["prep_plan"].sum()), 1), "orders": len(r["orders"])})
    days = []
    for r in recs:
        ms = metrics_summary([r])
        backup = r["received_by"].get("backup")
        days.append({"date": date_of(r["day"]), **ms, "backup_deliveries_usd": round(float((backup * W.COST).sum() * W.SUPPLIERS["backup"][2]), 2) if backup is not None else 0.0,
                     "lunch_units": int(r["sold"][:, :, :, list(W.LUNCH_RUSH)].sum())})
    truth.update({"told": told[-len(new):] if new else [], "demand_units": tm["demand_units"], "lost_units": tm["lost_units"], "stockout_rate": tm["stockout_rate"]})
    audit.record(c, worker_ctx(job), "chain.advanced", "chain", f["id"], {"days": p["days"], "from": str(date_of(d0)), "orders_placed_tonight": len(pending)})
    return {"from": date_of(d0), "days": days, "orders_placed_at_start": [{"supplier": x["supplier"], "due": date_of(x["due"]), "value_usd": round(float((x["qty"] * W.COST * W.SUPPLIERS[x["supplier"]][2]).sum()), 2)} for x in pending],
            "plans_followed": {str(date_of(k)): v for k, v in plans.items()}, "clock": date_of(d0 + p["days"]), "simulation_truth": truth}


def plan_arrays(c, mt, plans):
    out = {}
    for day, pid in plans.items():
        a = np.zeros((mt["L"], W.N_COMP))
        for r in c.execute("SELECT location_id, component_id, qty FROM prep_tasks WHERE plan_id = %s AND prep_window = 'lunch'", [pid]):
            a[mt["idx"][r["location_id"]], W.COMP.index(r["component_id"])] = r["qty"]
        out[(day, 0)] = a
    return out


# --- POS ingest ----------------------------------------------------------------------------------------------------------------
class Line(BaseModel):
    item: str = Field(min_length=1, max_length=40)
    qty: int = Field(ge=1, le=50)


class Ticket(BaseModel):
    ticket_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    location: str = Field(min_length=2, max_length=10)
    at: datetime.datetime
    channel: Literal["dine_in", "delivery"]
    lines: list[Line] = Field(min_length=1, max_length=40)


class IngestIn(BaseModel):
    tickets: list[Ticket] = Field(min_length=1, max_length=500)


@app.post("/v1/sales/ingest", status_code=201, tags=["sales"], summary="POS tickets for the business day in progress, validated one by one (known store and items, inside opening hours on today's date, a ticket id not seen before) and added to the 15-minute slots")
def ingest(body: IngestIn, ctx: Ctx = Depends(auth("sales:ingest")), idem: str | None = IdemKey):
    def work(c):
        f = chain(c)
        today = date_of(f["next_day"])
        known = {r["id"] for r in c.execute("SELECT id FROM locations")}
        prices = {r["id"]: float(r["price"]) for r in c.execute("SELECT id, price FROM menu_items WHERE status = 'active'")}
        accepted, refused, add = [], [], {}
        seen = set()
        for tk in body.tickets:
            local = tk.at.replace(tzinfo=None) if tk.at.tzinfo is None else tk.at.astimezone(datetime.UTC).replace(tzinfo=None)
            slot = int((local.hour + local.minute / 60 - W.OPEN_HOUR) * 4)
            why = None
            if tk.location not in known:
                why = f"unknown location {tk.location}"
            elif local.date() != today:
                why = f"business day is {today}; ticket is for {local.date()}"
            elif not 0 <= slot < W.SLOTS:
                why = "outside opening hours (10:00-22:00)"
            elif (tk.location, tk.ticket_id) in seen or c.execute("SELECT 1 FROM pos_tickets WHERE location_id = %s AND ticket_id = %s", [tk.location, tk.ticket_id]).fetchone():
                why = "duplicate ticket"
            else:
                bad = [ln.item for ln in tk.lines if ln.item not in prices]
                if bad:
                    why = f"unknown item {bad[0]}"
            if why:
                refused.append({"ticket_id": tk.ticket_id, "why": why})
                continue
            seen.add((tk.location, tk.ticket_id))
            for ln in tk.lines:
                a = add.setdefault((tk.location, ln.item), [[0] * W.SLOTS, [0] * W.SLOTS, 0.0])
                a[0 if tk.channel == "dine_in" else 1][slot] += ln.qty
                a[2] += ln.qty * prices[ln.item]
            c.execute("INSERT INTO pos_tickets (tenant_id, location_id, ticket_id, business_date) VALUES (%s,%s,%s,%s)", [ctx.tenant_id, tk.location, tk.ticket_id, today])
            accepted.append({"ticket_id": tk.ticket_id, "location": tk.location, "slot": slot_time(slot), "units": sum(ln.qty for ln in tk.lines)})
        for (loc, item), (di, de, rev) in add.items():
            c.execute("""INSERT INTO sales (tenant_id, location_id, item_id, business_date, dine_in, delivery, units, revenue) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                         ON CONFLICT (tenant_id, location_id, item_id, business_date) DO UPDATE SET dine_in = add_slots(sales.dine_in, EXCLUDED.dine_in),
                           delivery = add_slots(sales.delivery, EXCLUDED.delivery), units = sales.units + EXCLUDED.units, revenue = sales.revenue + EXCLUDED.revenue""",
                      [ctx.tenant_id, loc, item, today, di, de, sum(di) + sum(de), round(rev, 2)])
        audit.record(c, ctx, "sales.ingested", "sales", str(today), {"accepted": len(accepted), "refused": refused})
        return 201, {"business_date": today, "accepted": accepted, "refused": refused}
    return run(ctx, idem, body, work)


# --- forecast ---------------------------------------------------------------------------------------------------------------------
class RefreshIn(BaseModel):
    days: int = Field(2, ge=1, le=7, description="business days ahead, from tomorrow")


@app.post("/v1/forecast:refresh", status_code=202, tags=["forecast"], summary="(+) Refresh the 15-minute forecast for every store, item and slot for the next days, with 90% intervals, from the registered model and the conditions as now known (weather forecast, events, promotions). The duration is recorded against the blueprint's 2-minute refresh target")
def refresh(body: RefreshIn, ctx: Ctx = Depends(auth("forecast:refresh")), idem: str | None = IdemKey):
    def work(c):
        chain(c)
        return 202, jobs.enqueue(c, ctx, "forecast.refresh", body.model_dump())
    return run(ctx, idem, body, work)


@jobs.handler("forecast.refresh")
def refresh_job(c, job):
    t0 = time.perf_counter()
    f = chain(c)
    t, mt, m = f["tenant_id"], meta(c), models(f)
    dm = m["demand-forecast"]
    d = f["next_day"] - 1
    obs = DbObs(c, f, mt, d, lookback=0)
    rid = uuid.uuid4()
    rows, seen, logs = [], {}, []
    dates = list(range(d + 1, d + 1 + job["payload"]["days"]))
    c.execute("""INSERT INTO forecast_runs (id, tenant_id, dates, model_version, inputs_hash, weather_seen, duration_ms, created_by) VALUES (%s,%s,%s,%s,'',%s,0,%s)""",
              [rid, t, [date_of(x) for x in dates], f["model_version"], Jsonb({}), uuid.UUID(job["payload"]["actor_id"])])
    for day in dates:
        rain, ev, disc = obs.conditions(day)
        mu_c = dm.mean(day, rain, ev, disc)                                              # [L, I, C, S]
        lo, hi = E.slot_interval(dm, mu_c)
        mu = mu_c.sum(2)
        seen[str(date_of(day))] = {"rain_stores": int((rain.max(1) > 0).sum()), "max_rain": round(float(rain.max()), 2), "event_stores": int(ev.any(1).sum()),
                                   "promotions": int((disc > 0).any(0).sum())}
        for l in range(mt["L"]):
            for i in range(W.N_ITEM):
                rows.append((t, rid, mt["ids"][l], W.ITEM[i], date_of(day), np.round(mu[l, i], 3).tolist(), lo[l, i].tolist(), hi[l, i].tolist(), np.round(mu_c[l, i, 1], 3).tolist()))
            logs.append((t, E.FORECAST_VERSION, f["model_version"], f"{mt['ids'][l]}:{date_of(day)}", E.feature_hash(rain[l], ev[l], disc[l]),
                         Jsonb({"units": round(float(mu[l].sum()), 1), "lunch_units": round(float(mu[l][:, list(W.LUNCH_RUSH)].sum()), 1)})))
    db.load(c, "forecasts", ["tenant_id", "run_id", "location_id", "item_id", "business_date", "mean", "lo", "hi", "delivery_mean"], rows)
    db.load(c, "model_runs", ["tenant_id", "model_name", "version", "subject", "inputs_hash", "result"], logs)
    ms = round((time.perf_counter() - t0) * 1000, 1)
    c.execute("UPDATE forecast_runs SET inputs_hash = %s, weather_seen = %s, duration_ms = %s WHERE id = %s", [E.config_hash(seen), Jsonb(seen), ms, rid])
    audit.record(c, worker_ctx(job), "forecast.refreshed", "forecast_run", rid, {"dates": [str(date_of(x)) for x in dates], "ms": ms})
    return {"run_id": rid, "dates": [date_of(x) for x in dates], "stores": mt["L"], "series": len(rows), "slots": len(rows) * W.SLOTS, "duration_ms": ms,
            "target_ms": 120000, "conditions_seen": seen, "model_version": f["model_version"]}


def forecast_arrays(c, mt, run_id, day):
    L = mt["L"]
    mu, lo, hi, dl = (np.zeros((L, W.N_ITEM, W.SLOTS)) for _ in range(4))
    for r in c.execute("SELECT location_id, item_id, mean, lo, hi, delivery_mean FROM forecasts WHERE run_id = %s AND business_date = %s", [run_id, date_of(day)]):
        k = (mt["idx"][r["location_id"]], W.ITEM.index(r["item_id"]))
        mu[k], lo[k], hi[k], dl[k] = r["mean"], r["lo"], r["hi"], r["delivery_mean"]
    return mu, lo, hi, dl


@app.get("/v1/forecast", tags=["forecast"], summary="The latest forecast for a day: the chain's 15-minute curve with its 90% interval, every store's lunch rush (11:00-14:00) with its interval and the rain it expects, and for one store every item by slot. Intervals at every level come from the same model, so the levels add up")
def get_forecast(date: datetime.date | None = None, location: str | None = None, ctx: Ctx = Depends(auth("chain:read"))):
    with db.tx(ctx.tenant_id) as c:
        f = chain(c)
        mt, dm = meta(c), models(f)["demand-forecast"]
        day = day_of(date) if date else f["next_day"]
        run_ = c.execute("SELECT * FROM forecast_runs WHERE %s = ANY(dates) ORDER BY created_at DESC LIMIT 1", [date_of(day)]).fetchone()
        if not run_:
            raise Problem(404, "no_forecast", "refresh the forecast first: POST /v1/forecast:refresh")
        if location and location not in mt["idx"]:
            raise Problem(404, "location_not_found")
        mu, lo, hi, dl = forecast_arrays(c, mt, run_["id"], day)
        rain = {r["location_id"]: r["rain_forecast"] for r in c.execute("SELECT location_id, rain_forecast FROM conditions WHERE business_date = %s", [date_of(day)])}
        last = {}
        for r in c.execute("SELECT location_id, dine_in, delivery FROM sales WHERE business_date = %s", [date_of(day - 7)]):
            last[r["location_id"]] = last.get(r["location_id"], 0) + int(sum((np.asarray(r["dine_in"]) + np.asarray(r["delivery"]))[list(W.LUNCH_RUSH)]))
    R = list(W.LUNCH_RUSH)
    mu2 = (mu - dl) ** 2 + dl ** 2                                                       # sum over channels of mu_c^2
    store_slot = mu.sum(1)
    var_slot = dm.agg_var(store_slot, mu2.sum(1))
    chain_m, chain_v = store_slot.sum(0), var_slot.sum(0)
    clo, chi = E.DemandModel.nb_quantiles(chain_m, chain_v)
    lunch_m = mu[:, :, R].sum((1, 2))
    lunch_v = dm.agg_var(lunch_m, mu2[:, :, R].sum((1, 2)))
    llo, lhi = E.DemandModel.nb_quantiles(lunch_m, lunch_v)
    cl_lo, cl_hi = E.DemandModel.nb_quantiles(lunch_m.sum(), lunch_v.sum())
    stores = [{"id": mt["ids"][l], "name": mt["names"][l], "region": mt["region_name"][l], "format": W.FORMATS[mt["format"][l]], "xy": mt["xy"][l],
               "lunch_mean": round(float(lunch_m[l]), 1), "lunch_lo": int(llo[l]), "lunch_hi": int(lhi[l]), "lunch_last_week": last.get(mt["ids"][l]),
               "delivery_share_lunch": round(float(dl[l][:, R].sum() / max(lunch_m[l], 1e-9)), 3), "day_mean": round(float(mu[l].sum()), 1),
               "rain_lunch": round(float(np.max(np.asarray(rain.get(mt["ids"][l]) or [0])[R])) if rain.get(mt["ids"][l]) else 0.0, 2)} for l in range(mt["L"])]
    out = {"date": date_of(day), "run_id": run_["id"], "refreshed_at": run_["created_at"], "refresh_ms": run_["duration_ms"], "model_version": run_["model_version"],
           "chain": {"lunch_mean": round(float(lunch_m.sum()), 1), "lunch_lo": int(cl_lo), "lunch_hi": int(cl_hi), "day_mean": round(float(mu.sum()), 1),
                     "lunch_last_week": int(sum(v for v in last.values())),
                     "slots": [{"slot": s, "time": slot_time(s), "mean": round(float(chain_m[s]), 1), "lo": int(clo[s]), "hi": int(chi[s]),
                                "delivery": round(float(dl[:, :, s].sum()), 1)} for s in range(W.SLOTS)]},
           "stores": stores, "interval": "90%", "levels": "chain = sum of stores = sum of items = sum of 15-minute slots"}
    if location:
        l = mt["idx"][location]
        im = mu[l][:, R].sum(1)
        iv = dm.agg_var(im, mu2[l][:, R].sum(1))
        ilo, ihi = E.DemandModel.nb_quantiles(im, iv)
        out["location"] = {"id": location, "name": mt["names"][l], "items": [{"item": W.ITEM[i], "lunch_mean": round(float(im[i]), 1), "lunch_lo": int(ilo[i]), "lunch_hi": int(ihi[i]),
                                                                            "delivery_share": round(float(dl[l, i, R].sum() / max(im[i], 1e-9)), 3),
                                                                            "slots": [[round(float(mu[l, i, s]), 2), int(lo[l, i, s]), int(hi[l, i, s])] for s in range(W.SLOTS)]}
                                                                           for i in np.argsort(-im)],
                           "rain_forecast": rain.get(location)}
    return jsonable_encoder(out)


# --- prep plan --------------------------------------------------------------------------------------------------------------------
class PrepIn(BaseModel):
    date: datetime.date | None = Field(None, description="the business day to plan; default tomorrow")


UNITS_PER_COOK = 24                                    # items a line cook turns out in 15 minutes


@app.post("/v1/prep/plan", status_code=201, tags=["prep"], summary="Prep plans for every store for a business day: each component to the 90th percentile of its window's demand (lunch window and day components made by 10:45, dinner by 16:45 and updated at 15:00 from the lunch actually sold), with the usual par beside it, the labor minutes and the cooks each lunch-rush slot needs. Supersedes the day's previous plan")
def prep_plan(body: PrepIn, ctx: Ctx = Depends(auth("prep:plan")), idem: str | None = IdemKey):
    def work(c):
        f = chain(c)
        mt, m = meta(c), models(f)
        day = day_of(body.date) if body.date else f["next_day"]
        if day != f["next_day"]:
            raise Problem(422, "not_tomorrow", f"plans are made for the next business day, {date_of(f['next_day'])}")
        obs = DbObs(c, f, mt, day - 1)
        pol, usual = system_policy(m), W.UsualPractice()
        lunch, dinner = pol.prep(None, day, 0, obs), pol.prep(None, day, 1, obs)
        par0, par1 = usual.prep(None, day, 0, obs), usual.prep(None, day, 1, obs)
        mu = pol._day(obs, day)
        mean_w, var_w = pol.comp_demand(mu, slice(0, 20))
        mean_all, var_all = pol.comp_demand(mu, slice(0, 48))
        mean_d, var_d = pol.comp_demand(mu, slice(20, 48))
        mean0, sd0 = np.where(W.WINDOW_COMP, mean_w, mean_all), np.sqrt(np.where(W.WINDOW_COMP, var_w, var_all))
        run_ = c.execute("SELECT id FROM forecast_runs WHERE %s = ANY(dates) ORDER BY created_at DESC LIMIT 1", [date_of(day)]).fetchone()
        old = c.execute("SELECT id FROM prep_plans WHERE business_date = %s AND status = 'active'", [date_of(day)]).fetchone()
        if old:
            c.execute("UPDATE prep_plans SET status = 'superseded' WHERE id = %s", [old["id"]])
            c.execute("UPDATE prep_tasks SET status = 'superseded' WHERE plan_id = %s", [old["id"]])
        pid = uuid.uuid4()
        rows = []
        R = list(W.LUNCH_RUSH)
        slot_units = mu.sum(1)                                                            # [L, S]
        crew = np.maximum(2, np.ceil(E.quantile(slot_units, slot_units + pol.m.c * slot_units ** 2, 0.9) / UNITS_PER_COOK)).astype(int)
        for l in range(mt["L"]):
            h = E.feature_hash(mu[l])
            for k in range(W.N_COMP):
                for w, qty, par, mean, sd in ((0, lunch[l, k], par0[l, k], mean0[l, k], sd0[l, k]), (1, dinner[l, k], par1[l, k], mean_d[l, k], np.sqrt(var_d[l, k]))):
                    if w == 1 and not W.WINDOW_COMP[k]:
                        continue
                    rows.append((ctx.tenant_id, pid, mt["ids"][l], date_of(day), ("lunch", "dinner")[w], W.COMP[k], round(float(qty), 3),
                                 datetime.time(10, 45) if w == 0 else datetime.time(16, 45), round(float(qty * W.LABOR_MIN[k]), 1),
                                 Jsonb({"forecast_mean": round(float(mean), 3), "forecast_sd": round(float(sd), 3), "quantile": Q_PREP, "usual_par": round(float(par), 3),
                                        "hold": W.COMPONENTS[W.COMP[k]][1], "model_version": f["model_version"], "inputs_hash": h,
                                        "note": "updated at 15:00 from the lunch actually sold" if w else None}), "planned"))
            log_run(c, ctx.tenant_id, E.PLANNER_VERSION, f["model_version"], f"prep:{mt['ids'][l]}:{date_of(day)}", h,
                    {"lunch_kg": round(float(lunch[l].sum()), 2), "dinner_kg": round(float(dinner[l].sum()), 2)})
        db.load(c, "prep_tasks", ["tenant_id", "plan_id", "location_id", "business_date", "prep_window", "component_id", "qty", "ready_by", "labor_min", "evidence", "status"], rows)
        comp = lambda a: {W.COMP[k]: round(float(a[:, k].sum()), 1) for k in range(W.N_COMP)}            # noqa: E731
        summary = {"stores": mt["L"], "tasks": len(rows), "lunch_and_day_kg": comp(lunch), "usual_par_lunch_and_day_kg": comp(par0), "dinner_kg": comp(dinner),
                   "usual_par_dinner_kg": comp(par1), "labor_hours": round(float(sum(r[8] for r in rows)) / 60, 1),
                   "food_cost_usd": round(float(((lunch + dinner) * W.COMP_COST).sum()), 2),
                   "usual_par_food_cost_usd": round(float(((par0 + par1) * W.COMP_COST).sum()), 2), "quantile": Q_PREP, "forecast_run_id": run_["id"] if run_ else None}
        c.execute("INSERT INTO prep_plans (id, tenant_id, business_date, forecast_run_id, summary, created_by) VALUES (%s,%s,%s,%s,%s,%s)",
                  [pid, ctx.tenant_id, date_of(day), run_["id"] if run_ else None, Jsonb(jsonable_encoder(summary)), ctx.actor_id])
        audit.record(c, ctx, "prep.planned", "prep_plan", pid, {"date": str(date_of(day)), "tasks": len(rows), "superseded": str(old["id"]) if old else None})
        ex = int(np.argmax(np.asarray(mt["region_name"]) == "Uptown"))
        example = {"location": mt["ids"][ex], "name": mt["names"][ex], "tasks": [{"component": W.COMP[k], "window": w, "qty": round(float(q), 2), "usual_par": round(float(p_), 2),
                                                                                 "forecast_mean": round(float(mn), 2), "unit": W.COMPONENTS[W.COMP[k]][0], "labor_min": round(float(q * W.LABOR_MIN[k]), 1),
                                                                                 "ready_by": "10:45" if w == "lunch" else "16:45"}
                                                                                for k in range(W.N_COMP) for w, q, p_, mn in (("lunch", lunch[ex, k], par0[ex, k], mean0[ex, k]), ("dinner", dinner[ex, k], par1[ex, k], mean_d[ex, k]))
                                                                                if w == "lunch" or W.WINDOW_COMP[k]],
                   "crew_lunch": [{"time": slot_time(s), "cooks": int(crew[ex, s]), "units_mean": round(float(slot_units[ex, s]), 1)} for s in R]}
        return 201, {"plan_id": pid, "date": date_of(day), "superseded": old["id"] if old else None, "summary": summary, "example": example,
                     "by_store": [{"id": mt["ids"][l], "region": mt["region_name"][l], "lunch_kg": round(float(lunch[l].sum()), 1), "usual_par_kg": round(float(par0[l].sum()), 1),
                                   "max_cooks": int(crew[l, R].max())} for l in range(mt["L"])]}
    return run(ctx, idem, body, work)


# --- orders ---------------------------------------------------------------------------------------------------------------------
@app.post("/v1/orders/recommend", status_code=202, tags=["orders"], summary="Tonight's orders for every store and ingredient: base-stock to the 95th percentile of the forecast use over each delivery's cover, net of the stock the spoilage hazard expects to survive and what is due (with suppliers' delay notices applied), and a backup order when a late truck would leave a store short. Lines within $250 of the usual par are approved automatically; larger changes go to a store manager")
def recommend(ctx: Ctx = Depends(auth("orders:recommend")), idem: str | None = IdemKey):
    def work(c):
        chain(c)
        return 202, jobs.enqueue(c, ctx, "orders.recommend", {})
    return run(ctx, idem, {}, work)


@jobs.handler("orders.recommend")
def recommend_job(c, job):
    f = chain(c)
    t, mt, m = f["tenant_id"], meta(c), models(f)
    d = f["next_day"] - 1
    obs = DbObs(c, f, mt, d)
    pol, usual = system_policy(m), W.UsualPractice()
    sys_o = pol.order(obs.ch, d, obs)
    par = {o["supplier"]: o["qty"] for o in usual.order(obs.ch, d, obs)}
    at_risk = obs.lots * (1 - pol.survival(obs, np.arange(W.AGES), 2))
    rid = uuid.uuid4()
    old = c.execute("SELECT id, decision_id FROM recommendations WHERE as_of = %s AND status = 'active'", [date_of(d)]).fetchone()
    if old:
        c.execute("UPDATE recommendations SET status = 'superseded' WHERE id = %s", [old["id"]])
        c.execute("UPDATE supplier_orders SET status = 'superseded' WHERE recommendation_id = %s AND NOT placed", [old["id"]])
        c.execute("UPDATE decisions SET status = 'superseded' WHERE id = %s AND status = 'proposed'", [old["decision_id"]])
    c.execute("INSERT INTO recommendations (id, tenant_id, as_of, summary, created_by) VALUES (%s,%s,%s,'{}',%s)", [rid, t, date_of(d), uuid.UUID(job["payload"]["actor_id"])])
    for o in sys_o:
        o["par"] = par.get(o["supplier"], np.zeros_like(o["qty"]))
        o["value"] = E.change_value(o["supplier"], o["qty"], o["par"])

    def status_of(o, l, i):
        return "auto_approved" if o["value"][l, i] <= E.ORDER_LIMIT_USD else "proposed"

    def evidence_of(o, l, i):
        ev = {k: round(float(o[k][l, i]), 3) for k in ("need_mean", "need_sd", "target", "usable_on_hand", "incoming") if k in o}
        ev.update({"cover_days": o["cover_days"], "quantile": Q_ING, "at_risk_next_2_days": round(float(at_risk[l, i].sum()), 3),
                   "usual_par": round(float(o["par"][l, i]), 3), "change_usd": round(float(o["value"][l, i]), 2), "model_version": f["model_version"]})
        if o["supplier"] == "backup":
            ev["late_truck_qty"] = round(float(o["late"][l, i]), 3)
        return ev
    rows = order_lines(c, t, mt, sys_o, d, "planner", rid, status_of, evidence_of, delays=obs.delays)
    proposed = [r for r in rows if r[11] == "proposed"]
    value = lambda rs: round(float(sum(r[8] * r[10] for r in rs)), 2)            # noqa: E731
    did = None
    if proposed:
        did = uuid.uuid4()
        rationale = {"limit_usd": E.ORDER_LIMIT_USD, "lines": [{"location": r[2], "supplier": r[3], "ingredient": r[4], "qty": r[8], "usual_par": r[9],
                                                                "value_usd": round(r[8] * r[10], 2), "due": r[6], "why": r[14].obj} for r in proposed]}
        c.execute("""INSERT INTO decisions (id, tenant_id, kind, recommendation_id, lines, value_usd, rationale, proposed_by) VALUES (%s,%s,'order_change',%s,%s,%s,%s,%s)""",
                  [did, t, rid, len(proposed), value(proposed), Jsonb(jsonable_encoder(rationale)), uuid.UUID(job["payload"]["actor_id"])])
    by_sup = {}
    for r in rows:
        b = by_sup.setdefault(r[3], {"lines": 0, "value_usd": 0.0, "usual_par_value_usd": 0.0, "proposed_lines": 0})
        b["lines"] += 1
        b["value_usd"] = round(b["value_usd"] + r[8] * r[10], 2)
        b["usual_par_value_usd"] = round(b["usual_par_value_usd"] + r[9] * r[10], 2)
        b["proposed_lines"] += r[11] == "proposed"
    backup = [r for r in rows if r[3] == "backup"]
    summary = {"as_of": date_of(d), "lines": len(rows), "auto_approved": len(rows) - len(proposed), "proposed": len(proposed), "value_usd": value(rows),
               "usual_par_value_usd": round(float(sum(r[9] * r[10] for r in rows)), 2), "by_supplier": by_sup, "backup_stores": len({r[2] for r in backup}),
               "delays_known": [n | {"due": str(date_of(n["due"]))} for n in obs.delays if n["due"] > d - 1]}
    c.execute("UPDATE recommendations SET summary = %s, decision_id = %s WHERE id = %s", [Jsonb(jsonable_encoder(summary)), did, rid])
    for l in range(mt["L"]):
        log_run(c, t, E.PLANNER_VERSION, f["model_version"], f"orders:{mt['ids'][l]}:{date_of(d)}", E.feature_hash(obs.count[l], obs.lots[l]),
                {"lines": sum(1 for r in rows if r[2] == mt["ids"][l]), "value_usd": round(sum(r[8] * r[10] for r in rows if r[2] == mt["ids"][l]), 2)})
    audit.record(c, worker_ctx(job), "orders.recommended", "recommendation", rid, {"lines": len(rows), "proposed": len(proposed), "decision": str(did) if did else None})
    top = sorted(proposed, key=lambda r: -r[8] * r[10])[:12]
    return {"recommendation_id": rid, "decision_id": did, "superseded": old["id"] if old else None, **summary,
            "needs_approval": [{"location": r[2], "supplier": r[3], "ingredient": r[4], "qty": round(r[8], 2), "usual_par": round(r[9], 2), "value_usd": round(r[8] * r[10], 2),
                                "due": r[6], "eta": r[7], "evidence": r[14].obj} for r in top],
            "example_lines": [{"location": r[2], "supplier": r[3], "ingredient": r[4], "qty": round(r[8], 2), "usual_par": round(r[9], 2), "due": r[6], "status": r[11], "evidence": r[14].obj}
                              for r in rows if r[2] == mt["ids"][int(np.argmax(np.asarray(mt["region_name"]) == "Uptown"))]][:16]}


@app.post("/v1/decisions/{decision_id}/approve", tags=["decisions"], summary="(+) A store manager approves or rejects the order changes above the limit; the person who asked for the recommendation cannot. Rejected lines go at the usual par")
def approve(decision_id: uuid.UUID, decision: Literal["approved", "rejected"] = "approved", ctx: Ctx = Depends(auth("decisions:approve")), idem: str | None = IdemKey):
    def work(c):
        d = c.execute("SELECT * FROM decisions WHERE id = %s FOR UPDATE", [decision_id]).fetchone()
        if not d:
            raise Problem(404, "decision_not_found")
        if d["status"] != "proposed":
            raise Problem(409, "already_decided", f"this decision is {d['status']}")
        if d["proposed_by"] == ctx.actor_id:
            raise Problem(403, "proposer_cannot_approve", "order changes above the limit need a second person")
        c.execute("UPDATE decisions SET status = %s, decided_by = %s, decided_at = now() WHERE id = %s", [decision, ctx.actor_id, decision_id])
        n = c.execute("UPDATE supplier_orders SET status = %s WHERE recommendation_id = %s AND status = 'proposed'", [decision, d["recommendation_id"]]).rowcount
        audit.record(c, ctx, f"orders.{decision}", "decision", decision_id, {"lines": n, "value_usd": d["value_usd"]})
        return 200, {"decision_id": decision_id, "status": decision, "lines": n, "value_usd": d["value_usd"]}
    return run(ctx, idem, {"decision": decision}, work)


@app.get("/v1/decisions", tags=["decisions"], summary="(+) Order-change proposals and decisions")
def decisions(ctx: Ctx = Depends(auth("chain:read"))):
    with db.tx(ctx.tenant_id) as c:
        return jsonable_encoder({"items": c.execute("SELECT id, kind, recommendation_id, lines, value_usd, status, proposed_by, decided_by, created_at, decided_at FROM decisions ORDER BY created_at DESC").fetchall()})


# --- waste risk --------------------------------------------------------------------------------------------------------------------
@app.get("/v1/waste/risk", tags=["waste"], summary="Every open lot's risk of being thrown away in the next two days: the spoilage hazard at its age and the walk-in's temperature, and what will be left at its printed date at the forecast use; ranked by expected loss in dollars, beside what the printed date alone would flag")
def waste_risk(location: str | None = None, limit: int = Query(20, ge=1, le=200), ctx: Ctx = Depends(auth("chain:read"))):
    with db.tx(ctx.tenant_id) as c:
        f = chain(c)
        mt, m = meta(c), models(f)
        d = f["next_day"] - 1
        obs = DbObs(c, f, mt, d, lookback=0)                                           # the lots, temperatures and calendar are enough
        lots = c.execute("SELECT id, location_id, ingredient_id, received_on, expires_on, qty_on_hand FROM inventory_lots WHERE status = 'open' AND qty_on_hand > 0").fetchall()
        pol = system_policy(m)
        use = sum((pol.raw_need(obs, t)[0] for t in range(d + 1, d + 3)), np.zeros((mt["L"], W.N_ING)))
        hz = m["spoilage-hazard"]
        lots = [r for r in sorted(lots, key=lambda r: r["received_on"]) if W.PERISHABLE[W.ING.index(r["ingredient_id"])]]   # FIFO: older lots take the use first
        li = np.array([mt["idx"][r["location_id"]] for r in lots], int)
        ii = np.array([W.ING.index(r["ingredient_id"]) for r in lots], int)
        age = np.array([d - day_of(r["received_on"]) for r in lots], int)
        temp = obs.temp[li] if len(lots) else np.zeros(0)
        p2 = 1 - (1 - hz.p(ii, age + 1, temp)) * (1 - hz.p(ii, age + 2, temp)) if len(lots) else np.zeros(0)
        rows, older = [], {}
        for k, r in enumerate(lots):
            l, i = li[k], ii[k]
            days_left = day_of(r["expires_on"]) - d
            ahead = older.get((l, i), 0.0)
            used_before_date = max(0.0, min(r["qty_on_hand"], use[l, i] / 2 * max(days_left, 0) - ahead))
            older[(l, i)] = ahead + r["qty_on_hand"]
            left_at_date = r["qty_on_hand"] - used_before_date if days_left <= 2 else 0.0
            exp_loss = W.COST[i] * (p2[k] * r["qty_on_hand"] + (1 - p2[k]) * left_at_date)
            rows.append({"lot": r["id"], "location": r["location_id"], "ingredient": r["ingredient_id"], "qty": round(r["qty_on_hand"], 2), "unit": W.INGREDIENTS[W.ING[i]][0],
                         "age_days": int(age[k]), "shelf_life_days": int(W.SHELF[i]), "expires_on": r["expires_on"], "cooler_c": round(float(temp[k]), 1), "p_spoil_2d": round(float(p2[k]), 3),
                         "left_at_printed_date": round(float(left_at_date), 2), "expected_loss_usd": round(float(exp_loss), 2),
                         "printed_date_flags": bool(days_left <= 1), "action": "use first / move to a sister store" if p2[k] > 0.15 else "use first" if exp_loss > 5 else "-"})
        if location:
            rows = [r for r in rows if r["location"] == location]
        rows.sort(key=lambda r: -r["expected_loss_usd"])
        by_store = {}
        for r in rows:
            by_store[r["location"]] = by_store.get(r["location"], 0) + r["expected_loss_usd"]
        log_run(c, ctx.tenant_id, E.HAZARD_VERSION, f["model_version"], f"waste-risk:{location or 'chain'}:{date_of(d)}", E.feature_hash(obs.temp, obs.lots.sum(2)),
                {"lots": len(rows), "expected_loss_usd": round(sum(r["expected_loss_usd"] for r in rows), 2)})
        warm = [{"location": mt["ids"][l], "cooler_c": round(float(obs.temp[l]), 1)} for l in np.argsort(-obs.temp)[:5]]
    return jsonable_encoder({"as_of": date_of(d), "model": E.HAZARD_VERSION, "version": f["model_version"], "lots_scored": len(rows),
                             "expected_loss_usd": round(sum(r["expected_loss_usd"] for r in rows), 2), "high_risk_lots": sum(r["p_spoil_2d"] > 0.15 for r in rows),
                             "printed_date_flags": sum(r["printed_date_flags"] for r in rows),
                             "warmest_walk_ins": warm, "by_store": sorted([{"location": k, "expected_loss_usd": round(v, 2)} for k, v in by_store.items()], key=lambda x: -x["expected_loss_usd"])[:10],
                             "lots": rows[:limit]})


# --- margins and shrinkage ----------------------------------------------------------------------------------------------------------
@app.get("/v1/margins/explain", tags=["margins"], summary="Why food cost is what it is: for a period, theoretical food cost (sales at recipe) bridged to actual (counted usage, plus the backup premium) through prep waste, spoiled and expired lots, and unexplained usage, per store and ingredient; the stores furthest from recipe; and each promotion's incremental margin at its estimated elasticity")
def margins(days: int = Query(7, ge=1, le=56), location: str | None = None, ctx: Ctx = Depends(auth("chain:read"))):
    with db.tx(ctx.tenant_id) as c:
        f = chain(c)
        mt, dm = meta(c), models(f)["demand-forecast"]
        d1 = f["next_day"] - 1
        d0 = d1 - days + 1
        if location and location not in mt["idx"]:
            raise Problem(404, "location_not_found")
        L = mt["L"]
        rev, theo_cost, units, disc_usd = np.zeros(L), np.zeros(L), np.zeros((L, W.N_ITEM)), np.zeros(L)
        promo_units = {}
        for r in c.execute("SELECT location_id, item_id, business_date, units, revenue, discount FROM sales WHERE business_date BETWEEN %s AND %s", [date_of(d0), date_of(d1)]):
            l, i = mt["idx"][r["location_id"]], W.ITEM.index(r["item_id"])
            rev[l] += float(r["revenue"])
            units[l, i] += r["units"]
            theo_cost[l] += r["units"] * W.ITEM_FOOD_COST[i]
            if r["discount"]:
                disc_usd[l] += r["units"] * W.PRICE[i] * r["discount"]
                pu = promo_units.setdefault((i, r["discount"]), [0, 0.0])
                pu[0] += r["units"]
        waste = {k: np.zeros(L) for k in ("prep_discard", "spoiled", "expired")}
        for r in c.execute("SELECT location_id, reason, sum(cost) AS c FROM waste_events WHERE business_date BETWEEN %s AND %s GROUP BY location_id, reason", [date_of(d0), date_of(d1)]):
            waste[r["reason"]][mt["idx"][r["location_id"]]] = float(r["c"])
        act = np.zeros((L, W.N_ING))
        theo = np.zeros((L, W.N_ING))
        for r in c.execute("""SELECT location_id, ingredient_id, sum(actual_use) AS a, sum(theoretical_use) AS t FROM inventory_counts
                               WHERE business_date BETWEEN %s AND %s GROUP BY location_id, ingredient_id""", [date_of(d0), date_of(d1)]):
            act[mt["idx"][r["location_id"]], W.ING.index(r["ingredient_id"])] = r["a"]
            theo[mt["idx"][r["location_id"]], W.ING.index(r["ingredient_id"])] = r["t"]
        prem = np.zeros(L)
        for r in c.execute("""SELECT location_id, sum(qty * unit_cost) * (1 - 1 / 1.35) AS p FROM supplier_orders
                               WHERE supplier = 'backup' AND delivered_on BETWEEN %s AND %s GROUP BY location_id""", [date_of(d0), date_of(d1)]):
            prem[mt["idx"][r["location_id"]]] = float(r["p"])
        unexplained_ing = (act - theo) * W.COST                                            # usage nobody can account for, $ by ingredient
        unexplained = unexplained_ing.sum(1)
        actual = theo_cost + waste["prep_discard"] + waste["spoiled"] + waste["expired"] + unexplained + prem
        pct = lambda a, b: round(float(100 * a / max(b, 1e-9)), 2)                         # noqa: E731
        sel = [mt["idx"][location]] if location else list(range(L))
        R = rev[sel].sum()
        bridge = [{"step": "theoretical (sales at recipe)", "usd": round(float(theo_cost[sel].sum()), 2), "pct_of_revenue": pct(theo_cost[sel].sum(), R)},
                  {"step": "prep waste", "usd": round(float(waste["prep_discard"][sel].sum()), 2), "pct_of_revenue": pct(waste["prep_discard"][sel].sum(), R)},
                  {"step": "spoiled lots", "usd": round(float(waste["spoiled"][sel].sum()), 2), "pct_of_revenue": pct(waste["spoiled"][sel].sum(), R)},
                  {"step": "expired lots", "usd": round(float(waste["expired"][sel].sum()), 2), "pct_of_revenue": pct(waste["expired"][sel].sum(), R)},
                  {"step": "unexplained usage", "usd": round(float(unexplained[sel].sum()), 2), "pct_of_revenue": pct(unexplained[sel].sum(), R)},
                  {"step": "backup premium", "usd": round(float(prem[sel].sum()), 2), "pct_of_revenue": pct(prem[sel].sum(), R)},
                  {"step": "actual", "usd": round(float(actual[sel].sum()), 2), "pct_of_revenue": pct(actual[sel].sum(), R)}]
        norm = np.median(np.where(theo > 0, unexplained_ing / np.maximum(theo * W.COST, 1e-9), 0), 0)
        stores = []
        for l in range(L):
            gap = actual[l] - theo_cost[l]
            excess = unexplained_ing[l] - norm * theo[l] * W.COST
            drivers = {"prep waste": waste["prep_discard"][l], "spoiled/expired": waste["spoiled"][l] + waste["expired"][l], "unexplained usage": unexplained[l], "backup premium": prem[l]}
            stores.append({"location": mt["ids"][l], "region": mt["region_name"][l], "revenue_usd": round(float(rev[l]), 2), "food_cost_pct": pct(actual[l], rev[l]),
                           "theoretical_pct": pct(theo_cost[l], rev[l]), "gap_pts": round(float(100 * gap / max(rev[l], 1e-9)), 2), "top_driver": max(drivers, key=drivers.get),
                           "excess_ingredient": W.ING[int(np.argmax(excess))] if excess.max() > 50 else None, "excess_usd": round(float(excess.max()), 2)})
        stores.sort(key=lambda s: -s["gap_pts"])
        promos = []
        for p in c.execute("SELECT * FROM promotions WHERE starts_on <= %s AND ends_on > %s", [date_of(d1), date_of(d0)]):
            i = W.ITEM.index(p["item_id"])
            u = promo_units.get((i, p["discount"]), [0])[0]
            if not u:
                continue
            eps = float(dm.eps[i])
            base = u / (1 - p["discount"]) ** (-eps)
            m_full, m_promo = W.PRICE[i] - W.ITEM_FOOD_COST[i], W.PRICE[i] * (1 - p["discount"]) - W.ITEM_FOOD_COST[i]
            promos.append({"promotion": p["id"], "item": p["item_id"], "discount": p["discount"], "regions": p["regions"], "units": int(u), "elasticity": round(eps, 2),
                           "estimated_without_promo": int(round(base)), "incremental_units": int(round(u - base)),
                           "incremental_margin_usd": round(float(u * m_promo - base * m_full), 2), "discount_given_usd": round(float(u * W.PRICE[i] * p["discount"]), 2)})
        out = {"from": date_of(d0), "to": date_of(d1), "scope": location or "chain", "revenue_usd": round(float(R), 2), "bridge": bridge, "stores": stores[:12],
               "promotions": promos, "discount_given_usd": round(float(disc_usd[sel].sum()), 2)}
        if location:
            l = mt["idx"][location]
            out["ingredients"] = sorted([{"ingredient": W.ING[i], "theoretical": round(float(theo[l, i]), 2), "actual": round(float(act[l, i]), 2),
                                          "variance_pct": round(float(100 * (act[l, i] / max(theo[l, i], 1e-9) - 1)), 1), "chain_norm_pct": round(float(100 * norm[i] / max(W.COST[i], 1e-9) * W.COST[i]), 1),
                                          "unexplained_usd": round(float(unexplained_ing[l, i]), 2)} for i in range(W.N_ING)], key=lambda x: -x["unexplained_usd"])
    return jsonable_encoder(out)


@app.get("/v1/shrinkage", tags=["shrinkage"], summary="(+) Stores whose counted usage runs ahead of their sales at recipe by more than the chain's normal for that ingredient (in standard errors of the chain's daily scatter), classed as over-portioning or theft/unrecorded loss, beside a fixed 4% variance threshold")
def shrinkage(ctx: Ctx = Depends(auth("chain:read"))):
    with db.tx(ctx.tenant_id) as c:
        f = chain(c)
        mt = meta(c)
        L = mt["L"]
        D = f["next_day"]
        theo, act = np.zeros((D, L, W.N_ING)), np.zeros((D, L, W.N_ING))
        for r in c.execute("SELECT location_id, ingredient_id, business_date, actual_use, theoretical_use FROM inventory_counts"):
            k = (day_of(r["business_date"]), mt["idx"][r["location_id"]], W.ING.index(r["ingredient_id"]))
            act[k], theo[k] = r["actual_use"], r["theoretical_use"]
        theo, act = theo[1:], act[1:]                                                     # day 0 has no opening count
        scan, base = E.shrinkage_scan(theo, act)
        flagged = [{"location": mt["ids"][l], "name": mt["names"][l], **shrink_detail(scan, l),
                    "excess_usd": round(float(((act[:, l] - theo[:, l] * (1 + scan["chain_norm"])).sum(0) * W.COST * scan["flags"][l]).sum()), 2)}
                   for l in np.nonzero(scan["flags"].any(1))[0]]
        flagged.sort(key=lambda x: -x["excess_usd"])
        alerts = c.execute("SELECT location_id, detail, raised_on FROM alerts WHERE kind = 'shrinkage' AND status = 'open'").fetchall()
    return jsonable_encoder({"days": int(theo.shape[0]), "stores_flagged": len(flagged), "flagged": flagged,
                             "chain_norm_pct": {W.ING[i]: round(100 * float(v), 1) for i, v in enumerate(scan["chain_norm"])},
                             "threshold_baseline": {"rule": "variance above 4% of theoretical", "stores_flagged": int(base.any(1).sum()), "pairs_flagged": int(base.sum()),
                                                    "by_ingredient": {W.ING[i]: int(n) for i, n in enumerate(base.sum(0)) if n}},
                             "open_alerts": len(alerts)})


# --- outcomes: the same days under other plans ---------------------------------------------------------------------------------------
@app.post("/v1/outcomes:compare", status_code=202, tags=["outcomes"], summary="(+) Re-run the days the last advance played, from the same starting stock with the same customers, weather and spoilage draws, under other plans: as run (the check: it must reproduce), the plan made before the notices arrived, and the chain's usual practice. Waste, lost sales and spend come from the generator, so they include the demand the POS never saw")
def compare(ctx: Ctx = Depends(auth("outcomes:run")), idem: str | None = IdemKey):
    def work(c):
        f = chain(c)
        if not f["snapshot"]:
            raise Problem(409, "nothing_to_compare", "advance at least one day first")
        return 202, jobs.enqueue(c, ctx, "outcomes.compare", {})
    return run(ctx, idem, {}, work)


@jobs.handler("outcomes.compare")
def compare_job(c, job):
    f = chain(c)
    t, mt, m = f["tenant_id"], meta(c), models(f)
    snap = f["snapshot"]
    st = pickle.loads(c.execute("SELECT snapshot_state FROM chains").fetchone()["snapshot_state"])
    d0, n, told = snap["from_day"], snap["days"], snap["told"]
    ch = W.apply_told(W.chain(f["model_seed"]), told)
    ch0 = W.chain(f["model_seed"])
    pending = [{**p, "qty": np.array(p["qty"])} for p in snap["pending"]]
    plans = {int(k): uuid.UUID(v) for k, v in snap["plans"].items()}
    bounded = lambda: E.WithPlans(E.Bounded(system_policy(m), W.UsualPractice()))       # noqa: E731
    alts = []
    p_as = bounded()
    p_as.preps = plan_arrays(c, mt, plans)
    alts.append(("as run", "tonight's orders as approved, the re-plan's prep, the planner unattended after", pending, p_as))
    first_rec = c.execute("SELECT id FROM recommendations WHERE as_of = %s ORDER BY created_at LIMIT 1", [date_of(d0 - 1)]).fetchone()
    first_plan = c.execute("SELECT id FROM prep_plans WHERE business_date = %s ORDER BY created_at LIMIT 1", [date_of(d0)]).fetchone()
    if first_rec and first_plan and (first_plan["id"] != plans.get(d0)):
        q = {}
        for r in c.execute("SELECT supplier, due_on, location_id, ingredient_id, qty FROM supplier_orders WHERE recommendation_id = %s", [first_rec["id"]]):
            q.setdefault((r["supplier"], day_of(r["due_on"])), np.zeros((mt["L"], W.N_ING)))[mt["idx"][r["location_id"]], W.ING.index(r["ingredient_id"])] += r["qty"]
        p_b = bounded()
        p_b.preps = plan_arrays(c, mt, {d0: first_plan["id"]})
        alts.append(("plan before the notices", "the orders and prep the planner had before the delay notice and the storm forecast", [{"id": f"b-{s}-{d}", "supplier": s, "due": d, "ordered_on": d0 - 1, "qty": v} for (s, d), v in q.items()], p_b))
    usual = W.UsualPractice()
    obs0 = W.Obs(ch0, st, d0 - 1, W.delays_known(ch0, [], d0 - 1))
    alts.append(("usual practice", "par prep from the last two same weekdays, par orders, no backup", [dict(o, id=f"u-{k}", ordered_on=d0 - 1) for k, o in enumerate(usual.order(ch0, d0 - 1, obs0))], usual))
    out = []
    for name, how, pend, pol in alts:
        _, recs = W.run(ch, st, d0, d0 + n, pol, told, pend, last_orders=False)
        tm = W.metrics(recs)
        prem = sum(float((r["received_by"].get("backup", np.zeros((mt["L"], W.N_ING))) * W.COST * (W.SUPPLIERS["backup"][2] - 1)).sum()) for r in recs)
        out.append({"name": name, "how": how, **{k: tm[k] for k in ("waste_usd", "prep_waste_usd", "lot_waste_usd", "stockout_rate", "lost_units", "demand_units", "lost_revenue_usd", "purchases_usd", "revenue_usd")},
                    "backup_premium_usd": round(prem, 2),
                    "by_day": [{"date": date_of(r["day"]), **{k: v for k, v in W.metrics([r]).items() if k in ("waste_usd", "stockout_rate", "lost_units")}} for r in recs],
                    "units_sold": int(sum(r["sold"].sum() for r in recs))})
    rec_actual = snap.get("actual", {})
    reproduces = all(abs(out[0][k] - rec_actual.get(k, -1)) < 1e-6 for k in ("waste_usd", "lost_units", "units_sold"))
    oid = uuid.uuid4()
    result = {"outcome_id": oid, "from": date_of(d0), "days": n, "reproduces_actual": bool(reproduces), "alternatives": out,
              "how": "the generator re-runs the same days with the same customers, weather and spoilage draws, so each plan meets the same demand; lost sales include the demand the POS never saw"}
    c.execute("INSERT INTO outcomes (id, tenant_id, from_day, days, result, created_by) VALUES (%s,%s,%s,%s,%s,%s)",
              [oid, t, date_of(d0), n, Jsonb(jsonable_encoder(result)), uuid.UUID(job["payload"]["actor_id"])])
    audit.record(c, worker_ctx(job), "outcomes.compared", "outcome", oid, {"days": n, "alternatives": [a["name"] for a in out]})
    return result


# --- reading the chain ----------------------------------------------------------------------------------------------------------------
@app.get("/v1/chain/overview", tags=["chain"], summary="(+) The command centre: the clock, every store on the map with yesterday's sales, waste and item-slots 86'd, the last week's KPIs, notices, open alerts, promotions running, and the models in production")
def overview(ctx: Ctx = Depends(auth("chain:read"))):
    with db.tx(ctx.tenant_id) as c:
        f = chain(c)
        mt = meta(c)
        d = f["next_day"] - 1
        y = {r["location_id"]: r for r in c.execute("""SELECT location_id, sum(units) AS units, sum(revenue) AS revenue, sum(cardinality(unavailable)) AS out86
                                                        FROM sales WHERE business_date = %s GROUP BY location_id""", [date_of(d)])}
        wst = {r["location_id"]: float(r["c"]) for r in c.execute("SELECT location_id, sum(cost) AS c FROM waste_events WHERE business_date = %s GROUP BY location_id", [date_of(d)])}
        cool = {r["location_id"]: r["cooler_c"] for r in c.execute("SELECT location_id, cooler_c FROM conditions WHERE business_date = %s", [date_of(d)])}
        week = c.execute("""SELECT s.business_date, sum(s.units) AS units, sum(s.revenue) AS revenue, sum(cardinality(s.unavailable)) AS out86 FROM sales s
                             WHERE s.business_date BETWEEN %s AND %s GROUP BY s.business_date ORDER BY 1""", [date_of(d - 13), date_of(d)]).fetchall()
        wk_waste = {r["business_date"]: float(r["c"]) for r in c.execute("SELECT business_date, sum(cost) AS c FROM waste_events WHERE business_date BETWEEN %s AND %s GROUP BY 1", [date_of(d - 13), date_of(d)])}
        wk_buy = {r["business_date"]: float(r["c"]) for r in c.execute("""SELECT k.business_date, sum(k.received * i.unit_cost) AS c FROM inventory_counts k JOIN ingredients i ON i.id = k.ingredient_id
                                                                          WHERE k.business_date BETWEEN %s AND %s GROUP BY 1""", [date_of(d - 13), date_of(d)])}
        notices = c.execute("SELECT kind, received_on, detail FROM notices ORDER BY created_at DESC LIMIT 10").fetchall()
        alerts = c.execute("SELECT kind, location_id, detail, raised_on FROM alerts WHERE status = 'open' ORDER BY raised_on DESC").fetchall()
        promos = c.execute("SELECT id, item_id, discount, starts_on, ends_on, regions FROM promotions WHERE ends_on > %s AND starts_on <= %s ORDER BY starts_on", [date_of(d), date_of(d + 7)]).fetchall()
        mods = c.execute("SELECT name, version, data_snapshot, metrics, approved FROM model_artifacts ORDER BY name").fetchall()
        plans = c.execute("SELECT business_date, status, created_at FROM prep_plans ORDER BY created_at DESC LIMIT 5").fetchall()
        pending = c.execute("SELECT count(*) AS n FROM decisions WHERE status = 'proposed'").fetchone()["n"]
    days = [{"date": r["business_date"], "units": int(r["units"]), "revenue_usd": round(float(r["revenue"]), 2), "waste_usd": round(wk_waste.get(r["business_date"], 0.0), 2),
             "purchases_usd": round(wk_buy.get(r["business_date"], 0.0), 2), "item_slots_86d": int(r["out86"])} for r in week]
    last7 = days[-7:]
    return jsonable_encoder({"chain": f["name"], "clock": date_of(d), "next_business_day": date_of(f["next_day"]), "stores": [
        {"id": mt["ids"][l], "name": mt["names"][l], "region": mt["region_name"][l], "format": W.FORMATS[mt["format"][l]], "xy": mt["xy"][l],
         "units": int(y[mt["ids"][l]]["units"]) if mt["ids"][l] in y else 0, "revenue_usd": round(float(y[mt["ids"][l]]["revenue"]), 2) if mt["ids"][l] in y else 0.0,
         "item_slots_86d": int(y[mt["ids"][l]]["out86"]) if mt["ids"][l] in y else 0, "waste_usd": round(wst.get(mt["ids"][l], 0.0), 2), "cooler_c": cool.get(mt["ids"][l])} for l in range(mt["L"])],
        "days": days, "last7": {"revenue_usd": round(sum(x["revenue_usd"] for x in last7), 2), "waste_usd": round(sum(x["waste_usd"] for x in last7), 2),
                                "purchases_usd": round(sum(x["purchases_usd"] for x in last7), 2),
                                "waste_pct_of_purchases": round(sum(x["waste_usd"] for x in last7) / max(sum(x["purchases_usd"] for x in last7), 1), 4),
                                "item_slots_86d_per_store_day": round(sum(x["item_slots_86d"] for x in last7) / max(1, 7 * mt["L"]), 2)},
        "notices": notices, "alerts": alerts, "promotions": promos, "decisions_awaiting": pending, "prep_plans": plans,
        "models": [{**x, "metrics": x["metrics"] if x["name"] != "consumption" else {k: v for k, v in x["metrics"].items() if k != "chain_ratio"}} for x in mods]})
