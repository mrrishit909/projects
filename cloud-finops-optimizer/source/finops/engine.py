"""Models, optimisers and analysis. Everything here works on what the service stores (inventory, hourly utilisation,
billing lines, the price catalogue), never on the generator's truth.

    forecast        workload demand: an hour-of-week profile times a log-linear weekly trend, with whole-day residuals
                    bootstrapped into sample paths for the next weeks; baseline: seasonal naive (last week again)
    rightsize       the smallest size whose forecast p99 utilisation stays under the SLO target (CPU and memory) in 90% of
                    the sample paths; idle machines and unattached volumes found from the whole history; node-pool floors
                    lowered only as far as the autoscaler's added hot hours allow; baseline: the 14-day average-utilisation
                    rule most cost tools use
    risk            P(a resize breaches the SLO in the next four weeks): logistic regression on the estate's own history,
                    labelled by replaying each candidate size against the weeks that followed; baselines: the headroom
                    alone, and an environment/kind rule
    portfolio       one-year compute savings plans (per cloud, $1/h blocks) and database reservations (per instance type)
                    as a mixed-integer programme over forecast scenarios, after the planned rightsizing; baseline: commit
                    to last month's minimum
    verify          realised savings of applied changes: the old configuration re-priced against the post-period's observed
                    demand, through the commitments actually in force; baselines: before/after, difference-in-differences
                    against untouched resources, and the list-price estimate
    explain         a cost change between two periods split into usage, configuration, rate, new and removed resources
"""
import hashlib
import json
import math

import numpy as np
from ortools.linear_solver import pywraplp
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import world

FORECAST_VERSION = "seasonal-trend-bootstrap-1"
RIGHTSIZER_VERSION = "slo-rightsizer-1"
RISK_VERSION = "change-risk-logit-1"
PORTFOLIO_VERSION = "commitment-milp-1"
VERIFIER_VERSION = "counterfactual-repricing-1"
WEEK = 168
POLICY = {   # the defaults a tenant's policy starts from
    "cpu_p99_target": 0.80, "mem_p99_target": 0.85, "breach_cpu": 0.90, "path_quantile": 0.90, "horizon_weeks": 4,
    "min_history_days": 14, "max_steps": 2, "idle_cpu_max": 0.05, "idle_volume_days": 28, "pool_extra_hot_hours": 0.005,
    "min_monthly_savings": 5.0, "risk_review_above": 0.25, "freshness_minutes": 15, "allow_direct_mutation": False,
    "commitment_budget_per_month": None, "commitment_term_months": 12, "scenarios": 20,
}


def feature_hash(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True, default=lambda v: round(float(v), 4)).encode()).hexdigest()[:16]


# --- forecast ---------------------------------------------------------------------------------------------------------------
def fit_forecast(y, t0):
    """y: hourly demand, y[0] at absolute hour t0 (midnight). Uses the last whole weeks (up to eight)."""
    y = np.asarray(y, float)
    weeks = min(8, len(y) // WEEK)
    if weeks < 1:
        weeks = 0
    n = weeks * WEEK if weeks else (len(y) // 24) * 24
    yy, tt = y[len(y) - n:], t0 + len(y) - n
    t_end = t0 + len(y)
    b = 0.0
    if weeks >= 3:
        means = yy.reshape(weeks, WEEK).mean(1)
        if (means > 0).all():
            lm = np.log(means)
            slopes = [(lm[j] - lm[i]) / (j - i) for i in range(weeks) for j in range(i + 1, weeks)]
            b = float(np.clip(np.median(slopes), -0.15, 0.15))          # Theil-Sen on weekly log-means
    hours = np.arange(tt, t_end)
    z = yy / np.exp(b * (hours - t_end) / WEEK)
    how = hours % WEEK
    if weeks:
        profile = np.array([np.median(z[how == k]) for k in range(WEEK)])
    else:                                                               # under a week: an hour-of-day profile
        hod = np.array([np.median(z[hours % 24 == k]) for k in range(24)])
        profile = np.tile(hod, 7)
    fitted = profile[how] * np.exp(b * (hours - t_end) / WEEK)
    eps = 0.01 * max(float(yy.mean()), 1e-6)
    ratio = (yy + eps) / (fitted + eps)
    return {"b": b, "profile": profile, "t_end": t_end, "resid": ratio.reshape(-1, 24), "eps": eps, "weeks": weeks}


def predict(m, t_from, n):
    t = np.arange(t_from, t_from + n)
    return m["profile"][t % WEEK] * np.exp(m["b"] * (t - m["t_end"]) / WEEK)


def sample_paths(m, t_from, n, k, rng):
    """k sample paths of the next n hours (t_from at midnight): the point forecast times residual days drawn whole."""
    base = predict(m, t_from, n)
    days = math.ceil(n / 24)
    pick = rng.integers(0, len(m["resid"]), (k, days))
    ratio = m["resid"][pick].reshape(k, -1)[:, :n]
    return np.maximum((base + m["eps"]) * ratio - m["eps"], 0)


def wape(actual, pred):
    return float(np.abs(actual - pred).sum() / max(np.abs(actual).sum(), 1e-9))


# --- rightsizing --------------------------------------------------------------------------------------------------------------
def running_share(running, t0):
    """Share of each hour of the week a resource was running (0 for an hour of the week it has not lived through yet)."""
    how = np.arange(t0, t0 + len(running)) % WEEK
    return np.bincount(how, weights=running.astype(float), minlength=WEEK) / np.maximum(np.bincount(how, minlength=WEEK), 1)


def hot_share(util, running):
    """Share of running hours above the breach line."""
    return float(((util > POLICY["breach_cpu"]) & running).sum() / max(running.sum(), 1))


def autoscale(demand, prev, min_nodes, max_nodes):
    """Nodes per hour from demand one hour earlier (the cluster autoscaler), and the utilisation they give."""
    cap = world.VCPU[world.NODE_SIZE]
    demand = np.asarray(demand, float)
    first = np.broadcast_to(np.asarray(prev, float), demand.shape[:-1])[..., None]
    lag = np.concatenate([first, demand[..., :-1]], -1)
    nodes = np.clip(np.ceil(lag / (cap * world.SCALE_TARGET)), min_nodes, max_nodes)
    util = np.where(nodes > 0, np.minimum(demand / np.maximum(nodes * cap, 1e-9), 1.0), 0.0)
    return nodes, util


def rightsize(r, h, t0, rng, policy=POLICY):
    """One resource. r: {kind, cloud, size | min_nodes, max_nodes, gb}; h: its hourly history arrays (cpu_util, mem_util,
    units, io), h[...][0] at absolute hour t0. Returns a recommendation dict, or None when there is nothing to change."""
    kind, cloud = r["kind"], r["cloud"]
    n = len(h["units"])
    days = n // 24
    horizon = policy["horizon_weeks"] * WEEK
    t_next = t0 + n
    base = {"resource_id": r["id"], "kind": kind, "cloud": cloud, "history_days": days}
    if days < policy["min_history_days"]:
        return {**base, "action": "review", "reason": f"only {days} days of history (policy: {policy['min_history_days']})"}
    if kind == "volume":
        last = slice(n - policy["idle_volume_days"] * 24, n)
        if h["units"][last].sum() == 0 and h["io"][last].sum() == 0:
            monthly = world.price(cloud, "volume", gb=r["gb"]) * world.HOURS_MONTH
            return {**base, "action": "delete", "from": f"{r['gb']} GB", "to": "snapshot, then delete", "set": {"terminate": True},
                    "monthly_savings": round(monthly, 2), "confidence": 0.97,
                    "evidence": {"attached_hours": 0, "io": 0, "over_days": policy["idle_volume_days"], "gb": r["gb"]}}
        return None
    running = h["units"] > 0
    if kind == "pool":
        cap = world.VCPU[world.NODE_SIZE]
        demand = h["cpu_util"] * h["units"] * cap
        m = fit_forecast(demand, t0)
        paths = sample_paths(m, t_next, horizon, 100, rng)
        cur_nodes, cur_util = autoscale(paths, demand[-1], r["min_nodes"], r["max_nodes"])
        cur_hot = ((cur_util > policy["breach_cpu"]) & (cur_nodes > 0)).mean(1)
        best, best_q = r["min_nodes"], 0.0
        for mn in range(r["min_nodes"] - 1, -1, -1):
            nodes, util = autoscale(paths, demand[-1], mn, r["max_nodes"])
            extra = ((util > policy["breach_cpu"]) & (nodes > 0)).mean(1) - cur_hot
            q = float(np.quantile(extra, policy["path_quantile"]))
            if q > policy["pool_extra_hot_hours"]:
                break
            best, best_q, saved = mn, q, float((cur_nodes - nodes).sum(1).mean())
        if best == r["min_nodes"]:
            return None
        monthly = saved / horizon * world.HOURS_MONTH * world.price(cloud, "pool", world.NODE_SIZE)
        if monthly < policy["min_monthly_savings"]:
            return None
        return {**base, "action": "lower_min_nodes", "from": r["min_nodes"], "to": best, "set": {"min_nodes": best}, "monthly_savings": round(monthly, 2),
                "confidence": round(float(1 - best_q / max(policy["pool_extra_hot_hours"], 1e-9) * 0.1), 3),
                "evidence": {"nodes_now_mean": round(float(h["units"][-WEEK:].mean()), 1), "nodes_min_seen_week": int(h["units"][-WEEK:].min()),
                             "demand_p99_vcpu": round(float(np.quantile(demand, 0.99)), 1), "extra_hot_hours_share_q90": round(best_q, 4),
                             "forecast_growth_per_week": round(math.exp(m["b"]) - 1, 4), "node_vcpu": cap}}
    size = r["size"]
    v = world.VCPU[size]
    cpu = h["cpu_util"] * v
    mem = h["mem_util"] * v * world.GB_PER_VCPU
    util_run = h["cpu_util"][running]
    throttled = float((util_run >= 0.995).mean()) if running.any() else 0.0
    if kind == "vm" and running.any() and util_run.max() < policy["idle_cpu_max"]:
        frac = running[-28 * 24:].mean()
        monthly = world.price(cloud, kind, size) * world.HOURS_MONTH * frac
        if monthly >= policy["min_monthly_savings"]:
            return {**base, "action": "terminate", "from": world.type_name(cloud, kind, size), "to": "snapshot, then terminate", "set": {"terminate": True},
                    "monthly_savings": round(monthly, 2), "confidence": 0.95,
                    "evidence": {"cpu_max": round(float(util_run.max()), 4), "cpu_mean": round(float(util_run.mean()), 4), "over_days": days, "running_share": round(float(frac), 3)}}
        return None
    if throttled > 0.01:
        return {**base, "action": "review", "reason": f"CPU pinned at 100% for {throttled:.1%} of running hours: true demand is hidden"}
    mc, mm = fit_forecast(cpu, t0), fit_forecast(mem, t0)
    pc, pm = sample_paths(mc, t_next, horizon, 100, rng), sample_paths(mm, t_next, horizon, 100, rng)
    run_how = running_share(running, t0) >= 0.5
    fut = run_how[np.arange(t_next, t_next + horizon) % WEEK]
    if not fut.any():
        return None
    p99c, p99m = np.quantile(pc[:, fut], 0.99, axis=1), np.quantile(pm[:, fut], 0.99, axis=1)
    q = policy["path_quantile"]
    chosen = size
    for s in range(max(0, size - policy["max_steps"]), size):
        vc = world.VCPU[s]
        if np.quantile(p99c / vc, q) <= policy["cpu_p99_target"] and np.quantile(p99m / (vc * world.GB_PER_VCPU), q) <= policy["mem_p99_target"]:
            chosen = s
            break
    if chosen == size:
        return None
    vc = world.VCPU[chosen]
    ok = (p99c / vc <= policy["cpu_p99_target"]) & (p99m / (vc * world.GB_PER_VCPU) <= policy["mem_p99_target"])
    frac = running[-28 * 24:].mean()
    monthly = (world.price(cloud, kind, size) - world.price(cloud, kind, chosen)) * world.HOURS_MONTH * frac
    if monthly < policy["min_monthly_savings"]:
        return None
    return {**base, "action": "resize", "from": world.type_name(cloud, kind, size), "to": world.type_name(cloud, kind, chosen), "set": {"size": chosen},
            "steps": size - chosen, "monthly_savings": round(monthly, 2), "confidence": round(float(ok.mean()), 3),
            "evidence": {"cpu_p99_now": round(float(np.quantile(util_run, 0.99)), 3), "cpu_mean_now": round(float(util_run.mean()), 3),
                         "mem_p99_now": round(float(np.quantile(h["mem_util"][running], 0.99)), 3),
                         "forecast_cpu_p99_at_new_size": round(float(np.quantile(p99c / vc, q)), 3),
                         "forecast_mem_p99_at_new_size": round(float(np.quantile(p99m / (vc * world.GB_PER_VCPU), q)), 3),
                         "forecast_growth_per_week": round(math.exp(mc["b"]) - 1, 4), "slo": f"p99 CPU <= {policy['cpu_p99_target']:.0%}, memory <= {policy['mem_p99_target']:.0%} in {q:.0%} of paths"},
            "_features": risk_features(r, h, chosen, p99c, p99m, mc)}


def naive(r, h, policy=POLICY):
    """The average-utilisation rule: 14-day mean CPU under 2% -> terminate; under 20% -> the smallest size at which the
    mean would be 40% or less. Pools: minimum nodes to the fewest the last 14 days needed. Volumes: unattached now -> delete."""
    kind, last = r["kind"], slice(len(h["units"]) - 14 * 24, len(h["units"]))
    if len(h["units"]) // 24 < policy["min_history_days"]:
        return None
    if kind == "volume":
        if h["units"][-1] == 0:
            return {"resource_id": r["id"], "action": "delete", "set": {"terminate": True}, "monthly_savings": round(world.price(r["cloud"], "volume", gb=r["gb"]) * world.HOURS_MONTH, 2)}
        return None
    running = h["units"][last] > 0
    if not running.any():
        return None
    if kind == "pool":
        demand = (h["cpu_util"] * h["units"])[last] * world.VCPU[world.NODE_SIZE]
        mn = int(math.ceil(demand.min() / (world.VCPU[world.NODE_SIZE] * world.SCALE_TARGET)))
        if mn < r["min_nodes"]:
            saved = (h["units"][last] - np.clip(h["units"][last], mn, None)).mean()
            return {"resource_id": r["id"], "action": "lower_min_nodes", "set": {"min_nodes": mn}, "monthly_savings": round(float(saved) * world.HOURS_MONTH * world.price(r["cloud"], "pool", world.NODE_SIZE), 2)}
        return None
    avg = float(h["cpu_util"][last][running].mean())
    size, frac = r["size"], float(running.mean())
    if avg < 0.02 and kind == "vm":
        return {"resource_id": r["id"], "action": "terminate", "set": {"terminate": True}, "monthly_savings": round(world.price(r["cloud"], kind, size) * world.HOURS_MONTH * frac, 2)}
    if avg < 0.20:
        s = size
        while s > 0 and avg * world.VCPU[size] / world.VCPU[s - 1] <= 0.40:
            s -= 1
        if s < size:
            return {"resource_id": r["id"], "action": "resize", "set": {"size": s},
                    "monthly_savings": round((world.price(r["cloud"], kind, size) - world.price(r["cloud"], kind, s)) * world.HOURS_MONTH * frac, 2)}
    return None


def breached(r, change, fut, policy=POLICY):
    """Would `change` have broken the SLO over the future weeks? fut: true hourly demand {cpu, mem, prev, attach} at the
    current configuration's schedule. The SLO: hours above 90% CPU no more than 1% of running hours beyond what the current
    size already shows; memory never above 100%; a terminated or deleted resource never needed."""
    kind, s = r["kind"], change["set"]
    if kind == "volume":
        return bool(fut["attach"].sum() > 0)
    if kind == "pool":
        nodes0, u0 = autoscale(fut["cpu"], fut["prev"], r["min_nodes"], r["max_nodes"])
        nodes1, u1 = autoscale(fut["cpu"], fut["prev"], s["min_nodes"], r["max_nodes"])
        return bool(((u1 > policy["breach_cpu"]) & (nodes1 > 0)).mean() - ((u0 > policy["breach_cpu"]) & (nodes0 > 0)).mean() > 0.01)
    running = fut["running"]
    v0 = world.VCPU[r["size"]]
    if s.get("terminate"):
        return bool((fut["cpu"][running] > policy["idle_cpu_max"] * 2 * v0).any())
    v1 = world.VCPU[s["size"]]
    extra = hot_share(fut["cpu"] / v1, running) - hot_share(fut["cpu"] / v0, running)
    oom = (fut["mem"][running] > v1 * world.GB_PER_VCPU).any() and not (fut["mem"][running] > v0 * world.GB_PER_VCPU).any()
    return bool(extra > 0.01 or oom)


def observed(r, h):
    """A history window as the service sees it, in the shape `breached` scores (demand capped where utilisation hit 100%)."""
    v = world.VCPU[r["size"]] if r["kind"] in ("vm", "db") else world.VCPU[world.NODE_SIZE]
    cpu = h["cpu_util"] * v * (h["units"] if r["kind"] == "pool" else 1)
    return {"cpu": cpu, "mem": h["mem_util"] * v * world.GB_PER_VCPU, "running": h["units"] > 0, "prev": float(cpu[0]),
            "attach": h["units"] if r["kind"] == "volume" else None}


def slo_risk(r, h, t0, change, rng, k=200, weeks=4, policy=POLICY):
    """P(the change breaks the SLO in the next `weeks`) by the same rule `breached` scores, over k forecast sample paths.
    -> (probability, expected extra share of hours above the breach line)."""
    s, kind, n = change["set"], r["kind"], len(h["units"])
    H, t_next = weeks * WEEK, t0 + n
    if kind == "volume":                                 # no demand model for a volume: the share of history weeks it was attached
        wk = h["units"][-(n // WEEK) * WEEK:].reshape(-1, WEEK).sum(1) > 0 if n >= WEEK else np.array([h["units"].sum() > 0])
        return float(1 - (1 - wk.mean()) ** weeks), 0.0
    if kind == "pool":
        cap = world.VCPU[world.NODE_SIZE]
        demand = h["cpu_util"] * h["units"] * cap
        paths = sample_paths(fit_forecast(demand, t0), t_next, H, k, rng)
        n0, u0 = autoscale(paths, demand[-1], r["min_nodes"], r["max_nodes"])
        n1, u1 = autoscale(paths, demand[-1], s["min_nodes"], r["max_nodes"])
        extra = ((u1 > policy["breach_cpu"]) & (n1 > 0)).mean(1) - ((u0 > policy["breach_cpu"]) & (n0 > 0)).mean(1)
        return float((extra > 0.01).mean()), float(extra.mean())
    v0 = world.VCPU[r["size"]]
    running = h["units"] > 0
    pc = sample_paths(fit_forecast(h["cpu_util"] * v0, t0), t_next, H, k, rng)
    run_how = running_share(running, t0) >= 0.5
    fut = run_how[np.arange(t_next, t_next + H) % WEEK]
    if not fut.any():
        return 0.0, 0.0
    if s.get("terminate"):
        return float((pc[:, fut] > policy["idle_cpu_max"] * 2 * v0).any(1).mean()), 0.0
    pm = sample_paths(fit_forecast(h["mem_util"] * v0 * world.GB_PER_VCPU, t0), t_next, H, k, rng)
    v1 = world.VCPU[s["size"]]
    hot = lambda v: (pc[:, fut] / v > policy["breach_cpu"]).mean(1)        # noqa: E731
    extra = hot(v1) - hot(v0)
    oom = (pm[:, fut] > v1 * world.GB_PER_VCPU).any(1) & ~(pm[:, fut] > v0 * world.GB_PER_VCPU).any(1)
    return float(((extra > 0.01) | oom).mean()), float(extra.mean())


def forecast_band(y, t0, hours, rng, k=100):
    """Point forecast and the 10th/90th percentile of sample paths for the next `hours`."""
    m = fit_forecast(y, t0)
    paths = sample_paths(m, t0 + len(y), hours, k, rng)
    return predict(m, t0 + len(y), hours), np.quantile(paths, 0.1, axis=0), np.quantile(paths, 0.9, axis=0), m["b"]


# --- change risk --------------------------------------------------------------------------------------------------------------
RISK_FEATURES = ["log_worst_headroom", "cpu_headroom_used", "mem_headroom_used", "burstiness", "growth_per_week", "steps", "history_weeks", "is_db", "is_prod", "backtest_wape"]


def risk_features(r, h, size_new, p99c, p99m, mc):
    running = h["units"] > 0
    v = world.VCPU[size_new]
    demand = h["cpu_util"][running] * world.VCPU[r["size"]]
    y = h["cpu_util"] * world.VCPU[r["size"]]
    back = None
    if len(y) >= 3 * WEEK:
        mb = fit_forecast(y[:-WEEK], 0)
        back = wape(y[-WEEK:], predict(mb, len(y) - WEEK, WEEK))
    cpu_used = float(np.quantile(p99c / v, POLICY["path_quantile"]))
    mem_used = float(np.quantile(p99m / (v * world.GB_PER_VCPU), POLICY["path_quantile"]))
    return {"log_worst_headroom": float(np.log(max(cpu_used / POLICY["breach_cpu"], mem_used, 1e-3))), "cpu_headroom_used": cpu_used, "mem_headroom_used": mem_used,
            "burstiness": float(min(np.quantile(demand, 0.99) / max(np.median(demand), 1e-3), 50)), "growth_per_week": float(math.exp(mc["b"]) - 1),
            "steps": float(r["size"] - size_new), "history_weeks": float(len(y) / WEEK), "is_db": float(r["kind"] == "db"),
            "is_prod": float(r.get("env") == "prod"), "backtest_wape": float(min(back if back is not None else 1.0, 3.0))}


def candidate_features(r, h, t0, rng, steps=(1, 2)):
    """Features for resizing r down by each of `steps`, from history h (for training and evaluating the risk model)."""
    running = h["units"] > 0
    if r["kind"] not in ("vm", "db") or len(h["units"]) < 14 * 24 or not running.any():
        return []
    v = world.VCPU[r["size"]]
    mc = fit_forecast(h["cpu_util"] * v, t0)
    mm = fit_forecast(h["mem_util"] * v * world.GB_PER_VCPU, t0)
    n = len(h["units"])
    pc, pm = sample_paths(mc, t0 + n, 4 * WEEK, 60, rng), sample_paths(mm, t0 + n, 4 * WEEK, 60, rng)
    run_how = running_share(running, t0) >= 0.5
    fut = run_how[np.arange(t0 + n, t0 + n + 4 * WEEK) % WEEK]
    if not fut.any():
        return []
    p99c, p99m = np.quantile(pc[:, fut], 0.99, axis=1), np.quantile(pm[:, fut], 0.99, axis=1)
    return [(s, risk_features(r, h, r["size"] - s, p99c, p99m, mc)) for s in steps if r["size"] - s >= 0]


def train_risk(X, y):
    X, y = np.asarray(X, float), np.asarray(y, int)
    model = make_pipeline(StandardScaler(), LogisticRegression(C=2.0, max_iter=5000)).fit(X, y)
    return model


def risk_score(model, feats):
    if model is None:
        return None
    return float(model.predict_proba(np.array([[feats[k] for k in RISK_FEATURES]]))[0, 1])


def heuristic_risk(feats):
    """The rule a change board uses: production databases are risky, production machines less so, dev hardly."""
    return 0.6 if feats["is_db"] and feats["is_prod"] else 0.3 if feats["is_prod"] else 0.1


def score_risk(model, X, y):
    X, y = np.asarray(X, float), np.asarray(y, int)
    p = model.predict_proba(X)[:, 1]
    head = X[:, RISK_FEATURES.index("log_worst_headroom")]
    rule = np.array([heuristic_risk(dict(zip(RISK_FEATURES, x))) for x in X])
    ok = len(set(y)) > 1
    return {"n": int(len(y)), "positives": int(y.sum()), "auc": round(float(roc_auc_score(y, p)), 3) if ok else None,
            "auc_headroom_only": round(float(roc_auc_score(y, head)), 3) if ok else None,
            "auc_env_kind_rule": round(float(roc_auc_score(y, rule)), 3) if ok else None,
            "brier": round(float(brier_score_loss(y, p)), 4), "mean_predicted": round(float(p.mean()), 3), "observed_rate": round(float(y.mean()), 3)}


# --- commitments ----------------------------------------------------------------------------------------------------------------
def duration_buckets(series, buckets=96):
    """An hourly series -> `buckets` values of its duration curve (equal weights)."""
    s = np.sort(np.asarray(series, float))
    return np.array([b.mean() for b in np.array_split(s, buckets)])


def optimise(pools, dbs, hours, budget_per_month=None, block=1.0, time_limit_s=20):
    """pools: {cloud: (S, H) scenarios of hourly on-demand compute spend}; dbs: {(cloud, type): instances that will run};
    -> the portfolio minimising expected cost over `hours`. A savings plan covers `amount` $/h of on-demand usage and costs
    amount * (1 - discount) every hour; a reservation covers one instance of its type."""
    solver = pywraplp.Solver.CreateSolver("SCIP")
    solver.SetTimeLimit(int(time_limit_s * 1000))
    obj, fees, plan = solver.Objective(), [], {"compute_sp": {}, "db_ri": {}}
    obj.SetMinimization()
    var = {}
    for cloud, sc in pools.items():
        d = world.CLOUDS[cloud]["sp"]
        top = int(math.ceil(np.max(sc) / block))
        n = solver.IntVar(0, top, f"sp_{cloud}")
        var[("sp", cloud)] = n
        obj.SetCoefficient(n, block * (1 - d) * hours)
        fees.append((n, block * (1 - d) * world.HOURS_MONTH))
        S = len(sc)
        for si, s in enumerate(sc):
            for bi, u in enumerate(duration_buckets(s)):
                o = solver.NumVar(0, solver.infinity(), f"o_{cloud}_{si}_{bi}")
                c = solver.Constraint(float(u), solver.infinity())      # o + block * n >= u
                c.SetCoefficient(o, 1)
                c.SetCoefficient(n, block)
                obj.SetCoefficient(o, hours / S / 96)
    for (cloud, typ), count in dbs.items():
        d = world.CLOUDS[cloud]["ri"]
        p = world.price(cloud, "db", next(k for k in range(len(world.SIZES)) if world.type_name(cloud, "db", k) == typ))
        k = solver.IntVar(0, count, f"ri_{cloud}_{typ}")
        var[("ri", cloud, typ)] = k
        o = solver.NumVar(0, solver.infinity(), f"ro_{cloud}_{typ}")
        c = solver.Constraint(count, solver.infinity())
        c.SetCoefficient(o, 1)
        c.SetCoefficient(k, 1)
        obj.SetCoefficient(k, p * (1 - d) * hours)
        obj.SetCoefficient(o, p * hours)
        fees.append((k, p * (1 - d) * world.HOURS_MONTH))
    if budget_per_month is not None:
        c = solver.Constraint(0, float(budget_per_month))
        for v, f in fees:
            c.SetCoefficient(v, f)
    status = solver.Solve()
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        raise RuntimeError("commitment MILP found no solution")
    for key, v in var.items():
        if key[0] == "sp":
            plan["compute_sp"][key[1]] = round(v.solution_value() * block, 2)
        else:
            plan["db_ri"][f"{key[1]}|{key[2]}"] = int(round(v.solution_value()))
    plan["optimal"] = status == pywraplp.Solver.OPTIMAL
    plan["objective"] = round(solver.Objective().Value(), 2)
    return plan


def portfolio_cost(plan, pools, dbs, hours):
    """Expected cost of a plan over `hours` on scenarios (or on one actual path), split into fees, on-demand and unused."""
    out = {"fees": 0.0, "on_demand": 0.0, "unused": 0.0, "eligible_on_demand": 0.0, "covered": 0.0}
    for cloud, sc in pools.items():
        d = world.CLOUDS[cloud]["sp"]
        c = plan["compute_sp"].get(cloud, 0.0)
        sc = np.atleast_2d(sc)
        scale = hours / sc.shape[1]
        out["fees"] += c * (1 - d) * hours
        out["on_demand"] += float(np.maximum(sc - c, 0).sum(1).mean()) * scale
        out["unused"] += float(np.maximum(c - sc, 0).sum(1).mean()) * (1 - d) * scale
        out["eligible_on_demand"] += float(sc.sum(1).mean()) * scale
        out["covered"] += float(np.minimum(sc, c).sum(1).mean()) * scale
    for (cloud, typ), count in dbs.items():
        d = world.CLOUDS[cloud]["ri"]
        p = world.price(cloud, "db", next(k for k in range(len(world.SIZES)) if world.type_name(cloud, "db", k) == typ))
        k = plan["db_ri"].get(f"{cloud}|{typ}", 0)
        out["fees"] += k * p * (1 - d) * hours
        out["on_demand"] += max(count - k, 0) * p * hours
        out["unused"] += max(k - count, 0) * p * (1 - d) * hours
        out["eligible_on_demand"] += count * p * hours
        out["covered"] += min(k, count) * p * hours
    out["total"] = out["fees"] + out["on_demand"]
    return {k: round(v, 2) for k, v in out.items()}


def last_month_minimum(eligible, db_running):
    """The baseline: commit to the lowest hourly compute spend of the last 30 days; reserve every database that ran all month."""
    return {"compute_sp": {c: round(float(np.floor(np.min(s))), 2) for c, s in eligible.items()},
            "db_ri": {f"{c}|{t}": int(n) for (c, t), n in db_running.items() if n > 0}}


# --- savings verification -----------------------------------------------------------------------------------------------------
def pool_key(cloud, kind, size=None):
    """The pricing pool a resource's usage falls in: compute per cloud (savings plans), a database type (reservations), storage."""
    if kind in ("vm", "pool"):
        return f"compute:{cloud}"
    if kind == "db":
        return f"db:{cloud}:{world.type_name(cloud, 'db', size)}"
    return f"storage:{cloud}"


def unit_price(r, cfg):
    if r["kind"] == "volume":
        return world.price(r["cloud"], "volume", gb=r["gb"])
    return world.price(r["cloud"], r["kind"], world.NODE_SIZE if r["kind"] == "pool" else cfg["size"])


def counterfactual_delta(r, old, new, post, pre_running_how, t_from):
    """What the old configuration would have cost, hour by hour, minus what was paid at list price, by pricing pool.
    old/new: {size | min_nodes}; post: the post window's observed hourly units, cpu_util and the demand of the hour before
    (pools); pre_running_how: running share by hour of week before the change (for a terminated machine, whose hours
    after it can no longer be observed); t_from: absolute hour of the window's first hour."""
    H = len(post["units"])
    if new.get("terminate"):
        if r["kind"] == "volume":
            units_cf = np.ones(H)
        else:
            units_cf = (pre_running_how[np.arange(t_from, t_from + H) % WEEK] >= 0.5).astype(float)
        return {pool_key(r["cloud"], r["kind"], old.get("size")): units_cf * unit_price(r, old)}
    if r["kind"] == "pool":
        cap = world.VCPU[world.NODE_SIZE]
        demand = post["cpu_util"] * post["units"] * cap
        nodes_cf, _ = autoscale(demand, post["prev"], old["min_nodes"], r["max_nodes"])
        return {pool_key(r["cloud"], "pool"): (nodes_cf - post["units"]) * unit_price(r, old)}
    run_h = post["units"]
    if r["kind"] == "db":
        return {pool_key(r["cloud"], "db", old["size"]): run_h * unit_price(r, old), pool_key(r["cloud"], "db", new["size"]): -run_h * unit_price(r, new)}
    return {pool_key(r["cloud"], r["kind"]): run_h * (unit_price(r, old) - unit_price(r, new))}


def future_spend(r, h, cfg, t_next, H, S, rng):
    """Forecast hourly on-demand spend of one resource over the next H hours under configuration cfg, as S scenarios
    (pools vary with demand; machines follow their observed running schedule). -> (S, H) or None (not commitment-eligible)."""
    if r["kind"] == "volume" or cfg.get("terminate"):
        return None
    if r["kind"] == "pool":
        cap = world.VCPU[world.NODE_SIZE]
        demand = h["cpu_util"] * h["units"] * cap
        m = fit_forecast(demand, t_next - len(demand))
        nodes, _ = autoscale(sample_paths(m, t_next, H, S, rng), demand[-1], cfg["min_nodes"], r["max_nodes"])
        return nodes * unit_price(r, cfg)
    n = len(h["units"])
    t0 = t_next - n
    run_how = running_share(h["units"] > 0, t0) >= 0.5
    return np.tile(run_how[np.arange(t_next, t_next + H) % WEEK] * unit_price(r, cfg), (S, 1))


def pool_bill(E, C, d):
    """What a pricing pool pays per hour: eligible on-demand spend E under commitment coverage C (on-demand $ per hour, a
    savings plan's amount or a reservation's count times its price) at discount d. The same rule for compute savings
    plans, database reservations and (with C = 0) everything else."""
    return float((C * (1 - d) + np.maximum(E - C, 0)).sum())


def verify(treated, pools, controls, pre_days, post_days):
    """treated: [{id, cloud, kind, delta: {pool: (H,) counterfactual minus actual on-demand $ per hour}, eff_pre, eff_post}];
    pools: {pool: (E (H,), C (H,), d)} as observed over the post window; controls: {(cloud, kind): (pre $, post $)} for
    untouched resources. -> (per-resource rows, totals by method).

    counterfactual   each pool billed with and without the changes' hourly deltas, through the commitments in force
    did              treated cost before x (controls after / controls before) - treated cost after
    before_after     treated cost before - treated cost after (per day, scaled to the post window)
    list_price       the deltas at on-demand prices, ignoring commitments (what a recommendation promises)"""
    saved = {}
    for g in sorted({g for t in treated for g in t["delta"]}):
        D = sum(t["delta"][g] for t in treated if g in t["delta"])
        E, C, d = pools.get(g, (np.zeros_like(D), np.zeros_like(D), 0.0))      # a type nothing runs on any more
        saved[g] = (pool_bill(E + D, C, d) - pool_bill(E, C, d), float(D.sum()))
    rows, total = [], {"counterfactual": 0.0, "did": 0.0, "before_after": 0.0, "list_price": 0.0}
    for t in treated:
        est = sum(saved[g][0] * float(t["delta"][g].sum()) / saved[g][1] for g in t["delta"] if abs(saved[g][1]) > 1e-9)
        listed = sum(float(v.sum()) for v in t["delta"].values())
        pre_c, post_c = controls.get((t["cloud"], t["kind"]), (0.0, 0.0))
        ratio = post_c / pre_c if pre_c > 0 else 1.0                         # controls' cost per day after / before
        did = t["eff_pre"] / pre_days * ratio * post_days - t["eff_post"]
        ba = t["eff_pre"] / pre_days * post_days - t["eff_post"]
        rows.append({"resource_id": t["id"], "estimate": round(est, 2), "did": round(did, 2), "before_after": round(ba, 2), "list_price": round(listed, 2)})
        for k, v in (("counterfactual", est), ("did", did), ("before_after", ba), ("list_price", listed)):
            total[k] += v
    return rows, {k: round(v, 2) for k, v in total.items()}


# --- cost explanation ----------------------------------------------------------------------------------------------------------
def explain(a, b):
    """a, b: {key: (units, on-demand $, effective $, label)} for two periods of equal length -> the change in effective cost
    split into usage (units at the old effective rate), configuration (a different list price per unit: a resize),
    rate (a different discount on the same list price: commitments), new and removed resources."""
    usage = config = rate = new = gone = 0.0
    rows = []
    for k in set(a) | set(b):
        ua, oa, ea, la = a.get(k, (0, 0, 0, None))
        ub, ob, eb, lb = b.get(k, (0, 0, 0, None))
        if ua == 0 or ea == 0:
            new += eb - ea
            rows.append((k, lb, eb - ea, "new"))
            continue
        if ub == 0 or eb == 0:
            gone += eb - ea
            rows.append((k, la, eb - ea, "removed"))
            continue
        du = (ub - ua) * ea / ua
        dc = (ob / ub - oa / ua) * ub * (ea / oa if oa else 1.0)
        dr = (eb - ea) - du - dc
        usage, config, rate = usage + du, config + dc, rate + dr
        parts = {"usage": du, "configuration": dc, "rate": dr}
        rows.append((k, lb, eb - ea, max(parts, key=lambda x: abs(parts[x]))))
    rows.sort(key=lambda r: -abs(r[2]))
    return {"usage": round(usage, 2), "configuration": round(config, 2), "rate": round(rate, 2), "new_resources": round(new, 2), "removed_resources": round(gone, 2),
            "top": [{"resource": k, "label": lab, "delta": round(d, 2), "driver": drv} for k, lab, d, drv in rows[:10]]}
