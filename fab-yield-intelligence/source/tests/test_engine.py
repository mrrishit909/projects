"""The generator, the features and the analysis, without a database."""
import numpy as np

from fab import engine, world


def test_wafer_geometry_and_determinism():
    assert world.N_DIES == 540 and len(world.CHAMBERS) == 27 and len({c for c, _, _ in world.CHAMBERS}) == 27
    a, b = world.run(3, 10, 12), world.run(3, 10, 12)
    assert [w["yield"] for l in a for w in l["wafers"]] == [w["yield"] for l in b for w in l["wafers"]]
    assert all(len(w["bins"]) == world.N_DIES and [s["step"] for s in w["steps"]] == world.STEPS for l in a for w in l["wafers"])


def test_each_fault_makes_its_pattern_on_its_chamber_only():
    for kind, (step, _, pattern, *_rest) in world.FAULTS.items():
        ch = next(c for c, _, s in world.CHAMBERS if s == step)
        mx = {"etch_temp_drift": 3.6, "cmp_pad_wear": 0.45, "litho_focus_drift": 45, "depo_flow_fault": 4.0, "implant_dose_fault": 3.2}[kind]
        lots = world.run(2, 0, 30, [{"kind": kind, "chamber": ch, "start_lot": 0, "rate_per_lot": mx, "max": mx}])
        hit = [w for l in lots for w in l["wafers"] if any(s["chamber"] == ch for s in w["steps"])]
        miss = [w for l in lots for w in l["wafers"] if not any(s["chamber"] == ch for s in w["steps"])]
        assert hit and sum(w["truth_pattern"] == pattern for w in hit) / len(hit) > 0.9, kind
        assert not any(w["truth_pattern"] == pattern for w in miss), kind


def test_counterfactual_is_paired():
    f = [{"kind": "etch_temp_drift", "chamber": "ETCH-01/A", "start_lot": 0, "rate_per_lot": 3.6, "max": 3.6}]
    idx = {l["index"] for l in world.run(5, 0, 20, f) if l["route"]["etch"] == "ETCH-01"}
    same = world.run(5, 0, 20, f, only=idx)
    fixed = world.run(5, 0, 20, f, only=idx, route_around="ETCH-01/A")
    for a, b in zip(same, fixed):
        for wa, wb in zip(a["wafers"], b["wafers"]):
            fa, fb = np.asarray(wa["bins"]) != 1, np.asarray(wb["bins"]) != 1
            assert not (fb & ~fa).any()           # routing around the hot chamber never creates a failure it did not have
    assert np.mean([w["yield"] for l in fixed for w in l["wafers"]]) > np.mean([w["yield"] for l in same for w in l["wafers"]])


def test_features_are_rotation_invariant():
    w = world.run(4, 0, 1, [{"kind": "cmp_pad_wear", "chamber": "CMP-01/A", "start_lot": 0, "rate_per_lot": .45, "max": .45}])[0]["wafers"][0]
    grid = {(int(x), int(y)): b for x, y, b in zip(world.DIE_X, world.DIE_Y, w["bins"])}
    rotated = [grid[(int(y), -int(x) - 1)] for x, y in zip(world.DIE_X, world.DIE_Y)]       # a quarter turn of the die grid
    f0, f1 = engine.map_features(w["bins"]), engine.map_features(rotated)
    assert abs(f0[0] - f1[0]) < 0.02 and np.allclose(f0[1:11], f1[1:11], atol=0.05)


def test_bocpd_finds_a_step_and_stays_quiet_on_noise():
    rng = np.random.default_rng(0)
    noise = rng.normal(size=600)
    assert engine.drift_alarms(noise) == []
    shifted = np.concatenate([rng.normal(size=300), rng.normal(4, 1, 100)])
    alarms = engine.drift_alarms(shifted)
    assert alarms and 300 <= alarms[0] <= 310 and len(engine.drift_alarms(noise, "shewhart")) >= 1


def test_root_cause_prefers_the_chamber_inside_the_step():
    rng = np.random.default_rng(1)
    ws = []
    for _ in range(600):
        route = {s: str(rng.choice([c for c, _, st in world.CHAMBERS if st == s])) for s in world.STEPS}
        ws.append({"route": route, "affected": route["etch"] == "ETCH-02/C" and rng.random() < 0.8})
    rank = engine.root_cause(ws, "edge-ring", None, set(), ("commonality",))
    assert rank[0]["chamber"] == "ETCH-02/C" and rank[0]["confidence"] > 0.9 and rank[0]["evidence"]["affected_rate_elsewhere_in_step"] == 0
