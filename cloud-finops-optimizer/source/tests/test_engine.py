"""The generator, the models and the optimisers, without a database."""
import numpy as np

from finops import engine, world

WEEK = engine.WEEK


def test_estate_billing_and_determinism():
    res = world.estate(5)
    assert {r["kind"] for r in res} == {"vm", "pool", "db", "volume"} and len({r["external_id"] for r in res}) == len(res)
    a, b = world.run(5, 10, 17), world.run(5, 10, 17)
    assert np.array_equal(a["eff"], b["eff"]) and np.array_equal(a["cpu_util"], b["cpu_util"])
    vm = next(r for r in res if r["kind"] == "vm" and r["cls"] == "oversized" and r["launched_day"] == 0 and r["terminated_day"] is None)
    small = world.run(5, 10, 17, [{"resource": vm["external_id"], "day": 12, "set": {"size": vm["size"] - 1}}])
    i = vm["idx"]
    assert np.array_equal(small["cpu_demand"][i], a["cpu_demand"][i])                       # demand belongs to the workload ...
    assert np.allclose(small["cpu_util"][i, 2:], np.minimum(2 * a["cpu_util"][i, 2:], 1.0), atol=1e-9)   # ... resizing changes utilisation
    assert small["od"][i, 2:].sum() == a["od"][i, 2:].sum() / 2 and small["od"][i, :2].sum() == a["od"][i, :2].sum()
    cm = [{"id": "sp", "cloud": "aws", "kind": "compute_sp", "amount": 40.0, "start_day": 13},
          {"id": "ri", "cloud": "aws", "kind": "db_ri", "type": "db.m6i.4xlarge", "amount": 1, "start_day": 13}]
    c = world.run(5, 10, 17, commitments=cm)
    assert world.bill(c) < world.bill(a) and np.allclose(c["eff"][:, :3], a["eff"][:, :3])    # nothing changes before the start
    comp = np.array([r["kind"] in ("vm", "pool") and r["cloud"] == "aws" for r in res])
    E = a["od"][comp][:, 3:].sum(0).ravel()
    paid = c["eff"][comp][:, 3:].sum() + c["commit_lines"][0]["unused_fee"][3:].sum()
    assert abs(paid - engine.pool_bill(E, np.full_like(E, 40.0), world.CLOUDS["aws"]["sp"])) < 1e-6   # the verifier's pricing rule is the bill's


def test_forecast_follows_trend_and_season():
    rng = np.random.default_rng(0)
    t = np.arange(9 * WEEK)
    season = 1 + 0.6 * np.sin(2 * np.pi * t / 24) + 0.2 * (t % WEEK < 120)
    y = 10 * season * 1.05 ** (t / WEEK) * rng.lognormal(0, 0.05, len(t))
    m = engine.fit_forecast(y[:8 * WEEK], 0)
    assert abs(np.exp(m["b"]) - 1.05) < 0.01
    future = y[8 * WEEK:]
    assert engine.wape(future, engine.predict(m, 8 * WEEK, WEEK)) < 0.8 * engine.wape(future, y[7 * WEEK:8 * WEEK])      # beats last week again
    paths = engine.sample_paths(m, 8 * WEEK, WEEK, 200, rng)
    assert 0.85 < (future <= np.quantile(paths, 0.95, axis=0)).mean() <= 1.0


def history(cls, days=56, size=3, mem=0.3, seed=1):
    rng = np.random.default_rng(seed)
    h = np.arange(days * 24)
    shape = 0.35 + 0.65 * (0.5 - 0.5 * np.cos(2 * np.pi * ((h % 24) - 4) / 24))
    cpu = {"oversized": 0.12 * shape, "idle": np.full(len(h), 0.008), "bursty": np.where(h % 24 < 3, 0.85, 0.05),
           "growing": 0.12 * shape * 1.12 ** (h / WEEK), "right": 0.5 * shape}[cls] * rng.lognormal(0, 0.08, len(h))
    return {"cpu_util": np.minimum(cpu, 1.0), "mem_util": np.full(len(h), mem), "units": np.ones(len(h)), "io": np.zeros(len(h))}, \
        {"id": cls, "kind": "vm", "cloud": "aws", "size": size, "env": "prod"}


def test_rightsizer_respects_the_slo_and_the_baseline_does_not():
    rng = np.random.default_rng(2)
    h, r = history("oversized")
    rec = engine.rightsize(r, h, 0, rng)
    assert rec["action"] == "resize" and rec["set"]["size"] < 3 and rec["evidence"]["forecast_cpu_p99_at_new_size"] <= 0.8 and rec["confidence"] >= 0.9
    assert engine.rightsize(*reversed(history("idle")), 0, rng)["action"] == "terminate"
    for cls in ("bursty", "growing", "right"):                       # a nightly batch at 85%, a workload growing 12% a week, a busy one
        h, r = history(cls)
        assert engine.rightsize(r, h, 0, rng) is None, cls
        if cls != "right":
            nv = engine.naive(r, h)
            assert nv["action"] == "resize"                          # the 14-day average sees an idle-looking machine
    h, r = history("oversized", mem=0.55)                            # memory-bound: half the size would run out of memory
    assert engine.rightsize(r, h, 0, rng) is None and engine.naive(r, h)["action"] == "resize"
    h, r = history("oversized", days=10)
    assert engine.rightsize(r, h, 0, rng)["action"] == "review"
    h, r = history("bursty")
    fut = {"cpu": h["cpu_util"][-4 * WEEK:] * world.VCPU[3], "mem": h["mem_util"][-4 * WEEK:] * 64, "running": np.ones(4 * WEEK, bool)}
    assert engine.breached(r, engine.naive(r, h), fut) and not engine.breached(r, {"set": {"size": 3}}, fut)
    p, _ = engine.slo_risk(r, h, 0, engine.naive(r, h), rng, k=100)
    assert p > 0.9


def test_milp_portfolio_is_the_newsvendor_and_respects_a_budget():
    rng = np.random.default_rng(3)
    usage = 100 + 40 * np.sin(np.arange(2 * WEEK) * 2 * np.pi / 24) + rng.normal(0, 5, 2 * WEEK)
    sc = np.tile(usage, (4, 1))
    plan = engine.optimise({"aws": sc}, {("aws", "db.m6i.2xlarge"): 3}, len(usage))
    d = world.CLOUDS["aws"]["sp"]
    assert plan["optimal"] and abs(plan["compute_sp"]["aws"] - np.quantile(usage, d)) <= 3.0       # commit to the d-quantile of usage
    assert plan["db_ri"]["aws|db.m6i.2xlarge"] == 3
    cost = engine.portfolio_cost(plan, {"aws": sc}, {("aws", "db.m6i.2xlarge"): 3}, len(usage))
    for alt in (plan["compute_sp"]["aws"] - 10, plan["compute_sp"]["aws"] + 10):
        worse = engine.portfolio_cost({**plan, "compute_sp": {"aws": alt}}, {"aws": sc}, {("aws", "db.m6i.2xlarge"): 3}, len(usage))
        assert worse["total"] > cost["total"]
    capped = engine.optimise({"aws": sc}, {("aws", "db.m6i.2xlarge"): 3}, len(usage), budget_per_month=20 * world.HOURS_MONTH)
    fees = capped["compute_sp"]["aws"] * (1 - d) + capped["db_ri"]["aws|db.m6i.2xlarge"] * world.price("aws", "db", 2) * (1 - world.CLOUDS["aws"]["ri"])
    assert fees <= 20 + 1e-6
    greedy = {"compute_sp": {"aws": 25.0}, "db_ri": {"aws|db.m6i.2xlarge": 3}}        # deepest discount first, then whole blocks: $19.44 of $20
    pc = lambda p: engine.portfolio_cost(p, {"aws": sc}, {("aws", "db.m6i.2xlarge"): 3}, len(usage))["total"]      # noqa: E731
    assert pc(capped) < pc(greedy)                                                     # whole blocks make it a packing problem


def test_verifier_counts_the_margin_not_the_average_rate():
    E = np.full(100, 100.0)
    C = np.full(100, 60.0)
    above = [{"id": "a", "cloud": "aws", "kind": "vm", "delta": {"compute:aws": np.full(100, 10.0)}, "eff_pre": 1400.0, "eff_post": 1000.0}]
    rows, total = engine.verify(above, {"compute:aws": (E, C, 0.28)}, {("aws", "vm"): (100.0, 80.0)}, 14, 10)
    assert abs(total["counterfactual"] - 1000.0) < 1e-6        # usage above the commitment is saved at the full on-demand price
    assert abs(total["did"] - (1400 / 14 * 0.8 * 10 - 1000)) < 1e-6 and abs(total["before_after"] - 0.0) < 1e-6
    inside = [{**above[0], "delta": {"compute:aws": np.full(100, 10.0)}}]
    _, t2 = engine.verify(inside, {"compute:aws": (np.full(100, 40.0), C, 0.28)}, {}, 14, 10)
    assert t2["counterfactual"] == 0.0                         # inside an under-used commitment nothing is saved
    assert t2["list_price"] == 1000.0


def test_explain_adds_up():
    a = {"x": (24, 48.0, 36.0, "x"), "y": (24, 24.0, 24.0, "y"), "gone": (24, 10.0, 10.0, "gone")}
    b = {"x": (24, 24.0, 15.0, "x"), "y": (36, 36.0, 36.0, "y"), "new": (24, 5.0, 5.0, "new")}
    e = engine.explain(a, b)
    total = sum(v[2] for v in b.values()) - sum(v[2] for v in a.values())
    assert abs(e["usage"] + e["configuration"] + e["rate"] + e["new_resources"] + e["removed_resources"] - total) < 1e-9
    assert e["configuration"] == -18.0 and e["rate"] == -3.0 and e["usage"] == 12.0 and e["removed_resources"] == -10.0
