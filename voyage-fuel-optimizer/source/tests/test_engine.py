"""The generator, the models and the optimisers, without a database."""
import numpy as np

from voyage import engine, world

TERMS = {"hire_usd_day": 28000, "fuel_usd_t": 620, "ets_usd_t": 80, "ets_share": 0.5, "window_open_h": 204.0, "window_close_h": 240.0, "late_usd_h": 3000}


def test_ocean_grid_passages_and_determinism():
    g = world.grid()
    assert g.n > 7000 and not world.is_land(g.lat, g.lon).any()
    lat, lon = world.passage("USNYC", "NLRTM")
    P = world.Path(lat, lon)
    assert 3300 < P.length < 3450                                    # New York pilot station to Rotterdam's, via the Channel
    nodes = world.shortest_sea_route(g.node(*world.PORTS["USNYC"][2]), g.node(*world.PORTS["NLRTM"][2]))
    assert not world.is_land(g.lat[nodes], g.lon[nodes]).any()
    a, b = world.Weather(5).at(45.0, -40.0, 100.0), world.Weather(5).at(45.0, -40.0, 100.0)
    assert a["hs"] == b["hs"] and a["wu"] == b["wu"]


def test_forecast_errors_grow_with_lead_and_miss_late_storms():
    truth, fc = world.Weather(11), world.Weather(11, issued=500.0)
    la, lo = np.linspace(35, 55, 9)[:, None], np.linspace(-65, -15, 11)[None, :]
    err = [float(np.abs(fc.at(la, lo, 500.0 + h)["hs"] - truth.at(la, lo, 500.0 + h)["hs"]).mean()) for h in (0, 48, 192)]
    assert err[0] < 1e-9 < err[1] < err[2]                           # the analysis is right; errors grow with lead time
    late = world.storm_across(45, -40, 700.0, 600.0, sid="told-x")      # forms 100 h after the forecast is issued
    seen_now = world.Weather(11, [late], issued=500.0)
    assert "told-x" not in {s["id"] for s in seen_now.storms(700.0)}
    assert "told-x" in {s["id"] for s in world.Weather(11, [late], issued=580.0).storms(700.0)}
    member = world.Weather(11, issued=500.0, member=3)
    assert any(s["id"].startswith("m3:") for s in member._storms(500.0, 800.0))      # members carry storms of their own beyond the horizon


def test_ship_physics():
    v = world.fleet(3)[0]
    speeds = np.arange(10, 22, 0.5)
    p = world.power(v, speeds, 0, 0, 0, 0.9, 100)
    assert np.all(np.diff(p) > 0)
    head = world.achieved(v, 16.0, 5.0, 1.0, 12.0, 0.9, 100)
    follow = world.achieved(v, 16.0, 5.0, 0.0, -12.0, 0.9, 100)
    assert head < follow <= 16.0 and world.achieved(v, 16.0, 0.0, 0.0, 0.0, 0.9, 100) == 16.0   # a speed order is an engine setting
    clean, fouled = world.fuel_tph(v, world.power(v, 16, 0, 0, 0, 0.9, 0)), world.fuel_tph(v, world.power(v, 16, 0, 0, 0, 0.9, 400))
    assert fouled > 1.05 * clean
    assert abs(engine.sea_trial_tpd(v, 18.0) - world.trial_fuel_tpd(v, 18.0)) < 0.01        # the yard's curve is the clean calm truth


def test_fuel_model_beats_the_sea_trial_curve_and_finds_the_fouling():
    seed = 21
    fleet = world.fleet(seed, n=2)
    hist = world.history(seed, fleet, 200, 0.0)
    for v in fleet:
        m = engine.fit_fuel_model(v, [r for h in hist if h["vessel"] == v["ref"] for r in h["noon"]], 0.0)
        assert m["metrics"]["mape_pct"] < 7.0 and m["metrics"]["mape_pct"] < m["metrics"]["baseline_mape_pct"]
        truth = engine.true_fouling_pct(v, m["days_clean_now"])
        assert abs(m["fouling_now_pct"] - truth) < 0.5 * truth + 2


def test_route_avoids_a_storm_and_solves_fast():
    seed, v = 13, world.fleet(13)[0]
    m = {"coef": [2.4, 0.0, 3.2, 0.1, 0.5, 0.6, 0.1, 0.05], "design_speed": v["design_speed"], "mcr_kw": v["mcr_kw"], "fuel_cap_tpd": 120.0, "sigma_voyage": 0.02}
    g = world.grid()
    a, b = g.node(*world.PORTS["USNYC"][2]), g.node(*world.PORTS["NLRTM"][2])
    short = world.Path(*world.passage("USNYC", "NLRTM"))
    mid = min(range(len(short.lat)), key=lambda i: abs(short.s[i] - 1300))
    storm = world.storm_across(short.lat[mid], short.lon[mid], 96.0, 30.0, course=40, speed_kn=22, vmax=33, radius=4.5)
    fc = world.Weather(seed, [storm], issued=0.0)
    gf = engine.GridForecast(fc, 0.0, 24 * 14)
    days = lambda t: np.asarray(t) / 24 + 300                         # noqa: E731
    r = engine.optimize_route(m, gf, 0.0, a, b, 14.0, TERMS, 0.9, days)
    r0 = engine.optimize_route(m, gf, 0.0, a, b, 14.0, TERMS, 0.9, days, weather=False)
    assert r["seconds"] < 30 and r["nodes"][0] == a and r["nodes"][-1] == b
    worst = {}
    for k, nodes in (("opt", r["nodes"]), ("short", r0["nodes"])):
        P = world.Path(*world.passage("USNYC", "NLRTM", nodes))
        _, _, trk = engine.deterministic(m, P, [(P.length, 14.0)], world.Field(P, [fc], 0.0, 400.0), 0.0, 0.0, 0.9, days)
        worst[k] = max(h["hs"] for h in trk)
    assert worst["short"] > 7.0 > worst["opt"]


def test_speed_plan_keeps_its_deadline_and_beats_service_speed():
    v = world.fleet(13)[0]
    m = {"coef": [2.4, 0.0, 3.2, 0.1, 0.5, 0.6, 0.1, 0.05], "design_speed": v["design_speed"], "mcr_kw": v["mcr_kw"], "fuel_cap_tpd": 120.0, "sigma_voyage": 0.02}
    days = lambda t: np.asarray(t) / 24 + 300                         # noqa: E731
    P = world.Path(*world.passage("USNYC", "NLRTM"))
    F = world.Field(P, [world.Weather(13, issued=0.0)], 0.0, 450.0)
    opt = engine.optimize_speed(m, P, F, 0.0, 0.0, TERMS, 0.0, 0.9, days, v_max=20.0, deadline_h=230.0)
    svc = engine.optimize_speed(m, P, F, 0.0, 0.0, TERMS, 0.0, 0.9, days, v_max=0, fixed=v["service_speed"])
    assert opt["arrival_h"] <= 230.0 and all(engine.V_MIN <= s <= 20.0 for _, s in opt["legs"])
    assert opt["expected_cost_usd"] < svc["expected_cost_usd"]
    t_det, _, _ = engine.deterministic(m, P, opt["legs"], F, 0.0, 0.0, 0.9, days)
    assert abs(t_det - opt["arrival_h"]) < 1.5                       # the DP's arrival is what sailing its orders gives


def test_bunker_milp_is_never_worse_than_topping_up():
    rng = np.random.default_rng(4)
    for _ in range(60):
        cap = rng.uniform(3000, 7000)
        p50 = rng.uniform(200, 700)
        legs = [{"p50": p50 * f, "p90": p50 * f * rng.uniform(1.02, 1.15), "days": rng.uniform(7, 11)} for f in (1.0, 1.08, 1.0)]
        calls = [{"port": p, "price": pr, "fee": 6000.0} for p, pr in (("A", rng.uniform(600, 680)), ("B", rng.uniform(550, 620)), ("A", rng.uniform(600, 680)))]
        r = engine.bunker_plan(calls, legs, rob0=rng.uniform(0.2, 0.5) * cap, capacity=cap)
        assert r["status"] == "optimal" and r["saving_usd"] >= -1
        assert all(p["arrive_with_t"] >= p["reserve_t"] - 1e-6 and p["rob_after_t"] <= cap + 1e-6 for p in r["plan"])
        assert all(p["buy_t"] == 0 or p["buy_t"] >= 250 - 1e-6 for p in r["plan"])
