"""The generator, the normaliser, the models and the calculation, without a database."""
import numpy as np
import pytest

from carbon import engine, world


def test_company_is_deterministic_and_messy():
    a, b = world.company(3), world.company(3)
    assert [r["name"] for r in a["records"]] == [r["name"] for r in b["records"]]
    assert len(a["suppliers"]) == 460 and len(a["records"]) > 1.8 * len(a["suppliers"])          # most suppliers sit in several vendor masters
    m1, m2 = world.ledger_month(3, 4, 5000), world.ledger_month(3, 4, 5000)
    assert m1["description"] == m2["description"] and np.array_equal(m1["amount"], m2["amount"])
    assert m1["_injected"]["duplicate_postings"] > 0 and abs(sum(world.month_lines(2_000_000)) - 2_000_000) == 0
    india = [r["name"] for r in a["records"] if r["subsidiary"] == "MDG-IN"]
    assert max(map(len, india)) <= 24                                                          # that ERP truncates names


def test_normaliser_currencies_units_duplicates_and_reasons():
    assert engine.currency("RMB") == "CNY" and engine.currency(" us$ ") == "USD" and engine.currency("XXX") is None
    assert engine.energy("electricity", 2.5, "MWh") == (2500.0, "kWh") and engine.energy("diesel", 10, "gal")[0] == pytest.approx(37.85)
    assert engine.energy("natural_gas", 100, "therm")[0] == pytest.approx(2931.0)
    with pytest.raises(ValueError):
        engine.energy("diesel", 1, "kWh")
    lines = {"subsidiary": ["MDG-DE"] * 5, "vendor_ref": ["V1", "V1", "V1", "V9", "V1"], "invoice": ["A", "A", "B", "C", "D"], "line": [1, 1, 1, 1, 1],
             "period": ["2025-03-02", "2025-03-02", "2025-03-02", "2025-03-02", "2024-12-30"], "amount": [100.0, 100.0, 50.0, 10.0, 10.0], "currency": ["EURO", "EUR", "QQQ", "EUR", "EUR"]}
    keep, usd, rate, rejected, dups = engine.normalize_ap(lines, {"V1"}, 2025)
    assert list(keep) == [0] and dups == 1 and usd[0] == pytest.approx(100 * world.fx("EUR", 3))
    assert [code for _, code, _ in rejected] == ["unknown_currency", "unknown_vendor", "outside_reporting_year"]


def test_supplier_resolution_beats_both_baselines_and_never_joins_two_tax_ids():
    assert engine.norm_name("ALTAMIRA STEEL TRDG G.m.b.H. (old)") == engine.norm_name("Altamira Steel Trading GmbH") == "altamira steel trading"
    model, metrics = engine.train_resolver([world.company(s)["records"] for s in (900, 901)])
    assert metrics["weights"]["tax_id"] > 0 and metrics["weights"]["same_country"] > 0
    recs = world.company(103)["records"]
    truth = [r["supplier"] for r in recs]
    res = engine.resolve(recs, model)
    m, exact = engine.pairwise_scores(res["cluster"], truth), engine.pairwise_scores(engine.baseline_clusters(recs), truth)
    fuzzy = engine.pairwise_scores(engine.baseline_clusters(recs, "fuzzy", model.fuzzy_threshold_), truth)
    assert m["f1"] > fuzzy["f1"] > exact["f1"] and m["precision"] > 0.95 and exact["recall"] < 0.4
    taxes = {}
    for r, c in zip(recs, res["cluster"]):
        if r["tax_id"]:
            taxes.setdefault(c, set()).add(engine.norm_tax(r["tax_id"]))
    assert all(len(v) == 1 for v in taxes.values())
    uf = engine._UF(2, ["DE1", "DE2"])
    assert not uf.union(0, 1)


def test_classifier_abstains_to_rules_and_keeps_orphans_rare():
    w = world.company(7)
    names = {r["vendor_ref"]: r["name"] for r in w["records"]}
    lab = world.labelled_sample(7, 3000)
    clf = engine.train_classifier([engine.class_text(d, g, names[v]) for d, g, v in zip(lab["description"], lab["gl_code"], lab["vendor_ref"])], lab["label"])
    test = world.ledger_month(7, 6, 20000, defects=False)
    cats, conf, meth, keys, look = engine.map_lines(clf, test["description"], test["gl_code"], [names[v] for v in test["vendor_ref"]])
    assert set(meth) <= {"model", "fallback", "unmapped"} and all((c is None) == (m == "unmapped") for c, m in zip(cats, meth))
    assert all(p < engine.ABSTAIN for p, m in zip(conf, meth) if m != "model") and len(look) < len(keys)          # distinct inputs classified once
    m = engine.category_scores(cats, test["true_category"], test["true_usd"])
    r = engine.category_scores([engine.rule_category(d, g) for d, g in zip(test["description"], test["gl_code"])], test["true_category"], test["true_usd"])
    assert m["spend_weighted_accuracy"] > r["spend_weighted_accuracy"] and m["orphan_rate"] < 0.01 < r["orphan_rate"]
    assert engine.rule_category("Air freight AWB 1234", "6900") == "freight" and engine.rule_category("Misc", "6900") is None


def acts(**over):
    base = {"kind": ["ap", "ap", "ap", "ap", "freight", "utility", "utility"], "category": ["steel_metals", "steel_metals", "utilities", "", "", "", ""],
            "country": ["DE", "DE", "DE", "DE", "", "DE", "US"], "supplier": ["S1", "S1", "S1", "S2", "", "", ""],
            "amount_usd": [1000.0, 500.0, 200.0, 50.0, 0, 0, 0], "tkm": [0, 0, 0, 0, 120.0, 0, 0], "mode": ["", "", "", "", "air", "", ""],
            "fuel": ["", "", "", "", "", "electricity", "natural_gas"], "qty_norm": [0, 0, 0, 0, 0, 10000.0, 500.0]}
    return {k: np.array(over.get(k, v)) for k, v in base.items()}


def test_calculation_methods_lineage_and_reproducible_hash():
    F = world.catalogue("EF-2025.1")
    fid, method, scope, kg = engine.calculate(acts(), F, {})
    assert list(method) == ["spend-based", "spend-based", "covered", "unmapped", "activity", "activity", "activity"]
    assert list(scope) == [3, 3, 2, 0, 3, 2, 1]
    assert kg[0] == pytest.approx(1000 * F["SPEND:steel_metals:EU"]["value"]) and kg[2] == kg[3] == 0          # energy invoices are left to the bills
    assert kg[4] == pytest.approx(120 * F["FREIGHT:air"]["value"]) and kg[5] == pytest.approx(10000 * F["GRID:DE"]["value"])
    F2 = {**F, "SUP:S1": {"value": 2.0, "gsd": 1.1, "dispersion": 0.0}}
    fid2, m2, _, kg2 = engine.calculate(acts(), F2, {"S1|steel_metals": "SUP:S1"})
    assert m2[0] == m2[1] == "supplier-specific" and kg2[0] == 2000.0 and m2[2] == "covered"          # only the category the disclosure covers
    ids = np.arange(7)
    assert engine.result_hash(ids, fid, kg) == engine.result_hash(ids, *engine.calculate(acts(), F, {})[::3])
    assert engine.result_hash(ids, fid, kg) != engine.result_hash(ids, fid2, kg2)
    old = world.catalogue("EF-2024.2")
    assert engine.result_hash(ids, *engine.calculate(acts(), old, {})[::3]) != engine.result_hash(ids, fid, kg)
    with pytest.raises(KeyError):
        engine.calculate(acts(country=["ZZ"] * 7), {k: v for k, v in F.items() if not k.startswith("GRID")}, {})


def test_monte_carlo_is_centred_and_pairs_the_scenario():
    F = world.catalogue("EF-2025.1")
    groups = [{"factor_id": "SPEND:steel_metals:EU", "supplier": f"S{i}", "kg": 1e6, "buckets": ["total", "scope3"]} for i in range(30)]
    groups.append({"factor_id": "GRID:DE", "supplier": "", "kg": 5e6, "buckets": ["total", "scope2"]})
    mc = engine.monte_carlo(groups, F, draws=4000)
    assert abs(mc["total"]["mean"] / mc["total"]["t"] - 1) < 0.02 and mc["total"]["p2_5"] < mc["total"]["t"] < mc["total"]["p97_5"]
    assert mc["scope2"]["p97_5"] / mc["scope2"]["p2_5"] < mc["scope3"]["p97_5"] / mc["scope3"]["p2_5"]       # metered energy is tighter than spend
    alt = [g["kg"] * (0.7 if g["factor_id"].startswith("SPEND") else 1) for g in groups]
    mc2 = engine.monte_carlo(groups, F, draws=4000, scenario=alt)
    d = mc2["total"]["delta"]
    assert d["p97_5"] < 0 and d["p97_5"] - d["p2_5"] < (mc2["total"]["p97_5"] - mc2["total"]["p2_5"])         # paired: the change is tighter than either total


def test_disclosure_extraction_reads_units_and_validation_catches_the_slip():
    docs = world.disclosures(7)
    ok = 0
    for d in docs:
        x, tr = engine.extract(d["text"]), d["truth"]
        assert abs(x["scope1_t"] / tr["scope1_t"] - 1) < 0.01 and abs(x["scope2_t"] / tr["scope2_t"] - 1) < 0.01
        assert abs(x["revenue_usd"] / (tr["revenue_usd"] * (1000 if tr["unit_slip"] else 1)) - 1) < 0.01
        v, why = engine.validate_disclosure(x)
        if tr["unit_slip"]:
            assert v is None and "implausible" in why[0]
        elif tr["scope3_upstream_t"] is None:
            assert v is None and "boundary incomplete" in why[0]
        else:
            assert abs(v / tr["intensity"] - 1) < 0.01
            ok += 1
    assert ok >= 10 and sum(d["truth"]["unit_slip"] for d in docs) == 1
    naive_ok = sum(nx[f] is not None and abs(nx[f] / d["truth"][f] - 1) < 0.01 for d in docs if not d["truth"]["unit_slip"]
                   for nx in [engine.naive_extract(d["text"])] for f in ("scope1_t", "scope2_t"))
    assert naive_ok < 0.8 * 2 * (len(docs) - 1)                  # first-number-assumed-tonnes misreads kt and Mt


def test_network_influence_and_scenario_levers():
    infl = engine.influence({"mill": 100.0, "maker": 200.0, "other": 50.0}, {"maker": ["mill"]})
    assert infl["mill"] == pytest.approx(100 + 200 * engine.DEFAULT_UPSTREAM_SHARE) and infl["maker"] == 200
    assert engine.covered_emissions({"mill"}, {"mill": 100, "maker": 200}, {"maker": {"mill": 0.5}}) == 200
    F = world.catalogue("EF-2025.1")
    groups = [{"method": "activity", "factor_id": "FREIGHT:air", "kg": 6000.0, "mode": "air", "lane": ("CN", "DE"), "urgent": False, "tonnes": 10.0, "supplier": ""},
              {"method": "activity", "factor_id": "FREIGHT:air", "kg": 600.0, "mode": "air", "lane": ("CN", "DE"), "urgent": True, "tonnes": 1.0, "supplier": ""},
              {"method": "spend-based", "factor_id": "SPEND:steel_metals:CN", "kg": 1000.0, "supplier": "mill"},
              {"method": "spend-based", "factor_id": "SPEND:packaging:CN", "kg": 1000.0, "supplier": "maker"}]
    new, notes = engine.scenario_kg(groups, F, {"from": "air", "to": "ocean", "share": 1.0, "exclude_urgent": True}, {"suppliers": ["mill"], "reduction": 0.3}, {"maker": ["mill"]})
    sea = world.lane("CN", "DE")["sea_km"]
    assert new[0] == pytest.approx(10 * sea * F["FREIGHT:ocean"]["value"]) and new[0] < 6000 and new[1] == 600          # urgent air stays
    assert new[2] == pytest.approx(700) and new[3] == pytest.approx(1000 * (1 - engine.DEFAULT_UPSTREAM_SHARE * 0.3))
    assert notes["tonnes_shifted"] == 10 and notes["added_transit_days_per_tonne"] > 15
