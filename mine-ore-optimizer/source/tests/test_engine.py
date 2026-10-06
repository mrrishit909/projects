"""The generator, the models and the optimisers, without a database."""
import numpy as np
import pytest

from mine import engine, world

MINE = world.make_mine(7)


@pytest.fixture(scope="module")
def week():
    hist, st = world.history(MINE, 6)
    return hist, st


def test_geometry_determinism_and_pairing(week):
    assert world.N_BLOCKS == 28800 and len(MINE["trucks"]) == 28 and len({b for s in MINE["shovels"] for b in s["seq"]}) == 6 * 256
    _, st = week
    plan = world.legacy_plan(MINE, st, "fixed")
    a = world.run_shift(MINE, st, [(0, plan)], natural=False)
    b = world.run_shift(MINE, st, [(0, plan)], natural=False)
    assert a["haul"] == b["haul"] and a["plant"] == b["plant"]
    other = dict(plan, mode="nearest")
    c = world.run_shift(MINE, st, [(0, plan), (240, other)], natural=False)
    t0 = st["shift"] * world.SHIFT_MIN
    early = lambda r: [e for e in r["haul"] if e["ended_min"] - t0 < 240]      # noqa: E731
    assert early(a) == early(c) and a["haul"] != c["haul"]                     # the same past, a different future


def test_physics_and_the_low_grade_zone():
    loaded = world.segment(1000, 0.09, "ramp", world.TRUCK_EMPTY_T + world.PAYLOAD_T, False)
    empty = world.segment(1000, 0.09, "ramp", world.TRUCK_EMPTY_T, False)
    wet = world.segment(1000, 0.09, "ramp", world.TRUCK_EMPTY_T + world.PAYLOAD_T, True)
    assert loaded[0] > 1.8 * empty[0] and wet[0] > loaded[0] and loaded[1] > 2 * empty[1]
    st = world.initial_state(MINE)
    z = world.zone_ahead_of(MINE, st, "S1")
    cu, _, _ = world.true_grades(MINE, [z])
    changed = np.nonzero(cu != MINE["cu"])[0]
    assert len(changed) > 20 and {world.block_ijk(b)[2] for b in changed} == {z["bench"]}
    assert all(np.hypot(*(np.array(world.block_xy(b)) - [z["x"], z["y"]])) <= 1.3 * z["radius_m"] for b in changed)
    nb = world.next_blast(MINE, st, "S1")
    assert np.mean([world.blast_assay(MINE, b, [z])["cu"] for b in nb[:6]]) < 0.6 * np.mean([world.blast_assay(MINE, b)["cu"] for b in nb[:6]])
    assert all(h["cu"] == h2["cu"] for h, h2 in zip(world.drill_holes(MINE), world.drill_holes(MINE)))


def test_kriging_beats_inverse_distance():
    holes = world.drill_holes(MINE)
    gm = engine.GradeModel(holes)
    rng = np.random.default_rng(0)
    held = rng.choice(np.setdiff1d(np.arange(world.N_BLOCKS), [h["block"] for h in holes]), 4000, replace=False)
    p = gm.predict(held)
    g, i = engine.score_grade(MINE["cu"][held], p["cu"], p["p10"], p["p90"]), engine.score_grade(MINE["cu"][held], engine.idw(holes, held))
    assert g["rmse"] < 0.85 * i["rmse"] and g["misclassified"] < i["misclassified"] and 0.65 < g["coverage_80"] < 0.92
    near = max(holes, key=lambda h: h["cu"])["block"] + 1              # a blast-hole result pulls its own block towards it
    before = gm.predict([near])["cu"][0]
    gm.condition(holes + [{"block": near, "kind": "blasthole", "cu": 0.05, "as": 100.0, "bwi": 13.0}])
    assert gm.predict([near])["cu"][0] < 0.7 * before


def test_cycle_time_model_and_engine_detector(week):
    hist, st = week
    ev = [e for r in hist for e in r["haul"]]
    kinds, ages = {s["id"]: s["kind"] for s in MINE["shovels"]}, {t["id"]: t["age_h"] for t in MINE["trucks"]}
    model, m = engine.train_cycle(ev, kinds, ages, np.array([e["dispatched_min"] >= 4 * world.SHIFT_MIN for e in ev]))
    assert m["mape_pct"] < 10 and m["mape_pct"] < 0.8 * m["baseline_mape_pct"]
    windows = sorted((w for r in hist for w in r["telemetry"]), key=lambda w: (w["truck"], w["at_min"]))
    det = engine.train_anomaly(windows, [b for r in hist for b in r["breakdowns"]])
    told = [{"kind": "breakdown", "shift": st["shift"], "truck": "T05", "at_min": 400.0, "failure": "cooling"},
            {"kind": "breakdown", "shift": st["shift"], "truck": "T09", "at_min": 300.0, "failure": "tyre"}]
    r = world.run_shift(MINE, st, [(0, world.legacy_plan(MINE, st, "fixed"))], told, natural=False)
    found = engine.alarms(det, sorted(r["telemetry"], key=lambda w: (w["truck"], w["at_min"])))
    fail = st["shift"] * world.SHIFT_MIN + 400
    hits = [a for a in found if a[0] == "T05"]
    assert hits and hits[0][2] == "coolant_c" and 30 <= fail - hits[0][1] <= 120          # warned, ahead of the failure
    assert not [a for a in found if a[0] == "T09"] and len(found) <= 2                   # no warning for a tyre, quiet elsewhere


def test_dispatch_mip_respects_its_constraints():
    S = []
    for k, (rate, mix, src) in enumerate([(4000, {"HG": 0.8, "LG": 0.2, "W": 0.0}, {"HG": (0.62, 0.05, 220, 20, 14), "LG": (0.35, 0.03, 150, 15, 14)}),
                                          (3300, {"HG": 0.3, "LG": 0.5, "W": 0.2}, {"HG": (0.5, 0.05, 300, 30, 15), "LG": (0.3, 0.03, 200, 20, 14)}),
                                          (3300, {"HG": 0.0, "LG": 0.0, "W": 1.0}, {})]):
        S.append({"id": f"S{k + 1}", "rate_tph": rate, "load_min": 3.0, "mix": mix, "src": src, "travel": {"crusher": 12, "hg": 10, "lg": 11, "dump": 16},
                  "fuel_per_t": {"crusher": 0.3, "hg": 0.25, "lg": 0.27, "dump": 0.4}})
    stock = {"hg": {"tonnes": 3e5, "cu": 0.6, "cu_sd": 0.04, "as": 200, "as_sd": 15, "bwi": 14}, "lg": {"tonnes": 6e5, "cu": 0.32, "cu_sd": 0.03, "as": 150, "as_sd": 10, "bwi": 13}}
    inp = {"horizon_h": 8, "shovels": S, "groups": [{"shovel": "S1", "trucks": [f"T{i}" for i in range(6)]}, {"shovel": None, "trucks": [f"T{i}" for i in range(6, 14)]}],
           "stock": stock, "mill_tph": 3900}
    r = engine.optimize_dispatch(inp)
    assert sum(r["trucks"].values()) <= 14 and len(r["assign"]) == sum(r["trucks"].values()) and r["gap"] < 0.01
    for s in S:
        assert r["targets"][s["id"]] <= r["curves"][s["id"]][r["trucks"][s["id"]]] + 1
    feed = sum(r["targets"][s["id"]] * s["mix"][c] for s in S for c in ("HG", "LG") if r["route"][s["id"]][c] == "crusher") + sum(r["reclaim_tph"].values())
    assert feed <= 3900 + 1 and sum(r["reclaim_tph"].values()) <= world.LOADER_TPH + 1e-6
    curve = engine.shovel_curve(10, 3, 4000, 12)
    assert all(b >= a for a, b in zip(curve, curve[1:])) and all(c - b <= b - a + 1e-6 for a, b, c in zip(curve, curve[1:], curve[2:])) and max(curve) <= 4000
    pit = [{"S1/HG": (2000.0, 0.45, 0.04, 200.0, 20.0, 14.0)}] * 4
    b = engine.solve_blend(pit, stock, [3900] * 4, z=1.0)
    for h in b["hours"]:
        rec = h["reclaim_tph"]
        assert all(v % 50 == 0 and (v == 0 or v >= 300) for v in rec.values()) and sum(rec.values()) <= world.LOADER_TPH
        assert world.TARGET_CU - world.TOL_CU <= h["cu"] <= world.TARGET_CU + world.TOL_CU
    base = engine.proportional_blend(pit, stock, [3900] * 4)
    assert all(h["cu"] < world.TARGET_CU - world.TOL_CU for h in base["hours"])          # the proportional blend falls out of the window here


def test_twin_is_paired(week):
    hist, st = week
    ev = [e for r in hist for e in r["haul"]]
    kinds = {s["id"]: s["kind"] for s in MINE["shovels"]}
    model, _ = engine.train_cycle(ev, kinds, {t["id"]: t["age_h"] for t in MINE["trucks"]}, np.array([e["dispatched_min"] >= 3 * world.SHIFT_MIN for e in ev]))
    fuel, _ = engine.train_fuel(ev, np.zeros(len(ev), bool))
    sh = [{"id": s["id"], "kind": s["kind"], "load_min": world.LOAD_NOMINAL[s["kind"]], "seq": s["seq"], "pos": st["shovels"][s["id"]]["pos"], "remaining": st["shovels"][s["id"]]["remaining"],
           "rate_tph": s["rate_tph"]} for s in MINE["shovels"]]
    blocks = sorted({b for s in sh for b in s["seq"][s["pos"]:s["pos"] + 60]})
    gm = engine.GradeModel(world.drill_holes(MINE)[:400])
    est = engine.block_estimates(gm.predict(blocks), blocks)
    tr = engine.Travel(model, kinds, {})
    ctx = {"minutes": 240, "trucks": [(t["id"], "goline") for t in MINE["trucks"]], "shovels": sh, "est": est, "travel_split": tr.split,
           "fuel": lambda frm, face, dest, payload, idle: engine.fuel_litres(fuel, frm, face, dest, payload, idle), "resid_sd": model.resid_sd_,
           "stock": {"hg": [3e5, 0.6, 200, 14], "lg": [6e5, 0.33, 150, 13]}, "bin": [2500, 0.55, 200, 14]}
    plan = world.legacy_plan(MINE, st, "fixed")
    out = engine.twin(ctx, {"a": plan, "b": dict(plan)}, reps=4, seed=1)
    assert all(v["mean"] == 0 and v["p10"] == 0 for v in out["b"]["vs_a"].values())         # the same plan on the same draws: no difference
    assert out["a"]["moved_t"]["mean"] > 20000 and out["a"]["fuel_l"]["mean"] > 0
