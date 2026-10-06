"""Held-out evaluation on three metros the demo never uses (different seeds, so different topologies, traffic and faults).

    python -m noc.evaluate            # prints the markdown behind docs/evaluation.md

Each metro: four weeks with 24 faults in the first three and a dense fourth week of 18 more (three of each kind), so the
detectors are scored on many events. The models are trained exactly as the service trains them (three weeks, on intervals
with no fault alarm nearby) and scored on the fourth. Correlation and root cause run over all four weeks, interval by
interval, as the live path does. Then eight capacity incidents per metro are played forward a day after the history: the
optimiser plans on the forecast, and the generator re-runs the same day with no change, with the plan, and with every
possible reroute, to see what actually happens. Everything is scored against the generator's truth, which the service never sees.
"""
import collections
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression

from . import engine, world

SEEDS = (101, 102, 103)
T = 28 * world.PER_DAY
TRAIN_END = 21 * world.PER_DAY
ENVELOPE = {"max_link_utilisation": 0.8, "forecast_margin": 0.05, "max_elements_changed": 3, "allowed_actions": ["reroute_site", "rollback_config"], "horizon_hours": 24}
TOPOLOGY_ONLY = {"topology": 1, "own_cause": 0, "own_symptom": 0, "anomalous": 0, "config_change": 0, "first": 0}


def faults_for(net, seed):
    early = world.random_faults(net, seed, 2 * world.PER_DAY, TRAIN_END, 24)
    late = world.random_faults(net, seed + 500, TRAIN_END, T + 24, 18)
    for f in late:
        f["id"] = "T" + f["id"][1:]
    return early + late


def correlate(net, sim, out, single, pers, lflag):
    """The live path over the whole history: derived anomaly alarms, evidence, the correlator. -> (correlator, alarms)."""
    topo = engine.Topology(net)
    evidence, configs = collections.defaultdict(set), collections.defaultdict(list)
    for t, i in zip(*np.nonzero(pers)):
        evidence[net["cells"][i]["id"]].add(int(t))
    for t, j in zip(*np.nonzero(lflag)):
        evidence[net["links"][j]["id"]].add(int(t))
    for o in out:
        for r in o["config"]:
            configs[r[1]].append(r[0])
    cor = engine.Correlator(topo, evidence, configs)
    standing, prev_v, alarms, n = set(), np.zeros(len(net["cells"]), bool), [], 0
    for o in out:
        t = o["t"]
        batch = []
        for a in o["alarms"]:
            n += 1
            batch.append({"id": n, "t": t, "minute": a[1], "element": a[2], "type": a[3], "related": a[5], "cause": a[6]})
        v = np.zeros(len(net["cells"]), bool)
        for a in batch:
            if a["element"] in sim.cell_ix:
                v[sim.cell_ix[a["element"]]] = True
        if t:
            for i in engine.derived_alarms(single[t - 1], single[t], v | prev_v, standing):
                n += 1
                batch.append({"id": n, "t": t, "minute": 14, "element": net["cells"][i]["id"], "type": "KPI_ANOMALY", "related": None, "cause": o["cause"][i] or ""})
        prev_v = v
        cor.feed(t, batch)
        alarms += batch
    return cor, alarms


def final(cor, iid):
    while cor.incidents[iid]["status"] == "merged":
        iid = cor.incidents[iid]["merged_into"]
    return cor.incidents[iid]


def purity(groups):
    """Share of alarms whose cause is their group's main cause. Noise has no fault behind it: repeats of one element's alarm
    type are one cause, two unrelated noise alarms are two."""
    n = sum(len(g) for g in groups)
    key = lambda a: a["cause"] or (a["element"], a["type"])      # noqa: E731
    return sum(collections.Counter(key(a) for a in g).most_common(1)[0][1] for g in groups if g) / max(1, n)


def baseline_partition(topo, alarms, by, gap=4):
    key = (lambda a: (a["element"], a["type"])) if by == "dedup" else (lambda a: topo.site_of(a["element"]))
    groups, last, cur = [], {}, {}
    for a in sorted(alarms, key=lambda a: (a["t"], a["minute"])):
        k = key(a)
        if k not in last or a["t"] - last[k] > gap:
            cur[k] = []
            groups.append(cur[k])
        cur[k].append(a)
        last[k] = a["t"]
    return groups


def scenarios(net, seed, ad, fc, n=8):
    """Capacity incidents after the history: plan on the forecast, then re-run the generator to see what happened."""
    rng = np.random.default_rng([seed, 99])
    sim = world.Sim(net, seed)
    link_ids = [l["id"] for l in net["links"]]
    mw = [l["id"] for l in net["links"] if l["medium"] == "mw" and l["role"] == "primary" and engine.reroute_options(net, l["id"])]
    hubs = [x for x in mw if len(engine.reroute_options(net, x)) >= 2]          # links with several sites behind them first
    mw = [str(x) for x in rng.permutation(hubs)] + [str(x) for x in rng.permutation([x for x in mw if x not in hubs])]
    env = {**ENVELOPE, "protected_sites": sorted(s["id"] for s in net["sites"] if s["protected"])}
    out = []
    for k in range(n):
        root = mw[k % len(mw)]
        t0 = T + (k + 1) * world.PER_DAY + int(rng.integers(48, 68))       # a weekday or weekend afternoon
        fault = {"id": f"C{k}", "kind": "backhaul_degradation", "element": root, "start": t0, "end": None,
                 "cap_factor": round(float(rng.uniform(0.3, 0.6)), 2), "loss_pct": round(float(rng.uniform(0.2, 0.6)), 2)}
        td = t0 + 4                                                          # an hour in: the incident is open, the service decides
        obs = sim.run(td - 8, td, [fault])
        recent = np.array([o["cell"][:, 0] for o in obs])
        up = obs[-1]["cell"][:, 7] > 0.5
        pred, hts = fc.forecast(recent, np.arange(td - 8, td), world.PER_DAY, up)
        capacity = obs[-1]["link"][:, 1].astype(float)
        capacity = np.where(capacity > 0, capacity, [l["capacity"] for l in net["links"]])
        opt = engine.optimise(net, root, pred, capacity, env, (), hts)
        plan = [a["site"] for a in opt["best"]["actions"]] if opt["best"] else []
        everything = opt["options"]
        res = {"root": root, "do_nothing_ok": opt["do_nothing"]["feasible"], "plan": plan, "options": len(everything), "proposed": bool(plan),
               "predicted_peak_plan": opt["best"]["peak"] if opt["best"] else None, "predicted_peak_nothing": opt["do_nothing"]["peak"]}
        for name, sites in (("nothing", []), ("plan", plan), ("everything", everything)):
            told = [fault] + [{"kind": "reroute", "site": s, "start": td} for s in sites]
            run = sim.run(td, td + world.PER_DAY, told)
            rho = np.array([o["offered_link"] / np.maximum(o["capacity_link"], 1e-9) for o in run])
            watch = engine.affected_links(net, [{"type": "reroute_site", "site": s} for s in sites]) | {root}
            wj = [link_ids.index(x) for x in watch]
            res[name] = {"peak_watch": float(rho[:, wj].max()), "intervals_over_envelope": int((rho[:, wj] > 0.8).any(1).sum()),
                         "intervals_congested": int((rho[:, wj] > 1.0).any(1).sum()), "impaired_cell_intervals": int(sum(o["impaired"].sum() for o in run)),
                         "protected_moved": sorted({x for s in sites for x in engine.subtree_sites(net, s)} & set(env["protected_sites"]))}
            if name == "plan" and plan:
                res["realised_peak_plan"] = res[name]["peak_watch"]
        out.append(res)
    return out


def one(seed):
    net = world.network(seed)
    faults = faults_for(net, seed)
    sim = world.Sim(net, seed)
    out = sim.run(0, T, faults)
    ts = np.arange(T)
    cell = np.array([o["cell"] for o in out]).astype(float)
    link = np.array([o["link"] for o in out]).astype(float)
    truth = np.array([o["impaired"] for o in out])
    cause = np.array([o["cause"] for o in out])
    topo = engine.Topology(net)
    avail = cell[..., 7] > 0.5
    quiet = engine.quiet_mask(topo, [(o["t"], a[2], a[3]) for o in out for a in o["alarms"]], 0, T) & avail
    ad = engine.AnomalyModel().fit(cell[:TRAIN_END], ts[:TRAIN_END], quiet[:TRAIN_END])
    fc = engine.Forecaster().fit(cell[:TRAIN_END, :, 0], ts[:TRAIN_END], quiet[:TRAIN_END])
    single = ad.flag(cell, ts)
    pers = engine.persistent(single)
    cap = np.array([l["capacity"] for l in net["links"]])
    lflag = (link[..., 1] < 0.9 * cap) | (link[..., 3] > 0.2)
    # --- anomaly detection on the fourth week
    te = slice(TRAIN_END, T)
    tr = truth[te]
    det = {"model (two in a row)": pers[te], "model, one interval": single[te], "largest single-feature z (two in a row)": engine.persistent(ad.flag(cell, ts, diagonal=True))[te],
           "static thresholds": engine.static_flags(cell[te]), "static thresholds (two in a row)": engine.persistent(engine.static_flags(cell[te]))}
    anomaly = {}
    for k, fl in det.items():
        tp, fp, fn = int((fl & tr).sum()), int((fl & ~tr).sum()), int((~fl & tr).sum())
        p, r = tp / max(1, tp + fp), tp / max(1, tp + fn)
        anomaly[k] = {"precision": p, "recall": r, "f1": 2 * p * r / max(p + r, 1e-9), "false_per_1000": 1000 * fp / max(1, int((~tr).sum()))}
    by_kind = collections.defaultdict(lambda: {"faults": 0, "model": 0, "static": 0, "model_delay": [], "static_delay": []})
    stat_all = engine.static_flags(cell)
    for f in faults:
        if f["start"] < TRAIN_END:
            continue
        end = f["end"] if f["end"] is not None else T
        hit = cause[f["start"]:end] == f["id"]
        if not hit.any():
            continue
        kind = "rain_fade" if f["kind"] == "rain_fade" else f["kind"]
        d = by_kind[kind]
        d["faults"] += 1
        for name, fl in (("model", pers), ("static", stat_all)):
            rows = np.nonzero((fl[f["start"]:end] & hit).any(1))[0]
            if len(rows):
                d[name] += 1
                d[name + "_delay"].append(int(rows[0]))
    # --- forecast on the fourth week
    errs, naive, lerr, lnaive = [], [], [], []
    M = engine.incidence(net, ())
    si = {s["id"]: i for i, s in enumerate(net["sites"])}
    S = np.zeros((len(net["cells"]), len(si)))
    S[np.arange(len(net["cells"])), [si[c["site"]] for c in net["cells"]]] = 1
    dl = cell[..., 0]
    for o in range(TRAIN_END + 8, T - world.PER_DAY, 24):
        pred, _ = fc.forecast(dl[o - 8:o], ts[o - 8:o], world.PER_DAY)
        act, nv, ok = dl[o:o + world.PER_DAY], dl[o - world.PER_WEEK:o - world.PER_WEEK + world.PER_DAY], quiet[o:o + world.PER_DAY]
        errs.append(engine.wape(pred[ok], act[ok]))
        naive.append(engine.wape(nv[ok], act[ok]))
        offered = np.array([out[x]["offered_link"] for x in range(o, o + world.PER_DAY)])        # what the links really carried
        lp, ln = (pred @ S @ M).max(0), (nv @ S @ M).max(0)
        la = offered.max(0)[[sim.link_ix[l["id"]] for l in net["links"]]]
        keep = la > 0
        lerr.append(engine.wape(lp[keep], la[keep]))
        lnaive.append(engine.wape(ln[keep], la[keep]))
    forecast = {"cell_wape": float(np.mean(errs)), "cell_wape_naive": float(np.mean(naive)), "link_peak_wape": float(np.mean(lerr)), "link_peak_wape_naive": float(np.mean(lnaive)), "origins": len(errs)}
    # --- correlation and root cause over all four weeks
    cor, alarms = correlate(net, sim, out, single, pers, lflag)
    incs = [i for i in cor.incidents.values() if i["status"] != "merged"]
    fault_alarms = [a for a in alarms if a["cause"]]
    corr = {"alarms": len(alarms), "incidents": len(incs), "fault_alarms": len(fault_alarms),
            "fault_incidents": sum(1 for i in incs if any(a["cause"] for a in i["alarms"])), "purity": purity([i["alarms"] for i in incs])}
    for by in ("dedup", "site"):
        g = baseline_partition(topo, alarms, by)
        corr[by] = {"groups": len(g), "purity": purity(g), "fault_groups": sum(1 for x in g if any(a["cause"] for a in x))}
    ranks, feats, split = collections.defaultdict(list), [], []
    for f in faults:
        fal = [a for a in alarms if a["cause"] == f["id"]]
        if len(fal) < 3:
            continue
        cnt = collections.Counter(final(cor, cor.alarm_incident[a["id"]])["id"] for a in fal)
        split.append(sum(v >= 0.1 * len(fal) for v in cnt.values()))
        inc = cor.incidents[cnt.most_common(1)[0][0]]
        full = [r["element"] for r in inc["ranking"]]
        topo_only = [r["element"] for r in engine.rank(topo, inc["alarms"], cor.evidence, cor.configs, TOPOLOGY_ONLY)]
        count = engine.rank_by_count(inc["alarms"])
        pos = lambda lst: lst.index(f["element"]) + 1 if f["element"] in lst else 99      # noqa: E731
        kind = f["kind"]
        ranks["full"].append((kind, pos(full)))
        ranks["topology only"].append((kind, pos(topo_only)))
        ranks["most alarms"].append((kind, pos(count)))
        feats.append([(r["element"] == f["element"], [r["features"][k] for k in engine.WEIGHTS]) for r in inc["ranking"]])
    corr["faults_split"] = float(np.mean([s > 1 for s in split]))
    return {"anomaly": anomaly, "by_kind": dict(by_kind), "forecast": forecast, "corr": corr, "ranks": dict(ranks), "feats": feats,
            "scenarios": scenarios(net, seed, ad, fc), "net": {"sites": len(net["sites"]), "cells": len(net["cells"]), "links": len(net["links"]), "faults": len(faults)}}


def learned_ranker(res):
    """Leave one metro out: logistic regression on the same candidate features, trained on the other two metros' incidents."""
    out = {}
    for s in res:
        X = [x for o in res if o != s for inc in res[o]["feats"] for _, x in inc]
        y = [lab for o in res if o != s for inc in res[o]["feats"] for lab, _ in inc]
        clf = LogisticRegression(max_iter=2000, class_weight="balanced").fit(np.array(X), np.array(y))
        pos = []
        for inc in res[s]["feats"]:
            p = clf.predict_proba(np.array([x for _, x in inc]))[:, 1]
            order = np.argsort(-p, kind="stable")
            labels = [inc[i][0] for i in order]
            pos.append(labels.index(True) + 1 if True in labels else 99)
        out[s] = pos
    return out


def pct(x):
    return f"{100 * x:.0f}%"


def main():
    res = {s: one(s) for s in SEEDS}
    p = print
    p("# Evaluation\n")
    n0 = res[SEEDS[0]]["net"]
    p(f"Three held-out metros (seeds {', '.join(map(str, SEEDS))}), each with its own topology (about {n0['sites']} sites, {n0['cells']} cells, {n0['links']} links), "
      "traffic and faults: four weeks with 24 faults in the first three and a dense fourth week of 18 (three of each kind: microwave backhaul degradation, "
      "fibre degradation, rain fade over two or three links, site power outage, handover misconfiguration, sleeping cell). Models are trained on the first "
      "three weeks exactly as the service trains them and scored on the fourth; correlation and root cause run over all four weeks interval by interval; "
      "capacity incidents are played forward after the history. Everything is scored against the generator's truth. `python -m noc.evaluate` reproduces this file.\n")
    p("## Alarm correlation\n")
    p("| Metro | Raw alarms | Incidents | Ratio | Alarms caused by faults | Topology: incidents holding them | Ratio on fault alarms | De-duplication: groups holding them | Ratio | By site: groups holding them | Ratio |\n|---|---|---|---|---|---|---|---|---|---|---|")
    for s, r in res.items():
        c = r["corr"]
        p(f"| {s} | {c['alarms']:,} | {c['incidents']:,} | {c['alarms'] / c['incidents']:.1f}:1 | {c['fault_alarms']:,} | {c['fault_incidents']} | "
          f"**{c['fault_alarms'] / c['fault_incidents']:.0f}:1** | {c['dedup']['fault_groups']} | {c['fault_alarms'] / c['dedup']['fault_groups']:.1f}:1 | "
          f"{c['site']['fault_groups']} | {c['fault_alarms'] / c['site']['fault_groups']:.1f}:1 |")
    shares = [100 * (1 - r["corr"]["fault_alarms"] / r["corr"]["alarms"]) for r in res.values()]
    noise_lo, noise_hi = round(min(shares)), round(max(shares))
    p("\n| Metro | Purity: topology | De-duplication (groups over all alarms, purity) | By site (groups, purity) | Faults split over more than one incident |\n|---|---|---|---|---|")
    for s, r in res.items():
        c = r["corr"]
        p(f"| {s} | {pct(c['purity'])} | {c['dedup']['groups']:,}, {pct(c['dedup']['purity'])} | {c['site']['groups']:,}, {pct(c['site']['purity'])} | {pct(c['faults_split'])} |")
    p("\nPurity: the share of alarms whose cause is the main cause of the group they were put in (a noise alarm's cause is its own element and type). "
      "The blueprint's bar is a reduction above 20:1. On the alarms faults cause, topology correlation is past it on every metro. De-duplication barely "
      "compresses a storm, because every cell flaps on its own. Grouping by site compresses storms well too, but a storm behind a hub spans several sites, "
      "it puts unrelated noise together (lower purity) and it does not say which element is at fault. Over all alarms no method reaches 20:1 here: "
      f"{noise_lo}–{noise_hi}% of the raw alarms are noise with no fault behind them (VSWR, board temperature, sync, evening congestion on busy cells), mostly "
      "one-offs that no correlation can compress, and topology correlation keeps each one as its own incident.\n")
    p("## Root cause\n")
    learned = learned_ranker(res)
    p("| Metro | Faults ranked | Full: top-1 | Full: top-3 | Topology only: top-3 | Most alarms (baseline): top-3 | Learned ranker (other metros' tickets): top-3 |\n|---|---|---|---|---|---|---|")
    tot = collections.defaultdict(list)
    for s, r in res.items():
        rk = r["ranks"]
        for k, v in rk.items():
            tot[k] += [x for _, x in v]
        tot["learned"] += learned[s]
        f = lambda k, n: pct(np.mean([x <= n for _, x in rk[k]]))     # noqa: E731
        p(f"| {s} | {len(rk['full'])} | {f('full', 1)} | {f('full', 3)} | {f('topology only', 3)} | {f('most alarms', 3)} | {pct(np.mean([x <= 3 for x in learned[s]]))} |")
    f = lambda k, n: pct(np.mean([x <= n for x in tot[k]]))           # noqa: E731
    p(f"| **all** | {len(tot['full'])} | {f('full', 1)} | **{f('full', 3)}** | {f('topology only', 3)} | {f('most alarms', 3)} | {f('learned', 3)} (top-1 {f('learned', 1)}) |")
    kinds = collections.defaultdict(list)
    for r in res.values():
        for (k, x), (_, b) in zip(r["ranks"]["full"], r["ranks"]["most alarms"]):
            kinds[k].append((x, b))
    p("\n| Fault kind | Faults | Full: top-1 | Full: top-3 | Most alarms: top-3 |\n|---|---|---|---|---|")
    for k, v in sorted(kinds.items()):
        p(f"| {k.replace('_', ' ')} | {len(v)} | {pct(np.mean([x <= 1 for x, _ in v]))} | {pct(np.mean([x <= 3 for x, _ in v]))} | {pct(np.mean([b <= 3 for _, b in v]))} |")
    p("\nThe blueprint's bar is top-3 precision above 90%; here it is measured as the share of faults whose true element is among the top three of the "
      "incident that holds most of the fault's alarms. A fault is ranked when it caused at least three alarms. The most-alarmed element is usually a "
      "cell that flaps, not the link or router behind it. Topology alone ties a link with the router at its near end (both explain the same cells); the "
      "element's own alarms, telemetry and configuration changes break the tie. The learned ranker is logistic regression on the same six features, "
      "trained on the other two metros' incidents: the stand-in for asking whether learning the propagation (the blueprint's temporal graph network) "
      "would beat the hand-set weights.\n")
    p("## Anomaly detection (fourth week, per cell and interval)\n")
    p("| Metro | Detector | Precision | Recall | F1 | False flags per 1,000 healthy cell-intervals |\n|---|---|---|---|---|---|")
    for s, r in res.items():
        for k, a in r["anomaly"].items():
            p(f"| {s} | {k} | {a['precision']:.3f} | {a['recall']:.3f} | {a['f1']:.3f} | {a['false_per_1000']:.2f} |")
    p("\nA cell-interval is impaired when a fault cost it at least 0.25% packet loss, throughput through a link the fault had squeezed, three points of "
      "handover success, its traffic (a sleeping cell) or its service. The service acts on the model's two-in-a-row flag.\n")
    p("**Faults detected in the fourth week, by kind** (any impaired cell flagged while the fault lasted; delay in intervals from the fault's start):\n")
    p("| Fault kind | Faults | Model (two in a row) | Median delay | Static thresholds | Median delay |\n|---|---|---|---|---|---|")
    agg = collections.defaultdict(lambda: {"faults": 0, "model": 0, "static": 0, "model_delay": [], "static_delay": []})
    for r in res.values():
        for k, d in r["by_kind"].items():
            for x in ("faults", "model", "static"):
                agg[k][x] += d[x]
            agg[k]["model_delay"] += d["model_delay"]
            agg[k]["static_delay"] += d["static_delay"]
    for k, d in sorted(agg.items()):
        md = lambda v: f"{np.median(v):.0f}" if v else "–"            # noqa: E731
        p(f"| {k.replace('_', ' ')} | {d['faults']} | {d['model']} | {md(d['model_delay'])} | {d['static']} | {md(d['static_delay'])} |")
    p("\nStatic thresholds are the vendor alarms' own thresholds. They catch what is loud and miss what is silent: a sleeping cell carries no traffic and raises "
      "no alarm, and a fibre degradation below the loss threshold leaks packets quietly. The model's normal range is per cell, per day type and per quarter hour.\n")
    p("## Traffic forecast (24 hours ahead, fourth week)\n")
    p("| Metro | Cell WAPE | Seasonal naive (same slot last week) | Link busy-hour peak WAPE | Seasonal naive |\n|---|---|---|---|---|")
    for s, r in res.items():
        fo = r["forecast"]
        p(f"| {s} | {fo['cell_wape']:.3f} | {fo['cell_wape_naive']:.3f} | {fo['link_peak_wape']:.3f} | {fo['link_peak_wape_naive']:.3f} |")
    p("\nForecasts from every six hours of the fourth week, scored on cells with no fault nearby. Per cell, the profile beats last week's value because it "
      "averages out one week's noise; at the link's busy-hour peak, where dozens of cells add up and the noise cancels, the two are close, and the twin "
      "works at that level.\n")
    p("## Capacity incidents: plan on the forecast, then see what happened\n")
    p("| Metro | Incidents | Plans proposed | Doing nothing was enough | No plan inside the envelope | Plans that stayed inside the envelope (real traffic) | Twin's peak vs real peak on the links the plan touches (points) |\n|---|---|---|---|---|---|---|")
    allsc = []
    for s, r in res.items():
        sc = r["scenarios"]
        allsc += sc
        prop = [x for x in sc if x["proposed"]]
        ok = [x for x in prop if x["plan"]["peak_watch"] <= 0.8]
        err = [abs(x["predicted_peak_plan"] - x["realised_peak_plan"]) * 100 for x in prop]
        p(f"| {s} | {len(sc)} | {len(prop)} | {sum(x['do_nothing_ok'] for x in sc)} | {sum(not x['proposed'] and not x['do_nothing_ok'] for x in sc)} | "
          f"{len(ok)} of {len(prop)} | {np.mean(err):.1f} mean, {np.max(err):.1f} max |" if prop else f"| {s} | {len(sc)} | 0 | | | | |")
    prop = [x for x in allsc if x["proposed"]]
    p("\n**Over the following day, on the links each option touches** (all metros, incidents where a plan was proposed):\n")
    p("| Option | Intervals over the envelope (80%) | Intervals congested (over 100%) | Impaired cell-intervals | Moves a protected site |\n|---|---|---|---|---|")
    for name, label in (("nothing", "Do nothing"), ("plan", "The optimiser's plan"), ("everything", "Reroute everything possible (naive)")):
        p(f"| {label} | {sum(x[name]['intervals_over_envelope'] for x in prop)} | {sum(x[name]['intervals_congested'] for x in prop)} | "
          f"{sum(x[name]['impaired_cell_intervals'] for x in prop):,} | {sum(bool(x[name]['protected_moved']) for x in prop)} of {len(prop)} |")
    p("\nEach incident degrades one microwave link that has sites with a standby path behind it, on a weekday or weekend afternoon; the service decides an "
      "hour in, from the last two hours of counters and the link's measured capacity. The plan is the optimiser's choice on the forecast; the generator then "
      "re-runs the same day (same traffic, same noise) under each option. Impaired cell-intervals include the packet loss on the degraded link itself, "
      "which rerouting only removes for the sites it moves. \"Reroute everything\" ignores the envelope, which is why it is not allowed to be proposed. The plan moves the fewest sites that fix capacity, so the sites it leaves "
      "behind keep the degraded link's packet loss until the link is repaired; that is the difference in impaired cell-intervals against rerouting everything.\n")
    return res


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
    sys.exit(0)
