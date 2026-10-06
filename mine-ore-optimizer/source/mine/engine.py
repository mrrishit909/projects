"""Models, optimisers and the twin, all fitted on what the service stores (assays, the haul log, engine telemetry, plant
hours), never on the generator's fields. Each has a plain baseline it is scored against.

    grade estimator   Gaussian-process regression (kriging) of log-grade on drill and blast-hole assays, with each sample's
                      laboratory error as its own noise; posterior mean and spread per block; baselines: inverse distance
                      squared and the nearest hole
    cycle-time model  gradient-boosted regression of the whole truck cycle on the route's physics, payload, wet roads, truck
                      age and the queue the dispatcher saw; baseline: distance over the manufacturer's speed for the grade
    fuel model        litres per cycle, linear in the work done climbing and rolling and the idle minutes
    anomaly detector  each truck's normal coolant, oil pressure and exhaust as a function of its duty and the air temperature,
                      learned from windows far from any breakdown; alarm on two windows in a row more than 4 sd off in the
                      harmful direction; baseline: the manufacturer's fixed thresholds
    plant forecast    mill throughput by hour: the lesser of what the bin and the planned feed supply and the mill's rate at
                      the estimated hardness of the bin's blend, with one fitted scale; baseline: the trailing 12-hour mean
    dispatch          a mixed-integer programme (OR-Tools, SCIP): trucks per shovel from where they are, shovel rates on a
                      queueing curve built from the cycle-time model, each shovel's ore to the crusher or a stockpile, reclaim,
                      the plant's grade window and arsenic limit held at a confidence level; baselines: trucks split by dig
                      rate (fixed) and nearest-free-shovel dispatch, both with cut-off routing and proportional reclaim
    blend             a time-indexed MILP over the next hours: loader reclaim in whole loads from each stockpile, held inside the
                      grade window with the stockpiles' uncertainty; baseline: reclaim in proportion to the piles
    twin              the service's own event simulation of the rest of a shift under a plan, with the cycle-time model's
                      travel times, queues at the shovels and the crusher, block grades drawn from the estimator's posterior,
                      and the same random draws for every plan compared
"""
import hashlib
import heapq
import json
import math
import time

import numpy as np
from ortools.linear_solver import pywraplp
from scipy.optimize import minimize
from scipy.spatial import cKDTree
from scipy.stats import norm
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel

from . import world

GRADE_VERSION, CYCLE_VERSION, FUEL_VERSION = "grade-gp-1", "cycle-hgb-1", "fuel-linear-1"
ANOMALY_VERSION, PLANT_VERSION, DISPATCH_VERSION, BLEND_VERSION, TWIN_VERSION = "engine-normal-1", "plant-capacity-1", "dispatch-mip-1", "blend-milp-1", "twin-des-1"
LAB_SD = {"exploration": 0.08, "blasthole": 0.12}        # assay error (log units) by sample type: the lab's QA/QC
STOCK_FACTOR = 0.75                                       # a stockpiled tonne is worth 75% of milling it now (time, rehandle)
SENSORS = (("coolant_c", 1), ("oil_kpa", -1), ("exhaust_c", 1))       # (sensor, harmful direction)
STATIC = {"coolant_c": 105.0, "oil_kpa": 250.0, "exhaust_c": 720.0}   # the manufacturer's alarm thresholds
Z_ALARM, PERSIST = 4.0, 2


def feature_hash(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True, default=lambda v: round(float(v), 4)).encode()).hexdigest()[:16]


def block_xyz(b):
    i, j, k = world.block_ijk(np.asarray(b))
    return np.stack([(i + 0.5) * world.BLOCK_M, (j + 0.5) * world.BLOCK_M, world.TOP_RL - (k + 0.5) * world.BENCH_M], -1)


def _lbfgs(obj, theta, bounds):
    r = minimize(obj, theta, method="L-BFGS-B", jac=True, bounds=bounds, options={"maxiter": 60})
    return r.x, r.fun


# --- grade estimation ---------------------------------------------------------------------------------------------------------
class GradeModel:
    """Kriging (GP regression) of log Cu, log As and hardness. Hyperparameters are fitted on the exploration holes once; new
    assays condition the same model, so a blast-hole result updates the estimate around it without refitting the variogram."""

    def __init__(self, samples, fit_n=240):
        pick = np.random.default_rng(0).permutation(len(samples))[:fit_n]          # the variogram from a subsample; all samples condition it
        fit = [samples[i] for i in sorted(pick)]
        X = block_xyz([s["block"] for s in fit])
        self.kernels = {}
        for var in ("cu", "as", "bwi"):
            samples_ = fit
            y = self._y(samples_, var)
            k = ConstantKernel(1.0, (0.05, 20)) * RBF([60.0, 60.0, 25.0], [(10, 400), (10, 400), (5, 200)]) + WhiteKernel(0.05, (1e-4, 1))
            gp = GaussianProcessRegressor(k, alpha=self._alpha(samples_, var), normalize_y=True, optimizer=_lbfgs, random_state=0).fit(X, y)
            self.kernels[var] = gp.kernel_
        self.condition(samples)

    @classmethod
    def from_kernels(cls, kernels, samples):
        g = cls.__new__(cls)
        g.kernels = kernels
        return g.condition(samples)

    @staticmethod
    def _y(samples, var):
        v = np.array([s[var] for s in samples], float)
        return np.log(np.maximum(v, 1e-4)) if var in ("cu", "as") else v

    @staticmethod
    def _alpha(samples, var):
        if var == "bwi":
            return np.array([0.16 if s["kind"] == "exploration" else 0.36 for s in samples]) / 2.0
        return np.array([LAB_SD[s["kind"]] ** 2 for s in samples]) * (1.3 if var == "as" else 1.0)

    def condition(self, samples):
        X = block_xyz([s["block"] for s in samples])
        self.samples = list(samples)
        self.gps = {}
        for var in ("cu", "as", "bwi"):
            alpha = self._alpha(samples, var)
            ys = self._y(samples, var)
            sd = ys.std() or 1.0
            self.gps[var] = GaussianProcessRegressor(self.kernels[var], alpha=alpha / sd ** 2, optimizer=None, normalize_y=True).fit(X, ys)
        return self

    def predict(self, blocks):
        """-> dict of arrays: cu (expected %), cu_mu/cu_s (log mean, sd), p10/p90, as, as_s, bwi, p_hg, p_ore."""
        X = block_xyz(blocks)
        out = {}
        for var in ("cu", "as", "bwi"):
            mu, s = [], []
            for a in range(0, len(X), 6000):
                m_, s_ = self.gps[var].predict(X[a:a + 6000], return_std=True)
                mu.append(m_)
                s.append(s_)
            mu, s = np.concatenate(mu), np.concatenate(s)
            if var == "bwi":
                out["bwi"], out["bwi_s"] = mu, s
            else:
                out[f"{var}_mu"], out[f"{var}_s"] = mu, s
                out[var] = np.exp(mu + s ** 2 / 2)
        out["p10"], out["p90"] = np.exp(out["cu_mu"] - 1.2816 * out["cu_s"]), np.exp(out["cu_mu"] + 1.2816 * out["cu_s"])
        out["p_hg"] = 1 - norm.cdf((math.log(world.CUTOFF["HG"]) - out["cu_mu"]) / out["cu_s"])
        out["p_ore"] = 1 - norm.cdf((math.log(world.CUTOFF["LG"]) - out["cu_mu"]) / out["cu_s"])
        return out


def classify(cu):
    cu = np.asarray(cu)
    return np.where(cu >= world.CUTOFF["HG"], "HG", np.where(cu >= world.CUTOFF["LG"], "LG", "W"))


def idw(samples, blocks, power=2, k=16, var="cu"):
    """Inverse distance squared over the 16 nearest samples (vertical distance stretched x3, as the benches are)."""
    S = block_xyz([s["block"] for s in samples]) * [1, 1, 3]
    v = np.array([s[var] for s in samples], float)
    d, ix = cKDTree(S).query(block_xyz(blocks) * [1, 1, 3], k=k)
    w = 1 / np.maximum(d, 1.0) ** power
    return (w * v[ix]).sum(1) / w.sum(1)


def nearest_hole(samples, blocks, var="cu"):
    S = block_xyz([s["block"] for s in samples]) * [1, 1, 3]
    v = np.array([s[var] for s in samples], float)
    return v[cKDTree(S).query(block_xyz(blocks) * [1, 1, 3], k=1)[1]]


def score_grade(truth, est, p10=None, p90=None, tonnes=world.BLOCK_T):
    truth, est = np.asarray(truth), np.asarray(est)
    out = {"rmse": round(float(np.sqrt(np.mean((est - truth) ** 2))), 4), "mae": round(float(np.mean(np.abs(est - truth))), 4),
           "bias": round(float(np.mean(est - truth)), 4), "misclassified": round(float(np.mean(classify(est) != classify(truth))), 4),
           "blocks": int(len(truth))}
    if p10 is not None:
        out["coverage_80"] = round(float(np.mean((truth >= p10) & (truth <= p90))), 3)
    return out


# --- cycle time and fuel ----------------------------------------------------------------------------------------------------
CYCLE_FEATURES = ["phys_empty_min", "phys_loaded_min", "loaded_rise_m", "loaded_m", "empty_m", "payload_t", "rope", "to_crusher",
                  "queue_at_dispatch", "enroute_at_dispatch", "to_crusher_at_dispatch", "wet", "age_h"]


def route_physics(frm, face, dest):
    """What the manufacturer's speed-on-grade curve says, on a dry road at nominal payload: minutes empty and loaded, distances, rise."""
    e = world.route(frm, int(face))
    ld = world.route(int(face), dest)
    te = world.travel(e, world.TRUCK_EMPTY_T, False)[0]
    tl = world.travel(ld, world.TRUCK_EMPTY_T + world.PAYLOAD_T, False)[0]
    return {"phys_empty_min": te, "phys_loaded_min": tl, "loaded_rise_m": sum(L * g for L, g, _ in ld if g > 0),
            "loaded_m": sum(L for L, _, _ in ld), "empty_m": sum(L for L, _, _ in e)}


_PHYS = {}


def physics(frm, face, dest):
    key = (frm, int(face), dest)
    if key not in _PHYS:
        _PHYS[key] = route_physics(frm, face, dest)
    return _PHYS[key]


def cycle_features(e, shovel_kind, age_h):
    p = physics(e["from"], e["block"], e["dest"])
    return [p["phys_empty_min"], p["phys_loaded_min"], p["loaded_rise_m"], p["loaded_m"], p["empty_m"], e["payload_t"],
            1.0 if shovel_kind == "rope" else 0.0, 1.0 if e["dest"] == "crusher" else 0.0, e["queue_at_dispatch"], e["enroute_at_dispatch"],
            e["to_crusher_at_dispatch"], 1.0 if e["wet"] else 0.0, age_h]


def physics_cycle(e, shovel_kind):
    """The baseline: travel at the manufacturer's speed for each grade, nominal loading and dumping, no queues, no weather."""
    p = physics(e["from"], e["block"], e["dest"])
    return p["phys_empty_min"] + p["phys_loaded_min"] + world.LOAD_NOMINAL[shovel_kind] + world.DUMP_MIN[e["dest"]]


def mape(pred, y):
    return round(float(np.mean(np.abs(np.asarray(pred) - y) / y)) * 100, 2)


def train_cycle(events, kinds, ages, test_mask):
    X = np.array([cycle_features(e, kinds[e["shovel"]], ages[e["truck"]]) for e in events])
    y = np.array([e["cycle_min"] for e in events])
    model = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.06, random_state=0).fit(X[~test_mask], np.log(y[~test_mask]))
    pred = np.exp(model.predict(X[test_mask]))
    base = np.array([physics_cycle(e, kinds[e["shovel"]]) for e, t in zip(events, test_mask) if t])
    resid = np.log(y[test_mask]) - np.log(pred)
    model.resid_sd_ = float(np.std(resid))
    wet = X[test_mask][:, 11] > 0
    return model, {"mape_pct": mape(pred, y[test_mask]), "baseline_mape_pct": mape(base, y[test_mask]),
                   "mape_pct_wet": mape(pred[wet], y[test_mask][wet]) if wet.any() else None,
                   "baseline_mape_pct_wet": mape(base[wet], y[test_mask][wet]) if wet.any() else None,
                   "mae_min": round(float(np.mean(np.abs(pred - y[test_mask]))), 2), "residual_sd_log": round(model.resid_sd_, 4),
                   "train_cycles": int((~test_mask).sum()), "test_cycles": int(test_mask.sum())}


def fuel_features(e):
    p = physics(e["from"], e["block"], e["dest"])
    gross = world.TRUCK_EMPTY_T + e["payload_t"]
    idle = e["queue_load_min"] + e["load_min"] + e["queue_dump_min"] + e["dump_min"]
    return [gross * p["loaded_rise_m"], gross * p["loaded_m"], world.TRUCK_EMPTY_T * p["empty_m"], idle, 1.0 if e["wet"] else 0.0]


def train_fuel(events, test_mask):
    X = np.array([fuel_features(e) for e in events])
    y = np.array([e["fuel_l"] for e in events])
    A = np.c_[X, np.ones(len(X))]
    coef = np.linalg.lstsq(A[~test_mask], y[~test_mask], rcond=None)[0]
    pred = A[test_mask] @ coef
    return coef.tolist(), {"mape_pct": mape(pred, y[test_mask]), "litres_per_cycle": round(float(y.mean()), 1)}


def fuel_litres(coef, frm, face, dest, payload=world.PAYLOAD_T, idle_min=5.0, wet=False):
    e = {"from": frm, "block": face, "dest": dest, "payload_t": payload, "queue_load_min": idle_min, "load_min": 0, "queue_dump_min": 0, "dump_min": 0, "wet": wet}
    return float(np.dot(coef[:-1], fuel_features(e)) + coef[-1])


def uncongested(model, frm, face, dest, shovel_kind, age_h=30000.0, wet=False):
    e = {"from": frm, "block": face, "dest": dest, "payload_t": world.PAYLOAD_T * 0.985, "queue_at_dispatch": 0, "enroute_at_dispatch": 0, "to_crusher_at_dispatch": 0, "wet": wet}
    return float(np.exp(model.predict(np.array([cycle_features(e, shovel_kind, age_h)]))[0]))


# --- engine health ---------------------------------------------------------------------------------------------------------
def _health_x(w):
    return [1.0, w["duty"], w["ambient_c"] - 22, w["payload_t"] / world.PAYLOAD_T, w["speed_kmh"] / 40]


def train_anomaly(windows, breakdowns, clean_hours=4.0):
    """Per truck and sensor: a linear model of the reading on duty, air temperature, payload and speed, from windows at least
    `clean_hours` before any breakdown in the maintenance log (a precursor is never learned as normal); one trimming pass drops
    sensor glitches. Returns {truck: {sensor: (coef, sd)}}."""
    fails = {}
    for b in breakdowns:
        fails.setdefault(b["truck"], []).append(b["at_min"])
    by = {}
    for w in windows:
        if w["state"] != "working":
            continue
        if any(0 <= f - w["at_min"] <= clean_hours * 60 for f in fails.get(w["truck"], [])):
            continue
        by.setdefault(w["truck"], []).append(w)
    model = {}
    for tid, ws in by.items():
        X = np.array([_health_x(w) for w in ws])
        model[tid] = {}
        for s, _ in SENSORS:
            y = np.array([w[s] for w in ws])
            keep = np.ones(len(y), bool)
            for _ in range(2):
                coef = np.linalg.lstsq(X[keep], y[keep], rcond=None)[0]
                r = y - X @ coef
                sd = 1.4826 * np.median(np.abs(r[keep] - np.median(r[keep])))
                keep = np.abs(r) < 5 * sd
            model[tid][s] = (coef.tolist(), float(sd))
    return model


def health_scores(model, windows):
    """-> per window: directional z per sensor and the worst one; None when the truck has no normal yet."""
    out = []
    for w in windows:
        m = model.get(w["truck"])
        if w["state"] != "working" or not m:
            out.append(None)
            continue
        x = np.array(_health_x(w))
        z = {s: sign * (w[s] - float(np.dot(m[s][0], x))) / m[s][1] for s, sign in SENSORS}
        out.append(z)
    return out


def alarms(model, windows, rule="model"):
    """Windows (sorted by truck, time) -> [(truck, at_min, sensor, value)] where an alarm first fires (quiet for an hour before)."""
    out, last, run = [], {}, {}
    zs = health_scores(model, windows) if rule == "model" else [None] * len(windows)
    for w, z in zip(windows, zs):
        tid = w["truck"]
        if w["state"] != "working":
            run[tid] = 0
            continue
        if rule == "model":
            if z is None:
                continue
            s = max(z, key=z.get)
            hit = z[s] > Z_ALARM
            run[tid] = run.get(tid, 0) + 1 if hit else 0
            fire = run[tid] >= PERSIST
            val = round(z[s], 1)
        else:
            over = [s for s, sign in SENSORS if (w[s] - STATIC[s]) * sign > 0]
            fire, s = bool(over), (over[0] if over else None)
            val = w[s] if s else None
        if fire and w["at_min"] - last.get(tid, -1e9) > 60:
            out.append((tid, w["at_min"], s, val))
        if fire:
            last[tid] = w["at_min"]
    return out


def score_alarms(found, breakdowns, windows, lead_max=180.0):
    """Detected: an alarm within 3 h before a precursor breakdown. False: any alarm not within 3 h before a breakdown."""
    fails = [b for b in breakdowns if b["failure"] in world.PRECURSOR_MIN]
    det, leads = 0, []
    for b in fails:
        hits = [a for a in found if a[0] == b["truck"] and 0 < b["at_min"] - a[1] <= lead_max]
        if hits:
            det += 1
            leads.append(b["at_min"] - min(h[1] for h in hits))
    false = [a for a in found if not any(a[0] == b["truck"] and 0 <= b["at_min"] - a[1] <= lead_max for b in breakdowns)]
    hours = sum(1 for w in windows if w["state"] == "working") / 6
    return {"precursor_failures": len(fails), "detected": det, "median_lead_min": float(np.median(leads)) if leads else None,
            "false_alarms": len(false), "false_per_1000_truck_hours": round(1000 * len(false) / max(hours, 1), 2), "truck_hours": round(hours)}


# --- plant throughput forecast --------------------------------------------------------------------------------------------
BIN_MIX = 0.5            # the surge bin mixes: the hardness the mill sees is a blend of this hour's feed and what was there


def smooth_bwi(values, prev=None):
    out = []
    for v in values:
        prev = v if prev is None else BIN_MIX * prev + (1 - BIN_MIX) * v
        out.append(prev)
    return out


def predict_plant(model, supply_t, bwi_s):
    """Tonnes milled in an hour: what the bin and the feed can supply, or the mill's rate at the estimated hardness, scaled by the
    fitted factor (availability and the hardness estimate's bias), whichever is less."""
    return float(min(supply_t, model["scale"] * world.mill_tph(bwi_s)))


def train_plant(rows, test_mask):
    """rows: [{feed_tph, bin_start_t, bwi_s, processed_t}]. One parameter, fitted on the training hours the mill was not starved."""
    y = np.array([r["processed_t"] for r in rows])
    cap = np.array([world.mill_tph(r["bwi_s"]) for r in rows])
    supply = np.array([r["feed_tph"] + r["bin_start_t"] for r in rows])
    fed = (~test_mask) & (supply > 1.2 * cap)
    model = {"scale": float(np.median(y[fed] / cap[fed])) if fed.any() else 1.0}
    pred = np.array([predict_plant(model, s_, r["bwi_s"]) for s_, r in zip(supply, rows)])[test_mask]
    idx = np.nonzero(test_mask)[0]
    base = np.array([y[max(0, i - 12):i].mean() for i in idx])
    return model, {"mae_tph": round(float(np.mean(np.abs(pred - y[test_mask]))), 1), "baseline_mae_tph": round(float(np.mean(np.abs(base - y[test_mask]))), 1),
                   "mean_tph": round(float(y[test_mask].mean()), 1), "test_hours": int(test_mask.sum()), "scale": round(model["scale"], 3)}


# --- economics ----------------------------------------------------------------------------------------------------------------
def fuel_cost_per_t(coef, face, dest):
    return fuel_litres(coef, dest, face, dest) / world.PAYLOAD_T * world.FUEL_PRICE


def stock_value(tonnes, cu, as_, factor=STOCK_FACTOR):
    return factor * tonnes * world.value_per_t(cu, as_)


# --- shovel throughput ----------------------------------------------------------------------------------------------------
def shovel_curve(travel_min, load_min, rate_tph, n_max):
    """Tonnes an hour from n trucks on one shovel: the machine-interference (finite-source) queue, capped at the dig rate."""
    rho = load_min / max(travel_min, 1e-6)
    out = [0.0]
    for n in range(1, n_max + 1):
        terms = [1.0]
        for k in range(1, n + 1):
            terms.append(terms[-1] * (n - k + 1) * rho)
        p0 = 1 / sum(terms)
        out.append(min(rate_tph, 60 * world.PAYLOAD_T * (1 - p0) / load_min))
    return out


# --- dispatch ---------------------------------------------------------------------------------------------------------------
def optimize_dispatch(inp, time_limit_s=10.0, z=1.0, fix=None):
    """The dispatch MIP. inp: {"horizon_h", "shovels": [{id, rate_tph, load_min, mix: {HG, LG, W}, src: {cls: (cu, cu_sd, as, as_sd, bwi)},
    travel: {dest: minutes (cycle less loading)}, fuel_per_t: {dest: $/t}}], "groups": [{"shovel": current or None, "trucks": [ids]}],
    "stock": {k: {tonnes, cu, cu_sd, as, as_sd, bwi}}, "mill_tph"} -> plan with targets, routes, reclaim, trucks, objective and gap."""
    t_start = time.perf_counter()
    S = inp["shovels"]
    H = inp["horizon_h"]
    n_trucks = sum(len(g["trucks"]) for g in inp["groups"])
    solver = pywraplp.Solver.CreateSolver("SCIP")
    inf = solver.infinity()
    lo, hi = world.TARGET_CU - world.TOL_CU, world.TARGET_CU + world.TOL_CU
    m = {(gi, s["id"]): solver.IntVar(0, len(g["trucks"]), f"m_{gi}_{s['id']}") for gi, g in enumerate(inp["groups"]) for s in S}
    for gi, g in enumerate(inp["groups"]):
        solver.Add(solver.Sum([m[(gi, s["id"])] for s in S]) <= len(g["trucks"]))
    obj = []
    blend_lo, blend_hi, blend_as, feed = [], [], [], []
    curves, p, n = {}, {}, {}
    for s in S:
        sid = s["id"]
        n[sid] = solver.Sum([m[(gi, sid)] for gi in range(len(inp["groups"]))])
        p[sid] = solver.NumVar(0, s["rate_tph"], f"p_{sid}")
        mix_travel = sum(s["mix"][c] * s["travel"][d] for c, d in (("HG", "crusher"), ("LG", "lg"), ("W", "dump")))
        cv = shovel_curve(mix_travel, s["load_min"], s["rate_tph"], min(n_trucks, 16))
        curves[sid] = cv
        for k in range(len(cv) - 1):
            solver.Add(p[sid] <= cv[k] + (cv[k + 1] - cv[k]) * (n[sid] - k))
        solver.Add(n[sid] <= len(cv) - 1)
        short = solver.NumVar(0, inf, f"short_{sid}")
        solver.Add(p[sid] + short >= 0.5 * s["rate_tph"] * (1 if s.get("required", True) else 0))
        obj.append(-25.0 * short)                                          # the mine plan's movement: a shovel below half rate is a deferral
        obj.append(-s["mix"]["W"] * s["fuel_per_t"]["dump"] * p[sid])
        for c, dests in (("HG", ("crusher", "hg")), ("LG", ("crusher", "lg"))):
            if s["mix"][c] <= 1e-6:
                continue
            cu, cu_sd, as_, as_sd, _ = s["src"][c]
            v = world.value_per_t(cu, as_)
            ys = {d: solver.BoolVar(f"y_{sid}_{c}_{d}") for d in dests}
            if fix and sid in fix:
                solver.Add(ys[fix[sid][c]] == 1)
            solver.Add(solver.Sum(ys.values()) == 1)
            qs = {d: solver.NumVar(0, s["rate_tph"], f"q_{sid}_{c}_{d}") for d in dests}
            solver.Add(solver.Sum(qs.values()) == s["mix"][c] * p[sid])
            for d in dests:
                solver.Add(qs[d] <= s["rate_tph"] * ys[d])
                gain = v if d == "crusher" else STOCK_FACTOR * v
                obj.append((gain - s["fuel_per_t"][d]) * qs[d])
            s.setdefault("_q", {})[c] = (qs, ys)
            q = qs["crusher"]
            feed.append(q)
            blend_lo.append((cu - z * cu_sd - lo) * q)
            blend_hi.append((cu + z * cu_sd - hi) * q)
            blend_as.append((as_ + z * as_sd - world.AS_LIMIT) * q)
    r = {}
    for k, st in inp["stock"].items():
        r[k] = solver.NumVar(0, min(world.LOADER_TPH, st["tonnes"] / H), f"r_{k}")
        v = world.value_per_t(st["cu"], st["as"])
        obj.append(((1 - STOCK_FACTOR) * v - world.REHANDLE) * r[k])
        feed.append(r[k])
        blend_lo.append((st["cu"] - z * st["cu_sd"] - lo) * r[k])
        blend_hi.append((st["cu"] + z * st["cu_sd"] - hi) * r[k])
        blend_as.append((st["as"] + z * st["as_sd"] - world.AS_LIMIT) * r[k])
    solver.Add(solver.Sum(r.values()) <= world.LOADER_TPH)
    solver.Add(solver.Sum(feed) <= inp["mill_tph"])
    if inp.get("waste_tph_min"):                     # stripping is held at the rate the plan in force would manage: no gain from deferring it
        strip_short = solver.NumVar(0, inf, "strip_short")
        solver.Add(solver.Sum([s["mix"]["W"] * p[s["id"]] for s in S]) + strip_short >= inp["waste_tph_min"])
        obj.append(-40.0 * strip_short)
    slack = {k: solver.NumVar(0, inf, f"slack_{k}") for k in ("lo", "hi", "as")}
    solver.Add(solver.Sum(blend_lo) + slack["lo"] >= 0)
    solver.Add(solver.Sum(blend_hi) - slack["hi"] <= 0)
    solver.Add(solver.Sum(blend_as) - 0.01 * slack["as"] <= 0)
    obj += [-60.0 * slack["lo"], -60.0 * slack["hi"], -0.6 * slack["as"]]          # $ per (t/h x %Cu) and per (t/h x 100 ppm) outside
    for gi, g in enumerate(inp["groups"]):
        for s in S:
            if g["shovel"] != s["id"]:
                obj.append(-20.0 * m[(gi, s["id"])])                                # a reassignment costs a little: no churn for nothing
    solver.Maximize(solver.Sum(obj))
    solver.SetTimeLimit(int(time_limit_s * 1000))
    solver.SetSolverSpecificParametersAsString("limits/gap = 0.005\n")
    status = solver.Solve()
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        raise RuntimeError("dispatch model infeasible")
    best, bound = solver.Objective().Value(), solver.Objective().BestBound()
    targets, routes, trucks_per, assign = {}, {}, {}, {}
    for s in S:
        sid = s["id"]
        targets[sid] = round(p[sid].solution_value(), 1)
        trucks_per[sid] = int(round(n[sid].solution_value()))
        routes[sid] = {"W": "dump"}
        for c in ("HG", "LG"):
            if c in s.get("_q", {}):
                routes[sid][c] = next(d for d, y in s["_q"][c][1].items() if y.solution_value() > 0.5)
            else:
                routes[sid][c] = "crusher" if c == "HG" else "lg"
        s.pop("_q", None)
    for sid, r_ in routes.items():                   # ore sent to the crusher overflows to its stockpile when the bin is full, rather than queue
        if r_.get("HG") == "crusher":
            r_["HG"] = "crusher|hg"
    for gi, g in enumerate(inp["groups"]):
        pool = list(g["trucks"])
        order = sorted(S, key=lambda s: s["id"] != g["shovel"])                     # trucks stay where they are first
        for s in order:
            for _ in range(int(round(m[(gi, s["id"])].solution_value()))):
                assign[pool.pop(0)] = s["id"]
    reclaim = {k: round(v.solution_value(), 1) for k, v in r.items()}
    return {"targets": targets, "trucks": trucks_per, "route": routes, "reclaim_tph": reclaim, "assign": assign,
            "objective_per_h": round(best, 1), "bound_per_h": round(bound, 1), "gap": round(abs(bound - best) / max(abs(best), 1e-6), 5),
            "solve_ms": round((time.perf_counter() - t_start) * 1000, 1), "variables": solver.NumVariables(), "constraints": solver.NumConstraints(),
            "slack": {k: round(v.solution_value(), 2) for k, v in slack.items()}, "z": z, "trucks_available": n_trucks,
            "curves": {k: [round(x) for x in v] for k, v in curves.items()}, "solver": "SCIP via OR-Tools"}


def plan_rates_fixed(inp, assign):
    """Expected dig rate per shovel when trucks stay where a fixed plan put them (the queueing curve at the trucks it has)."""
    n = {}
    for sid in assign.values():
        n[sid] = n.get(sid, 0) + 1
    out = {}
    for s in inp["shovels"]:
        mix_t = sum(s["mix"][c] * s["travel"][d] for c, d in (("HG", "crusher"), ("LG", "lg"), ("W", "dump")))
        k = n.get(s["id"], 0)
        out[s["id"]] = shovel_curve(mix_t, s["load_min"], s["rate_tph"], max(k, 1))[k]
    return out


def waste_floor(inp, assign):
    rates = plan_rates_fixed(inp, assign)
    return sum(s["mix"]["W"] * rates[s["id"]] for s in inp["shovels"])


def heuristic_dispatch(inp, mode="fixed"):
    """The baseline: trucks split in proportion to what each shovel needs to reach its dig rate (the match factor), cut-off
    routing (HG to the crusher, LG to its stockpile, waste to the dump), proportional reclaim."""
    S = inp["shovels"]
    trucks = [t for g in inp["groups"] for t in g["trucks"]]
    need = np.array([s["rate_tph"] * (s["load_min"] + sum(s["mix"][c] * s["travel"][d] for c, d in (("HG", "crusher"), ("LG", "lg"), ("W", "dump"))))
                     / (60 * world.PAYLOAD_T) for s in S])
    share = need / need.sum() * len(trucks)
    k = np.floor(share).astype(int)
    for i in np.argsort(-(share - k))[: len(trucks) - k.sum()]:
        k[i] += 1
    assign, it = {}, iter(trucks)
    for s, kk in zip(S, k):
        for _ in range(kk):
            assign[next(it)] = s["id"]
    return {"mode": mode, "assign": assign, "trucks": {s["id"]: int(kk) for s, kk in zip(S, k)}, "targets": {s["id"]: float(s["rate_tph"]) for s in S},
            "route": {s["id"]: {"HG": "crusher|hg", "LG": "lg", "W": "dump"} for s in S}, "reclaim": {"mode": "proportional"}}


# --- blend --------------------------------------------------------------------------------------------------------------------
def pit_feed_by_hour(shovels, targets, routes, est, hours, t_from_h=0.0):
    """Walk each shovel's sequence at its target rate: tonnes per hour per (shovel, class) routed to the crusher, with the
    estimator's grade and spread for those blocks. est: {block: (cu, cu_sd, as, as_sd, bwi, cls)}."""
    out = [dict() for _ in range(hours)]
    for s in shovels:
        rate = targets.get(s["id"], 0.0)
        if rate <= 0:
            continue
        pos, rem = s["pos"], s["remaining"]
        for h in range(hours):
            need = rate
            while need > 1e-6 and pos < len(s["seq"]):
                b = s["seq"][pos]
                take = min(need, rem)
                g = est[b]
                cu, cu_sd, as_, as_sd, bwi, cls = g["cu"], g["cu_sd"], g["as"], g["as_sd"], g["bwi"], g["cls"]
                d = routes[s["id"]].get(cls, "dump")
                if d.startswith("crusher"):
                    acc = out[h].setdefault(f"{s['id']}/{cls}", [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
                    for i, v in enumerate((1.0, cu, cu_sd, as_, as_sd, bwi)):
                        acc[i] += take * v if i else take
                need -= take
                rem -= take
                if rem <= 1e-6:
                    pos += 1
                    rem = world.BLOCK_T
    return [{k: (v[0], v[1] / v[0], v[2] / v[0], v[3] / v[0], v[4] / v[0], v[5] / v[0]) for k, v in h.items()} for h in out]


def solve_blend(pit, stock, mill_tph, z=1.28, unit=50.0, min_tph=300.0, time_limit_s=10.0):
    """Hourly loader reclaim from each stockpile (whole 50-t loads, at least 300 t/h when a loader works a pile) and how much
    of each pit source goes to the crusher, holding the feed inside the grade window and under the arsenic limit with the
    sources' estimation spread (one-sided z). pit: [{source: (t/h, cu, cu_sd, as, as_sd, bwi)}] per hour."""
    t0 = time.perf_counter()
    H = len(pit)
    solver = pywraplp.Solver.CreateSolver("SCIP")
    inf = solver.infinity()
    lo, hi = world.TARGET_CU - world.TOL_CU, world.TARGET_CU + world.TOL_CU
    obj, R, X, slacks = [], {}, {}, []
    for h in range(H):
        feed, blo, bhi, bas = [], [], [], []
        for src, (tph, cu, cu_sd, as_, as_sd, _) in pit[h].items():
            x = solver.NumVar(0, tph, f"x_{h}_{src}")
            X[(h, src)] = x
            v = world.value_per_t(cu, as_)
            obj.append(v * x + STOCK_FACTOR * v * (tph - x))
            feed.append(x)
            blo.append((cu - z * cu_sd - lo) * x)
            bhi.append((cu + z * cu_sd - hi) * x)
            bas.append((as_ + z * as_sd - world.AS_LIMIT) * x)
        load = []
        for k, st in stock.items():
            u = solver.IntVar(0, int(world.LOADER_TPH // unit), f"u_{k}_{h}")
            w = solver.BoolVar(f"w_{k}_{h}")
            r = unit * u
            solver.Add(r <= world.LOADER_TPH * w)
            solver.Add(r >= min_tph * w)
            R[(k, h)] = u
            load.append(r)
            v = world.value_per_t(st["cu"], st["as"])
            obj.append(((1 - STOCK_FACTOR) * v - world.REHANDLE) * r)
            feed.append(r)
            blo.append((st["cu"] - z * st["cu_sd"] - lo) * r)
            bhi.append((st["cu"] + z * st["cu_sd"] - hi) * r)
            bas.append((st["as"] + z * st["as_sd"] - world.AS_LIMIT) * r)
        solver.Add(solver.Sum(load) <= world.LOADER_TPH)
        solver.Add(solver.Sum(feed) <= mill_tph[h])
        sl = [solver.NumVar(0, inf, f"s{i}_{h}") for i in range(3)]
        solver.Add(solver.Sum(blo) + sl[0] >= 0)
        solver.Add(solver.Sum(bhi) - sl[1] <= 0)
        solver.Add(solver.Sum(bas) - 0.01 * sl[2] <= 0)
        obj += [-60.0 * sl[0], -60.0 * sl[1], -0.6 * sl[2]]
        slacks.append(sl)
    for k, st in stock.items():
        solver.Add(solver.Sum([unit * R[(k, h)] for h in range(H)]) <= st["tonnes"])
    solver.Maximize(solver.Sum(obj))
    solver.SetTimeLimit(int(time_limit_s * 1000))
    status = solver.Solve()
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        raise RuntimeError("blend model infeasible")
    best, bound = solver.Objective().Value(), solver.Objective().BestBound()
    hours = []
    for h in range(H):
        rec = {k: unit * R[(k, h)].solution_value() for k in stock}
        pits = {src: X[(h, src)].solution_value() for src in pit[h]}
        hours.append({"hour": h, "reclaim_tph": {k: round(v) for k, v in rec.items()}, "pit_tph": {k: round(v) for k, v in pits.items()},
                      "diverted_tph": {k: round(pit[h][k][0] - v) for k, v in pits.items() if pit[h][k][0] - v > 1},
                      **blend_grade(pit[h], pits, stock, rec, z), "outside_window": [round(sl.solution_value(), 2) for sl in slacks[h]]})
    return {"hours": hours, "objective": round(best), "gap": round(abs(bound - best) / max(abs(best), 1), 5), "solve_ms": round((time.perf_counter() - t0) * 1000, 1),
            "z": z, "window": [round(lo, 3), round(hi, 3)], "as_limit": world.AS_LIMIT, "solver": "SCIP via OR-Tools"}


def blend_grade(pit_h, pits, stock, rec, z):
    t = cu = sd = as_ = asd = bwi = 0.0
    for src, x in pits.items():
        _, c, cs, a, asg, bw = pit_h[src]
        t += x; cu += x * c; sd += x * cs; as_ += x * a; asd += x * asg; bwi += x * bw
    for k, x in rec.items():
        st = stock[k]
        t += x; cu += x * st["cu"]; sd += x * st["cu_sd"]; as_ += x * st["as"]; asd += x * st["as_sd"]; bwi += x * st["bwi"]
    if t <= 0:
        return {"feed_tph": 0, "cu": None, "cu_band": None, "as": None, "bwi": None}
    return {"feed_tph": round(t), "cu": round(cu / t, 4), "cu_band": [round((cu - z * sd) / t, 4), round((cu + z * sd) / t, 4)],
            "as": round(as_ / t, 1), "as_high": round((as_ + z * asd) / t, 1), "bwi": round(bwi / t, 2)}


def proportional_blend(pit, stock, mill_tph):
    """The baseline: all pit ore to the crusher, the rest of the mill's capacity from the stockpiles in proportion to their tonnes."""
    tot = sum(st["tonnes"] for st in stock.values())
    hours = []
    for h, ph in enumerate(pit):
        pits = {src: v[0] for src, v in ph.items()}
        room = max(0.0, mill_tph[h] - sum(pits.values()))
        rec = {k: min(world.LOADER_TPH, room) * st["tonnes"] / tot for k, st in stock.items()}
        hours.append({"hour": h, "reclaim_tph": {k: round(v) for k, v in rec.items()}, "pit_tph": {k: round(v) for k, v in pits.items()}, **blend_grade(ph, pits, stock, rec, 1.28)})
    return {"hours": hours}


# --- what the optimisers and the twin are given -----------------------------------------------------------------------------
def block_estimates(pred, blocks):
    """GradeModel.predict output for `blocks` -> {block: {cu, cu_mu, cu_s, cu_sd, as, as_sd, bwi, cls}}."""
    out = {}
    for n, b in enumerate(blocks):
        cu, s = float(pred["cu"][n]), float(pred["cu_s"][n])
        out[int(b)] = {"cu": cu, "cu_mu": float(pred["cu_mu"][n]), "cu_s": s, "cu_sd": cu * math.sqrt(math.exp(s * s) - 1), "as": float(pred["as"][n]),
                       "as_sd": float(pred["as"][n]) * math.sqrt(math.exp(float(pred["as_s"][n]) ** 2) - 1), "bwi": float(pred["bwi"][n]), "cls": str(classify(cu))}
    return out


class Travel:
    """Uncongested travel from the cycle-time model, split into the empty leg and the loaded leg (with the dump) in the proportions
    the physics gives; loading is the shovel's own measured time. Queues are left to the twin's simulation."""

    def __init__(self, model, shovel_kind, load_min, wet=False):
        self.model, self.kind, self.load, self.wet, self.cache = model, shovel_kind, load_min, wet, {}

    def split(self, frm, face, dest, shovel=None):
        key = (frm, int(face), dest)
        if key not in self.cache:
            p = physics(frm, face, dest)
            kind = self.kind.get(shovel) or self.kind.get(self._shovel_of(face)) or "hydraulic"
            u = uncongested(self.model, frm, face, dest, kind, wet=self.wet)
            load = self.load.get(shovel) or world.LOAD_NOMINAL[kind]
            trav = max(1.0, u - load)
            share = p["phys_empty_min"] / (p["phys_empty_min"] + p["phys_loaded_min"] + world.DUMP_MIN[dest])
            self.cache[key] = (trav * share, trav * (1 - share))
        return self.cache[key]

    def _shovel_of(self, face):
        return getattr(self, "face_shovel", {}).get(int(face))


def horizon_blocks(seq, pos, remaining, rate_tph, hours):
    """[(block, tonnes)] a shovel digs in the next hours at its rate."""
    need, out = rate_tph * hours, []
    while need > 1e-6 and pos < len(seq):
        take = min(need, remaining)
        out.append((seq[pos], take))
        need -= take
        pos += 1
        remaining = world.BLOCK_T
    return out


def dispatch_inputs(shovels, est, travel, fuel_coef, groups, stock, horizon_h, required=None):
    """shovels: [{id, kind, rate_tph, load_min, seq, pos, remaining}] -> the MIP's input."""
    S = []
    for s in shovels:
        blocks = horizon_blocks(s["seq"], s["pos"], s["remaining"], s["rate_tph"], horizon_h)
        tot = sum(t for _, t in blocks) or 1.0
        mix, src = {"HG": 0.0, "LG": 0.0, "W": 0.0}, {}
        for c in mix:
            bl = [(b, t) for b, t in blocks if est[b]["cls"] == c]
            ct = sum(t for _, t in bl)
            mix[c] = ct / tot
            if ct:
                src[c] = tuple(sum(t * est[b][k] for b, t in bl) / ct for k in ("cu", "cu_sd", "as", "as_sd", "bwi"))
        face = s["seq"][min(s["pos"], len(s["seq"]) - 1)]
        trav = {d: sum(travel.split(d, face, d, s["id"])) for d in world.DESTS}
        S.append({"id": s["id"], "rate_tph": s["rate_tph"], "load_min": s["load_min"], "mix": mix, "src": src, "travel": trav,
                  "fuel_per_t": {d: fuel_litres(fuel_coef, d, face, d) / world.PAYLOAD_T * world.FUEL_PRICE for d in world.DESTS},
                  "required": True if required is None else s["id"] in required})
    bwi = [v[4] for s in S for c, v in s["src"].items() if c == "HG"] or [world.MILL_BASE_BWI]
    return {"horizon_h": horizon_h, "shovels": S, "groups": groups, "stock": stock, "mill_tph": world.mill_tph(float(np.mean(bwi)))}


# --- the twin -----------------------------------------------------------------------------------------------------------------
def twin(ctx, plans, reps=20, seed=0):
    """The service's simulation of the rest of a shift under each plan, with common random numbers: replication r draws the same
    block grades, cycle noise and loading times whichever plan runs. ctx: {"minutes", "trucks": [(id, last node)], "shovels":
    [{id, kind, load_min, seq, pos, remaining}], "est": {block: (cu_mu, cu_s, as, bwi, cls)}, "travel": fn(frm, face, dest) -> minutes
    empty+loaded uncongested, "fuel": fn(frm, face, dest, payload, idle) -> litres, "resid_sd", "stock": {k: [t, cu, as, bwi]}, "bin": [t, cu, as, bwi]}.
    Returns per plan: per-replication KPIs, their mean and 10th/90th percentiles, and paired differences against the first plan."""
    runs = {name: [_twin_once(ctx, plan, seed, r) for r in range(reps)] for name, plan in plans.items()}
    names = list(plans)
    keys = ["moved_t", "ore_to_crusher_t", "processed_t", "reclaimed_t", "copper_t", "revenue_usd", "fuel_l", "net_value_usd", "hours_in_window"]
    out = {}
    for name in names:
        rs = runs[name]
        out[name] = {k: {"mean": round(float(np.mean([r[k] for r in rs])), 1), "p10": round(float(np.percentile([r[k] for r in rs], 10)), 1),
                         "p90": round(float(np.percentile([r[k] for r in rs], 90)), 1)} for k in keys}
        out[name]["hourly_feed_cu"] = [round(float(np.mean([r["hourly"][h]["cu"] for r in rs if r["hourly"][h]["cu"] is not None] or [0])), 4) for h in range(len(rs[0]["hourly"]))]
        out[name]["hourly_processed_t"] = [round(float(np.mean([r["hourly"][h]["t"] for r in rs])), 1) for h in range(len(rs[0]["hourly"]))]
        out[name]["hourly_delivered_t"] = [round(float(np.mean([r["hourly"][h]["delivered"] for r in rs])), 1) for h in range(len(rs[0]["hourly"]))]
        if name != names[0]:
            d = {k: [a[k] - b[k] for a, b in zip(rs, runs[names[0]])] for k in keys}
            out[name]["vs_" + names[0]] = {k: {"mean": round(float(np.mean(v)), 1), "p10": round(float(np.percentile(v, 10)), 1), "p90": round(float(np.percentile(v, 90)), 1),
                                                "better_in": round(float(np.mean(np.array(v) * (-1 if k == "fuel_l" else 1) > 0)), 3)} for k, v in d.items()}
    return out


def _twin_once(ctx, plan, seed, rep):
    minutes = ctx["minutes"]
    shovels = {s["id"]: s for s in ctx["shovels"]}
    sh = {s["id"]: {"pos": s["pos"], "remaining": s["remaining"], "queue": [], "busy": False, "loads": 0, "loaded_t": 0.0, "enroute": 0} for s in ctx["shovels"]}
    grades = {}

    def grade(b):
        if b not in grades:
            g = ctx["est"][b]
            r = np.random.default_rng([seed, rep, 1, b])
            grades[b] = (float(np.exp(g["cu_mu"] + g["cu_s"] * r.normal())), g["as"], g["bwi"])
        return grades[b]
    stock = {k: list(v) for k, v in ctx["stock"].items()}
    binv = list(ctx["bin"])                        # [t, cu, as, bwi] as tonnage-weighted means
    ev, seq = [], [0]

    def push(t, kind, *a):
        seq[0] += 1
        heapq.heappush(ev, (t, seq[0], kind, a))
    T = {}
    for n, (tid, node) in enumerate(ctx["trucks"]):
        T[tid] = {"k": 0, "node": node or "goline"}
        push(float(np.random.default_rng([seed, rep, 2, n]).uniform(0, 12)), "dispatch", tid)
    for mm in range(0, minutes, 5):
        push(float(mm), "tick")
    tot = {"moved_t": 0.0, "ore_to_crusher_t": 0.0, "processed_t": 0.0, "reclaimed_t": 0.0, "copper_t": 0.0, "revenue_usd": 0.0, "fuel_l": 0.0, "value": 0.0}
    hourly = [{"t": 0.0, "cu": 0.0, "delivered": 0.0} for _ in range(int(math.ceil(minutes / 60)))]
    stock0 = {k: stock_value(v[0], v[1], v[2]) for k, v in stock.items()}
    crusher_q, cr = [], {"busy": False}

    def face(s):
        sq = shovels[s]["seq"]
        return sq[min(sh[s]["pos"], len(sq) - 1)]

    def choose(tid, t):
        if plan["mode"] == "fixed":
            return plan["assign"].get(tid)
        best, score = None, None
        for s in sh:
            tgt = plan["targets"].get(s, 0)
            if tgt <= 0:
                continue
            tt = ctx["travel_split"](T[tid]["node"], face(s), "crusher")[0]
            due = tgt * (t + tt) / 60
            done = sh[s]["loaded_t"] + (sh[s]["enroute"] + len(sh[s]["queue"])) * world.PAYLOAD_T
            val = (due - done) / tgt - 0.002 * tt
            if score is None or val > score:
                best, score = s, val
        return best

    def start_load(s, t):
        if sh[s]["queue"]:
            tid = sh[s]["queue"].pop(0)
            sh[s]["busy"] = True
            r = np.random.default_rng([seed, rep, 3, int(s[1:]), sh[s]["loads"]])
            sh[s]["loads"] += 1
            lt = shovels[s]["load_min"] * float(r.lognormal(0, 0.06))
            T[tid]["c"]["idle"] += lt + (t - T[tid]["c"]["arrived"])
            push(t + lt, "loaded", tid, s)

    def try_crusher(t):
        while crusher_q and not cr["busy"] and binv[0] + world.PAYLOAD_T <= world.BIN_T:
            tid, arr = crusher_q.pop(0)
            cr["busy"] = True
            T[tid]["c"]["idle"] += t - arr + 1.0
            push(t + world.DUMP_MIN["crusher"], "dumped", tid)

    def mix(acc, t_, cu, as_, bwi):
        new = acc[0] + t_
        if new > 0:
            acc[1:] = [(acc[1] * acc[0] + cu * t_) / new, (acc[2] * acc[0] + as_ * t_) / new, (acc[3] * acc[0] + bwi * t_) / new]
        acc[0] = new
    while ev:
        t, _, kind, a = heapq.heappop(ev)
        if t >= minutes:
            break
        if kind == "tick":
            h = int(t // 60)
            rc = plan.get("reclaim", {"mode": "proportional"})
            if rc["mode"] == "schedule":
                rates = rc["hours"][h] if h < len(rc["hours"]) else {}
            else:
                tt = sum(v[0] for v in stock.values())
                rates = {k: world.LOADER_TPH * v[0] / tt for k, v in stock.items()} if binv[0] < 0.6 * world.BIN_T and tt > 0 else {}
            for k, rate in rates.items():
                take = min(rate * 5 / 60, stock[k][0], max(0.0, 0.92 * world.BIN_T - binv[0]))
                if take > 0:
                    stock[k][0] -= take
                    mix(binv, take, stock[k][1], stock[k][2], stock[k][3])
                    tot["reclaimed_t"] += take
            if binv[0] > 1e-6:
                proc = min(binv[0], world.mill_tph(binv[3]) * 5 / 60)
                binv[0] -= proc
                tot["processed_t"] += proc
                tot["copper_t"] += proc * binv[1] / 100 * world.recovery(binv[1])
                tot["revenue_usd"] += proc * binv[1] / 100 * world.recovery(binv[1]) * world.PRICE
                tot["value"] += proc * world.value_per_t(binv[1], binv[2])
                hourly[h]["t"] += proc
                hourly[h]["cu"] += proc * binv[1]
            try_crusher(t)
            continue
        tid = a[0]
        if kind == "dispatch":
            s = choose(tid, t)
            if s is None:
                continue
            r = np.random.default_rng([seed, rep, 4, int(tid[1:]), T[tid]["k"]])
            e_min, _ = ctx["travel_split"](T[tid]["node"], face(s), "crusher")
            e_min *= float(r.lognormal(0, ctx["resid_sd"]))
            T[tid]["c"] = {"s": s, "from": T[tid]["node"], "noise": float(r.lognormal(0, ctx["resid_sd"])), "idle": 0.0}
            sh[s]["enroute"] += 1
            push(t + e_min, "arrive", tid, s)
        elif kind == "arrive":
            s = a[1]
            sh[s]["enroute"] -= 1
            T[tid]["c"]["arrived"] = t
            sh[s]["queue"].append(tid)
            if not sh[s]["busy"]:
                start_load(s, t)
        elif kind == "loaded":
            s = a[1]
            c = T[tid]["c"]
            b = face(s)
            cls = plan["block_class"].get(str(b), ctx["est"][b]["cls"])
            dest = plan["route"].get(s, {}).get(cls, "dump" if cls == "W" else "lg")
            if dest == "crusher|hg":
                dest = "hg" if binv[0] > 0.9 * world.BIN_T or len(crusher_q) >= 3 else "crusher"
            c.update(b=b, dest=dest, grade=grade(b))
            sh[s]["remaining"] -= world.PAYLOAD_T
            sh[s]["loaded_t"] += world.PAYLOAD_T
            if sh[s]["remaining"] <= 0:
                sh[s]["pos"] += 1
                sh[s]["remaining"] += world.BLOCK_T
            sh[s]["busy"] = False
            start_load(s, t)
            _, l_min = ctx["travel_split"](c["from"], b, dest)
            push(t + l_min * c["noise"], "at_dest", tid)
        elif kind == "at_dest":
            c = T[tid]["c"]
            if c["dest"] == "crusher":
                crusher_q.append((tid, t))
                try_crusher(t)
            else:
                c["idle"] += world.DUMP_MIN[c["dest"]]
                push(t + world.DUMP_MIN[c["dest"]], "dumped", tid)
        elif kind == "dumped":
            c = T[tid]["c"]
            cu, as_, bwi = c["grade"]
            if c["dest"] == "crusher":
                cr["busy"] = False
                mix(binv, world.PAYLOAD_T, cu, as_, bwi)
                tot["ore_to_crusher_t"] += world.PAYLOAD_T
                hourly[min(int(t // 60), len(hourly) - 1)]["delivered"] += world.PAYLOAD_T
            elif c["dest"] in stock:
                mix(stock[c["dest"]], world.PAYLOAD_T, cu, as_, bwi)
            tot["moved_t"] += world.PAYLOAD_T
            tot["fuel_l"] += ctx["fuel"](c["from"], c["b"], c["dest"], world.PAYLOAD_T, c["idle"])
            T[tid]["k"] += 1
            T[tid]["node"] = c["dest"]
            push(t, "dispatch", tid)
            if c["dest"] == "crusher":
                try_crusher(t)
    d_stock = sum(stock_value(v[0], v[1], v[2]) - stock0[k] for k, v in stock.items())
    d_bin = (binv[0] - ctx["bin"][0]) * world.value_per_t(binv[1], binv[2])
    lo, hi = world.TARGET_CU - world.TOL_CU, world.TARGET_CU + world.TOL_CU
    hrs = [{"t": h["t"], "cu": h["cu"] / h["t"] if h["t"] > 0 else None, "delivered": h["delivered"]} for h in hourly]
    tot["hours_in_window"] = sum(1 for h in hrs if h["cu"] is not None and lo <= h["cu"] <= hi)
    tot["net_value_usd"] = tot["value"] - tot["fuel_l"] * world.FUEL_PRICE - tot["reclaimed_t"] * world.REHANDLE + d_stock + d_bin
    tot["hourly"] = hrs
    return tot


def shift_value(plant_hours, haul, stock_before, stock_after, bin_before, bin_after, factor=STOCK_FACTOR):
    """The economic objective of a shift as it happened (truth, for the evaluation and the demo's check): mill value less fuel and
    rehandle, plus the change in what the stockpiles and the bin are worth."""
    val = sum(h["truth"]["value"] for h in plant_hours)
    fuel = sum(e["fuel_l"] for e in haul)
    rec = sum(h["reclaim_t"] for h in plant_hours)

    def sv(acc):
        return stock_value(acc[0], acc[1] / acc[0], acc[2] / acc[0], factor) if acc[0] > 0 else 0.0
    d_stock = sum(sv(stock_after[k]) - sv(stock_before[k]) for k in stock_before)
    d_bin = (bin_after[0] - bin_before[0]) * world.value_per_t(bin_after[1] / max(bin_after[0], 1), bin_after[2] / max(bin_after[0], 1))
    return {"moved_t": round(sum(e["payload_t"] for e in haul)), "ore_to_crusher_t": round(sum(e["payload_t"] for e in haul if e["dest"] == "crusher")),
            "processed_t": round(sum(h["processed_t"] for h in plant_hours)), "reclaimed_t": round(rec), "copper_t": round(sum(h["truth"]["copper_t"] for h in plant_hours), 1),
            "revenue_usd": round(sum(h["truth"]["copper_t"] for h in plant_hours) * world.PRICE), "fuel_l": round(fuel),
            "net_value_usd": round(val - fuel * world.FUEL_PRICE - rec * world.REHANDLE + d_stock + d_bin),
            "hours_in_window": sum(1 for h in plant_hours if h["truth"]["feed_cu"] is not None and abs(h["truth"]["feed_cu"] - world.TARGET_CU) <= world.TOL_CU),
            "hours": len(plant_hours)}
