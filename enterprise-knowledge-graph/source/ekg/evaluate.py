"""Held-out evaluation on three corpora the demo never uses (other seeds: other people, vendors, decisions, owners).

    python -m ekg.evaluate            # prints the markdown behind docs/evaluation.md

Each corpus is processed exactly as the service processes it: the extractor and the linker are trained on that corpus's
annotated fifth, and everything is scored against the generator's truth on the other four fifths. Retrieval and answers are
scored on questions generated from the truth, for two principals: one who can read every container and one engineer who
cannot read procurement, security or contracts. The security suite runs for every principal with a distinct set of
readable containers.
"""
import collections
import re
import sys
import time

import numpy as np

from . import engine as E
from . import world

SEEDS = (101, 102, 103)


def build(seed, day=world.NOW, told=()):
    objs = world.view(world.objects(seed, told), day)
    for o in objs:
        o["id"] = o["external_id"]
    ann, records = world.annotations(objs)
    t0 = time.perf_counter()
    m = E.train(objs, ann, records)
    det, A = E.Detector(m["gazetteer"]), E.Anchors(m["gazetteer"])
    t1 = time.perf_counter()
    ch, me, asr = E.process(objs, det, m["extractor"], A, m["linker"])
    ix = E.Index(objs, ch, me, asr, E.entities_from(me, asr, A), day)
    t2 = time.perf_counter()
    co = world.company(seed)
    acl = world.containers(co)
    users = {u["email"]: E.readable_containers(acl, u["groups"]) for u in world.principals(co)[0]}
    return {"seed": seed, "objs": objs, "ann": ann, "models": m, "det": det, "A": A, "chunks": ch, "mentions": me, "assertions": asr, "ix": ix,
            "co": co, "acl": acl, "users": users, "seconds": {"train": t1 - t0, "process": t2 - t1}}


def reducer(b):
    """An index built from the readable objects only (same entity links): the reference for non-interference."""
    def red(conts):
        keep = {o["id"] for o in b["objs"] if o["container"] in conts}
        return E.Index([o for o in b["objs"] if o["id"] in keep], [c for c in b["chunks"] if c["object_id"] in keep],
                       [m for m in b["mentions"] if m["object_id"] in keep], [a for a in b["assertions"] if a["object_id"] in keep], b["ix"].entities, b["ix"].clock)
    return red


# --- entity resolution ---------------------------------------------------------------------------------------------------
def bcubed(pairs):
    byp, byg = collections.defaultdict(list), collections.defaultdict(list)
    for i, (p, g) in enumerate(pairs):
        byp[p].append(i)
        byg[g].append(i)
    P = R = 0.0
    for p, g in pairs:
        inter = sum(1 for j in byp[p] if pairs[j][1] == g)
        P += inter / len(byp[p])
        R += inter / len(byg[g])
    n = len(pairs)
    P, R = P / n, R / n
    c2 = lambda n: n * (n - 1) // 2                                          # noqa: E731
    tp = sum(c2(c) for c in collections.Counter(pairs).values())
    pp, gg = sum(c2(len(v)) for v in byp.values()), sum(c2(len(v)) for v in byg.values())
    return {"b3_precision": round(P, 4), "b3_recall": round(R, 4), "b3_f1": round(2 * P * R / (P + R), 4),
            "pairwise_precision": round(tp / max(1, pp), 4), "pairwise_recall": round(tp / max(1, gg), 4), "pairwise_f1": round(2 * tp / max(1, pp + gg), 4), "mentions": n}


def resolution(b):
    """Mentions in the documents nobody annotated, scored against the truth's identity of each mention."""
    objmap = {o["id"]: o for o in b["objs"]}
    merges = {s["merge"]: s["keep"] for s in E.merge_suggestions(b["assertions"])}
    A = b["A"]
    anchors = collections.defaultdict(list)
    for k in list(A.p) + list(A.teams) + list(A.vendors):
        for a in A.aliases(k):
            anchors[k.split(":")[0]].append((E.norm(a), k))
    rows = []
    for m in b["mentions"]:
        o = objmap[m["object_id"]]
        if o["annotated"] or m["type"] not in ("person", "team", "service", "vendor"):
            continue
        g = E._span_key(m, o["truth"]["mentions"])
        if g:
            rows.append((m, g["key"]))
    out = {}
    for mode in ("system", "system + approved merges", "string equality", "fuzzy (Jaro-Winkler >= 0.92)"):
        pairs = []
        for m, gk in rows:
            if mode == "system":
                p = m["entity"] or "~abstain~" + m["id"]
            elif mode == "system + approved merges":
                p = merges.get(m["entity"], m["entity"]) or "~abstain~" + m["id"]
            elif mode == "string equality":
                p = m["text"].lower()
            else:
                n = E.norm(m["text"])
                best = max(((E.jaro_winkler(n, a), k) for a, k in anchors.get(m["type"], ())), default=(0, None))
                p = best[1] if best[0] >= 0.92 else m["text"].lower()
            pairs.append((p, gk))
        out[mode] = bcubed(pairs)
    out["_merge_proposals"] = len(merges)
    et = entity_truth(b)
    out["_merge_proposals_correct"] = sum(et.get(s) == et.get(k) for s, k in merges.items())
    out["_abstained"] = sum(1 for m, _ in rows if m["method"] in ("ambiguous", "unresolved"))
    return out


def entity_truth(b):
    """System entity -> the truth entity most of its mentions refer to."""
    objmap = {o["id"]: o for o in b["objs"]}
    c = collections.defaultdict(collections.Counter)
    for m in b["mentions"]:
        if m["entity"]:
            g = E._span_key(m, objmap[m["object_id"]]["truth"]["mentions"])
            if g:
                c[m["entity"]][g["key"]] += 1
    return {e: x.most_common(1)[0][0] for e, x in c.items()}


# --- temporal reconciliation ---------------------------------------------------------------------------------------------
def temporal(b):
    et, co = entity_truth(b), b["co"]
    by = collections.defaultdict(list)
    for a in b["assertions"]:
        if a["pred"] in ("OWNS", "HANDOVER"):
            by[a["obj"]].append(a)
    res, n = collections.Counter(), collections.Counter()
    days = list(range(30, world.NOW, 30)) + [world.NOW]
    for svc, xs in by.items():
        tk = et.get(svc)
        if tk not in co["services"]:
            continue
        changed = len(co["services"][tk]["owners"]) > 1
        segs = E.reconcile(xs, world.NOW)
        first = min(a["day"] for a in xs)
        for d in days:
            truth = world.owner_at(co, tk, d)
            if truth is None or first > d:
                continue
            got = {"system": next((s["owner"] for s in segs if s["start"] <= d and (s["end"] is None or d < s["end"])), None),
                   "latest mention": E.owner_baseline(xs, d, "latest"), "majority of mentions": E.owner_baseline(xs, d, "majority")}
            for scope, on in (("all", True), ("changed", changed), ("now", d == world.NOW), ("now_changed", d == world.NOW and changed)):
                if on:
                    n[scope] += 1
                    for k, v in got.items():
                        res[(k, scope)] += et.get(v) == truth
    return {k: {scope: round(res[(k, scope)] / n[scope], 3) for scope in n} for k in ("system", "latest mention", "majority of mentions")} | {"_n": dict(n)}


# --- retrieval and answers ----------------------------------------------------------------------------------------------
def relevant(b):
    """Truth-relevant chunks: who owns each service now (the chunks asserting its current owner), why each decision went
    the way it did (selection and reasons), and what else was considered (candidates and rejections)."""
    co = b["co"]
    spans = collections.defaultdict(list)
    for c in b["chunks"]:
        spans[c["object_id"]].append(c)
    rel = collections.defaultdict(set)
    for o in b["objs"]:
        for f in o["truth"]["facts"]:
            if not (f["asserted"] and f["polarity"]):
                continue
            cid = next((c["id"] for c in spans[o["id"]] if c["start"] <= f["start"] < c["end"] + 1), None)
            if cid is None:
                continue
            if f["pred"] in ("OWNS", "HANDOVER") and f["obj"] in co["services"] and world.owner_at(co, f["obj"], world.NOW) == f["subj"]:
                rel[("owner", f["obj"])].add(cid)
            if f["pred"] in ("SELECTED", "REASON"):
                rel[("why", f["subj"])].add(cid)
            if f["pred"] in ("CONSIDERED", "REJECTED"):
                rel[("alternatives", f["subj"])].add(cid)
    return rel


def questions(b):
    co, r = b["co"], world.rng(b["seed"], "questions")
    out = []
    for k, s in co["services"].items():
        form = world.service_form(s["slug"], r)
        out.append((("owner", k), r.choice([f"who owns {form}", f"which team is responsible for {form}", f"{form} owner", f"who maintains {form} now"])))
    for k, d in co["decisions"].items():
        v = co["vendors"][d["selected"]]
        syn = r.choice(d["synonyms"])
        out.append((("why", k), r.choice([f"why did we pick {v['short']}", f"why was {v['short']} chosen as our {syn}", f"reasons for choosing {v['name']}"])))
        out.append((("alternatives", k), r.choice([f"what alternatives to {v['short']} were considered", f"which vendors competed for the {syn}"])))
    return out


def retrieval(b, view, modes=("bm25", "vector", "bm25+vector", "hybrid+lsa", "hybrid")):
    rel = relevant(b)
    res = {m: collections.defaultdict(list) for m in modes}
    for key, q in questions(b):
        want = {c for c in rel.get(key, ()) if c in view.chunk_ids}
        if not want:
            continue
        for mode in modes:
            got = [h["chunk_id"] for h in view.search(q, k=10, mode=mode)]
            first = next((i + 1 for i, c in enumerate(got) if c in want), None)
            for scope in ("all", key[0]):
                res[mode][scope].append((len(set(got) & want) / min(10, len(want)), 1 / first if first else 0.0))
    return {m: {s: {"queries": len(v), "recall@10": round(float(np.mean([x[0] for x in v])), 3), "mrr": round(float(np.mean([x[1] for x in v])), 3)} for s, v in r.items()}
            for m, r in res.items()}


def answers(b, view):
    """Answer accuracy against the truth, citation coverage by the verifier, abstention where nothing supports an answer."""
    co, et, r = b["co"], entity_truth(b), world.rng(b["seed"], "answers")
    rel = relevant(b)
    stats = collections.Counter()
    covered = []

    def ask(q):
        a = view.answer(q)
        v = E.verify(view, a)
        if v["sentences"]:
            covered.append((v["supported"], v["sentences"]))
        return a

    def first_fact(a):
        s = next((s for s in a["sentences"] if not s.get("abstain") and s["facts"]), None)
        return view.facts.get(s["facts"][0]) if s else None
    for k, s in co["services"].items():
        if not any(c in view.chunk_ids for c in rel.get(("owner", k), ())):
            continue
        a = ask(f"Who owns {s['slug']}?")
        f = first_fact(a)
        stats["owner_now"] += 1
        stats["owner_now_right"] += bool(f and et.get(f["subj"]) == world.owner_at(co, k, world.NOW))
        if len(s["owners"]) > 1:
            d = r.randint(max(s["created"], 30), world.NOW - 30)
            day = E.day_of(world.date_of(d).replace(day=15))
            a = ask(f"Who owned {s['slug']} in {world.date_of(day):%B %Y}?")
            f = first_fact(a)
            stats["owner_then"] += 1
            stats["owner_then_right"] += bool(f and et.get(f["subj"]) == world.owner_at(co, k, day))
    for k, d in co["decisions"].items():
        if not any(c in view.chunk_ids for c in rel.get(("why", k), ())):
            continue
        a = ask(f"Why was {co['vendors'][d['selected']]['short']} selected?")
        f = first_fact(a)
        stats["why"] += 1
        stats["why_right"] += bool(f and f["pred"] == "SELECTED" and et.get(f["obj"]) == d["selected"])
        reasons = [view.facts[x] for s in a["sentences"] if s["text"].startswith("Reasons given") for x in s["facts"]]
        stats["reasons"] += len(reasons)
        stats["reasons_right"] += sum(x["value"] in d["reasons"] for x in reasons)
    for q in ("Who owns quantum-ledger-api?", "Who owns svc-hologram-renderer?", "Why was Zephyrine Analytics selected?", "How much does the Moonbeam contract cost?",
              "Who owned orbit-scheduler in March 2026?"):
        a = ask(q)
        stats["unanswerable"] += 1
        stats["unanswerable_abstained"] += a["abstained"]
        stats["unanswerable_claims"] += sum(1 for s in a["sentences"] if s["facts"])
    sup, tot = sum(x for x, _ in covered), sum(y for _, y in covered)
    return dict(stats) | {"citation_coverage": round(sup / tot, 4) if tot else None, "sentences": tot}


def security(b):
    """Every principal with a distinct view, probed for restricted content; the personas also with the filter off and
    against an index built without their unreadable objects."""
    ix = b["ix"]
    full = sorted(b["acl"])
    distinct = {}
    for email, conts in sorted(b["users"].items()):
        distinct.setdefault(tuple(conts), email)
    users = [(e, list(c)) for c, e in distinct.items()]
    on = E.security_suite(ix, users, full)
    personas = [(e, b["users"][e]) for e in ("samuel.okafor@halden.example", "ines.duarte@halden.example")]
    off = E.security_suite(ix, personas, full, filter_off=True)
    ni = E.security_suite(ix, personas, full, reduced_index=reducer(b))
    return {"users": on["users"], "probes": on["probes"], "leaks": on["leaks"], "by_channel": on["by_channel"],
            "filter_off_probes": off["probes"], "filter_off_leaks": off["leaks"], "non_interference_checked": ni["non_interference_checked"],
            "non_interference_failed": ni["non_interference_failed"]}


def incremental(seed):
    """Incremental sync in-process: the changed objects of three more days (with a failing service) through the pipeline."""
    co = world.company(seed)
    svc = next(s["slug"] for s in co["services"].values() if len(s["owners"]) > 1)
    told = [{"kind": "service_failure", "service": svc, "day": world.NOW + 1}]
    b = build(seed)
    objs = world.changed(world.objects(seed, told), world.NOW, world.NOW + 3)
    for o in objs:
        o["id"] = o["external_id"]
    t0 = time.perf_counter()
    m = b["models"]
    E.discover(objs, m["gazetteer"])
    det, A = E.Detector(m["gazetteer"]), E.Anchors(m["gazetteer"])
    ch, me, asr = E.process(objs, det, m["extractor"], A, m["linker"])
    keep = {o["id"] for o in objs}
    E.Index([o for o in b["objs"] if o["id"] not in keep] + objs, [c for c in b["chunks"] if c["object_id"] not in keep] + ch,
            [x for x in b["mentions"] if x["object_id"] not in keep] + me, [a for a in b["assertions"] if a["object_id"] not in keep] + asr, b["ix"].entities, world.NOW + 3)
    return {"objects": len(objs), "seconds": round(time.perf_counter() - t0, 2)}


def one(seed):
    b = build(seed)
    ext = E.extraction_scores([o for o in b["objs"] if not o["annotated"]], b["det"], b["models"]["extractor"])
    full = b["ix"].view(sorted(b["acl"]))
    eng = b["ix"].view(b["users"]["samuel.okafor@halden.example"])
    return {"seed": seed, "objects": len(b["objs"]), "chunks": len(b["chunks"]), "mentions": len(b["mentions"]), "annotated": len(b["ann"]),
            "assertions": len(b["assertions"]), "seconds": b["seconds"], "extraction": ext, "resolution": resolution(b), "temporal": temporal(b),
            "retrieval": {"full": retrieval(b, full), "engineer": retrieval(b, eng)}, "answers": {"full": answers(b, full), "engineer": answers(b, eng)},
            "security": security(b), "incremental": incremental(seed)}


def rng_(vals, fmt="{:.3f}"):
    lo, hi = min(vals), max(vals)
    return fmt.format(lo) if fmt.format(lo) == fmt.format(hi) else f"{fmt.format(lo)}–{fmt.format(hi)}"


def main():
    res = [one(s) for s in SEEDS]
    p = print
    p("# Evaluation\n")
    p(f"Three held-out corpora (seeds {', '.join(map(str, SEEDS))}): each a different invented company with its own people, owners, vendors and "
      f"decisions, {', '.join(str(r['objects']) for r in res)} source objects as of {world.iso(world.NOW)}. Each is processed exactly as the service "
      "processes it: the extractor and the linker are trained on the corpus's annotated fifth "
      f"({', '.join(str(r['annotated']) for r in res)} documents) and everything is scored against the generator's truth on the rest. "
      "`python -m ekg.evaluate` reproduces this file. No language model or external API is called anywhere.\n")
    p("## Extraction (free text, documents nobody annotated)\n")
    p("| Corpus | Assertions in the truth | Model precision | Model recall | Trigger-word baseline precision | Baseline recall |\n|---|---|---|---|---|---|")
    for r in res:
        x = r["extraction"]
        p(f"| {r['seed']} | {x['model']['assertions']} | {x['model']['precision']} | {x['model']['recall']} | {x['rules']['precision']} | {x['rules']['recall']} |")
    p("\nAn assertion counts when its relation, both arguments and its value (a reason, a price) match the truth; an argument matches when the "
      "detected mention overlaps the true one, so a missed mention is a missed assertion. Relations: who owns a service, a handover, a "
      "vendor selected, considered or rejected (with the reason), who decided, the reasons, a contract value, a team rename. The baseline "
      "fires on trigger words and is fooled by hedges, questions and \"budget owner\"; the logistic model reads the words between and "
      "around the two mentions. By relation, all corpora together (model: true positives / false positives / misses):\n")
    tot = collections.defaultdict(collections.Counter)
    for r in res:
        for use in ("model", "rules"):
            for rel, c in r["extraction"][use]["by_relation"].items():
                tot[(use, rel)].update(c)
    p("| Relation | Model TP / FP / FN | Baseline TP / FP / FN |\n|---|---|---|")
    for rel in sorted(E.FREE_TEXT):
        m, bl = tot[("model", rel)], tot[("rules", rel)]
        p(f"| {rel} | {m['tp']} / {m['fp']} / {m['fn']} | {bl['tp']} / {bl['fp']} / {bl['fn']} |")
    p("\nThe corpus is generated from templates with varied wording, so these numbers say the pipeline is wired correctly and the "
      "model handles hedges and negation that trigger words do not; they do not say how it would do on real prose (see the README).\n")
    p("## Entity resolution\n")
    p("| Corpus | Mentions | System B³ F1 (precision / recall) | + approved rename merges | String equality | Fuzzy match | System pairwise F1 |\n|---|---|---|---|---|---|---|")
    for r in res:
        x = r["resolution"]
        s, m, st, fz = x["system"], x["system + approved merges"], x["string equality"], x["fuzzy (Jaro-Winkler >= 0.92)"]
        p(f"| {r['seed']} | {s['mentions']} | {s['b3_f1']} ({s['b3_precision']} / {s['b3_recall']}) | {m['b3_f1']} ({m['b3_precision']} / {m['b3_recall']}) | "
          f"{st['b3_f1']} ({st['b3_precision']} / {st['b3_recall']}) | {fz['b3_f1']} ({fz['b3_precision']} / {fz['b3_recall']}) | {s['pairwise_f1']} |")
    p("\nMentions of people, teams, services and vendors in the documents nobody annotated, scored with B³ (every mention weighs the same, "
      "so a big entity cannot hide a small one's errors) and pairwise F1. The blueprint's bar is F1 above 0.95. String equality keeps "
      "\"P. Raman\", \"@praman\" and \"priya.raman@…\" apart and puts the two Daniel Kims together; the fuzzy match merges the two people "
      "who share an initial and a surname. The system abstains when two candidates score alike (two people with the same name and no "
      f"context): {', '.join(str(r['resolution']['_abstained']) for r in res)} mentions. Rename merges are proposals from \"X is now Y\" "
      f"statements ({', '.join(str(r['resolution']['_merge_proposals_correct']) + ' of ' + str(r['resolution']['_merge_proposals']) for r in res)} correct); "
      "the system never merges two named entities on its own, so the second column is after a person approves them.\n")
    p("## Who owns it, then and now\n")
    p("| Corpus | Rule | All service-months | Services that changed owner | Today | Today, changed services |\n|---|---|---|---|---|---|")
    for r in res:
        t = r["temporal"]
        for rule in ("system", "latest mention", "majority of mentions"):
            p(f"| {r['seed']} | {rule} | {t[rule]['all']:.1%} | {t[rule]['changed']:.1%} | {t[rule]['now']:.1%} | {t[rule]['now_changed']:.1%} |")
    n = res[0]["temporal"]["_n"]
    p(f"\nThe owner of every service with any ownership evidence, on the 15th of every month and today, end to end from the extracted "
      f"assertions (seed {res[0]['seed']}: {n['all']} service-months, {n['now']} services today, {n['now_changed']} of which changed owner). The system decodes "
      "the most likely ownership history (Viterbi over days, sources weighted by reliability, stated handovers as transitions). "
      "Today, on these corpora, the latest-mention rule is as right as the system: the latest thing said about most services is a "
      "ticket or a catalog revision. The difference is in the months around a handover, when the latest mention is a service page "
      "edited without its owner line or a chat line that still names the old team. (The demo corpus has a service where the stale "
      "page is the latest mention today; that is why the demo picks it.)\n")
    p("## Retrieval\n")
    p("| Corpus | Reader | Queries | BM25 recall@10 / MRR | LSA | BM25 + LSA | BM25 + LSA + graph | BM25 + graph (the default) |\n|---|---|---|---|---|---|---|---|")
    for r in res:
        for who in ("full", "engineer"):
            x = r["retrieval"][who]
            cell = lambda m: f"{x[m]['all']['recall@10']} / {x[m]['all']['mrr']}"     # noqa: E731
            p(f"| {r['seed']} | {'every container' if who == 'full' else 'an engineer'} | {x['bm25']['all']['queries']} | {cell('bm25')} | {cell('vector')} | {cell('bm25+vector')} | {cell('hybrid+lsa')} | {cell('hybrid')} |")
    p("\nBy question kind (recall@10, all corpora, reader with every container):\n")
    p("| Question | BM25 | BM25 + graph |\n|---|---|---|")
    for kind in ("owner", "why", "alternatives"):
        vb = [r["retrieval"]["full"]["bm25"][kind]["recall@10"] for r in res if kind in r["retrieval"]["full"]["bm25"]]
        vh = [r["retrieval"]["full"]["hybrid"][kind]["recall@10"] for r in res if kind in r["retrieval"]["full"]["hybrid"]]
        p(f"| {kind} | {rng_(vb)} | {rng_(vh)} |")
    p("\nQuestions are generated from the truth with varied wording and aliases (\"who maintains svc-ledger-api now\", \"why did we pick "
      "Northwind\"); the relevant chunks are the ones that assert the current owner, the selection and its reasons, or the candidates "
      "and rejections. Recall@10 is the share of relevant chunks in the top ten (capped at ten), MRR the reciprocal rank of the first. "
      "Every statistic is computed inside the reader's view: BM25's document frequencies and the LSA basis come from the chunks that "
      "reader may read. LSA (TF-IDF, 96 dimensions, fitted per view) is no better than BM25 alone here and drags the fusion down; on "
      "the demo corpus 32 and 256 dimensions and a lower fusion weight did not change that, so the default fuses BM25 and the graph. "
      "Templated text gives a co-occurrence model little to learn that exact terms do not already carry; the graph earns its place "
      "because the chunks that answer a question often do not contain its words (the reasons for a decision sit in a sentence that "
      "never names the vendor).\n")
    p("## Answers\n")
    p("| Corpus | Reader | Owner today | Owner in a past month | Why a vendor was selected | Reasons correct | Unanswerable: abstained | Citation coverage |\n|---|---|---|---|---|---|---|---|")
    for r in res:
        for who in ("full", "engineer"):
            a = r["answers"][who]
            p(f"| {r['seed']} | {'every container' if who == 'full' else 'an engineer'} | {a.get('owner_now_right', 0)} of {a.get('owner_now', 0)} | "
              f"{a.get('owner_then_right', 0)} of {a.get('owner_then', 0)} | {a.get('why_right', 0)} of {a.get('why', 0)} | {a.get('reasons_right', 0)} of {a.get('reasons', 0)} | "
              f"{a['unanswerable_abstained']} of {a['unanswerable']} | {a['citation_coverage']:.0%} of {a['sentences']} sentences |")
    p("\nAnswers are composed only from the reader's facts. Citation coverage is measured by a separate verifier: a sentence counts "
      "when every fact it states is backed by a cited chunk the reader may read that names the fact's subject and object (or holds its "
      "value). The blueprint's bar is 100%. Unanswerable questions name services and vendors that do not exist; the answer must say "
      "it found nothing rather than guess. The engineer cannot read procurement, so the vendor questions they can ask are the ones "
      "announced in an engineering channel, and their answers carry the announced reason only.\n")
    p("## Permission leakage\n")
    p("| Corpus | Principals probed | Probes | Leaks | With the permission filter off | Non-interference checks failed |\n|---|---|---|---|---|---|")
    for r in res:
        s = r["security"]
        p(f"| {r['seed']} | {s['users']} | {s['probes']:,} | {s['leaks']} | {s['filter_off_leaks']:,} of {s['filter_off_probes']:,} leak | {s['non_interference_failed']} of {s['non_interference_checked']} |")
    ch = collections.Counter()
    for r in res:
        ch.update(r["security"]["by_channel"])
    p(f"\nEvery principal with a distinct set of readable containers is probed through search, graph queries, answers, entities and "
      f"provenance ({', '.join(f'{k} {v:,}' for k, v in sorted(ch.items()))} across the corpora): provenance and entity lookups on "
      "every fact and entity the principal cannot see, graph queries around every decision, questions and searches naming every "
      "vendor and every restricted literal (contract values, rejection reasons, codenames, names only restricted documents use), "
      "and searches by the title of every unreadable document. A probe leaks when its response carries an identifier of something the "
      "view cannot see, or a restricted literal the probe did not itself contain. The blueprint's bar is zero. Run with the permission "
      "filter off, the same probes leak most of the time, which is what shows the suite can see a leak. Non-interference compares the "
      "persona's search results and answers on the full index with those of an index built from only the objects they may read: "
      "identical, because every statistic is computed inside the view.\n")
    p("## Incremental sync\n")
    p("| Corpus | Changed objects (three days, one failing service) | Pipeline time in process |\n|---|---|---|")
    for r in res:
        p(f"| {r['seed']} | {r['incremental']['objects']} | {r['incremental']['seconds']} s |")
    p("\nNormalising, detecting, linking and extracting the changed objects and rebuilding the index; the live figure through the "
      "API and the job queue is in docs/performance.md. The blueprint's bar is under five minutes.\n")
    return res


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
    sys.exit(0)
