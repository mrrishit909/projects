"""Held-out evaluation on three chains the demo never uses (other seeds, 50 stores, eight weeks of history each).

    python -m resto.evaluate            # prints the markdown behind docs/evaluation.md

Each chain: its history runs the way the chain always ran; the models are fitted exactly as the service fits them and
scored on what the generator knows and the service never sees (true demand including what was lost to stockouts,
true elasticities, the injected shrinkage, which lots spoiled). Then the planners run the same 14 days from the same stock
with the same customers, weather and spoilage draws; and the demo's disruption (a late produce truck and a lunch
rainstorm) is played on each chain under three plans.
"""
import collections
import sys
import time

import numpy as np

from . import engine as E
from . import world as W

SEEDS = (101, 102, 103)
SHRINK_SEEDS = (101, 102, 103, 104, 105, 106)
TRAIN, HIST, RUN = 42, 56, 14
Q_PREP, Q_ING = 0.9, 0.95
TOLD = [{"kind": "supplier_delay", "supplier": "produce", "due": HIST, "days": 1, "regions": ["Harbor", "Uptown"]},
        {"kind": "rainstorm", "day": HIST, "from_hour": 11, "to_hour": 15, "intensity": 0.9, "regions": ["Uptown", "Midtown"]}]


def history(seed):
    ch = W.chain(seed)
    st, recs = W.run(ch, W.initial_state(ch), 0, HIST, W.UsualPractice(), last_orders=False)
    return ch, st, recs


def usage(st, recs):
    theo = np.stack([r["sold"].sum((2, 3)) @ W.ITEM_THEORETICAL_RAW + r["prep_discard"].sum(2) @ W.RAW_PER_COMP for r in recs])
    act = np.stack([st["use"][r["day"]] for r in recs])
    return theo, act


def lot_rows(recs, until):
    closed = {}
    for r in recs:
        for l, i, rd, status, q in r["closures"]:
            closed[(l, i, rd)] = (r["day"], status)
    lots = [(l, i, r["day"], *closed.get((l, i, r["day"]), (None, "open"))) for r in recs for l, i in zip(*np.nonzero(r["received"] > 0))]
    return E.lot_days(lots, np.stack([r["temp"] for r in recs], 1), until, with_day=True)


def naive_window_q(tot, agg):
    """Empirical 90% error quantiles of 'same window last week' at an aggregate level, by forecast level, from the training weeks."""
    f, y = agg(tot[:, :, :-7]), agg(tot[:, :, 7:])
    edges = np.quantile(f, np.linspace(0, 1, 9))
    k = np.clip(np.searchsorted(edges, f, side="right") - 1, 0, 7)
    return edges, {b: (np.quantile((y - f)[k == b], E.Q_LO), np.quantile((y - f)[k == b], E.Q_HI)) for b in range(8) if (k == b).sum() > 20}


def naive_window_interval(fc, edges, q):
    k = np.clip(np.searchsorted(edges, fc, side="right") - 1, 0, 7)
    lo, hi = np.zeros_like(fc, float), np.zeros_like(fc, float)
    for b, (a, c) in q.items():
        lo[k == b], hi[k == b] = a, c
    return np.maximum(fc + lo, 0), fc + hi


def forecast_eval(ch, recs):
    h = E.history_arrays(recs[:TRAIN], ch)
    t0 = time.perf_counter()
    m = E.DemandModel().fit(h)
    fit_s = time.perf_counter() - t0
    test = recs[TRAIN:]
    conds = [(W.rain_forecast(ch, r["day"]), W.event_mask(ch, r["day"]), r["discount"]) for r in test]     # the day-ahead forecast, as in production
    mu_c = np.stack([m.mean(r["day"], *cd) for r, cd in zip(test, conds)], 3)                       # [L, I, C, D, S]
    mu = mu_c.sum(2)
    y = np.stack([r["truth"]["demand"].sum(2) for r in test], 2).astype(float)                     # true demand, lost sales included
    lo, hi = E.slot_interval(m, mu_c)
    pit = E.pit_coverage(m, mu_c, y)
    Y = np.stack([r["sold"] for r in recs], 3).astype(float)
    tot = Y.sum(2)
    bins, q = E.seasonal_naive(Y[:, :, :, :TRAIN], None)
    fc = tot[:, :, TRAIN - 7:HIST - 7]
    nlo, nhi = E.naive_interval(fc, bins, q)
    R = list(W.LUNCH_RUSH)
    wape = lambda a, b: float(np.abs(a - b).sum() / b.sum())                                      # noqa: E731
    cov = lambda yy, a, b: float(((yy >= a) & (yy <= b)).mean())                                  # noqa: E731
    out = {"fit_s": round(fit_s, 1)}
    s = (slice(None), slice(None), slice(None), R)
    out["slot"] = {"wape": wape(mu[s], y[s]), "naive_wape": wape(fc[s], y[s]), "pit": float(pit[s].mean()), "cover": cov(y[s], lo[s], hi[s]),
                   "naive_cover": cov(y[s], nlo[s], nhi[s]), "width": float((hi - lo)[s].mean()), "naive_width": float((nhi - nlo)[s].mean()), "mean": float(y[s].mean())}
    wlo, whi = E.window_interval(m, mu_c[..., R])
    yl, ml = y[..., R].sum(-1), mu[..., R].sum(-1)
    edges, qw = naive_window_q(tot[:, :, :TRAIN], lambda a: a[..., R].sum(-1))
    fl = fc[..., R].sum(-1)
    nwl, nwh = naive_window_interval(fl, edges, qw)
    out["window"] = {"wape": wape(ml, yl), "naive_wape": wape(fl, yl), "cover": cov(yl, wlo, whi), "naive_cover": cov(yl, nwl, nwh),
                     "width": float((whi - wlo).mean()), "naive_width": float((nwh - nwl).mean()), "mean": float(yl.mean())}
    md = mu.sum((1, 3))
    vd = m.agg_var(md, (mu_c ** 2).sum((1, 2, 4)))
    dlo, dhi = E.DemandModel.nb_quantiles(md, vd)
    yd, fd = y.sum((1, 3)), fc.sum((1, 3))
    edges, qd = naive_window_q(tot[:, :, :TRAIN], lambda a: a.sum((1, 3))[:, None])
    ndl, ndh = naive_window_interval(fd[:, None], edges, qd)
    out["day"] = {"wape": wape(md, yd), "naive_wape": wape(fd, yd), "cover": cov(yd, dlo, dhi), "naive_cover": cov(yd[:, None], ndl, ndh)}
    cl = y[..., R].sum((0, 1, 3))
    out["chain_lunch"] = {"wape": wape(mu[..., R].sum((0, 1, 3)), cl), "naive_wape": wape(fc[..., R].sum((0, 1, 3)), cl)}
    rain = np.stack([r["rain"] for r in test], 1)[:, None, :, :].repeat(W.N_ITEM, 1)
    rs = (rain[..., R] > 0.2)
    out["rain"] = {"slots": int(rs.sum()), "wape": wape(mu[..., R][rs], y[..., R][rs]), "naive_wape": wape(fc[..., R][rs], y[..., R][rs]),
                   "pit": float(pit[..., R][rs].mean())}
    disc = np.stack([r["discount"] for r in test], 2)
    ps = disc > 0
    out["promo"] = {"item_days": int(ps.sum()), "wape": wape(mu.sum(-1)[ps], y.sum(-1)[ps]) if ps.any() else None,
                    "naive_wape": wape(fc.sum(-1)[ps], y.sum(-1)[ps]) if ps.any() else None}
    t0 = time.perf_counter()
    times = []
    for _ in range(20):                                                                           # a refresh: 50 stores, 2 days, every item and slot
        t1 = time.perf_counter()
        for k in range(2):
            mc = m.mean(HIST + k, W.rain_forecast(ch, HIST + k), W.event_mask(ch, HIST + k), W.discounts(ch, HIST + k))
            E.slot_interval(m, mc)
        times.append(time.perf_counter() - t1)
    out["refresh_ms"] = (float(np.median(times) * 1000), float(np.percentile(times, 95) * 1000))
    return out


def policies(ch, st, model, raw_ratio, hz):
    sysp = E.SystemPolicy(model, raw_ratio=raw_ratio, hazard=hz, q_prep=Q_PREP, q_ing=Q_ING)
    nohz = E.SystemPolicy(model, raw_ratio=raw_ratio, hazard=None, q_prep=Q_PREP, q_ing=Q_ING)
    pols = {"usual practice": W.UsualPractice(), "system, unattended (lines over $250 at par)": E.Bounded(sysp, W.UsualPractice()),
            "system, every line approved": sysp, "system, printed dates instead of the hazard": nohz}
    out = {}
    for name, p in pols.items():
        obs = W.Obs(ch, st, HIST - 1, W.delays_known(ch, [], HIST - 1))
        pend = [dict(o, id=f"p{k}", ordered_on=HIST - 1) for k, o in enumerate(p.order(ch, HIST - 1, obs))]
        _, recs = W.run(ch, st, HIST, HIST + RUN, p, (), pend)
        mm = W.metrics(recs)
        mm["backup_usd"] = float(sum((r["received_by"].get("backup", np.zeros((ch["L"], W.N_ING))) * W.COST).sum() for r in recs))
        out[name] = mm
    return out


def disruption(ch0, st, model, raw_ratio, hz, days=3):
    ch = W.apply_told(ch0, TOLD)
    sysp = E.SystemPolicy(model, raw_ratio=raw_ratio, hazard=hz, q_prep=Q_PREP, q_ing=Q_ING)
    usual = W.UsualPractice()
    blind = W.Obs(ch0, st, HIST - 1, W.delays_known(ch0, (), HIST - 1))
    know = W.Obs(ch, st, HIST - 1, W.delays_known(ch, TOLD, HIST - 1))
    alts = {"usual practice": (usual.order(ch0, HIST - 1, blind), usual),
            "system, plan before the notices": (sysp.order(ch0, HIST - 1, blind), E.WithPlans(E.Bounded(sysp, usual), {(HIST, 0): sysp.prep(ch0, HIST, 0, W.Obs(ch0, st, HIST, []))})),
            "system, re-planned": (sysp.order(ch, HIST - 1, know), E.Bounded(sysp, usual))}
    out = {}
    for name, (pend, pol) in alts.items():
        pend = [dict(o, id=f"p{k}", ordered_on=HIST - 1) for k, o in enumerate(pend)]
        _, recs = W.run(ch, st, HIST, HIST + days, pol, TOLD, pend, last_orders=False)
        mm = W.metrics(recs)
        mm["backup_premium_usd"] = float(sum((r["received_by"].get("backup", np.zeros((ch["L"], W.N_ING))) * W.COST * 0.35).sum() for r in recs))
        mm["day1_stockout"] = W.metrics(recs[:1])["stockout_rate"]
        out[name] = mm
    return out


def one(seed):
    ch, st, recs = history(seed)
    fe = forecast_eval(ch, recs)
    model = E.DemandModel().fit(E.history_arrays(recs, ch))                                        # production: all eight weeks
    promoted = {p["item"] for p in ch["promos"] if p["start"] < HIST}
    el = {W.ITEM[i]: (float(model.eps[i]), float(ch["elasticity"][i]), W.ITEM[i] in promoted) for i in range(W.N_ITEM)}
    theo, act = usage(st, recs)
    ratio_tr, _ = E.usage_ratios(theo[:TRAIN], act[:TRAIN])
    t_te, a_te = theo[TRAIN:], act[TRAIN:]
    lastweek = act[TRAIN - 7:HIST - 7]
    cons = {"ratio": float(np.abs(a_te.sum(0) - t_te.sum(0) * ratio_tr).sum() / a_te.sum()), "recipes": float(np.abs(a_te.sum(0) - t_te.sum(0)).sum() / a_te.sum()),
            "lastweek": float(np.abs(a_te.sum(0) - lastweek.sum(0)).sum() / a_te.sum()),
            "daily_ratio": float(np.abs(a_te - t_te * ratio_tr).sum() / a_te.sum()), "daily_recipes": float(np.abs(a_te - t_te).sum() / a_te.sum()),
            "daily_lastweek": float(np.abs(a_te - lastweek).sum() / a_te.sum())}
    rows, rdays = lot_rows(recs, HIST)
    tr = rdays < TRAIN
    hz_tr = E.HazardModel().fit(rows[tr, 1].astype(int), rows[tr, 2], rows[tr, 3], rows[tr, 4])
    hz_within = E.evaluate_hazard(hz_tr, rows[~tr])
    _, _, recs2 = history(seed + 1000)
    rows2, _ = lot_rows(recs2, HIST)
    hz_cross = E.evaluate_hazard(hz_tr, rows2)
    warm = rows2[:, 3] > 5.5
    hz_cross["warm_lot_days"] = int(warm.sum())
    hz_cross["warm_spoiled"] = int(rows2[warm, 4].sum())
    hz_cross["warm_mean_p"] = float(hz_tr.p(rows2[warm, 1].astype(int), rows2[warm, 2], rows2[warm, 3]).mean()) if warm.any() else None
    hz_cross["warm_rate"] = float(rows2[warm, 4].mean()) if warm.any() else None
    hz = E.HazardModel().fit(rows[:, 1].astype(int), rows[:, 2], rows[:, 3], rows[:, 4])
    raw_ratio, _ = E.usage_ratios(theo, act)
    pol = policies(ch, st, model, raw_ratio, hz)
    dis = disruption(ch, st, model, raw_ratio, hz)
    return {"forecast": fe, "elasticity": el, "consumption": cons, "hazard_within": hz_within, "hazard_cross": hz_cross, "policies": pol, "disruption": dis,
            "promos": len([p for p in ch["promos"] if p["start"] < HIST])}


def shrink(seed):
    ch, st, recs = history(seed)
    theo, act = usage(st, recs[1:])
    scan, base = E.shrinkage_scan(theo, act)
    truth = {s["store"]: s for s in ch["shrinkage"]}
    true_pairs = np.zeros_like(scan["flags"])
    for l, s in truth.items():
        for i in (range(W.N_ING) if s["kind"] == "over-portioning" else [W.ING.index(x) for x in s["ingredients"]]):
            true_pairs[l, i] = s["kind"] != "over-portioning" or W.ING[i] in W.PORTIONED
    flagged = set(np.nonzero(scan["flags"].any(1))[0])
    bflag = set(np.nonzero(base.any(1))[0])
    right_class = sum((E.classify_shrinkage(scan, l) == "over-portioning") == (truth[l]["kind"] == "over-portioning") for l in flagged if l in truth)
    theft_pairs = np.zeros_like(true_pairs)
    for l, s in truth.items():
        if s["kind"] == "theft":
            for x in s["ingredients"]:
                theft_pairs[l, W.ING.index(x)] = True
    return {"true": len(truth), "found": len(flagged & set(truth)), "false": len(flagged - set(truth)), "class_right": right_class,
            "base_found": len(bflag & set(truth)), "base_false": len(bflag - set(truth)), "base_pairs": int(base.sum()), "pairs": int(scan["flags"].sum()),
            "theft_pairs": int(theft_pairs.sum()), "theft_pairs_found": int((scan["flags"] & theft_pairs).sum()), "base_theft_pairs_found": int((base & theft_pairs).sum()),
            "kinds": collections.Counter(s["kind"] for s in truth.values())}


def pct(x, d=1):
    return f"{100 * x:.{d}f}%"


def main():
    res = {s: one(s) for s in SEEDS}
    sh = {s: shrink(s) for s in SHRINK_SEEDS}
    p = print
    p("# Evaluation\n")
    p(f"Three held-out chains (seeds {', '.join(map(str, SEEDS))}), 50 stores each, {HIST} days of history run the chain's usual way (par prep and par "
      f"orders). Models are fitted exactly as the service fits them on days 0-{TRAIN - 1} and scored on days {TRAIN}-{HIST - 1} against what the generator "
      "knows and the service never sees: true demand, including what stockouts hid; true elasticities; which lots spoiled; the injected shrinkage. "
      f"The planners then run days {HIST}-{HIST + RUN - 1} from the same stock with the same customers, weather and spoilage draws. The prep and order "
      f"quantiles ({Q_PREP} and {Q_ING}) were chosen on a tuning chain (seed 11) that neither this file nor the demo uses. `python -m resto.evaluate` "
      "reproduces this file.\n")
    p("## Demand forecast (15-minute, hierarchical)\n")
    p("Lunch rush (11:00-14:00) of the two held-out weeks, against true demand. The forecast uses the weather service's day-ahead forecast, not the "
      "rain that fell. Baseline: seasonal naive (the same slot last week, from sales) with empirical 90% error quantiles from the training weeks.\n")
    p("| Chain | Level | WAPE | Baseline WAPE | 90% interval coverage | Baseline coverage | Interval width | Baseline width |\n|---|---|---|---|---|---|---|---|")
    for s, r in res.items():
        f = r["forecast"]
        sl, wn, dy = f["slot"], f["window"], f["day"]
        p(f"| {s} | item x store x 15 min (mean {sl['mean']:.1f}) | {sl['wape']:.3f} | {sl['naive_wape']:.3f} | {pct(sl['cover'])} (PIT {pct(sl['pit'])}) | {pct(sl['naive_cover'])} | {sl['width']:.1f} | {sl['naive_width']:.1f} |")
        p(f"| {s} | item x store x lunch rush (mean {wn['mean']:.0f}) | {wn['wape']:.3f} | {wn['naive_wape']:.3f} | {pct(wn['cover'])} | {pct(wn['naive_cover'])} | {wn['width']:.1f} | {wn['naive_width']:.1f} |")
        p(f"| {s} | store x day | {dy['wape']:.3f} | {dy['naive_wape']:.3f} | {pct(dy['cover'])} | {pct(dy['naive_cover'])} | | |")
        p(f"| {s} | chain lunch rush | {f['chain_lunch']['wape']:.3f} | {f['chain_lunch']['naive_wape']:.3f} | | | | |")
    p("\nThe blueprint's band is 85-95% item interval coverage. At 15 minutes an item sells about three units in a store, and a 90% interval on whole "
      "numbers covers more than 90% because its ends are whole numbers; the calibration that matters there is the randomised PIT (Czado, Gneiting "
      "and Held, 2009), shown in brackets. Summed to the lunch rush, where prep plans are made, the literal interval lands in the band. Most of the "
      "remaining error at 15 minutes is Poisson noise no model removes.\n")
    p("| Chain | Lunch slots in rain (item x store) | WAPE | Baseline | PIT coverage | Promotion item-days | WAPE | Baseline |\n|---|---|---|---|---|---|---|---|")
    for s, r in res.items():
        f = r["forecast"]
        pr = f["promo"]
        p(f"| {s} | {f['rain']['slots']:,} | {f['rain']['wape']:.3f} | {f['rain']['naive_wape']:.3f} | {pct(f['rain']['pit'])} | {pr['item_days']} | "
          + (f"{pr['wape']:.3f} | {pr['naive_wape']:.3f} |" if pr["wape"] is not None else "– | – |"))
    p("\nFitting takes " + ", ".join(f"{r['forecast']['fit_s']} s" for r in res.values()) + " (six weeks, 50 stores). A refresh (every store, item and 15-minute slot "
      "for two days, with intervals, from the fitted model) takes " + ", ".join(f"{r['forecast']['refresh_ms'][0]:.0f} ms (p95 {r['forecast']['refresh_ms'][1]:.0f} ms)" for r in res.values())
      + " in the model alone; the blueprint's bar is p95 under 2 minutes. Through the API, with the reads and writes, see docs/performance.md.\n")
    p("## Promotion elasticity\n")
    p("| Chain | Items promoted in the history | MAE of elasticity, those items | Baseline: one pooled elasticity | Baseline: no promotion effect | Items never promoted (fall back to pooled) |\n|---|---|---|---|---|---|")
    for s, r in res.items():
        el = r["elasticity"]
        pro = [(e, t) for e, t, k in el.values() if k]
        pooled = np.mean([e for e, t in pro])
        p(f"| {s} | {len(pro)} | {np.mean([abs(e - t) for e, t in pro]):.2f} | {np.mean([abs(pooled - t) for e, t in pro]):.2f} | {np.mean([t for e, t in pro]):.2f} | "
          f"{', '.join(k for k, (e, t, pr) in el.items() if not pr) or 'none'} |")
    p("\nElasticities run from 1.0 to 3.2 in the generator. Each promoted item is estimated from its own promotion (one discount level, 20-30 stores "
      "for 4-7 days) shrunk toward the pooled value; an item the history never promoted gets the pooled value, and its error is whatever that is.\n")
    p("## Ingredient consumption\n")
    p("Counted usage over the two held-out weeks, per store and ingredient, predicted from the sales those weeks at recipe.\n")
    p("| Chain | Recipes x learned ratio (2 weeks) | Recipes alone | Last week's usage | Daily: ratio | Daily: recipes | Daily: last week |\n|---|---|---|---|---|---|---|")
    for s, r in res.items():
        c = r["consumption"]
        p(f"| {s} | {pct(c['ratio'], 2)} | {pct(c['recipes'], 2)} | {pct(c['lastweek'], 2)} | {pct(c['daily_ratio'], 1)} | {pct(c['daily_recipes'], 1)} | {pct(c['daily_lastweek'], 1)} |")
    p("\nWAPE. The learned ratio absorbs what recipes miss (avocados yield less flesh than the spec everywhere; spillage; the over-portioning stores); "
      "daily error is dominated by the closing count's own error.\n")
    p("## Spoilage hazard\n")
    p("| Chain | Test | Lot-days | Spoiled | AUC | AUC, age only | AUC, printed date | Log loss | Base rate | Spoilage caught in the riskiest 5% | Age only |\n|---|---|---|---|---|---|---|---|---|---|---|")
    for s, r in res.items():
        for name, h in (("held-out weeks", r["hazard_within"]), ("another chain, 8 weeks", r["hazard_cross"])):
            p(f"| {s} | {name} | {h['lot_days']:,} | {h['spoiled']} | {h['auc']} | {h['auc_age_only']} | {h['auc_printed_date']} | {h['log_loss']} | {h['log_loss_base_rate']} | "
              f"{pct(h['caught_top5pct'], 0)} | {pct(h['caught_top5pct_age_only'], 0)} |")
    p("\nOn lot-days in a warm walk-in (above 5.5 °C) of the other chain: " + "; ".join(
        f"{s}: {r['hazard_cross']['warm_lot_days']} lot-days, {r['hazard_cross']['warm_spoiled']} spoiled ({pct(r['hazard_cross']['warm_rate'] or 0)}), model said {pct(r['hazard_cross']['warm_mean_p'] or 0)}"
        for s, r in res.items()) + ". The printed date flags almost nothing because lots are used or spoil before it; the hazard's advantage over "
      "age alone is the temperature, and warm walk-ins are rare, so on most lot-days the two rank alike.\n")
    p("## Shrinkage detection\n")
    tot = collections.Counter()
    for s, r in sh.items():
        for k, v in r.items():
            if k != "kinds":
                tot[k] += v
    p(f"Six chains (seeds {', '.join(map(str, SHRINK_SEEDS))}), 300 stores, {tot['true']} with injected shrinkage (two thefts of one or two ingredients at "
      "6-12% of usage, two over-portioning stores at 8-16% on proteins, cheese and guacamole per chain), 55 days of counts.\n")
    p("| | Shrinkage stores found | Stores flagged that had none | Theft store-ingredient pairs found | Pairs flagged in all |\n|---|---|---|---|---|")
    p(f"| Usage against the chain's normal, z > 4 | {tot['found']} of {tot['true']} (class right for {tot['class_right']}) | {tot['false']} of {300 - tot['true']} | {tot['theft_pairs_found']} of {tot['theft_pairs']} | {tot['pairs']} |")
    p(f"| Baseline: variance above 4% | {tot['base_found']} of {tot['true']} | {tot['base_false']} of {300 - tot['true']} | {tot['base_theft_pairs_found']} of {tot['theft_pairs']} | {tot['base_pairs']} |")
    p("\nThe threshold flags every store, because the chain's avocados yield less flesh than the recipe assumes (about 9% more avocado used everywhere): a chain-wide yield "
      "problem looks like shrinkage at every store to a fixed rule, and like the normal to a comparison with the chain.\n")
    p(f"## Planning: {RUN} days on each policy\n")
    p("Days 56-69 from the same stock with the same customers, weather and spoilage draws. Waste is prep thrown away at the end of its hold plus spoiled "
      "and expired lots, as a share of purchases; stockouts are demand lost because an item was 86'd (the generator's truth: the POS never sees it).\n")
    p("| Chain | Policy | Waste | Waste $ | of which prep | Stockout rate | Lost revenue | Purchases | Backup spend |\n|---|---|---|---|---|---|---|---|---|")
    agg = collections.defaultdict(lambda: collections.Counter())
    for s, r in res.items():
        for name, m in r["policies"].items():
            p(f"| {s} | {name} | {pct(m['waste_pct_of_purchases'])} | ${m['waste_usd']:,.0f} | ${m['prep_waste_usd']:,.0f} | {pct(m['stockout_rate'], 2)} | ${m['lost_revenue_usd']:,.0f} | ${m['purchases_usd']:,.0f} | ${m['backup_usd']:,.0f} |")
            for k in ("waste_usd", "prep_waste_usd", "purchases_usd", "lost_units", "demand_units", "lost_revenue_usd", "backup_usd"):
                agg[name][k] += m[k]
    p("| **all** | | | | | | | | |")
    for name, a in agg.items():
        p(f"| | {name} | {pct(a['waste_usd'] / a['purchases_usd'])} | ${a['waste_usd']:,.0f} | ${a['prep_waste_usd']:,.0f} | {pct(a['lost_units'] / a['demand_units'], 2)} | ${a['lost_revenue_usd']:,.0f} | ${a['purchases_usd']:,.0f} | ${a['backup_usd']:,.0f} |")
    u, b, f, n = (agg[k] for k in ("usual practice", "system, unattended (lines over $250 at par)", "system, every line approved", "system, printed dates instead of the hazard"))
    p(f"\nMost of the waste avoided is prep (${u['prep_waste_usd'] - b['prep_waste_usd']:,.0f} of ${u['waste_usd'] - b['waste_usd']:,.0f} unattended): the usual par is the same weekday "
      "of the last two weeks plus 15%, so it carries two weeks of noise and none of the weather, events or promotions, while the forecast's 90th "
      "percentile carries the day's own risk and the dinner prep is updated from lunch. Unattended, the lines that would move more than $250 from par "
      "go at par, which gives back a little of each gain. The hazard model does not earn its place in ordering here: with printed dates instead, the "
      f"planner wasted ${n['waste_usd']:,.0f} against ${f['waste_usd']:,.0f} (every line approved) and ran out on {pct(n['lost_units'] / n['demand_units'], 2)} "
      f"against {pct(f['lost_units'] / f['demand_units'], 2)}. Lots here turn over in two or three days, so few live long enough for their risk to change an order; "
      "its use is the waste-risk list.\n")
    p("## The demo's disruption on each chain\n")
    p("A late produce truck (Harbor and Uptown, one day) and a lunch rainstorm (Uptown and Midtown, 11:00-15:00), both on day 56, then three days. "
      "The plan made before the notices ran unattended after them; the re-plan knew both on the night before.\n")
    p("| Chain | Plan | Waste $ | Stockout rate (3 days) | Day 1 stockout rate | Lost revenue | Backup premium |\n|---|---|---|---|---|---|---|")
    for s, r in res.items():
        for name, m in r["disruption"].items():
            p(f"| {s} | {name} | ${m['waste_usd']:,.0f} | {pct(m['stockout_rate'], 1)} | {pct(m['day1_stockout'], 1)} | ${m['lost_revenue_usd']:,.0f} | ${m['backup_premium_usd']:,.0f} |")
    p("\nThe plan made before the notices does barely better than usual practice on day one: without produce, guacamole, pico and lettuce run out at "
      "the 20 stores and with them most of the menu, and only the backup order the re-plan places prevents that.\n")
    return res


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
    sys.exit(0)
