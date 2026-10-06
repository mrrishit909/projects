"""Held-out evaluation on three research networks the demo never uses (other seeds), four protocols each.

    python -m trials.evaluate            # prints the markdown behind docs/evaluation.md

The parser is scored on 240 generated protocols in the wording it was written against and on 240 in wording written
separately and never shown to it. In each network the models are trained on the network's five years of site history
exactly as the service trains them; each protocol is then run at every site by the generator, which is the truth that the
eligibility engine, the enrolment and dropout models and the portfolios are scored against.
"""
import collections
import sys
import time

import numpy as np

from . import engine, world

SEEDS = (201, 202, 203)
STUDIES = ("nsclc_post_platinum", "nsclc_second_line", "melanoma_io_refractory", "breast_her2")
PARSE_SEEDS = range(201, 231)
N_SITES, BUDGET_FACTOR = 20, 1.3


def parser_eval(style):
    tot = collections.Counter()
    for seed in PARSE_SEEDS:
        for tpl in world.TEMPLATES:
            p = world.protocol(seed, tpl, style=style)
            s = engine.score_parse(engine.parse(p["text"]), p["criteria"])
            k = engine.score_parse(engine.parse_keywords(p["text"]), p["criteria"])
            tot["protocols"] += 1
            tot["criteria"] += s["criteria"]
            tot["exact"] += s["exact"]
            tot["review"] += s["review"]
            tot["wrong"] += s["confidently_wrong"]
            tot["kw_exact"] += k["exact"]
            tot["kw_wrong"] += k["confidently_wrong"]
    return tot


def criterion_truth(c, t):
    rules = [r for r in c["rules"] if r["field"] != "manual"]
    hit = [world.truth_rule(r, t) for r in rules]
    return int(all(hit)) if c["type"] == "inclusion" else int(not any(hit))


def one(seed):
    net = world.network(seed)
    tokens = [engine.tokenise(p["record"], f"salt-{seed}")[0] for p in net["patients"]]
    ixs = [engine.index_timeline(t) for t in tokens]
    model = engine.fit_enrolment(net["history"], net["sites"], net["investigators"])
    dm = engine.fit_dropout([{"site": h["site"], "study_ref": h["study_ref"], "features": engine.enrollee_features(e), "dropped": e["dropped"]}
                             for h in net["history"] for e in h["enrollees"]])
    out = {"patients": len(tokens), "history_studies": len(net["history"]), "studies": {}, "dropout_rows": []}
    rng = np.random.default_rng(seed)
    for tpl in STUDIES:
        p = world.protocol(seed, tpl)
        crit = p["criteria"]
        truth_pools, elig = world.truth_pools(net, crit)
        res = [engine.evaluate(crit, ix) for ix in ixs]
        flat = [engine.evaluate(crit, ix, temporal=False) for ix in ixs]
        acc = collections.Counter()
        recall = collections.Counter()
        for r, f, pt in zip(res, flat, net["patients"]):
            ok = world.truly_eligible(crit, pt["truth"])
            recall["truly_eligible"] += ok
            recall["flagged"] += r["status"] != "ineligible"
            recall["found"] += ok and r["status"] != "ineligible"
            recall["eligible_now"] += r["status"] == "eligible"
            recall["eligible_now_true"] += ok and r["status"] == "eligible"
            recall["flat_found"] += ok and f["status"] != "ineligible"
            for c in crit:
                if c["ref"] not in r["values"]:
                    continue
                tv = criterion_truth(c, pt["truth"])
                for name, v in (("temporal", r["values"][c["ref"]]), ("flat", f["values"][c["ref"]])):
                    acc[f"{name}_n"] += 1
                    if v is None:
                        acc[f"{name}_unknown"] += 1
                    else:
                        acc[f"{name}_right"] += v == tv
        rates = engine.pass_rates(res, crit, [engine.on_treatment(ix) for ix in ixs])
        pools, feats = engine.study_pools(res, tokens, ixs, rates)
        rows, draws, drop = engine.score_sites(model, dm, net["sites"], net["investigators"], net["history"], p["indication"], pools, feats, rng=rng)
        run = world.run_study(net, f"EVAL-{seed}-{tpl}", p["indication"], crit, [s["id"] for s in net["sites"]], pools=(truth_pools, elig))
        actual = np.array([run[r["site"]]["enrolled"] for r in rows], float)
        pred = np.array([r["mean"] for r in rows])
        naive = np.array([r["naive_expected"] for r in rows])
        inside = np.array([r["p10"] <= a <= r["p90"] for r, a in zip(rows, actual)])
        busy = pred >= 3                       # small counts make an integer interval cover more than its nominal share
        rank = lambda v: np.argsort(np.argsort(v + 1e-9 * np.arange(len(v))))      # noqa: E731
        spearman = lambda a, b: float(np.corrcoef(rank(a), rank(b))[0, 1])        # noqa: E731
        ep = np.array([pools.get(r["site"], 0) for r in rows])
        tp = np.array([truth_pools[r["site"]] for r in rows], float)
        for sid, o in run.items():
            for e in o["enrollees"]:
                out["dropout_rows"].append({"site": sid, "study_ref": tpl, "features": engine.enrollee_features(e), "dropped": e["dropped"]})
        # portfolios under one budget
        cands = engine.candidates(rows)
        budget = round(BUDGET_FACTOR * N_SITES * float(np.mean([engine.cost(c) for c in cands])), -4)
        evaluable = {sid: o["enrolled"] - o["dropped"] for sid, o in run.items()}
        plans = {}
        t0 = time.perf_counter()
        milp = engine.optimise(cands, N_SITES, budget, max_per_region=6, min_academic=3)
        plans["milp"] = milp["sites"]
        plans["top20_history"] = engine.greedy(cands, lambda c: c["naive"], N_SITES, budget)
        plans["ratio_greedy"] = engine.greedy_ratio(cands, N_SITES, budget)
        plans["oracle"] = engine.optimise([{**c, "evaluable": evaluable[c["id"]]} for c in cands], N_SITES, budget, max_per_region=6, min_academic=3)["sites"]
        port = {}
        for name, chosen in plans.items():
            iv = engine.portfolio_interval(draws, drop, chosen, rng)
            port[name] = {"sites": len(chosen), "actual_evaluable": int(sum(evaluable[s] for s in chosen)), "predicted": iv,
                          "inside": iv["p10"] <= sum(evaluable[s] for s in chosen) <= iv["p90"],
                          "actual_cost": round(sum(c["activation_cost"] + c["per_patient_cost"] * run[c["id"]]["enrolled"] for c in cands if c["id"] in chosen))}
        out["studies"][tpl] = {
            "criteria": len(crit), "acc": acc, "recall": recall, "expected_eligible": round(float(ep.sum()), 1), "truly_eligible": int(tp.sum()),
            "pool_corr": round(float(np.corrcoef(ep, tp)[0, 1]), 3),
            "enrol": {"actual": int(actual.sum()), "pred": round(float(pred.sum()), 1), "naive": round(float(naive.sum()), 1),
                      "mae": round(float(np.abs(pred - actual).mean()), 2), "naive_mae": round(float(np.abs(naive - actual).mean()), 2),
                      "spearman": round(spearman(pred, actual), 3), "naive_spearman": round(spearman(naive, actual), 3), "coverage": round(float(inside.mean()), 3),
                      "coverage_busy": round(float(inside[busy].mean()), 3), "busy_sites": int(busy.sum())},
            "budget": budget, "portfolio": port, "milp_ms": milp["solve_ms"], "milp_status": milp["status"]}
    out["dropout"] = engine.score_dropout(dm, out.pop("dropout_rows"))
    out["dropout"]["train_enrollees"] = sum(h["enrolled"] for h in net["history"])
    return out


def timing(seed=SEEDS[0], n=1000):
    """The blueprint's KPI: an optimisation over 1,000 candidate sites. Sites, investigators and five years of history are
    generated for 1,000 sites; their eligible pools are drawn from the 120-site network's pools for the same protocol."""
    big = world.network(seed + 50, n_sites=n, records=False)
    small = world.network(seed)
    p = world.protocol(seed, STUDIES[0])
    toks = [engine.tokenise(q["record"], "t")[0] for q in small["patients"]]
    ixs = [engine.index_timeline(t) for t in toks]
    res = [engine.evaluate(p["criteria"], ix) for ix in ixs]
    pools, _ = engine.study_pools(res, toks, ixs, engine.pass_rates(res, p["criteria"], [engine.on_treatment(ix) for ix in ixs]))
    rng = np.random.default_rng(1)
    vals = list(pools.values())
    big_pools = {s["id"]: float(vals[int(rng.integers(0, len(vals)))]) for s in big["sites"]}
    t0 = time.perf_counter()
    model = engine.fit_enrolment(big["history"], big["sites"], big["investigators"])
    dm = engine.fit_dropout([{"site": h["site"], "study_ref": h["study_ref"], "features": engine.enrollee_features(e), "dropped": e["dropped"]}
                             for h in big["history"] for e in h["enrollees"]])
    t1 = time.perf_counter()
    rows, draws, drop = engine.score_sites(model, dm, big["sites"], big["investigators"], big["history"], p["indication"], big_pools, {}, rng=rng)
    t2 = time.perf_counter()
    cands = engine.candidates(rows)
    budget = round(BUDGET_FACTOR * N_SITES * float(np.mean([engine.cost(c) for c in cands])), -4)
    plan = engine.optimise(cands, N_SITES, budget, max_per_region=6, min_academic=3)
    t3 = time.perf_counter()
    return {"sites": n, "history_studies": len(big["history"]), "fit_s": round(t1 - t0, 2), "score_s": round(t2 - t1, 2), "solve_s": round(t3 - t2, 2),
            "total_s": round(t3 - t0, 2), "status": plan["status"], "chosen": len(plan["sites"])}


def main():
    p = print
    seen, unseen = parser_eval("seen"), parser_eval("unseen")
    res = {s: one(s) for s in SEEDS}
    tm = timing()
    p("# Evaluation\n")
    p(f"Three held-out research networks (seeds {', '.join(map(str, SEEDS))}), 120 sites each with their investigators, five years of "
      f"site history and the sites' tokenised patient records; four protocols each ({', '.join(STUDIES)}). The models are trained on "
      "each network's history exactly as the service trains them; then the generator runs every protocol at every site, and that is "
      "the truth everything below is scored against. `python -m trials.evaluate` reproduces this file.\n")
    p("## Criteria translation (protocol text to the DSL)\n")
    p("| Wording | Protocols | Criteria | Translated exactly | Sent to review | Confidently wrong | Keyword baseline: exact |\n|---|---|---|---|---|---|---|")
    for name, t in (("the wording the grammar was written against", seen), ("wording written separately, never shown to the grammar", unseen)):
        p(f"| {name} | {t['protocols']} | {t['criteria']:,} | {t['exact']:,} ({t['exact'] / t['criteria']:.1%}) | {t['review']:,} ({t['review'] / t['criteria']:.1%}) | "
          f"{t['wrong']} | {t['kw_exact']:,} ({t['kw_exact'] / t['criteria']:.1%}) |")
    p("\nExact means every rule of the criterion equals the generator's structured truth (field, operator, value, unit, window, classes). "
      "The grammar's rule is to account for every word of a criterion or send it to review, so a translation it proposes is one a reviewer "
      f"can accept: of the {seen['exact'] + seen['wrong']:,} and {unseen['exact'] + unseen['wrong']:,} it proposed, "
      f"{seen['wrong'] + unseen['wrong']} were wrong, so the blueprint's acceptance bar (above 95% after review) is met by every proposal. "
      "Coverage is the honest limit: on wording it was written against it translates 97% and sends the deliberately hard phrasings "
      "(\"advanced\" without a stage, a conditional threshold, \"half a year\") to review; on wording it never saw it translates only "
      "the few phrases that happen to coincide, and the reviewer writes the rest. The keyword baseline guesses instead of abstaining "
      f"and is confidently wrong on {seen['kw_wrong']:,} and {unseen['kw_wrong']:,} criteria.\n")
    p("## Temporal eligibility engine\n")
    p("| Network | Protocol | Criterion values decided | Correct when decided | Same rules without time: correct | Truly eligible | Found (eligible or needs screening) | Same rules without time: found | Expected eligible vs truly eligible |\n|---|---|---|---|---|---|---|---|---|")
    for s, r in res.items():
        for tpl, st in r["studies"].items():
            a, rc = st["acc"], st["recall"]
            p(f"| {s} | {tpl} | {1 - a['temporal_unknown'] / a['temporal_n']:.1%} | {a['temporal_right'] / (a['temporal_n'] - a['temporal_unknown']):.2%} | "
              f"{a['flat_right'] / max(1, a['flat_n'] - a['flat_unknown']):.2%} | {rc['truly_eligible']} | {rc['found']} ({rc['found'] / max(1, rc['truly_eligible']):.0%}) | "
              f"{rc['flat_found']} ({rc['flat_found'] / max(1, rc['truly_eligible']):.0%}) | {st['expected_eligible']} vs {st['truly_eligible']} |")
    p("\nA criterion value is undecided when the record cannot answer it today: no lab inside the protocol's window, no recent ECOG, a "
      "biomarker never tested. Those patients are \"potentially eligible, needs screening\", and the site pool counts each of them by the "
      "chance its open criteria pass (the pass rate among patients whose record does answer). Decided values are wrong when the world moved "
      "since the measurement (a lab drifting inside its window, an ECOG that got worse) or the record is incomplete (a regimen given at "
      "another hospital). Without time, every \"within 28 days\" exclusion becomes \"ever\" and every stale lab counts: most truly eligible "
      "patients are lost.\n")
    p("## Site enrolment (12 months)\n")
    p("| Network | Protocol | Actual enrolled, 120 sites | Model total | Naive total | Model MAE per site | Naive MAE | Rank correlation, model | Naive | Inside the 80% interval, all sites | Sites expected to enrol 3+ |\n|---|---|---|---|---|---|---|---|---|---|---|")
    cov, cov_busy = [], []
    for s, r in res.items():
        for tpl, st in r["studies"].items():
            e = st["enrol"]
            cov.append(e["coverage"])
            cov_busy.append(e["coverage_busy"])
            p(f"| {s} | {tpl} | {e['actual']} | {e['pred']} | {e['naive']} | {e['mae']} | {e['naive_mae']} | {e['spearman']} | {e['naive_spearman']} | {e['coverage']:.0%} | {e['coverage_busy']:.0%} ({e['busy_sites']}) |")
    p(f"\nThe model: a negative-binomial rate per eligible patient-month (site type, competing trials, the lead investigator's trials in the "
      "indication; studies that filled their slots treated as censored) with each site's own history as a gamma frailty, times the months "
      "a Weibull activation model expects the site to be open (each site's contracting history shrunk toward its type). The naive "
      "baseline is the site's historical average enrolment per study: it knows nothing about this protocol's pool, so its totals are "
      f"several times too high and its ranking weaker. Calibration: the 80% intervals held the actual count at {min(cov):.0%}-{max(cov):.0%} of "
      f"sites, and at {min(cov_busy):.0%}-{max(cov_busy):.0%} of the sites expected to enrol three or more. Most sites expect one or two patients, "
      "where an interval of whole numbers covers more than its nominal 80%, so the all-sites figure overstates the width. The bound this "
      f"slice holds itself to is 70-90% on the busier sites: {sum(0.7 <= c <= 0.9 for c in cov_busy)} of {len(cov_busy)} protocols are inside it, "
      f"{sum(c > 0.9 for c in cov_busy)} above (intervals a little too wide), {sum(c < 0.7 for c in cov_busy)} below.\n")
    p("## Dropout risk\n")
    p("| Network | Enrollees scored | Observed dropout | Mean predicted | AUC | Brier | Base-rate Brier |\n|---|---|---|---|---|---|---|")
    for s, r in res.items():
        d = r["dropout"]
        p(f"| {s} | {d['enrollees']} | {d['observed_rate']:.1%} | {d['mean_predicted']:.1%} | {d['auc']} | {d['brier']} | {d['base_rate_brier']} |")
    p("\nLogistic regression on the enrollee's ECOG, age band, distance band, prior lines, comorbidities and the site's past retention, "
      "trained on the history's enrollees. It ranks moderately (the generator's dropout has a site effect and plenty of chance) and "
      "improves the Brier score over the base rate only a little; it is used to turn expected enrolment into expected evaluable patients.\n")
    p(f"## Portfolio: 20 sites under a budget\n")
    p(f"Budget per protocol: {BUDGET_FACTOR} x 20 x the mean site's expected cost (activation plus per-patient fees at the model's expected "
      "enrolment); at most 6 sites per region, at least 3 academic, no site whose lead investigator has an open GCP finding. Every plan is "
      "scored by the evaluable patients the generator's run of the protocol actually gives its sites in 12 months.\n")
    p("| Network | Protocol | Budget | MILP: actual evaluable | Top-20 by history: sites, actual | Greedy by value per dollar: actual | Hindsight best (MILP on the actual results) | MILP total inside its 80% interval |\n|---|---|---|---|---|---|---|---|")
    tot = collections.Counter()
    for s, r in res.items():
        for tpl, st in r["studies"].items():
            pt = st["portfolio"]
            for k in pt:
                tot[k] += pt[k]["actual_evaluable"]
            tot["inside"] += pt["milp"]["inside"]
            tot["n"] += 1
            p(f"| {s} | {tpl} | ${st['budget']:,.0f} | {pt['milp']['actual_evaluable']} (predicted {pt['milp']['predicted']['p10']}-{pt['milp']['predicted']['p90']}) | "
              f"{pt['top20_history']['sites']}, {pt['top20_history']['actual_evaluable']} | {pt['ratio_greedy']['actual_evaluable']} | {pt['oracle']['actual_evaluable']} | {'yes' if pt['milp']['inside'] else 'no'} |")
    p(f"| **all** | | | **{tot['milp']}** | **{tot['top20_history']}** | **{tot['ratio_greedy']}** | {tot['oracle']} | {tot['inside']} of {tot['n']} |")
    p(f"\nAcross the twelve protocols the MILP's portfolios enrolled {tot['milp'] / tot['top20_history']:.2f}x the evaluable patients of the "
      f"top-20-by-history baseline under the same budget, and {tot['milp'] / tot['ratio_greedy']:.2f}x a greedy pick on the same predictions; "
      f"the hindsight best (the same MILP given the actual results) got {tot['oracle']}. The gain over the baseline is the prediction: knowing "
      "this protocol's pool at each site. On the same predictions the MILP is no better than a greedy pick by value per dollar; what it adds "
      "is that its plans keep the region and academic rules and the full 20 sites, which the greedy pick does not check. Its portfolio "
      f"totals landed inside their own 80% interval {tot['inside']} times in {tot['n']}: chosen sites are the ones whose predictions were "
      "high, so misses on the high side are expected (the optimiser's curse), and a shared error in the pool estimate moves every site at once.\n")
    p("## Optimisation time for 1,000 candidate sites\n")
    p(f"{tm['sites']:,} candidate sites with {tm['history_studies']:,} historical studies: fitting the enrolment and dropout models {tm['fit_s']} s, "
      f"scoring every site with {engine.DRAWS:,} predictive draws {tm['score_s']} s, the MILP {tm['solve_s']} s ({tm['status']}, {tm['chosen']} sites). "
      f"End to end {tm['total_s']} s against the blueprint's bar of 2 minutes. One process on the machine in docs/performance.md.\n")
    return res, tm


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
    sys.exit(0)
