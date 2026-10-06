"""The generator, the models and the planners, without a database."""
import numpy as np
import pytest

from resto import engine as E
from resto import world as W


@pytest.fixture(scope="module")
def chain():
    ch = W.chain(5)
    st, recs = W.run(ch, W.initial_state(ch), 0, 42, W.UsualPractice(), last_orders=False)
    return ch, st, recs


def test_menu_hierarchy_and_determinism(chain):
    ch = chain[0]
    assert ch["L"] == 50 and W.N_ITEM == 12 and W.N_ING == 15 and W.N_COMP == 6
    assert np.allclose(W.ITEM_THEORETICAL_RAW, W.ITEM_RAW + W.ITEM_COMP @ W.RAW_PER_COMP) and (W.ITEM_FOOD_COST / W.PRICE < 0.35).all()
    a = W.run(ch, W.initial_state(ch), 0, 3, W.UsualPractice())[1]
    b = W.run(ch, W.initial_state(ch), 0, 3, W.UsualPractice())[1]
    assert all((x["sold"] == y["sold"]).all() and x["closures"] == y["closures"] for x, y in zip(a, b))
    # another policy meets the same customers: the demand draws do not depend on what the kitchen does
    c = W.run(ch, W.initial_state(ch), 0, 3, E.WithPlans(W.UsualPractice(), {(0, 0): np.zeros((50, W.N_COMP))}))[1]
    assert (c[0]["truth"]["demand"] == a[0]["truth"]["demand"]).all() and c[0]["truth"]["lost"].sum() > a[0]["truth"]["lost"].sum()


def test_rain_events_and_promotions_move_demand_the_right_way(chain):
    ch = chain[0]
    dry = W.demand_mean(ch, 60, rain=np.zeros((50, W.SLOTS)))
    wet = W.demand_mean(ch, 60, rain=np.ones((50, W.SLOTS)))
    assert np.isclose(wet[:, :, 0].sum() / dry[:, :, 0].sum(), 0.5) and np.isclose(wet[:, :, 1].sum() / dry[:, :, 1].sum(), 1.6)
    p = next(p for p in ch["promos"] if p["id"] == "P09")
    i, stores = W.ITEM.index(p["item"]), np.isin(np.array(W.REGIONS)[ch["region"]], p["regions"])
    lift = W.demand_mean(ch, 56)[stores, i].sum() / W.demand_mean(ch, 49)[stores, i].sum()
    assert np.isclose(lift, 0.8 ** -ch["elasticity"][i], rtol=0.15)


def test_kitchen_and_walk_in_balance(chain):
    _, st, recs = chain
    for r in recs[-7:]:
        assert (r["sold"].sum(2) <= r["truth"]["demand"].sum(2)).all() and (r["prep_discard"] >= -1e-9).all() and (r["lots"] >= 0).all()
        # an item sold short in a slot is recorded as 86'd there: the censoring the forecast must respect
        short = r["sold"].sum(2) < r["truth"]["demand"].sum(2)
        assert (r["unavailable"][short]).all()
        # discarded prep never exceeds what was made, and every lot thrown away was at least a day old or spoiled
        assert (r["prep_discard"].sum(2) <= r["prepped"].sum(2) + 1e-6).all()
        assert all(status in ("used", "spoiled", "expired") for *_, status, _ in r["closures"])
    d = recs[-1]["day"]
    use = st["use"][d]
    assert np.allclose(use, recs[-2]["count"] + recs[-1]["received"] - recs[-1]["count"] - recs[-1]["lot_waste"].sum(2))


def test_demand_model_recovers_the_generator(chain):
    ch, st, recs = chain
    m = E.DemandModel().fit(E.history_arrays(recs, ch))
    assert abs(m.a_rain[0] - W.RAIN_EFFECT[0]) < 0.1 and abs(m.a_rain[1] - W.RAIN_EFFECT[1]) < 0.15 and abs(1 + m.b_event - W.EVENT_LIFT) < 0.15
    assert abs(np.sqrt(m.sigma2) - W.DAY_SD) < 0.03
    promoted = {W.ITEM.index(p["item"]) for p in ch["promos"] if p["end"] <= 42}
    assert promoted and np.mean([abs(m.eps[i] - ch["elasticity"][i]) for i in promoted]) < 0.25
    # the hierarchy adds up and the store-day interval holds its level on the generator's own next days
    next_days = W.run(ch, st, 42, 49, W.UsualPractice())[1]
    mu = np.stack([m.mean(r["day"], W.rain_forecast(ch, r["day"]), W.event_mask(ch, r["day"]), r["discount"]) for r in next_days], 3)
    y = np.stack([r["truth"]["demand"].sum(2) for r in next_days], 2).sum((1, 3))
    md = mu.sum((1, 2, 4))
    lo, hi = E.DemandModel.nb_quantiles(md, m.agg_var(md, (mu ** 2).sum((1, 2, 4))))
    assert np.isclose(mu.sum(), md.sum()) and 0.8 < ((y >= lo) & (y <= hi)).mean() < 0.98
    lo, hi = E.slot_interval(m, mu)
    assert (lo <= mu.sum(2) + 1e-9).all() and (hi >= np.floor(mu.sum(2))).all()


def test_hazard_learns_temperature_and_shrinkage_beats_the_threshold(chain):
    ch, st, recs = chain
    closed = {(l, i, rd): (r["day"], s) for r in recs for l, i, rd, s, q in r["closures"]}
    lots = [(l, i, r["day"], *closed.get((l, i, r["day"]), (None, "open"))) for r in recs for l, i in zip(*np.nonzero(r["received"] > 0))]
    rows = E.lot_days(lots, np.stack([r["temp"] for r in recs], 1), 42)
    hz = E.HazardModel().fit(rows[:, 1].astype(int), rows[:, 2], rows[:, 3], rows[:, 4])
    lettuce = W.ING.index("lettuce")
    assert hz.p(np.array([lettuce]), np.array([3]), 7.5)[0] > 2 * hz.p(np.array([lettuce]), np.array([3]), 3.0)[0]
    assert hz.p(np.array([lettuce]), np.array([3]), 3.0)[0] > hz.p(np.array([lettuce]), np.array([0]), 3.0)[0]
    assert hz.p(np.array([W.ING.index("rice")]), np.array([3]), 9.0)[0] == 0                   # dry goods do not spoil here
    theo = np.stack([r["sold"].sum((2, 3)) @ W.ITEM_THEORETICAL_RAW + r["prep_discard"].sum(2) @ W.RAW_PER_COMP for r in recs[1:]])
    act = np.stack([st["use"][r["day"]] for r in recs[1:]])
    scan, base = E.shrinkage_scan(theo, act)
    truth = {s["store"] for s in ch["shrinkage"]}
    assert set(np.nonzero(scan["flags"].any(1))[0]) == truth and base.any(1).sum() > 40   # the threshold flags the chain-wide avocado yield
    theft = next(s for s in ch["shrinkage"] if s["kind"] == "theft")
    assert E.classify_shrinkage(scan, theft["store"]) == "theft or unrecorded loss"


def test_planner_beats_usual_practice_and_backs_up_a_late_truck(chain):
    ch, st, recs = chain
    m = E.DemandModel().fit(E.history_arrays(recs, ch))
    sysp = E.SystemPolicy(m, q_prep=0.9)
    out = {}
    for name, p in (("usual", W.UsualPractice()), ("system", sysp)):
        pend = [dict(o, id=f"x{k}", ordered_on=41) for k, o in enumerate(p.order(ch, 41, W.Obs(ch, st, 41, [])))]
        out[name] = W.metrics(W.run(ch, st, 42, 49, p, (), pend)[1])
    assert out["system"]["waste_usd"] < out["usual"]["waste_usd"] and out["system"]["stockout_rate"] < out["usual"]["stockout_rate"]
    late = [{"kind": "supplier_delay", "supplier": "produce", "due": 42, "days": 1, "regions": ["Harbor"]}]
    orders = sysp.order(ch, 41, W.Obs(ch, st, 41, W.delays_known(ch, late, 41)))
    backup = next(o for o in orders if o["supplier"] == "backup")
    harbor = np.array(W.REGIONS)[ch["region"]] == "Harbor"
    lettuce = W.ING.index("lettuce")
    assert backup["qty"][harbor, lettuce].sum() > 0 and backup["qty"][~harbor, lettuce].sum() < backup["qty"][harbor, lettuce].sum()
    bounded = E.Bounded(sysp, W.UsualPractice()).order(ch, 41, W.Obs(ch, st, 41, W.delays_known(ch, late, 41)))
    for o in bounded:                                                                          # unattended: nothing beyond the limit is placed
        assert (E.change_value(o["supplier"], o["qty"], o["par"]) <= E.ORDER_LIMIT_USD + 1e-6).all()
