"""Held-out evaluation on three fabs the demo never uses (different seeds, 14 excursions each, eight weeks).

    python -m fab.evaluate            # prints the markdown behind docs/evaluation.md

Each fab: the models are trained exactly as the service trains them (six weeks) and scored on the last two weeks; drift
detection and root cause are scored on every excursion of the eight weeks against the generator's truth, which the
service never sees.
"""
import collections
import sys

import numpy as np

from . import engine, world

SEEDS = (101, 102, 103)
N_LOTS, N_FAULTS, TEST_FROM = 448, 14, 336


def chamber_series(recs, baselines):
    out = collections.defaultdict(list)
    for r in recs:
        for st in r["steps"]:
            k = world.PRIMARY[st["step"]]
            med, sd = baselines[st["chamber"]][r["product"]][k]
            out[st["chamber"]].append((r["lot_index"], (st["sensors"][k] - med) / sd))
    return out


def one(seed):
    faults = world.random_faults(seed, N_LOTS, N_FAULTS)
    lots = world.run(seed, 0, N_LOTS, faults)
    recs = engine.records(lots)
    fitted = engine.fit(recs, TEST_FROM)
    pred, _ = engine.classify(fitted["classifier"], np.array([engine.map_features(r["bins"]) for r in recs]))
    series = chamber_series(recs, fitted["baselines"])

    def in_fault(ch, li):
        return any(f["chamber"] == ch and f["start_lot"] <= li < f["end_lot"] + 3 for f in faults)
    drift = {}
    for rule in ("bocpd", "shewhart"):
        alarms = {ch: [v[i][0] for i in engine.drift_alarms([z for _, z in v], rule)] for ch, v in series.items()}
        delays, detectable = [], 0
        for f in faults:
            runs = [z for li, z in series[f["chamber"]] if f["start_lot"] <= li < f["end_lot"]]
            if sum(abs(z) > 3 for z in runs) < 5:            # the fault never visibly moved the sensor (tool idle, or too small)
                continue
            detectable += 1
            hit = [li for li in alarms[f["chamber"]] if f["start_lot"] <= li < f["end_lot"]]
            delays.append(hit[0] - f["start_lot"] if hit else None)
        runs_total = sum(len(v) for v in series.values())
        false = sum(not in_fault(ch, li) for ch, lis in alarms.items() for li in lis)
        found = [d for d in delays if d is not None]
        drift[rule] = {"detectable": detectable, "detected": len(found), "median_delay_lots": float(np.median(found)) if found else None,
                       "false_alarms_per_1000_runs": round(1000 * false / runs_total, 2)}
    bocpd_alarms = {ch: [v[i][0] for i in engine.drift_alarms([z for _, z in v])] for ch, v in series.items()}
    ranks = collections.defaultdict(list)
    for f in faults:
        pat = world.FAULTS[f["kind"]][2]
        first = [r["lot_index"] for r, p in zip(recs, pred) if p == pat and f["start_lot"] <= r["lot_index"] < f["end_lot"]
                 and f["chamber"] in [s["chamber"] for s in r["steps"]]]
        if len(first) < 5:
            continue
        lo = first[0]
        win = [i for i, r in enumerate(recs) if lo - 8 <= r["lot_index"] < lo + 8]
        ws = [{"affected": pred[i] == pat, "route": {st["step"]: st["chamber"] for st in recs[i]["steps"]}} for i in win]
        drifting = {ch for ch, lis in bocpd_alarms.items() if any(lo - 20 <= li < lo + 8 for li in lis)}
        for name, use in (("full", ("commonality", "drift", "prior")), ("commonality + change-point", ("commonality", "drift")), ("commonality only", ("commonality",))):
            ranks[name].append([r["chamber"] for r in engine.root_cause(ws, pat, fitted["priors"], drifting, use)].index(f["chamber"]) + 1)
    other = engine.records(world.run(seed + 1000, 0, N_LOTS, world.random_faults(seed + 1000, N_LOTS, N_FAULTS)))
    yo = np.array([r["label"] for r in other])
    po = np.array(engine.classify(fitted["classifier"], np.array([engine.map_features(r["bins"]) for r in other]))[0])
    cross = {pat: {"wafers": int((yo == pat).sum()), "recall": round(float((po[yo == pat] == pat).mean()), 3),
                   "review": round(float((po[yo == pat] == "review").mean()), 3)} for pat in world.PATTERNS if (yo == pat).sum()}
    cross["_false_calls_on_none"] = round(float((po[yo == "none"] != "none").mean()), 4)
    return {"cross": cross, "classifier": fitted["metrics"]["classifier"], "yield": fitted["metrics"]["yield"], "drift": drift, "ranks": dict(ranks),
            "excursions": len(faults), "kinds": collections.Counter(f["kind"] for f in faults)}


def main():
    res = {s: one(s) for s in SEEDS}
    p = print
    p("# Evaluation\n")
    p(f"Three held-out fabs (seeds {', '.join(map(str, SEEDS))}), {N_LOTS} lots each, {N_FAULTS} excursions each across all five steps. Models are trained on "
      f"lots 0-{TEST_FROM - 1} exactly as the service trains them and scored on lots {TEST_FROM}-{N_LOTS - 1}; drift and root cause are scored on every "
      "excursion against the generator's truth. `python -m fab.evaluate` reproduces this file.\n")
    p("## Wafer-map pattern classifier\n")
    p("| Fab | Macro-F1 | Baseline (nearest centroid, radial profile) | Sent for review | Recall by pattern |\n|---|---|---|---|---|")
    for s, r in res.items():
        c = r["classifier"]
        p(f"| {s} | {c['macro_f1']} | {c['baseline_macro_f1']} | {c['abstained']:.1%} | " + ", ".join(f"{k} {v}" for k, v in c["per_pattern_recall"].items()) + " |")
    p("\nMacro-F1 over the patterns present in the test weeks; a wafer sent for review counts as a miss. Recall per pattern swings with how many "
      "examples of it the six training weeks happened to contain: a pattern seen in one short excursion is learned poorly, and a pattern never "
      "seen is sent for review rather than called normal (the novelty rule). Scratches and clusters come from handling and particles, not chambers.\n")
    p("**Trained on one fab, applied to all eight weeks of another** (seed + 1000), where every pattern occurs many times:\n")
    p("| Trained on | " + " | ".join(world.PATTERNS[1:]) + " | Normal wafers wrongly flagged |\n|---|" + "---|" * (len(world.PATTERNS) - 1) + "---|")
    for s, r in res.items():
        cr = r["cross"]
        p(f"| {s} | " + " | ".join(f"{cr[k]['recall']:.0%} ({cr[k]['wafers']})" if k in cr else "–" for k in world.PATTERNS[1:]) + f" | {cr['_false_calls_on_none']:.2%} |")
    p("\nRecall per pattern, wafers in brackets. A pattern the training fab rarely saw is the weak spot; the cure is labels, not a bigger model.\n")
    p("## Yield before test\n")
    p("| Fab | MAE, all test wafers (pp) | Baseline: product's trailing 20-lot mean | MAE, excursion wafers | Baseline |\n|---|---|---|---|---|")
    for s, r in res.items():
        y = r["yield"]
        p(f"| {s} | {y['mae_pp']} | {y['baseline_mae_pp']} | {y['mae_pp_excursion_wafers']} ({y['excursion_wafers']} wafers) | {y['baseline_mae_pp_excursion_wafers']} |")
    p("\nThe blueprint's bar is 2.5 percentage points. Most of the remaining error is incoming-material variation no sensor sees, and "
      "scratches and particle clusters, which no process sensor predicts.\n")
    p("## Drift detection on the chamber sensors\n")
    p("| Fab | Rule | Detected / detectable excursions | Median delay (lots) | False alarms per 1,000 runs |\n|---|---|---|---|---|")
    for s, r in res.items():
        for rule, name in (("bocpd", "Bayesian online change-point"), ("shewhart", "Shewhart 3-sigma")):
            d = r["drift"][rule]
            p(f"| {s} | {name} | {d['detected']} / {d['detectable']} | {d['median_delay_lots']} | {d['false_alarms_per_1000_runs']} |")
    p("\nAn excursion is detectable when its chamber ran at least five wafers more than 3 sigma off its qualified baseline; some excursions "
      "never were (the tool processed no lots while it lasted, or the drift stayed small). The two rules catch about the same excursions "
      "about as fast; the change-point detector does it with a small fraction of the false alarms, which is what makes an alert worth reading "
      "across 27 chambers.\n")
    p("## Root cause ranking\n")
    p("| Fab | Excursions ranked | Full: top-1 | Full: top-3 | Commonality + change-point: top-3 | Commonality only: top-3 |\n|---|---|---|---|---|---|")
    tot = collections.defaultdict(list)
    for s, r in res.items():
        rk = r["ranks"]
        for k, v in rk.items():
            tot[k] += v
        f = lambda k, n: f"{np.mean([x <= n for x in rk[k]]):.0%}"      # noqa: E731
        p(f"| {s} | {len(rk['full'])} | {f('full', 1)} | {f('full', 3)} | {f('commonality + change-point', 3)} | {f('commonality only', 3)} |")
    f = lambda k, n: f"{np.mean([x <= n for x in tot[k]]):.0%}"           # noqa: E731
    p(f"| **all** | {len(tot['full'])} | {f('full', 1)} | {f('full', 3)} | {f('commonality + change-point', 3)} | {f('commonality only', 3)} |")
    p("\nThe blueprint's bar is top-3 recall above 85% on injected faults. An excursion is ranked when the classifier called its pattern on at "
      "least five wafers from the faulty chamber; the window is eight lots either side of the first. Commonality alone is confused when two "
      "excursions overlap or a pattern has two possible steps (random-high comes from deposition or implant); the change-point on the "
      "chamber's own sensor is what separates them.\n")
    return res


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
    sys.exit(0)
