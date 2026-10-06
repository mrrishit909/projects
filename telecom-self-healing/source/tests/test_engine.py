"""The generator, the models and the analysis, without a database."""
import numpy as np
import pytest

from noc import engine, world

NET = world.network(7)
DAY = world.PER_DAY


def test_topology_and_determinism():
    assert len(NET["sites"]) == 44 and len(NET["cells"]) == 264 and len({c["id"] for c in NET["cells"]}) == 264
    assert all(chain[-1] == "CORE-01" and chain[0] == f"CSR-{s}" for s, chain in world.paths(NET).items())
    a, b = world.run(NET, 7, 100, 104), world.run(NET, 7, 100, 104)
    assert all(np.array_equal(x["cell"], y["cell"]) and x["alarms"] == y["alarms"] for x, y in zip(a, b))
    looped = {**NET, "sites": [dict(s, alt_parent="S10", alt_link="A-S05-S10") if s["id"] == "S05" else s for s in NET["sites"]]}
    with pytest.raises(ValueError, match="loop"):          # S10's standby goes to S05; give S05 one to S10 and move both
        world.paths(looped, {"S05", "S10"})


def test_faults_propagate_down_the_topology_and_only_there():
    t0 = 28 * DAY + 60
    behind = {c["id"] for c in NET["cells"] if c["site"] in engine.subtree_sites(NET, "S08")}
    deg = {"id": "X1", "kind": "backhaul_degradation", "element": "L-S08-AGG-NE", "start": t0, "end": None, "cap_factor": 0.5, "loss_pct": 0.8}
    power = {"id": "X2", "kind": "site_power_outage", "element": "CSR-S12", "start": t0, "end": None}
    out = world.run(NET, 7, t0, t0 + 8, [deg, power])
    ids = [c["id"] for c in NET["cells"]]
    hit = {ids[i] for o in out for i in np.nonzero(o["cause"] == "X1")[0]}
    assert hit and hit <= behind and len(hit) >= 0.8 * len(behind)
    dark = {ids[i] for i in np.nonzero(out[-1]["cell"][:, 7] < 0.5)[0]}         # after the hour on battery: S12 and the tails behind it
    assert dark == {c["id"] for c in NET["cells"] if c["site"] in engine.subtree_sites(NET, "S12")}
    alarms = [a for o in out for a in o["alarms"]]
    assert any(a[3] == "POWER_MAINS_FAIL" and a[2] == "CSR-S12" for a in alarms) and any(a[3] == "MW_CAPACITY_DEGRADED" and a[2] == "L-S08-AGG-NE" for a in alarms)
    assert all(a[6] in ("X1", "X2", "") for a in alarms)


def test_rerouting_is_paired_and_moves_the_load():
    t0 = 28 * DAY + 76
    base = world.run(NET, 7, t0, t0 + 4)
    moved = world.run(NET, 7, t0, t0 + 4, [{"kind": "reroute", "site": "S10", "start": t0}, {"kind": "reroute", "site": "S11", "start": t0}])
    sim = world.Sim(NET, 7)
    a, b = base[-1], moved[-1]
    assert np.allclose(a["cell"][:, 2], b["cell"][:, 2])                       # same users everywhere: the same traffic
    j8, j5 = sim.link_ix["L-S08-AGG-NE"], sim.link_ix["L-S05-AGG-NE"]
    shift = a["offered_link"][j8] - b["offered_link"][j8]
    assert shift > 300 and abs(b["offered_link"][j5] - a["offered_link"][j5] - shift) < 1e-6


def test_one_storm_becomes_one_incident_ranked_at_the_link():
    t0 = 28 * DAY + 56
    topo = engine.Topology(NET)
    out = world.run(NET, 7, t0, t0 + 10, [{"id": "X1", "kind": "backhaul_degradation", "element": "L-S08-AGG-NE", "start": t0, "end": None, "cap_factor": 0.5, "loss_pct": 0.55}])
    cor = engine.Correlator(topo)
    n = 0
    for o in out:
        batch = []
        for a in o["alarms"]:
            n += 1
            batch.append({"id": n, "t": a[0], "minute": a[1], "element": a[2], "type": a[3], "related": a[5], "cause": a[6]})
        cor.feed(o["t"], batch)
    storm = [i for i in cor.incidents.values() if i["status"] == "open" and any(a["cause"] == "X1" for a in i["alarms"])]
    assert len(storm) == 1 and storm[0]["root"] == "L-S08-AGG-NE" and len(storm[0]["alarms"]) >= 100
    assert all(a["cause"] == "X1" for a in storm[0]["alarms"] if a["type"] != "RRC_CONGESTION")
    top = storm[0]["ranking"][0]
    assert top["evidence"]["own_alarm_types"] and top["features"]["topology"] > 0.9
    assert engine.rank_by_count(storm[0]["alarms"])[0] != "CSR-S08"


def test_anomaly_model_finds_the_silent_cell_and_stays_quiet():
    T = 15 * DAY
    sleep = {"id": "Z", "kind": "sleeping_cell", "element": "S20-A-N", "start": T - 40, "end": None, "traffic_factor": 0.1}
    out = world.run(NET, 7, 0, T, [sleep])
    cell = np.array([o["cell"] for o in out]).astype(float)
    ts = np.arange(T)
    topo = engine.Topology(NET)
    quiet = engine.quiet_mask(topo, [(o["t"], a[2], a[3]) for o in out for a in o["alarms"]], 0, T)
    ad = engine.AnomalyModel().fit(cell[:T - 96], ts[:T - 96], quiet[:T - 96])
    i = [c["id"] for c in NET["cells"]].index("S20-A-N")
    flags = engine.persistent(ad.flag(cell, ts))
    assert flags[T - 38:, i].all() and not engine.static_flags(cell[T - 38:, i]).any()
    others = np.delete(flags[T - 96:], i, axis=1)
    assert others.mean() < 0.001
    assert ad.explain(ad.score(cell[-1:], ts[-1:])[1][0, i])[0]["feature"] in ("log_dl", "log_users")


def test_forecaster_beats_seasonal_naive_per_cell():
    T = 22 * DAY
    out = world.run(NET, 7, 0, T)
    dl = np.array([o["cell"][:, 0] for o in out]).astype(float)
    ts = np.arange(T)
    fc = engine.Forecaster().fit(dl[:21 * DAY], ts[:21 * DAY], np.ones((21 * DAY, dl.shape[1]), bool))
    o = 21 * DAY
    pred, hts = fc.forecast(dl[o - 8:o], ts[o - 8:o], DAY)
    assert hts[0] == o and engine.wape(pred, dl[o:o + DAY]) < engine.wape(dl[o - 7 * DAY:o - 6 * DAY], dl[o:o + DAY])


def test_policy_envelope_and_the_optimiser():
    env = {"max_link_utilisation": 0.8, "forecast_margin": 0.05, "max_elements_changed": 2, "allowed_actions": ["reroute_site"], "protected_sites": ["S09"]}
    cap = np.array([l["capacity"] for l in NET["links"]])
    cap[[l["id"] for l in NET["links"]].index("L-S08-AGG-NE")] *= 0.5
    hts = np.arange(28 * DAY + 68, 28 * DAY + 68 + 24)
    fcst = np.array([world.demand(NET, 7, t) for t in hts])
    opt = engine.optimise(NET, "L-S08-AGG-NE", fcst, cap, env, (), hts)
    assert not opt["do_nothing"]["feasible"] and opt["best"] and opt["best"]["peak"] <= 0.75 and len(opt["best"]["actions"]) <= 2
    assert all("S09" not in [a["site"] for a in c["actions"]] for c in opt["candidates"] if c["feasible"])
    v = engine.policy_check(NET, [{"type": "reroute_site", "site": "S09"}, {"type": "rollback_config", "element": "S09-A-L"}, {"type": "reroute_site", "site": "S10"}],
                            None, env)
    assert {x["rule"] for x in v} == {"protected_sites", "allowed_actions", "max_elements_changed"}
    assert engine.affected_links(NET, [{"type": "reroute_site", "site": "S10"}]) >= {"L-S10-S08", "A-S10-S05", "L-S08-AGG-NE", "L-S05-AGG-NE"}
