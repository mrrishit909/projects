"""Models and optimisers, all fitted on what the service stores (noon reports, the sea-trial curve, forecasts, port
line-ups), never on the generator's internals.

    fuel model        per vessel: non-negative least squares on physically shaped features of each noon report (speed
                      cubed and its neighbours scaled by displacement, the same times days since hull cleaning, wave height
                      squared by heading, apparent head wind); baseline: the yard's sea-trial curve
    hull fouling      the fouling term of that fit: extra fuel today against the same hull clean; baseline: assume clean
    route cost        the fuel model on the forecast's waves and wind plus the current along each edge, charter hire and
                      a heavy-weather risk charge; edges above the wave limit are closed
    route optimiser   time-dependent A* over the 0.5-degree grid with the forecast; baseline: the shortest sea route
                      (great circle where land allows)
    speed optimiser   dynamic programming over arrival time along the route, leg by leg in 0.25-knot steps, minimising
                      fuel, carbon, hire, waiting at anchor and late penalties against the berth window and the port's
                      earliest berth; baseline: constant service speed
    ETA uncertainty   the plan sailed through the forecast ensemble with the fuel model, plus the model's own error ->
                      P10/P50/P90 arrival and fuel
    bunker planner    a small MILP over the next port calls: how much to buy where, with minimum stems, delivery fees,
                      tank capacity and a P90 reserve; baseline: top up at every call for the next leg
"""
import hashlib
import heapq
import json
import math
import time

import numpy as np
from scipy.optimize import nnls

from . import world

FUEL_VERSION = "fuel-nnls-1"
ROUTE_VERSION = "route-astar-1"
SPEED_VERSION = "speed-dp-1"
ETA_VERSION = "eta-ensemble-1"
BUNKER_VERSION = "bunker-milp-1"
FEATURES = ["aux", "calm_v2", "calm_v3", "calm_v4", "fouling_v3", "waves_head", "waves_all", "wind_head"]
HOLDOUT_DAYS = 60
LEG_NM = 120.0
DT_BIN = 0.25
SPEED_STEP = 0.25
V_MIN = 10.0


def feature_hash(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True, default=lambda o: round(float(o), 4)).encode()).hexdigest()[:16]


# --- fuel model --------------------------------------------------------------------------------------------------------
def features(v, hs, g, head, disp, days):
    """Feature matrix [..., 8] for t/day. Scaled so the coefficients have similar size."""
    v, hs, g, head, disp, days = np.broadcast_arrays(*(np.asarray(a, float) for a in (v, hs, g, head, disp, days)))
    d = disp ** (2 / 3)
    wr = v + head * world.KN_PER_MS
    return np.stack([np.ones_like(v), d * v ** 2 / 100, d * v ** 3 / 1000, d * v ** 4 / 10000, d * v ** 3 / 1000 * np.maximum(days, 0) / 365,
                     hs ** 2 * g * v / 100, hs ** 2 * v / 100, (wr * np.abs(wr) - v ** 2) * v / 10000], axis=-1)


def report_inputs(r):
    """A noon report's observed conditions -> model inputs (speed, wave height, head-sea factor, head wind, displacement, days)."""
    g = (1 + math.cos(math.radians(45 * r["wave_sector"]))) / 2
    return r["stw"], r["hs_obs"], g, r["head_wind_obs"], r["disp"], r["days_clean"]


def predict_tpd(m, v, hs, g, head, disp, days):
    """The model's fuel in t/day: the same sum as `features(...) @ coef`, written out because planners call it a lot."""
    c = m["coef"]
    v, hs, g, head = np.asarray(v, float), np.asarray(hs, float), np.asarray(g, float), np.asarray(head, float)
    d = np.asarray(disp, float) ** (2 / 3)
    v2 = v * v
    v3 = v2 * v
    wr = v + head * world.KN_PER_MS
    f = (c[0] + d * (c[1] * v2 / 100 + c[2] * v3 / 1000 + c[3] * v3 * v / 10000 + c[4] * v3 / 1000 * np.maximum(days, 0) / 365)
         + hs * hs * v / 100 * (c[5] * g + c[6]) + c[7] * (wr * np.abs(wr) - v2) * v / 10000)
    return np.maximum(f, max(c[0], 0.5))


def _fit(X, y):
    coef, _ = nnls(X / y[:, None], np.ones(len(y)))
    rel = X @ coef / y - 1
    mad = np.median(np.abs(rel - np.median(rel))) * 1.4826 + 1e-9
    keep = np.abs(rel) < 4 * mad                       # a mistyped report should not move the curve
    coef, _ = nnls(X[keep] / y[keep, None], np.ones(int(keep.sum())))
    return coef, int((~keep).sum())


def sea_trial_tpd(particulars, speed):
    """The yard's curve, log-log interpolated between the trial points (t/day)."""
    st = np.array(particulars["sea_trial"], float)
    return np.exp(np.interp(np.log(np.asarray(speed, float)), np.log(st[:, 0]), np.log(st[:, 2]), left=None, right=None)
                  + np.where(np.asarray(speed) > st[-1, 0], 3.0 * (np.log(np.maximum(speed, 1e-3)) - np.log(st[-1, 0])), 0.0))


def fuel_cap_tpd(particulars):
    """Fuel at 90% of MCR, from the trial table's power-fuel relation."""
    st = np.array(particulars["sea_trial"], float)
    return float(np.exp(np.interp(math.log(0.9 * particulars["mcr_kw"]), np.log(st[:, 1]), np.log(st[:, 2]))))


def fit_fuel_model(particulars, reports, now_h):
    """Score on the last 60 days (fitted on everything before), then refit on everything for production."""
    reports = sorted(reports, key=lambda r: r["t"])
    rows = np.array([report_inputs(r) for r in reports], float)
    y = np.array([r["fuel_t"] * 24 / r["hours"] for r in reports])
    X = features(*rows.T)
    test = np.array([r["t"] >= now_h - 24 * HOLDOUT_DAYS for r in reports])
    coef_tr, dropped = _fit(X[~test], y[~test])
    pred = X[test] @ coef_tr
    base = sea_trial_tpd(particulars, rows[test, 0])
    mape = lambda p: round(float(np.mean(np.abs(p / y[test] - 1)) * 100), 2)      # noqa: E731
    coef, _ = _fit(X, y)
    resid = np.log(X @ coef / y)
    # systematic error over a voyage: the spread of week-long mean residuals (what the ETA/fuel band adds per member)
    weeks = np.array([int(r["t"] // (24 * 7)) for r in reports])
    wk = [resid[weeks == w].mean() for w in np.unique(weeks) if (weeks == w).sum() >= 3]
    m = {"vessel": particulars["ref"], "version": FUEL_VERSION, "features": FEATURES, "coef": [float(c) for c in coef],
         "design_speed": particulars["design_speed"], "mcr_kw": particulars["mcr_kw"], "fuel_cap_tpd": fuel_cap_tpd(particulars),
         "sigma_daily": float(np.std(resid)), "sigma_voyage": float(np.std(wk)) if len(wk) > 2 else 0.03,
         "metrics": {"mape_pct": mape(pred), "baseline_mape_pct": mape(base), "bias_pct": round(float(np.mean(pred / y[test] - 1)) * 100, 2),
                     "test_reports": int(test.sum()), "train_reports": int((~test).sum()), "outliers_dropped": dropped,
                     "test_from_h": now_h - 24 * HOLDOUT_DAYS}}
    m["fouling_now_pct"] = fouling_pct(m, particulars, float(reports[-1]["days_clean"]) + (now_h - reports[-1]["t"]) / 24)
    m["days_clean_now"] = round(float(reports[-1]["days_clean"]) + (now_h - reports[-1]["t"]) / 24, 1)
    return m


def fouling_pct(m, particulars, days, speed=None, disp=0.85):
    """Extra fuel from fouling today against the same hull clean, at service speed in calm water (%)."""
    sp = speed or particulars["service_speed"]
    a = float(predict_tpd(m, sp, 0, 0, 0, disp, days))
    b = float(predict_tpd(m, sp, 0, 0, 0, disp, 0))
    return round(100 * (a / b - 1), 2)


def true_fouling_pct(v, days, speed=None, disp=0.85):
    sp = speed or v["service_speed"]
    a = float(world.fuel_tph(v, world.power(v, sp, 0, 0, 0, disp, days)))
    b = float(world.fuel_tph(v, world.power(v, sp, 0, 0, 0, disp, 0)))
    return round(100 * (a / b - 1), 2)


def model_fns(m, disp, days_at, err=None):
    """Speed and fuel functions of the fitted model (what the planners use). `err`: per-member multiplicative fuel error."""
    cap = m["fuel_cap_tpd"]

    def rate(stw, hs, g, head, t):
        f = predict_tpd(m, stw, hs, g, head, disp, days_at(t)) / 24
        return f if err is None else f * err

    def speed(cmd, hs, g, head, t):
        """The model's view of a speed order (an engine setting): the speed at which the model's fuel rate in this weather
        equals its calm-water rate at the ordered speed, capped by the heavy-weather rule."""
        cmd = np.asarray(cmd, float)
        d = days_at(t)
        aux = m["coef"][0]
        target = np.minimum(predict_tpd(m, cmd, 0.0, 0.0, 0.0, disp, d), cap) - aux
        v = cmd.copy()
        for _ in range(4):
            v = np.clip(v * (target / np.maximum(predict_tpd(m, v, hs, g, head, disp, d) - aux, 1e-3)) ** (1 / 3), 0.5, cmd)
        return np.minimum(np.minimum(v, cmd), world.voluntary_cap(m["design_speed"], hs, g))
    return speed, rate


def anchor_tph_model(m):
    """Auxiliary burn at anchor as the model sees it (its constant term, t/day -> t/h)."""
    return max(m["coef"][0], 1.5) / 24 * 1.1


# --- economics -----------------------------------------------------------------------------------------------------------
def fuel_cost_per_t(terms):
    """Fuel price plus the carbon allowance the voyage must surrender (EU ETS share for voyages into the EU)."""
    return terms["fuel_usd_t"] + world.CO2_PER_T_FUEL * terms["ets_usd_t"] * terms["ets_share"]


def outcome(terms, t0, arrival_h, fuel_t, berth_h, anchor_tph):
    """Cost of a voyage that left at t0, reached the pilot station at arrival_h and could berth from berth_h (the port's
    earliest berth, never before the window opens). Waiting at anchor burns auxiliary fuel; hire runs until berthing;
    the late penalty counts hours after the window closed that are the ship's fault (not the port's)."""
    arrival_h, fuel_t = np.asarray(arrival_h, float), np.asarray(fuel_t, float)
    b = np.maximum(berth_h, terms["window_open_h"])
    berth = np.maximum(arrival_h, b)
    wait = berth - arrival_h
    total_fuel = fuel_t + wait * anchor_tph
    late = np.maximum(0.0, arrival_h - max(terms["window_close_h"], berth_h))
    cost = total_fuel * fuel_cost_per_t(terms) + terms["hire_usd_day"] / 24 * (berth - t0) + terms["late_usd_h"] * late
    return {"fuel_t": total_fuel, "passage_fuel_t": fuel_t, "co2_t": total_fuel * world.CO2_PER_T_FUEL, "wait_h": wait, "late_h": late,
            "berth_h": berth, "cost_usd": cost, "hire_usd": terms["hire_usd_day"] / 24 * (berth - t0), "late_usd": terms["late_usd_h"] * late,
            "fuel_usd": total_fuel * terms["fuel_usd_t"], "carbon_usd": total_fuel * world.CO2_PER_T_FUEL * terms["ets_usd_t"] * terms["ets_share"]}


# --- forecast on the routing grid -----------------------------------------------------------------------------------------------
class GridForecast:
    """A forecast view sampled at every ocean node every `dt` hours: what the route optimiser reads."""

    def __init__(self, wx, t_lo, hours, dt=3.0):
        g = world.grid()
        self.t_lo, self.dt = float(t_lo), dt
        self.tg = self.t_lo + dt * np.arange(int(hours / dt) + 2)
        w = wx.at(g.lat[None, :], g.lon[None, :], self.tg[:, None])
        self.hs, self.wu, self.wv, self.wdir = (w[k].astype(np.float32) for k in ("hs", "wu", "wv", "wdir"))

    def ti(self, t):
        return int(min(len(self.tg) - 1, max(0, round((t - self.t_lo) / self.dt))))


_EDGE_CUR = None


def edge_current():
    """Current along every grid edge (knots), from the edge's midpoint."""
    global _EDGE_CUR
    if _EDGE_CUR is None:
        g = world.grid()
        safe = np.maximum(g.nb, 0)
        mlat, mlon = (g.lat[:, None] + g.lat[safe]) / 2, (g.lon[:, None] + g.lon[safe]) / 2
        ce, cn = world.current(mlat, mlon)
        c = np.radians(g.course)
        _EDGE_CUR = np.where(g.nb >= 0, ce * np.sin(c) + cn * np.cos(c), 0.0)
    return _EDGE_CUR


def optimize_route(m, gf, t_start, start_node, goal_node, cmd, terms, disp, days_at, hs_limit=7.0, risk_usd_h_m=1500.0, weather=True):
    """Time-dependent A* over the grid at a commanded speed. Edge cost: fuel (fuel model on the forecast at the hour the
    ship would be there) at fuel + carbon price, hire for the hours, and a heavy-weather charge per hour per metre of sea
    above 4.5 m. Edges from a node whose forecast sea exceeds `hs_limit` are closed. `weather=False` gives the shortest
    sea route at the same speed. -> nodes, cost, hours, expanded nodes, seconds."""
    g = world.grid()
    cur = edge_current()
    speed_fn, rate_fn = model_fns(m, disp, days_at)
    price = fuel_cost_per_t(terms)
    hire_h = terms["hire_usd_day"] / 24
    calm_rate = float(rate_fn(cmd, 0.0, 0.0, 0.0, t_start))
    per_nm = 0.85 * (calm_rate * price + hire_h) / (cmd + 3.0)            # discounted so the heuristic stays below the true cost
    glat, glon = g.lat[goal_node], g.lon[goal_node]
    h_all = world.nm(g.lat, g.lon, glat, glon) * (per_nm if weather else 1.0)
    t0 = time.perf_counter()
    best = np.full(g.n, np.inf)
    arr = np.full(g.n, np.inf)
    prev = -np.ones(g.n, int)
    closed = np.zeros(g.n, bool)
    best[start_node], arr[start_node] = 0.0, t_start
    heap = [(h_all[start_node], start_node)]
    expanded = 0
    while heap:
        _, u = heapq.heappop(heap)
        if closed[u]:
            continue
        closed[u] = True
        expanded += 1
        if u == goal_node:
            break
        nb = g.nb[u]
        ok = nb >= 0
        if not weather:
            cost = g.dist[u]
            dt = g.dist[u] / cmd
        else:
            k = gf.ti(arr[u])
            hs_u = float(gf.hs[k, u])
            if hs_u > hs_limit and u != start_node:
                continue                                                         # closed: no safe way out of this cell
            crs = g.course[u]
            step = np.where(ok, g.dist[u], 0.0).max() / max(cmd, 1.0)
            t_mid = arr[u] + step / 2
            k2 = gf.ti(arr[u] + step)
            tgt = np.maximum(nb, 0)
            hs = 0.5 * (hs_u + gf.hs[k2, tgt])                                   # the edge's sea: both ends, at their hours
            wx = {"wu": 0.5 * (gf.wu[k, u] + gf.wu[k2, tgt]), "wv": 0.5 * (gf.wv[k, u] + gf.wv[k2, tgt]), "wdir": None}
            wx["wdir"] = (np.degrees(np.arctan2(wx["wu"], wx["wv"])) + 360) % 360
            gg, head = world.relative(crs, wx)
            stw = speed_fn(np.full(len(nb), cmd), hs, gg, head, t_mid)
            sog = np.maximum(2.0, stw + cur[u])
            dt = np.where(ok, g.dist[u], 0.0) / sog
            fuel = rate_fn(stw, hs, gg, head, t_mid) * dt
            ok = ok & (gf.hs[k2, tgt] <= hs_limit)
            cost = fuel * price + hire_h * dt + risk_usd_h_m * np.maximum(0.0, hs - 4.5) * dt
        for j in np.nonzero(ok)[0]:
            v2 = nb[j]
            if closed[v2]:
                continue
            c2 = best[u] + cost[j]
            if c2 < best[v2]:
                best[v2], arr[v2], prev[v2] = c2, arr[u] + dt[j], u
                heapq.heappush(heap, (c2 + h_all[v2], v2))
    if not np.isfinite(best[goal_node]):
        return None
    nodes = [goal_node]
    while nodes[-1] != start_node:
        nodes.append(int(prev[nodes[-1]]))
    nodes.reverse()
    return {"nodes": nodes, "cost": float(best[goal_node]), "hours": float(arr[goal_node] - t_start), "expanded": expanded,
            "seconds": round(time.perf_counter() - t0, 3)}


def choose_route(m, fc, gf, t0, start_node, goal, cmd, terms, disp, days_at, orig, dest, start=None):
    """Weather routing with a check: the A* route and the shortest sea route are both sailed through the forecast on the
    same lattice at the same speed order, and the cheaper is kept. A* reads the weather at grid nodes; the lattice reads it
    along the path hour by hour, so when the weather gives no reason to leave the shortest route, the shortest route wins."""
    opt = optimize_route(m, gf, t0, start_node, goal, cmd, terms, disp, days_at)
    short = optimize_route(m, gf, t0, start_node, goal, cmd, terms, disp, days_at, weather=False)
    evals = {}
    for kind, r in (("optimized", opt), ("shortest", short)):
        if r is None:
            continue
        P = world.Path(*world.passage(orig, dest, r["nodes"], start=start, tol_nm=30.0 if kind == "optimized" else None))
        F = world.Field(P, [fc], t0, t0 + P.length / 8 + 72)
        arr, fuel, track = deterministic(m, P, [(P.length, cmd)], F, t0, 0.0, disp, days_at)
        cost = float(outcome(terms, t0, arr, fuel, t0, anchor_tph_model(m))["cost_usd"]) + 1500.0 * sum(max(0.0, h["hs"] - 4.5) * h["hours"] for h in track)
        evals[kind] = {"route": r, "path": P, "arrival_h": arr, "fuel_t": fuel, "track": track, "cost": cost}
    if "optimized" not in evals:
        return None
    best = "optimized" if evals["optimized"]["cost"] <= evals["shortest"]["cost"] else "shortest"
    info = dict(evals[best]["route"], seconds=opt["seconds"], expanded=opt["expanded"], chosen=best,
                optimized_cost=round(evals["optimized"]["cost"]), shortest_cost=round(evals["shortest"]["cost"]))
    info["path"] = [(float(a), float(b)) for a, b in zip(evals[best]["path"].lat, evals[best]["path"].lon)]
    return {"info": info, "chosen": best, "evals": evals}


def remaining_path(P, s0):
    """What is left of a path from distance s0: the position there, then the points still ahead."""
    lat, lon, _ = P.at(s0)
    return [(float(lat), float(lon))] + [(float(a), float(b)) for a, b, s in zip(P.lat, P.lon, P.s) if s > s0 + 1e-6]


# --- speed along a route -----------------------------------------------------------------------------------------------------
def legs_of(path, s0=0.0):
    """Leg boundaries (nm) of about 120 nm from s0 to the end."""
    n = max(1, int(math.ceil((path.length - s0) / LEG_NM)))
    return list(s0 + (path.length - s0) * np.arange(1, n + 1) / n)


def sample0(F, s, t):
    """Member 0 of a field at arrays of (s, t) of any shape."""
    i = np.clip(np.rint(np.asarray(s) / F.ds).astype(int), 0, len(F.sg) - 1)
    x = np.clip((np.asarray(t) - F.t_lo) / F.dt, 0, len(F.tg) - 1.001)
    j = x.astype(int)
    f = x - j
    pick = lambda a: a[0, i, j] * (1 - f) + a[0, i, j + 1] * f       # noqa: E731
    return pick(F.hs), pick(F.g), pick(F.head), F.cur[i]


def optimize_speed(m, path, F, t0, s0, terms, berth_h, disp, days_at, v_max, v_min=V_MIN, deadline_h=None, fixed=None, risk_usd_h_m=1500.0):
    """Dynamic programming over arrival time, leg by leg, with the commanded speed on each leg chosen in 0.25-knot steps.
    Leg cost: fuel at fuel + carbon price and the heavy-weather charge, read from the forecast field F at the hour the ship
    would be there. Terminal cost: hire until berthing, auxiliary fuel waiting at anchor, late penalty (see `outcome`).
    `deadline_h` closes arrival times after it; `fixed` forces one speed on every leg (the constant-speed baseline)."""
    ends = legs_of(path, s0)
    starts = [s0] + ends[:-1]
    speeds = np.array([fixed]) if fixed is not None else np.arange(v_min, v_max + 1e-9, SPEED_STEP)
    speed_fn, rate_fn = model_fns(m, disp, days_at)
    price = fuel_cost_per_t(terms)
    best = {0: (0.0, float(t0))}          # arrival bin -> (cost so far, exact arrival hour of the cheapest way there)
    back = []
    for a, b in zip(starts, ends):
        taus = np.array(sorted(best))
        base = np.array([best[k][0] for k in taus])
        exact = np.array([best[k][1] for k in taus])
        n_sub = max(1, int(math.ceil((b - a) / 30.0)))
        edges = a + (b - a) * np.arange(n_sub + 1) / n_sub
        T = np.repeat(exact[:, None], len(speeds), 1)
        V = np.repeat(speeds[None, :], len(taus), 0)
        cost = np.zeros_like(T)
        for k in range(n_sub):
            hs, gg, head, cur = sample0(F, (edges[k] + edges[k + 1]) / 2, T)
            stw = speed_fn(V, hs, gg, head, T)
            sog = np.maximum(2.0, stw + cur)
            dt = (edges[k + 1] - edges[k]) / sog
            cost += rate_fn(stw, hs, gg, head, T) * dt * price + risk_usd_h_m * np.maximum(0, hs - 4.5) * dt
            T = T + dt
        tot = base[:, None] + cost
        bins = np.rint((T - t0) / DT_BIN).astype(int)
        flat = np.argsort(tot, axis=None)
        fb = bins.ravel()[flat]
        _, first = np.unique(fb, return_index=True)
        pick = flat[first]
        new, bk = {}, {}
        for p in pick:
            i, j = divmod(int(p), len(speeds))
            nb_ = int(bins[i, j])
            new[nb_] = (float(tot[i, j]), float(T[i, j]))
            bk[nb_] = (int(taus[i]), float(speeds[j]))
        back.append(bk)
        best = new
    arr_bins = np.array(sorted(best))
    arr_h = np.array([best[k][1] for k in arr_bins])
    leg_cost = np.array([best[k][0] for k in arr_bins])
    hire_h = terms["hire_usd_day"] / 24
    b0 = max(berth_h, terms["window_open_h"])
    berth = np.maximum(arr_h, b0)
    term = hire_h * (berth - t0) + (berth - arr_h) * anchor_tph_model(m) * price + terms["late_usd_h"] * np.maximum(0, arr_h - max(terms["window_close_h"], berth_h))
    total = leg_cost + term
    if deadline_h is not None:
        total = np.where(arr_h <= deadline_h, total, np.inf)
        if not np.isfinite(total).any():
            total = np.where(arr_h == arr_h.min(), 0.0, np.inf)         # cannot make it: go as fast as possible
    k = int(np.argmin(total))
    cur_bin = int(arr_bins[k])
    chosen = []
    for bk in reversed(back):
        prev_bin, sp = bk[cur_bin]
        chosen.append(sp)
        cur_bin = prev_bin
    chosen.reverse()
    return {"legs": [(float(e), float(v)) for e, v in zip(ends, chosen)], "arrival_h": float(arr_h[k]), "expected_cost_usd": float(total[k])}


# --- sailing a plan through a weather view with the model -------------------------------------------------------------------------
def ensemble(m, path, legs, members_field, t0, s0, disp, days_at, seed_key):
    """The plan sailed through every forecast member with the fuel model; each member also draws the model's own
    voyage-level error. -> arrays of arrival hour and passage fuel."""
    rng = np.random.default_rng([seed_key, 3])
    err = np.exp(rng.normal(0, max(m["sigma_voyage"], 0.01), members_field.M))
    speed_fn, rate_fn = model_fns(m, disp, days_at, err=err)
    r = world.integrate(members_field, legs, t0, s0, speed_fn, rate_fn)
    return r["t"], r["fuel_t"]


def deterministic(m, path, legs, field, t0, s0, disp, days_at):
    speed_fn, rate_fn = model_fns(m, disp, days_at)
    r = world.integrate(field, legs, t0, s0, speed_fn, rate_fn, record=True)
    return float(r["t"][0]), float(r["fuel_t"][0]), r["track"]


def bands(x):
    q = np.percentile(x, [10, 50, 90])
    return {"p10": float(q[0]), "p50": float(q[1]), "p90": float(q[2])}


# --- bunkers -----------------------------------------------------------------------------------------------------------------
def bunker_plan(calls, legs, rob0, capacity, min_stem=250.0, reserve_days=3.0):
    """calls: [{port, price, fee}] in order (the first is now); legs: [{p50, p90, days}] from call i to call i+1.
    Reserve on arrival from each leg: its P90 over P50 plus `reserve_days` of its daily burn. End with at least what we
    started with, so the plan cannot win by running the tanks down. -> MILP plan and the top-up baseline."""
    from ortools.linear_solver import pywraplp
    n = len(legs)
    reserve = [max(0.0, lg["p90"] - lg["p50"]) + reserve_days * lg["p50"] / max(lg["days"], 0.5) for lg in legs]
    s = pywraplp.Solver.CreateSolver("CBC")
    buy = [s.NumVar(0, capacity, f"buy{i}") for i in range(n)]
    y = [s.IntVar(0, 1, f"y{i}") for i in range(n)]
    rob = rob0
    for i in range(n):
        s.Add(buy[i] <= capacity * y[i])
        s.Add(buy[i] >= min_stem * y[i])
        rob = rob + buy[i]
        s.Add(rob <= capacity)
        rob = rob - legs[i]["p50"]
        s.Add(rob >= reserve[i])
    s.Add(rob >= rob0)
    s.Minimize(sum(calls[i]["price"] * buy[i] + calls[i]["fee"] * y[i] for i in range(n)))
    t = time.perf_counter()
    status = s.Solve()
    solve_s = time.perf_counter() - t
    if status != pywraplp.Solver.OPTIMAL:
        return {"status": "infeasible", "reserve_t": reserve}
    plan, r = [], rob0
    for i in range(n):
        b = buy[i].solution_value() if y[i].solution_value() > 0.5 else 0.0
        r_before = r
        r = r + b
        plan.append({"port": calls[i]["port"], "buy_t": round(b, 1), "price": calls[i]["price"], "rob_before_t": round(r_before, 1), "rob_after_t": round(r, 1),
                     "leg_p50_t": round(legs[i]["p50"], 1), "arrive_with_t": round(r - legs[i]["p50"], 1), "reserve_t": round(reserve[i], 1)})
        r -= legs[i]["p50"]
    cost = sum(p["buy_t"] * p["price"] + (calls[i]["fee"] if p["buy_t"] > 0 else 0) for i, p in enumerate(plan))
    # baseline: at each call top up to the next leg's P50 plus reserve (at least a minimum stem), then square the
    # ending stock at the last port's price so both plans end where they started
    base, r = [], rob0
    for i in range(n):
        need = legs[i]["p50"] + reserve[i] - r
        b = max(min_stem, need) if need > 0 else 0.0
        b = min(b, capacity - r)
        base.append({"port": calls[i]["port"], "buy_t": round(b, 1)})
        r = r + b - legs[i]["p50"]
    base_cost = sum(b["buy_t"] * calls[i]["price"] + (calls[i]["fee"] if b["buy_t"] > 0 else 0) for i, b in enumerate(base))
    square = max(0.0, rob0 - r)
    if square > 1e-6:                       # squaring the stock is a delivery like any other
        base_cost += square * calls[-1]["price"] + calls[-1]["fee"]
    return {"status": "optimal", "plan": plan, "cost_usd": round(cost), "baseline": base, "baseline_cost_usd": round(base_cost),
            "saving_usd": round(base_cost - cost), "baseline_square_t": round(square, 1), "solve_ms": round(solve_s * 1000, 1), "reserve_t": [round(x, 1) for x in reserve]}


# --- variance: plan against what happened -----------------------------------------------------------------------------------------
def variance(m, planned, actual, disp, days_at):
    """Split the fuel difference between the plan and the sailed hours into: speed (the ship did not make, or was not
    commanded, the planned speed), weather (the sea it met was not the forecast's) and model (what the model cannot explain
    in the sea and speed it met: hull, engine, the model itself). `planned` and `actual` are hourly rows over the same
    hours: planned with forecast conditions, actual with observed conditions and metered fuel."""
    _, rate_fn = model_fns(m, disp, days_at)
    P = {k: np.array([h[k] for h in planned]) for k in ("stw", "hs", "g", "head_ms", "t", "hours")}
    A = {k: np.array([h[k] for h in actual]) for k in ("stw", "hs_obs", "g_obs", "head_obs", "t", "hours", "fuel_t")}
    plan_fuel = float(np.sum(rate_fn(P["stw"], P["hs"], P["g"], P["head_ms"], P["t"]) * P["hours"]))
    speed_only = float(np.sum(rate_fn(A["stw"], P["hs"], P["g"], P["head_ms"], A["t"]) * A["hours"]))
    model_obs = float(np.sum(rate_fn(A["stw"], A["hs_obs"], A["g_obs"], A["head_obs"], A["t"]) * A["hours"]))
    act = float(A["fuel_t"].sum())
    return {"planned_fuel_t": round(plan_fuel, 1), "actual_fuel_t": round(act, 1), "variance_t": round(act - plan_fuel, 1),
            "speed_t": round(speed_only - plan_fuel, 1), "weather_t": round(model_obs - speed_only, 1), "model_t": round(act - model_obs, 1)}


# --- the whole plan -------------------------------------------------------------------------------------------------------------
MEMBERS = 24


def plan(m, particulars, seed, told_seen, issued, t0, orig, dest, terms, berth_h, disp, days_at, start=None, route="optimize", speed="optimize",
         deadline_h=None, gf=None, members=MEMBERS, path_pts=None):
    """Plan a passage from the pilot station of `orig` (or a position at sea, `start`) at hour t0 with the forecast issued at
    `issued`. route: 'optimize' (weather routing) | 'shortest' | 'path' (keep the given path, `path_pts`); speed: 'optimize' |
    a constant speed order. The speed plan keeps its P90 arrival inside the window (or the port's earliest berth, if later),
    tightening its own deadline until it does. -> path, legs, deterministic and ensemble arrival and fuel, expected cost."""
    g = world.grid()
    fc = world.Weather(seed, told_seen, issued=issued)
    route_info = None
    start_node = g.node(*(start if start is not None else world.PORTS[orig][2]))
    goal = g.node(*world.PORTS[dest][2])
    cmd0 = particulars["service_speed"] if speed == "optimize" else float(speed)
    if route == "optimize" and gf is None:
        gf = GridForecast(fc, issued, 24 * 18)
    limit = max(terms["window_close_h"], berth_h)
    for rpass in range(2 if (route == "optimize" and speed == "optimize") else 1):
        if route == "path":
            pts = list(path_pts)
        elif route == "optimize":
            ch = choose_route(m, fc, gf, t0, start_node, goal, cmd0, terms, disp, days_at, orig, dest, start)
            route_info = ch["info"]
            pts = route_info["path"]
        else:
            route_info = optimize_route(m, gf, t0, start_node, goal, cmd0, terms, disp, days_at, weather=False)
            la, lo = world.passage(orig, dest, route_info["nodes"], start=start, tol_nm=None)
            pts = list(zip(la, lo))
        P, Fc, Fm, sp, arr, fu, tries, dp_s = _speeds(m, particulars, seed, told_seen, issued, t0, pts, terms, berth_h, disp,
                                                      days_at, speed, deadline_h, members, limit)
        if rpass == 0 and route == "optimize" and speed == "optimize":
            first = route_info
            mean_v = (P.length) / max(1e-6, sum((e - s_) / v for (e, v), s_ in zip(sp["legs"], [0.0] + [e for e, _ in sp["legs"][:-1]])))
            if abs(mean_v - cmd0) < 0.75:
                break
            cmd0 = round(mean_v * 4) / 4                                   # route again at the speed the plan will really sail
    if route_info is not None and route == "optimize" and speed == "optimize":
        route_info = dict(route_info, first_pass_seconds=first["seconds"], routed_at_kn=cmd0)
    det_t, det_f, det_track = deterministic(m, P, sp["legs"], Fc, t0, 0.0, disp, days_at)
    exp = outcome(terms, t0, arr, fu, berth_h, anchor_tph_model(m))
    return {"path": P, "nodes": (route_info or {}).get("nodes", []), "legs": sp["legs"], "route": route_info, "speed_seconds": round(dp_s, 2), "tries": tries,
            "det_arrival_h": det_t, "det_fuel_t": det_f, "det_track": det_track, "arrival": bands(arr), "fuel": bands(fu),
            "arrivals": arr, "fuels": fu, "p_late": float(np.mean(arr > limit + 1e-6)),
            "expected": {k: float(np.mean(v)) for k, v in exp.items()}, "berth_h": berth_h, "t0": t0}


def _speeds(m, particulars, seed, told_seen, issued, t0, pts, terms, berth_h, disp, days_at, speed, deadline_h, members, limit):
    fc = world.Weather(seed, told_seen, issued=issued)
    v_max = particulars["design_speed"] - 1.0
    P = world.Path([a for a, _ in pts], [b for _, b in pts])
    horizon = P.length / 8.0 + 72
    Fc = world.Field(P, [fc], t0, t0 + horizon)
    Fm = world.Field(P, [world.Weather(seed, told_seen, issued=issued, member=k) for k in range(1, members + 1)], t0, t0 + horizon, ds=20.0, dt=2.0)
    dl, tries = deadline_h, []
    t_dp = time.perf_counter()
    for _ in range(4):
        if speed == "optimize":
            sp = optimize_speed(m, P, Fc, t0, 0.0, terms, berth_h, disp, days_at, v_max=v_max, deadline_h=dl)
        else:
            sp = optimize_speed(m, P, Fc, t0, 0.0, terms, berth_h, disp, days_at, v_max=0, fixed=float(speed))
        arr, fu = ensemble(m, P, sp["legs"], Fm, t0, 0.0, disp, days_at, int(issued) + 17)
        p90 = float(np.percentile(arr, 90))
        tries.append({"deadline_h": dl, "p90_h": p90})
        if speed != "optimize" or p90 <= limit + 0.5:
            break
        dl = (dl if dl is not None else sp["arrival_h"]) - (p90 - limit) - 0.5
    return P, Fc, Fm, sp, arr, fu, tries, time.perf_counter() - t_dp


def assess(m, P, legs, seed, told_seen, issued, t0, s0, terms, berth_h, disp, days_at, members=MEMBERS):
    """An existing plan (path and legs) from distance s0 at hour t0, with the forecast issued at `issued`: deterministic
    track, ensemble bands and expected outcome. The voyage monitor and the 'keep the plan' alternative use this."""
    fc = world.Weather(seed, told_seen, issued=issued)
    horizon = (P.length - s0) / 8.0 + 72
    Fc = world.Field(P, [fc], t0, t0 + horizon)
    Fm = world.Field(P, [world.Weather(seed, told_seen, issued=issued, member=k) for k in range(1, members + 1)], t0, t0 + horizon, ds=20.0, dt=2.0)
    arr, fu = ensemble(m, P, legs, Fm, t0, s0, disp, days_at, int(issued) + 17)
    det_t, det_f, det_track = deterministic(m, P, legs, Fc, t0, s0, disp, days_at)
    exp = outcome(terms, t0, arr, fu, berth_h, anchor_tph_model(m))
    limit = max(terms["window_close_h"], berth_h)
    return {"path": P, "legs": legs, "det_arrival_h": det_t, "det_fuel_t": det_f, "det_track": det_track, "arrival": bands(arr), "fuel": bands(fu),
            "arrivals": arr, "fuels": fu, "p_late": float(np.mean(arr > limit + 1e-6)), "expected": {k: float(np.mean(v)) for k, v in exp.items()},
            "berth_h": berth_h, "t0": t0, "route": None, "tries": [], "speed_seconds": 0.0}
