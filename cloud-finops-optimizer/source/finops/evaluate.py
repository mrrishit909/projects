"""Held-out evaluation on three estates the demo never uses (other seeds), each with eight weeks of history and thirteen
weeks that follow.

    python -m finops.evaluate            # prints the markdown behind docs/evaluation.md

Each estate is analysed exactly as the service analyses one (what a cloud API shows: utilisation, units, billing); the
weeks after the history, and the generator's truth (true demand, which resources are idle or bursty, the bill with and
without a change), are used only to score.
"""
import collections
import sys

import numpy as np

from . import engine, world

SEEDS = (101, 102, 103)
HIST = world.HISTORY_DAYS
APPLY = HIST + 1                    # changes merged and applied, commitments bought, the day after the analysis
POST = 28                           # the verifier's window
COMMIT_DAYS = 91                    # thirteen weeks of a one-year term
KEYS = ("cpu_util", "mem_util", "units", "io")


def rdict(r):
    return {"id": r["external_id"], "kind": r["kind"], "cloud": r["cloud"], "size": r.get("size"), "min_nodes": r.get("min_nodes"),
            "max_nodes": r.get("max_nodes"), "gb": r.get("gb"), "env": r["env"], "account": r["account"]}


def history(sim, r, d_from, d_to):
    i, lo = r["idx"], max(d_from, r["launched_day"])
    return {k: sim[k][i, lo - sim["d0"]:d_to - sim["d0"]].ravel() for k in KEYS}, lo * 24


def future(sim, r, d_from, d_to):
    i, sl = r["idx"], slice(d_from - sim["d0"], d_to - sim["d0"])
    return {"cpu": sim["cpu_demand"][i, sl].ravel(), "mem": sim["mem_demand"][i, sl].ravel(), "running": sim["units"][i, sl].ravel() > 0,
            "prev": sim["cpu_demand"][i, d_from - sim["d0"] - 1, 23], "attach": sim["units"][i, sl].ravel() if r["kind"] == "volume" else None}


def judged(r, day):
    """Resources the analysis can judge on `day` and the four weeks after can score."""
    return r["launched_day"] <= day - 1 and (r["terminated_day"] is None or r["terminated_day"] >= day + POST + 1)


def one(seed):
    res = world.estate(seed)
    sim = world.run(seed, 0, APPLY + COMMIT_DAYS)
    rng = np.random.default_rng(seed)
    out = {"resources": sum(r["launched_day"] < HIST and (r["terminated_day"] is None or r["terminated_day"] >= HIST) for r in res)}

    # forecast: point WAPE against seasonal naive, and how often the true p99 stays under the forecast's 90% path p99
    err = collections.Counter()
    cover = []
    for r in res:
        if r["kind"] not in ("vm", "db", "pool") or r["launched_day"] > 0 or not judged(r, HIST) or r.get("batch"):
            continue
        h, t0 = history(sim, r, 0, HIST)
        cap = world.VCPU[r["size"]]
        y = h["cpu_util"] * (h["units"] * cap if r["kind"] == "pool" else cap)
        f = sim["cpu_util"][r["idx"], HIST:HIST + POST].ravel() * (sim["units"][r["idx"], HIST:HIST + POST].ravel() * cap if r["kind"] == "pool" else cap)
        m = engine.fit_forecast(y, t0)
        pred = engine.predict(m, HIST * 24, POST * 24)
        snaive = np.tile(y[-engine.WEEK:], POST * 24 // engine.WEEK)
        err["abs_model"] += np.abs(f - pred).sum()
        err["abs_naive"] += np.abs(f - snaive).sum()
        err["actual"] += np.abs(f).sum()
        run = sim["units"][r["idx"], HIST:HIST + POST].ravel() > 0
        if run.any():
            paths = engine.sample_paths(m, HIST * 24, POST * 24, 100, rng)
            cover.append(np.quantile(f[run], 0.99) <= np.quantile(np.quantile(paths[:, run], 0.99, axis=1), 0.9) + 1e-9)
    out["forecast"] = {"wape": round(err["abs_model"] / err["actual"], 3), "wape_naive": round(err["abs_naive"] / err["actual"], 3),
                       "p99_covered": round(float(np.mean(cover)), 3), "series": len(cover)}

    # risk model: trained on the estate's own history (cut at day 28, labelled by the four weeks after), scored on the future
    X, y = [], []
    for r in res:
        if r["kind"] in ("vm", "db") and r["launched_day"] == 0 and judged(r, 28) and (r["terminated_day"] is None or r["terminated_day"] > HIST):
            h, t0 = history(sim, r, 0, 28)
            for s, feats in engine.candidate_features(rdict(r), h, t0, rng):
                X.append([feats[k] for k in engine.RISK_FEATURES])
                y.append(engine.breached(rdict(r), {"set": {"size": r["size"] - s}}, engine.observed(rdict(r), history(sim, r, 28, HIST)[0])))
    risk_model = engine.train_risk(X, y) if len(set(y)) > 1 else None
    Xf, yf = [], []

    # rightsizing at the end of the history, ours against the average-utilisation rule, scored on the next four weeks
    rs = {"ours": [], "naive": []}
    review = 0
    for r in res:
        if not judged(r, HIST):
            continue
        h, t0 = history(sim, r, 0, HIST)
        rr = rdict(r)
        fut = future(sim, r, HIST, HIST + POST)
        rec = engine.rightsize(rr, h, t0, rng)
        if rec and rec["action"] == "review":
            review += 1
        elif rec:
            feats = rec.pop("_features", None)
            rec["risk"] = engine.risk_score(risk_model, feats) if feats else None
            rs["ours"].append((r, rec, engine.breached(rr, rec, fut)))
        nv = engine.naive(rr, h)
        if nv:
            rs["naive"].append((r, nv, engine.breached(rr, nv, fut)))
        if r["kind"] in ("vm", "db") and r["launched_day"] == 0:
            for s, feats in engine.candidate_features(rr, h, t0, rng):
                Xf.append([feats[k] for k in engine.RISK_FEATURES])
                yf.append(engine.breached(rr, {"set": {"size": r["size"] - s}}, fut))
    for k, recs in rs.items():
        fp = [x for x in recs if x[2]]
        out[k] = {"recommendations": len(recs), "false_positives": len(fp), "fp_rate": round(len(fp) / max(1, len(recs)), 3),
                  "monthly_savings": round(sum(x[1]["monthly_savings"] for x in recs)), "safe_monthly_savings": round(sum(x[1]["monthly_savings"] for x in recs if not x[2])),
                  "fp_by_class": dict(collections.Counter(x[0]["cls"] for x in fp)), "by_action": dict(collections.Counter(x[1]["action"] for x in recs))}
    out["ours"]["review"] = review
    gated = [x for x in rs["ours"] if x[1]["risk"] is None or x[1]["risk"] <= engine.POLICY["risk_review_above"]]
    out["ours_gated"] = {"recommendations": len(gated), "false_positives": sum(x[2] for x in gated), "fp_rate": round(sum(x[2] for x in gated) / max(1, len(gated)), 3),
                         "monthly_savings": round(sum(x[1]["monthly_savings"] for x in gated))}
    out["risk"] = engine.score_risk(risk_model, Xf, yf) if risk_model else None
    out["risk_train"] = {"n": len(y), "positives": int(sum(y))}

    # commitments: the portfolio after the gated changes, against last month's minimum, regret on the thirteen weeks after
    applied = [(r, rec) for r, rec, _ in rs["ours"] if rec["risk"] is None or rec["risk"] <= engine.POLICY["risk_review_above"]]
    changes = [{"resource": r["external_id"], "day": APPLY, "set": rec["set"]} for r, rec in applied]
    planned = {r["external_id"]: rec["set"] for r, rec in applied}
    H = COMMIT_DAYS * 24
    pools, dbs = collections.defaultdict(lambda: 0), collections.Counter()
    for r in res:
        if not (r["launched_day"] <= HIST - 1 and (r["terminated_day"] is None or r["terminated_day"] >= HIST)):
            continue
        cfg = {"size": r.get("size"), "min_nodes": r.get("min_nodes"), **planned.get(r["external_id"], {})}
        if r["kind"] == "db" and not cfg.get("terminate"):
            dbs[(r["cloud"], world.type_name(r["cloud"], "db", cfg["size"]))] += 1
            continue
        h, _ = history(sim, r, 0, HIST)
        sp = engine.future_spend(rdict(r), h, cfg, APPLY * 24, H, engine.POLICY["scenarios"], rng)
        if sp is not None:
            pools[r["cloud"]] = pools[r["cloud"]] + sp
    pools = dict(pools)
    plan = engine.optimise(pools, dict(dbs), H)
    comp = np.array([r["kind"] in ("vm", "pool") for r in res])
    clouds = np.array([r["cloud"] for r in res])
    last = slice(HIST - 30, HIST)
    elig = {c: sim["od"][comp & (clouds == c), last].sum(0).ravel() for c in world.CLOUDS}
    db_run = collections.Counter()
    for r in res:
        if r["kind"] == "db" and (sim["units"][r["idx"], last] > 0).all():
            db_run[(r["cloud"], world.type_name(r["cloud"], "db", r["size"]))] += 1
    base = engine.last_month_minimum(elig, db_run)
    act = world.run(seed, APPLY, APPLY + COMMIT_DAYS, changes)
    actual = {c: act["od"][comp & (clouds == c)].sum(0).ravel()[None] for c in world.CLOUDS}
    adb = collections.Counter()
    for r in res:
        if r["kind"] == "db":
            on = act["units"][r["idx"]] > 0
            if on.any():
                adb[(r["cloud"], world.type_name(r["cloud"], "db", int(act["size"][r["idx"], -1])))] += 1
    for k in list(dbs) + list(db_run):
        adb.setdefault(k, 0)
    hind = engine.optimise(actual, dict(adb), H)
    none = {"compute_sp": {}, "db_ri": {}}
    cost = {k: engine.portfolio_cost(p, actual, dict(adb), H) for k, p in (("optimised", plan), ("baseline", base), ("hindsight", hind), ("none", none))}
    out["commit"] = {"cost": {k: v["total"] for k, v in cost.items()}, "unused": {k: v["unused"] for k, v in cost.items()},
                     "regret": {k: round(cost[k]["total"] - cost["hindsight"]["total"]) for k in ("optimised", "baseline", "none")},
                     "plan": plan, "baseline_plan": base}

    # savings verification: the gated changes and the portfolio applied on day APPLY; four weeks later, every method against the truth
    commits = [{"id": f"sp-{c}", "cloud": c, "kind": "compute_sp", "amount": a, "start_day": APPLY} for c, a in plan["compute_sp"].items() if a > 0]
    commits += [{"id": f"ri-{k}", "cloud": k.split("|")[0], "kind": "db_ri", "type": k.split("|")[1], "amount": n, "start_day": APPLY} for k, n in plan["db_ri"].items() if n > 0]
    out["verify"] = verify_one(seed, res, sim, applied, commits)
    return out


def verify_one(seed, res, base_sim, applied, commits, pre=14):
    lo = APPLY - pre
    w = world.run(seed, lo, APPLY + POST, [{"resource": r["external_id"], "day": APPLY, "set": rec["set"]} for r, rec in applied], commits)
    wo = world.run(seed, lo, APPLY + POST, [], commits)
    truth = world.bill(wo, (APPLY, APPLY + POST)) - world.bill(w, (APPLY, APPLY + POST))
    rate_truth = world.bill(world.run(seed, lo, APPLY + POST, [{"resource": r["external_id"], "day": APPLY, "set": rec["set"]} for r, rec in applied], []), (APPLY, APPLY + POST)) - world.bill(w, (APPLY, APPLY + POST))
    post = slice(pre, pre + POST)
    H = POST * 24
    keys = [engine.pool_key(r["cloud"], r["kind"], int(w["size"][r["idx"], pre])) for r in res]
    od = w["od"][:, post].reshape(len(res), -1)
    pools = {}
    keys_all = set(keys) | {f"db:{c['cloud']}:{c['type']}" for c in commits if c["kind"] == "db_ri"}
    for k in keys_all:
        idx = [i for i, kk in enumerate(keys) if kk == k]
        E = od[idx].sum(0) if idx else np.zeros(H)
        C = np.zeros(H)
        cloud = k.split(":")[1]
        for c in commits:
            if c["kind"] == "compute_sp" and k == f"compute:{c['cloud']}":
                C = C + c["amount"]
            if c["kind"] == "db_ri" and k == f"db:{c['cloud']}:{c['type']}":
                C = C + c["amount"] * engine.unit_price({"kind": "db", "cloud": c["cloud"]}, {"size": next(s for s in range(5) if world.type_name(c["cloud"], "db", s) == c["type"])})
        d = world.CLOUDS[cloud]["sp"] if k.startswith("compute") else world.CLOUDS[cloud]["ri"] if k.startswith("db") else 0.0
        pools[k] = (E, C, d)
    treated, touched = [], set()
    for r, rec in applied:
        i = r["idx"]
        touched.add(i)
        pre_units = base_sim["units"][i, :HIST].ravel() > 0
        how = engine.running_share(pre_units, 0)
        p = {"units": w["units"][i, post].ravel(), "cpu_util": w["cpu_util"][i, post].ravel(),
             "prev": float(w["cpu_util"][i, pre - 1, 23] * w["units"][i, pre - 1, 23] * world.VCPU[world.NODE_SIZE])}
        old = {"size": r.get("size"), "min_nodes": r.get("min_nodes")}
        delta = engine.counterfactual_delta(rdict(r), old, rec["set"], p, how, APPLY * 24)
        treated.append({"id": r["external_id"], "cloud": r["cloud"], "kind": r["kind"], "delta": delta,
                        "eff_pre": float(w["eff"][i, :pre].sum()), "eff_post": float(w["eff"][i, post].sum())})
    controls = collections.defaultdict(lambda: [0.0, 0.0])
    for r in res:
        i = r["idx"]
        if i in touched or not w["alive"][i].all():
            continue
        controls[(r["cloud"], r["kind"])][0] += float(w["eff"][i, :pre].sum()) / pre
        controls[(r["cloud"], r["kind"])][1] += float(w["eff"][i, post].sum()) / POST
    rows, total = engine.verify(treated, pools, {k: tuple(v) for k, v in controls.items()}, pre, POST)
    errs = {k: round(abs(v - truth) / truth, 4) for k, v in total.items()}
    return {"truth": round(truth, 2), "estimates": total, "error": errs, "changes": len(applied), "commitment_rate_savings_truth": round(rate_truth, 2)}


def main():
    res = {s: one(s) for s in SEEDS}
    p = print
    usd = lambda v: f"${v:,.0f}"          # noqa: E731
    p("# Evaluation\n")
    p(f"Three held-out estates (seeds {', '.join(map(str, SEEDS))}), each six accounts on three clouds with {HIST} days of history and "
      f"{COMMIT_DAYS} days after it. Every estate is analysed exactly as the service analyses one (utilisation, units and billing as a cloud "
      "API reports them); the days after the history and the generator's truth (true demand, the bill with and without each change) only score. "
      "`python -m finops.evaluate` reproduces this file.\n")
    p("## Workload forecast (four weeks ahead, per resource)\n")
    p("| Estate | Series | WAPE | Baseline: seasonal naive (last week again) | True p99 under the forecast's 90% path p99 |\n|---|---|---|---|---|")
    for s, r in res.items():
        f = r["forecast"]
        p(f"| {s} | {f['series']} | {f['wape']:.3f} | {f['wape_naive']:.3f} | {f['p99_covered']:.1%} |")
    p("\nCPU demand of every machine, database and node pool alive for the whole history (the batch training pool excluded: its jobs are "
      "random by construction). The last column is the calibration the rightsizer relies on: it sizes to the 90th percentile of the "
      "forecast's p99 across sample paths, so about 90% is the target.\n")
    p("## Rightsizing under the SLO, scored on the four weeks after\n")
    p("A recommendation is a false positive when, on the four weeks after the history, the resource at its new size would have broken the "
      "SLO by the generator's true demand: hours above 90% CPU more than 1% of running hours beyond what its current size shows, memory above "
      "100% in any hour, a terminated machine or deleted volume that was needed, or a node-pool floor that adds more than 1% hot hours.\n")
    p("| Estate | Recommendations | False positives | FP rate | $/month | Baseline: 14-day average rule | Its FPs | Its FP rate | Its $/month (of which safe) |\n|---|---|---|---|---|---|---|---|---|")
    for s, r in res.items():
        o, n = r["ours"], r["naive"]
        p(f"| {s} | {o['recommendations']} | {o['false_positives']} | {o['fp_rate']:.1%} | {usd(o['monthly_savings'])} | {n['recommendations']} | {n['false_positives']} | {n['fp_rate']:.1%} | {usd(n['monthly_savings'])} ({usd(n['safe_monthly_savings'])}) |")
    tot = {k: sum(r[k]["recommendations"] for r in res.values()) for k in ("ours", "naive")}
    fps = {k: sum(r[k]["false_positives"] for r in res.values()) for k in ("ours", "naive")}
    p(f"| **all** | {tot['ours']} | {fps['ours']} | {fps['ours'] / tot['ours']:.1%} | | {tot['naive']} | {fps['naive']} | {fps['naive'] / tot['naive']:.1%} | |")
    cls = collections.Counter()
    for r in res.values():
        cls.update(r["naive"]["fp_by_class"])
    p("\nThe blueprint's bar is a false-positive rate under 10%. The baseline's false positives by what the generator knows the workload to be: "
      + ", ".join(f"{k} {v}" for k, v in cls.most_common()) + " (oversized machines too: the rule shrinks them until the *average* is 40%, "
      "which puts the daily peak over the line; weekly = a volume attached for a Sunday restore test). The rightsizer finds more safe savings "
      "than the rule's safe part because it can go two sizes down where the forecast allows. Review tasks (too little history, CPU pinned at "
      "100%): " + ", ".join(str(r["ours"]["review"]) for r in res.values()) + ".\n")
    p("Applied after change-risk gating (risk above 0.25 goes to review):\n")
    p("| Estate | Changes applied | False positives | $/month |\n|---|---|---|---|")
    for s, r in res.items():
        g = r["ours_gated"]
        p(f"| {s} | {g['recommendations']} | {g['false_positives']} | {usd(g['monthly_savings'])} |")
    p("\n## Change-risk scoring\n")
    p("Trained on each estate's own history (features four weeks before the end of the history for every one- and two-size resize, labelled by "
      "the observed four weeks that followed), scored on every one- and two-size resize at the end of the history against the true four weeks after.\n")
    p("| Estate | Training rows (positives) | Scored | AUC | Baseline: headroom alone | Baseline: environment and kind rule | Brier | Mean predicted vs observed |\n|---|---|---|---|---|---|---|---|")
    for s, r in res.items():
        k, t = r["risk"], r["risk_train"]
        p(f"| {s} | {t['n']} ({t['positives']}) | {k['n']} | {k['auc']} | {k['auc_headroom_only']} | {k['auc_env_kind_rule']} | {k['brier']} | {k['mean_predicted']} vs {k['observed_rate']} |")
    p("\nMost of what the model knows is the forecast headroom at the new size, which the rightsizer already uses; the other features "
      "(burstiness, growth, backtest error, environment, kind) add a little. A change board's rule of thumb (production databases risky, dev safe) "
      "barely ranks better than chance here.\n")
    p("## Commitment portfolio, regret on the thirteen weeks after\n")
    p("The portfolio (one-year compute savings plans per cloud in $1/h blocks, database reservations per type) is chosen on twenty forecast "
      "scenarios of usage after the gated changes; then the changes are applied and the real thirteen weeks run, including machines the teams "
      "launch and retire. Regret is the cost over those weeks minus the cost of the best portfolio chosen with hindsight on the same weeks.\n")
    p("| Estate | No commitments | Hindsight best | Optimised: regret | Unused fees | Baseline (last month's minimum): regret | Unused fees |\n|---|---|---|---|---|---|---|")
    for s, r in res.items():
        c = r["commit"]
        p(f"| {s} | {usd(c['cost']['none'])} | {usd(c['cost']['hindsight'])} | {usd(c['regret']['optimised'])} ({c['regret']['optimised'] / c['cost']['hindsight']:.1%}) | {usd(c['unused']['optimised'])} | "
          f"{usd(c['regret']['baseline'])} ({c['regret']['baseline'] / c['cost']['hindsight']:.1%}) | {usd(c['unused']['baseline'])} |")
    p("\nMost of the value is committing at all (about a quarter off). The baseline's regret is the sequencing mistake: it commits to last "
      "month's usage before the rightsizing, and pays for commitments the smaller estate no longer uses. Thirteen weeks is the start of a "
      "one-year term; churn and growth over the rest of it are not scored.\n")
    p("## Savings verification, against the generator's truth\n")
    p(f"The gated changes and the optimised portfolio take effect on day {APPLY}; {POST} days later each method estimates what the changes "
      "saved over those days. The truth is the generator's bill for the same days re-run without the changes (same demand, same "
      "commitments, same churn).\n")
    p("| Estate | Changes | True savings | Counterfactual re-pricing | Error | List price | Error | Difference-in-differences | Error | Before / after | Error |\n|---|---|---|---|---|---|---|---|---|---|---|")
    for s, r in res.items():
        v = r["verify"]
        e, x = v["estimates"], v["error"]
        p(f"| {s} | {v['changes']} | {usd(v['truth'])} | {usd(e['counterfactual'])} | {x['counterfactual']:.1%} | {usd(e['list_price'])} | {x['list_price']:.1%} | "
          f"{usd(e['did'])} | {x['did']:.1%} | {usd(e['before_after'])} | {x['before_after']:.1%} |")
    p("\nThe blueprint's bar is an attribution error under 5%. The counterfactual puts the old configurations' hourly on-demand cost back into "
      "each pricing pool and bills the pool again through the commitments in force, so a dollar above a savings plan saves a dollar and a "
      "dollar inside an under-used one saves nothing. What it cannot observe it has to model: the node-pool autoscaler (the service's model "
      "does not know the real one removes nodes one an hour), demand hidden while a pool ran at 100%, and a terminated machine's hours after "
      "it was gone (taken from its schedule before); its residual error was not broken down by source. This is the best case: the verifier prices with the same catalogue and allocation rule the "
      "generator bills by, where a real bill adds credits, private discounts and amortisation. Before/after counts the new commitments' "
      "discount as rightsizing; difference-in-differences scales each resource's cost before by how much the untouched resources' cost "
      "moved, which prices savings at their average discounted rate (the margin above a fixed commitment is paid at full price) and carries "
      "their own usage changes, so it misses in either direction; the list price ignores commitments.\n")
    return res


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
    sys.exit(0)
