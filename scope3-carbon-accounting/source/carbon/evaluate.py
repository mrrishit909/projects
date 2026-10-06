"""Held-out evaluation on three companies the demo never uses (different seeds: other suppliers, names, spend, factors'
errors and supplier network).

    python -m carbon.evaluate            # prints the markdown behind docs/evaluation.md

Each company runs the service's own pipeline in memory (the same engine functions the API calls): the supplier matcher
trained on earlier engagements (seeds 900 and 901), the category classifier trained on the company's own analyst-labelled
lines from last year, its disclosures read and validated, its inventory calculated with and without supplier-specific
factors, and engagement ranked. Everything is scored against the generator's truth, which the pipeline never reads.
"""
import collections
import sys
import time

import numpy as np

from . import engine, world

SEEDS = (101, 102, 103)
N_LINES = 240_000                 # invoice lines per company; the inventory's size does not depend on it (spend is fixed)
TRAIN = (900, 901)
TOP = 20


def one(seed, resolver):
    w = world.company(seed)
    recs = w["records"]
    truth_sup = [r["supplier"] for r in recs]
    res = engine.resolve(recs, resolver)
    pairs, _x, _n = engine.candidates(recs)
    true_pairs = {(i, j) for i in range(len(recs)) for j in range(i + 1, len(recs)) if truth_sup[i] == truth_sup[j]}
    resolution = {"records": len(recs), "true_suppliers": len(set(truth_sup)), "model": engine.pairwise_scores(res["cluster"], truth_sup),
                  "exact": engine.pairwise_scores(engine.baseline_clusters(recs), truth_sup),
                  "fuzzy": engine.pairwise_scores(engine.baseline_clusters(recs, "fuzzy", resolver.fuzzy_threshold_), truth_sup),
                  "blocking_recall": len(true_pairs & set(pairs)) / max(1, len(true_pairs)), "candidate_pairs": len(pairs),
                  "all_pairs": len(recs) * (len(recs) - 1) // 2, "review": len(res["review"])}
    key = {r["vendor_ref"]: f"S{res['cluster'][i]}" for i, r in enumerate(recs)}
    vname = {r["vendor_ref"]: r["name"] for r in recs}
    vcountry = {r["vendor_ref"]: r["country"] for r in recs}
    # categories: trained on last year's labels, scored on this year's lines
    lab = world.labelled_sample(seed)
    clf = engine.train_classifier([engine.class_text(d, g, vname[v]) for d, g, v in zip(lab["description"], lab["gl_code"], lab["vendor_ref"])], lab["label"])
    parts = [world.ledger_month(seed, m, n) for m, n in enumerate(world.month_lines(N_LINES), 1)]
    L = {k: (np.concatenate([p[k] for p in parts]) if isinstance(parts[0][k], np.ndarray) else sum((p[k] for p in parts), [])) for k in parts[0] if k != "_injected"}
    keep, usd, _rate, rejected, dups = engine.normalize_ap(L, set(vname), world.YEAR)
    desc, gl, ven = [L["description"][i] for i in keep], [L["gl_code"][i] for i in keep], [L["vendor_ref"][i] for i in keep]
    tcat = [L["true_category"][i] for i in keep]
    cats, _conf, meth, _k, _l = engine.map_lines(clf, desc, gl, [vname[v] for v in ven])
    rules = [engine.rule_category(d, g) for d, g in zip(desc, gl)]
    new_sup = {s["idx"] for s in w["suppliers"] if s["since"] == world.YEAR}
    newm = np.array([L["true_supplier"][i] in new_sup for i in keep])
    categories = {"model": engine.category_scores(cats, tcat, usd), "rules": engine.category_scores(rules, tcat, usd),
                  "new_suppliers_model": engine.category_scores([c for c, m in zip(cats, newm) if m], [c for c, m in zip(tcat, newm) if m], usd[newm]),
                  "fallback_share": round(meth.count("fallback") / len(meth), 4), "lines": len(keep), "duplicates": dups, "rejected": len(rejected)}
    # disclosures
    docs = world.disclosures(seed)
    names = [engine.norm_name(r["name"]) for r in recs]
    vec = engine.name_vectorizer().fit(names)
    X = vec.transform(names)
    fields = collections.Counter()
    sup_f, factors_extra, edges, matched_ok, accepted = {}, {}, {}, 0, 0
    for d in docs:
        tr = d["truth"]
        x, nx = engine.extract(d["text"]), engine.naive_extract(d["text"])
        for f, tv in (("revenue_usd", tr["revenue_usd"] * (1000 if tr["unit_slip"] else 1)), ("scope1_t", tr["scope1_t"]), ("scope2_t", tr["scope2_t"]), ("scope3_upstream_t", tr["scope3_upstream_t"])):
            if tv is None:
                continue
            fields["total"] += 1
            fields["parser"] += x[f] is not None and abs(x[f] / tv - 1) < 0.01
            fields["naive"] += nx[f] is not None and abs(nx[f] / tv - 1) < 0.01
        v, _why = engine.validate_disclosure(x)
        j, _s = engine.match_name(x["company"] or "", names, X, vec)
        if j is None:
            continue
        matched_ok += recs[j]["supplier"] == d["supplier"]
        k = key[recs[j]["vendor_ref"]]
        ups = [key[recs[jj]["vendor_ref"]] for p in x["principal_suppliers"] if (jj := engine.match_name(p, names, X, vec)[0]) is not None]
        if ups:
            edges[k] = [u for u in ups if u != k]
        if v is not None:
            accepted += 1
            # the supplier's main category with us, as the service derives it from the mapped lines
            spend = collections.Counter()
            for c, vv, u in zip(cats, ven, usd):
                if key[vv] == k and c:
                    spend[c] += u
            main = spend.most_common(1)[0][0] if spend else None
            if main and main not in world.COVERED:
                sup_f[f"{k}|{main}"] = f"SUP:{k}"
                factors_extra[f"SUP:{k}"] = {"value": v, "gsd": 1.1, "dispersion": 0.0}
    extraction = {"documents": len(docs), "fields": fields["total"], "parser": fields["parser"], "naive": fields["naive"], "accepted": accepted,
                  "slips_caught": sum(d["truth"]["unit_slip"] and engine.validate_disclosure(engine.extract(d["text"]))[0] is None for d in docs),
                  "slips": sum(d["truth"]["unit_slip"] for d in docs), "matched_right": matched_ok}
    # the inventory, against the truth
    ship, bills = world.shipments(seed), world.utility_bills(seed)
    fac = {f["id"]: f["country"] for f in w["facilities"]}
    seen_bills, bill_rows = set(), []
    for b in bills:
        if b["bill"] not in seen_bills:
            seen_bills.add(b["bill"])
            bill_rows.append(b)
    n_ap, n_fr, n_ut = len(keep), len(ship), len(bill_rows)
    A = {"kind": np.array(["ap"] * n_ap + ["freight"] * n_fr + ["utility"] * n_ut),
         "category": np.array([c or "" for c in cats] + [""] * (n_fr + n_ut)),
         "country": np.array([vcountry[v] for v in ven] + [s["origin"] for s in ship] + [fac[b["facility_id"]] for b in bill_rows]),
         "supplier": np.array([key[v] for v in ven] + [""] * (n_fr + n_ut)),
         "amount_usd": np.concatenate([usd, np.zeros(n_fr + n_ut)]),
         "tkm": np.array([0.0] * n_ap + [s["weight"] * engine.TO_KG[s["weight_unit"]] / 1000 * s["distance"] * engine.TO_KM[s["distance_unit"]] for s in ship] + [0.0] * n_ut),
         "mode": np.array([""] * n_ap + [s["mode"] for s in ship] + [""] * n_ut),
         "fuel": np.array([""] * (n_ap + n_fr) + [b["fuel"] for b in bill_rows]),
         "qty_norm": np.array([0.0] * (n_ap + n_fr) + [engine.energy(b["fuel"], b["quantity"], b["unit"])[0] for b in bill_rows])}
    true_kg = np.concatenate([[L["true_kg"][i] for i in keep], [s["true_kg"] for s in ship], [b["true_kg"] for b in bill_rows]])
    tcat_all = np.array(tcat + [""] * (n_fr + n_ut))
    true_s3 = engine.s3_categories(A["kind"], tcat_all)
    true_scope = np.where(A["kind"] == "utility", np.where(A["fuel"] == "electricity", 2, 1), 3)
    true_b = {"total": true_kg.sum(), "scope1": true_kg[true_scope == 1].sum(), "scope2": true_kg[true_scope == 2].sum(), "scope3": true_kg[true_scope == 3].sum()}
    for k in (1, 2, 4, 6):
        true_b[f"s3:{k}"] = true_kg[(true_scope == 3) & (true_s3 == k)].sum()
    for c in world.CATS:
        if c not in world.COVERED:
            true_b[f"cat:{c}"] = true_kg[(A["kind"] == "ap") & (tcat_all == c)].sum()
    inv = {}
    t0 = time.time()
    for name, version, sf in (("catalogue", "EF-2025.1", {}), ("with disclosures", "EF-2025.1", sup_f), ("last year's catalogue", "EF-2024.2", {})):
        F = {**world.catalogue(version), **factors_extra}
        fid, method, scope, kg = engine.calculate(A, F, sf)
        h1 = engine.result_hash(np.arange(len(kg)), fid, kg)
        h2 = engine.result_hash(np.arange(len(kg)), *engine.calculate(A, F, sf)[::3])
        s3c = engine.s3_categories(A["kind"], A["category"])
        groups = engine.mc_groups(fid, A["supplier"], scope, s3c, np.where(A["kind"] == "ap", A["category"], ""), kg, F)
        mc = engine.monte_carlo(groups, F, seed=seed)
        inv[name] = {"mc": mc, "hash": h1, "reproduced": h1 == h2, "supplier_specific_spend": float(usd[np.array(method[:n_ap] == "supplier-specific")].sum() / usd.sum())}
    calc_seconds = round((time.time() - t0) / 6, 2)
    # engagement: which suppliers to engage first
    est = inv["with disclosures"]["mc"]
    fid, method, scope, kg = engine.calculate(A, {**world.catalogue("EF-2025.1"), **factors_extra}, sup_f)
    direct = collections.Counter()
    spend = collections.Counter()
    for k, m, x, u in zip(A["supplier"][:n_ap], method[:n_ap], kg[:n_ap], usd):
        spend[k] += u
        if m in ("spend-based", "supplier-specific"):
            direct[k] += x / 1000
    infl = engine.influence(dict(direct), edges)
    order = {"spend": sorted(spend, key=lambda k: -spend[k]), "emissions": sorted(direct, key=lambda k: -direct[k]), "influence": sorted(infl, key=lambda k: -infl[k])}
    key_true = collections.defaultdict(collections.Counter)
    for r in recs:
        key_true[key[r["vendor_ref"]]][r["supplier"]] += 1
    true_e = {s["idx"]: s["spend_usd"] * sum(sh * world.true_intensity(w, s, c) for c, sh in s["mix"].items() if c not in world.COVERED) / 1000 for s in w["suppliers"]}
    up = {s["idx"]: s["upstream"] for s in w["suppliers"] if s["upstream"]}
    tot = sum(true_e.values())
    engage = {by: engine.covered_emissions({key_true[k].most_common(1)[0][0] for k in o[:TOP]}, true_e, up) / tot for by, o in order.items()}
    best = sorted(true_e, key=lambda s: -world.true_influence(w, true_e)[s])[:TOP]
    engage["oracle"] = engine.covered_emissions(set(best), true_e, up) / tot
    return {"resolution": resolution, "categories": categories, "extraction": extraction, "truth": true_b, "inventory": inv, "engage": engage,
            "edges": sum(len(v) for v in edges.values()), "calc_seconds": calc_seconds, "lines": len(kg), "est": est}


def pct(x, d=0):
    return f"{100 * x:.{d}f}%"


def main():
    t0 = time.time()
    resolver, rm = engine.train_resolver([world.company(s)["records"] for s in TRAIN])
    res = {s: one(s, resolver) for s in SEEDS}
    p = print
    p("# Evaluation\n")
    p(f"Three held-out companies (seeds {', '.join(map(str, SEEDS))}), each with six subsidiaries' vendor masters, {N_LINES:,} invoice lines for the year "
      "(the inventory's size does not depend on the line count: the year's spend is fixed), 40,000 shipments, a year of utility bills and the larger suppliers' "
      f"disclosures. The supplier matcher is trained on two earlier engagements (seeds {TRAIN[0]} and {TRAIN[1]}, {rm['training_pairs']:,} candidate pairs); the "
      "category classifier on each company's own 6,000 analyst-labelled lines from last year (about 2% mislabelled, as people do). Everything is scored against "
      "the generator's truth, which the pipeline never reads. `python -m carbon.evaluate` reproduces this file.\n")
    p("## Supplier resolution\n")
    p("| Company | Vendor records | True suppliers | Matcher: precision / recall / F1 | Exact name (after case and punctuation) | Fuzzy name similarity alone | Pairs sent for review |\n|---|---|---|---|---|---|---|")
    for s, r in res.items():
        x = r["resolution"]
        f = lambda m: f"{m['precision']:.3f} / {m['recall']:.3f} / **{m['f1']:.3f}**"     # noqa: E731
        p(f"| {s} | {x['records']} | {x['true_suppliers']} | {f(x['model'])} ({x['model']['clusters']} suppliers) | {f(x['exact'])} ({x['exact']['clusters']}) | "
          f"{f(x['fuzzy'])} ({x['fuzzy']['clusters']}) | {x['review']} |")
    b = res[SEEDS[0]]["resolution"]
    p(f"\nPairwise scores over every pair of vendor records placed together. Blocking (character n-gram neighbours plus shared tax ids and domains) keeps "
      f"{b['candidate_pairs']:,} of {b['all_pairs']:,} possible pairs and loses {', '.join(pct(1 - r['resolution']['blocking_recall'], 1) for r in res.values())} of the true ones. "
      "Exact matching is precise but finds only a seventh to a fifth of the duplicates; fuzzy similarity alone finds most and also merges different companies with near-identical "
      "names. The matcher's weights say why it does better: a shared tax id or company domain and the same country carry as much as the name, and two "
      f"different tax ids veto a merge. Weights: {', '.join(f'{k} {v}' for k, v in rm['weights'].items())}.\n")
    p("## Spend categories\n")
    p("| Company | Classifier: accuracy / spend-weighted / macro-F1 | Rules (keywords, then GL account) | Orphans after mapping: classifier | Rules | Classifier on suppliers new this year (spend-weighted) | Sent to the fallback |\n|---|---|---|---|---|---|---|")
    for s, r in res.items():
        m, b_, n = r["categories"]["model"], r["categories"]["rules"], r["categories"]["new_suppliers_model"]
        p(f"| {s} | {m['accuracy']:.3f} / {m['spend_weighted_accuracy']:.3f} / {m['macro_f1']:.3f} | {b_['accuracy']:.3f} / {b_['spend_weighted_accuracy']:.3f} / {b_['macro_f1']:.3f} | "
          f"{pct(m['orphan_rate'], 2)} of lines, {pct(m['orphan_spend_share'], 2)} of spend | {pct(b_['orphan_rate'], 2)}, {pct(b_['orphan_spend_share'], 2)} | {n['spend_weighted_accuracy']:.3f} | {pct(r['categories']['fallback_share'], 1)} |")
    p("\nOrphans are lines no category could be given to (the classifier abstained below 0.55 and neither a keyword nor the GL account answered); the blueprint's bar "
      "is under 1%. The descriptions come from a few hundred templates, a fifth of them shared between categories or uninformative, so these accuracies are an "
      "upper bound for real ledgers: the vendor's name and the account carry much of the signal, which is why lines from suppliers new this year (absent from the labels) score lower.\n")
    p("## Supplier disclosures\n")
    p("| Company | Disclosures | Figures read within 1%: parser | Naive (first number, assumed units) | Accepted as factors | Unit slips caught | Matched to the right supplier |\n|---|---|---|---|---|---|---|")
    for s, r in res.items():
        x = r["extraction"]
        p(f"| {s} | {x['documents']} | {x['parser']} of {x['fields']} | {x['naive']} of {x['fields']} | {x['accepted']} | {x['slips_caught']} of {x['slips']} | {x['matched_right']} of {x['documents']} |")
    p("\nA disclosure is accepted when revenue, scope 1, scope 2 and scope 3 upstream are all found and the intensity is plausible; the rest go to review with the reason "
      "(about one in six omits its upstream emissions). The planted unit slip (revenue in thousands labelled millions) is read exactly as written and then refused by the "
      "plausibility check, which is the point: the parser reads, the validation judges.\n")
    p("## The inventory against the truth\n")
    p("Estimated tCO2e with the 95% Monte Carlo interval, against the generator's true emissions (true sector intensities, each supplier's own offset, true grid, fuel "
      "and freight factors). *With disclosures* replaces the sector factor for the accepted suppliers' main category.\n")
    p("| Company | Scope | True | Catalogue only | Error | 95% interval covers truth | With disclosures | Error | Covers |\n|---|---|---|---|---|---|---|---|---|")
    cover = collections.Counter()
    for s, r in res.items():
        T = r["truth"]
        for k, label in (("total", "Total"), ("scope1", "Scope 1"), ("scope2", "Scope 2"), ("s3:1", "S3 cat 1 purchased goods"), ("s3:2", "S3 cat 2 capital goods"),
                         ("s3:4", "S3 cat 4 transport"), ("s3:6", "S3 cat 6 travel")):
            tv = T[k] / 1000
            row = [f"| {s} | {label} | {tv:,.0f}"]
            for name in ("catalogue", "with disclosures"):
                m = r["inventory"][name]["mc"][k]
                ok = m["p2_5"] <= tv <= m["p97_5"]
                row.append(f"{m['t']:,.0f} [{m['p2_5']:,.0f}–{m['p97_5']:,.0f}] | {100 * (m['t'] / tv - 1):+.1f}% | {'yes' if ok else '**no**'}")
            p(" | ".join(row) + " |")
    for s, r in res.items():
        for name in ("catalogue", "with disclosures"):
            for k, m in r["inventory"][name]["mc"].items():
                if k in r["truth"] and r["truth"][k] > 0:
                    tv = r["truth"][k] / 1000
                    cover[(name, "n")] += 1
                    cover[(name, "95")] += m["p2_5"] <= tv <= m["p97_5"]
                    cover[(name, "90")] += m["p5"] <= tv <= m["p95"]
                    if k.startswith("cat:"):
                        cover[(name, "abs_err")] += abs(m["t"] / tv - 1)
                        cover[(name, "cats")] += 1
    p("\n**Calibration across every bucket** (total, scopes, scope 3 categories and the ten spend categories, three companies):\n")
    p("| Factors | Buckets | Inside the 95% interval | Inside the 90% interval | Mean absolute error, spend categories | Spend on supplier-specific factors |\n|---|---|---|---|---|---|")
    for name in ("catalogue", "with disclosures"):
        n = cover[(name, "n")]
        ss = np.mean([r["inventory"][name]["supplier_specific_spend"] for r in res.values()])
        p(f"| {name} | {n} | {cover[(name, '95')]} ({pct(cover[(name, '95')] / n)}) | {cover[(name, '90')]} ({pct(cover[(name, '90')] / n)}) | {pct(cover[(name, 'abs_err')] / cover[(name, 'cats')], 1)} | {pct(ss, 1)} |")
    c95 = {n: cover[(n, "95")] / cover[(n, "n")] for n in ("catalogue", "with disclosures")}
    p(f"\nThe big errors are the catalogue's: when a sector average is itself 15% or more off, it moves a whole category, and no amount of good mapping fixes "
      f"that. With the catalogue alone the 95% intervals hold the truth in {pct(c95['catalogue'])} of buckets, so they are somewhat too narrow; with the "
      f"accepted disclosures, {pct(c95['with disclosures'])}. Supplier-specific factors replace the sector average only for the suppliers who disclosed in full "
      "(the spend share in the last column), so the rest of the error stays where it was.\n")
    p("## Reproducibility and lineage\n")
    p("| Company | Activity lines | Same version twice: identical hash | 2025.1 vs 2024.2: different hash | Calculation time (in memory) |\n|---|---|---|---|---|")
    for s, r in res.items():
        inv = r["inventory"]
        p(f"| {s} | {r['lines']:,} | {'yes' if inv['catalogue']['reproduced'] and inv['with disclosures']['reproduced'] else 'NO'} | "
          f"{'yes' if inv['catalogue']['hash'] != inv[chr(108) + 'ast year' + chr(39) + 's catalogue']['hash'] else 'NO'} | {r['calc_seconds']} s |")
    p("\nIn the service the same hash is recomputed from the stored activities and from the stored lineage rows (`POST /v1/calculations/{id}:reproduce`); the tests "
      "check that a frozen version cannot be edited in the database and that every line carrying CO2e has its source, mapping and factor.\n")
    p("## Which suppliers to engage\n")
    p(f"Share of the generator's true supplier emissions within reach of the top {TOP} suppliers: their own, plus the part of every other supplier's footprint they "
      "sell to it (a mill whose steel goes into our component makers' parts). The network is what the disclosures reveal: each discloser's principal suppliers.\n")
    p("| Company | By spend (baseline) | By estimated emissions | By emissions + network centrality | Ranked by true emissions + network (oracle) | Network edges seen |\n|---|---|---|---|---|---|")
    for s, r in res.items():
        e = r["engage"]
        p(f"| {s} | {pct(e['spend'], 1)} | {pct(e['emissions'], 1)} | {pct(e['influence'], 1)} | {pct(e['oracle'], 1)} | {r['edges']} |")
    gain = [100 * (r["engage"]["influence"] - r["engage"]["emissions"]) for r in res.values()]
    step = [100 * (r["engage"]["emissions"] - r["engage"]["spend"]) for r in res.values()]
    p(f"\nRanking by estimated emissions instead of spend is the large step ({', '.join(f'+{x:.1f}' for x in step)} points). Adding the network centrality "
      f"changes the result by {', '.join(f'{x:+.1f}' for x in gain)} points: no better overall, because only the disclosing suppliers reveal who they buy from, and "
      "a mill that sells to many component makers is usually already near the top on its own emissions.\n")
    print(f"<!-- {time.time() - t0:.0f} s -->", file=sys.stderr)
    return res


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
    sys.exit(0)
