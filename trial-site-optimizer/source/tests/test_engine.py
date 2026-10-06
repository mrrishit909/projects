"""The generator, the parser, the rules engine, the models and the optimiser, without a database."""
import itertools
import json
import re

import numpy as np

from trials import engine, world


def test_tokenising_keeps_no_identifier_and_normalises_units():
    site = world.network(3, n_sites=4)["sites"][0]
    pats = world.site_patients(3, site)
    assert [p["record"]["mrn"] for p in world.site_patients(3, site)] == [p["record"]["mrn"] for p in pats]       # keyed: same seed, same patients
    assert len({p["record"]["mrn"] for p in pats}) == len(pats)
    for p in pats[:200]:
        tok, problems = engine.tokenise(p["record"], "salt-a")
        text = json.dumps(tok)
        assert p["record"]["mrn"] not in text and p["record"]["birth_date"] not in text and not re.search(r"\d{4}-\d\d-\d\d", text)
        assert "note" not in tok and re.fullmatch(r"\d\d-\d\d|90\+", tok["age_band"]) and tok["token"] != engine.tokenise(p["record"], "salt-b")[0]["token"]
        assert all(e["day"] <= 0 for e in tok["events"] if "day" in e)
    rec = {"mrn": "1", "birth_date": "1960-05-01", "sex": "F", "site": "S-001", "home_distance_km": 12.0, "events": [
        {"type": "lab", "name": "ANC", "value": 1800, "unit": "cells/uL", "date": "2026-08-25"}, {"type": "lab", "name": "HGB", "value": 7.1, "unit": "mmol/L", "date": "2026-08-25"},
        {"type": "medication", "drug": "blinded study drug", "line": 0, "start": "2025-01-01", "end": None}, {"type": "x-ray", "date": "2026-01-01"}]}
    tok, problems = engine.tokenise(rec, "s")
    assert tok["events"] == [{"type": "lab", "name": "ANC", "value": 1.8, "day": -7}] and tok["age_band"] == "65-69" and tok["distance_band"] == "10-30 km"
    assert len(problems) == 3 and any("mmol/L" in x for x in problems)


def test_parser_translates_what_it_can_account_for_and_sends_the_rest_to_review():
    demo = world.catalogue_protocol("ONC-LUNG-301")
    parsed = engine.parse(demo["text"])
    truth = {c["ref"]: c for c in demo["criteria"]}
    assert [p["ref"] for p in parsed] == list(truth) and [p["ref"] for p in parsed if p["status"] == "review"] == ["I4", "E2"]
    assert all(engine.canonical(p["rules"]) == engine.canonical(truth[p["ref"]]["rules"]) for p in parsed if p["status"] != "review")
    assert sum(p["status"] == "manual" for p in parsed) == 4
    tot = {"wrong": 0, "exact": 0, "kw": 0, "n": 0}
    for seed in range(300, 312):
        for tpl in world.TEMPLATES:
            p = world.protocol(seed, tpl)
            s, k = engine.score_parse(engine.parse(p["text"]), p["criteria"]), engine.score_parse(engine.parse_keywords(p["text"]), p["criteria"])
            tot["wrong"] += s["confidently_wrong"]
            tot["exact"] += s["exact"]
            tot["kw"] += k["exact"]
            tot["n"] += s["criteria"]
    assert tot["wrong"] == 0 and tot["exact"] / tot["n"] > 0.95 > 0.6 > tot["kw"] / tot["n"]
    for text in ("ANC must not fall below 1.5 × 10^9/L within 14 days prior to screening.", "Histologically confirmed advanced NSCLC.",
                 "AST and ALT ≤ 2.5 × ULN (≤ 5 × ULN if liver metastases are present) within 14 days prior to screening."):
        assert engine.parse_criterion(text, "inclusion")["status"] == "review", text
    assert engine.parse_criterion("Platelets at least 100,000/mm³ within 2 weeks of screening.", "inclusion")["rules"] == \
        [{"field": "lab", "name": "PLT", "op": ">=", "value": 100.0, "unit": "10^9/L", "within_days": 14}]
    assert "a unit slip?" in engine.validate({"field": "lab", "name": "ANC", "op": ">=", "value": 1500, "unit": "10^9/L", "within_days": 14})[0]
    assert engine.validate({"field": "lab", "name": "ANC", "op": ">=", "value": 1.5, "unit": "10^9/L"}) == ["lab: a lab criterion needs a time window"]
    assert engine.validate({"field": "therapy", "classes": ["anti-PD-1"], "within_days": 182}) == [] and engine.validate({"field": "telepathy"})


def tok(events, age_band="60-64"):
    return engine.index_timeline({"token": "t", "site": "S-001", "age_band": age_band, "distance_band": "<10 km", "events": events})


def test_temporal_rules_engine_reads_time_and_says_when_it_cannot_answer():
    crit = [{"ref": "I1", "type": "inclusion", "text": "", "rules": [{"field": "lab", "name": "ANC", "op": ">=", "value": 1.5, "unit": "10^9/L", "within_days": 14}]},
            {"ref": "E1", "type": "exclusion", "text": "", "rules": [{"field": "therapy", "classes": ["anti-PD-1", "anti-PD-L1"], "within_days": 182}]},
            {"ref": "I2", "type": "inclusion", "text": "", "rules": [{"field": "age", "op": ">=", "value": 62}]},
            {"ref": "I9", "type": "inclusion", "text": "", "rules": [{"field": "manual", "topic": "consent"}]}]
    pembro = lambda end: {"type": "medication", "drug": "pembrolizumab", "class": "anti-PD-1", "line": 1, "start": end - 200, "end": end}     # noqa: E731
    recent = tok([{"type": "lab", "name": "ANC", "value": 2.0, "day": -9}, pembro(-100)])
    old = tok([{"type": "lab", "name": "ANC", "value": 2.0, "day": -9}, pembro(-400)], age_band="70-74")
    stale = tok([{"type": "lab", "name": "ANC", "value": 2.0, "day": -40}, pembro(-400)], age_band="70-74")
    r = engine.evaluate(crit, recent, explain=True)
    assert r["status"] == "ineligible" and r["failed"] == ["E1"] and r["values"]["I1"] == 1 and r["unknown"] == ["I2"] and "I9" not in r["values"]
    assert r["trace"][1]["rules"][0]["evidence"]["regimens"][0]["end"] == -100
    assert engine.evaluate(crit, old)["status"] == "eligible"
    s = engine.evaluate(crit, stale, explain=True)
    assert s["status"] == "potential" and s["unknown"] == ["I1"] and "no ANC in the last 14 days (last on day -40)" in s["trace"][0]["rules"][0]["evidence"]["why"]
    flat = engine.evaluate(crit, stale, temporal=False)
    assert flat["values"]["I1"] == 1 and engine.evaluate(crit, old, temporal=False)["status"] == "ineligible"     # without time: stale labs count, old therapy excludes
    rates = {("I1", False): 0.8}
    assert engine.expected_eligible(s, rates, False) == 0.8 and engine.expected_eligible(r, rates) == 0.0


def test_engine_against_the_generators_truth():
    net = world.network(11, n_sites=12)
    p = world.protocol(11, "nsclc_second_line")
    toks = [engine.tokenise(x["record"], "s")[0] for x in net["patients"]]
    ixs = [engine.index_timeline(t) for t in toks]
    res = [engine.evaluate(p["criteria"], ix) for ix in ixs]
    truth = [world.truly_eligible(p["criteria"], x["truth"]) for x in net["patients"]]
    assert sum(truth) > 5 and sum(t and r["status"] != "ineligible" for t, r in zip(truth, res)) / sum(truth) > 0.9      # almost every eligible patient is found
    assert sum(not t and r["status"] == "eligible" for t, r in zip(truth, res)) <= 2
    rates = engine.pass_rates(res, p["criteria"], [engine.on_treatment(ix) for ix in ixs])
    pools, _ = engine.study_pools(res, toks, ixs, rates)
    assert 0.6 < sum(pools.values()) / sum(truth) < 1.5
    steps = engine.funnel(res, p["criteria"])
    assert all(a["remaining"] >= b["remaining"] for a, b in zip(steps, steps[1:])) and steps[0]["remaining"] == len(res)


def test_enrolment_and_dropout_models_beat_their_baselines_on_later_studies():
    net = world.network(5, records=False)
    enr = [{"site": h["site"], "study_ref": h["study_ref"], "features": engine.enrollee_features(e), "dropped": e["dropped"]} for h in net["history"] for e in h["enrollees"]]
    bt = engine.backtest(net["history"], enr, net["sites"], net["investigators"])
    assert bt["enrolment"]["mae"] < bt["enrolment"]["naive_mae"] and 0.65 <= bt["enrolment"]["interval_coverage_80"] <= 0.97
    assert bt["dropout"]["brier"] < bt["dropout"]["base_rate_brier"] and bt["dropout"]["auc"] > 0.55
    m = engine.fit_enrolment(net["history"], net["sites"], net["investigators"])
    s = net["sites"][0]
    small, _ = engine.predict_site(m, s, 2, 1.0)
    big, _ = engine.predict_site(m, s, 2, 8.0)
    assert big["mean"] > 3 * small["mean"] and big["p10"] <= big["mean"] <= big["p90"] <= s["capacity"]
    # the same site enrols the same way in any portfolio: a paired comparison
    pi = {p["id"]: p for p in net["investigators"]}
    lead = pi[world.lead_investigator(s, "NSCLC", pi)]
    assert world.run_site(5, "X", s, lead, "NSCLC", 6)["monthly"] == world.run_site(5, "X", s, lead, "NSCLC", 6)["monthly"]


def test_portfolio_milp_is_feasible_and_optimal():
    rng = np.random.default_rng(3)
    for trial in range(6):
        cands = [{"id": f"S{i}", "region": "ABC"[i % 3], "kind": "academic" if i % 4 == 0 else "community", "enrolled": float(rng.uniform(1, 12)),
                  "activation_cost": float(rng.uniform(30e3, 80e3)), "per_patient_cost": float(rng.uniform(9e3, 18e3)), "excluded": i == 5} for i in range(13)]
        for c in cands:
            c["evaluable"] = c["enrolled"] * 0.8
        budget = 0.35 * sum(engine.cost(c) for c in cands)
        plan = engine.optimise(cands, 5, budget, max_per_region=2, min_academic=1)
        by = {c["id"]: c for c in cands}
        ok = lambda ch: (len(ch) == 5 and sum(engine.cost(by[s]) for s in ch) <= budget + 1e-6 and "S5" not in ch            # noqa: E731
                         and max(sum(by[s]["region"] == r for s in ch) for r in "ABC") <= 2 and any(by[s]["kind"] == "academic" for s in ch))
        best = max((sum(by[s]["evaluable"] for s in ch) for ch in itertools.combinations(by, 5) if ok(ch)), default=None)
        assert plan["status"] == "optimal" and ok(plan["sites"]) and abs(plan["expected_evaluable"] - round(best, 1)) < 0.11, trial
        for alt in (engine.greedy_ratio(cands, 5, budget), engine.greedy(cands, lambda c: c["enrolled"], 5, budget)):
            assert not ok(alt) or sum(by[s]["evaluable"] for s in alt) <= best + 1e-9      # the baselines ignore the region and academic rules
    assert engine.optimise(cands, 5, 10.0)["status"] == "infeasible"
