"""Held-out evaluation on three mines the demo never uses (different seeds: a different orebody, panels and fleet).

    python -m mine.evaluate            # prints the markdown behind docs/evaluation.md

Each mine runs a week of history under its legacy dispatch; the models are trained on the first ten shifts exactly as the
service trains them and scored on the last four. The dispatch comparison then runs the next shift several times, each with a
different disruption the generator is told about (a low-grade zone ahead of a shovel, breakdowns, or nothing), re-plans four
hours in with every method on the service's own estimates, and lets the generator play out the remaining eight hours under
each plan on the same random draws. Truth comes from the generator only here, to score.
"""
import sys
import time

import numpy as np

from . import engine, world

SEEDS = (101, 102, 103)
HISTORY, TEST_FROM = 14, 10
SPLIT = TEST_FROM * world.SHIFT_MIN


def service_view(gen, hist, st):
    """What the service would hold at the start of the next shift: assays, estimates, trained models, stockpile estimates."""
    samples = world.drill_holes(gen)
    expl = list(samples)
    for blocks in world.blasts_assayed(gen, st).values():
        samples += [world.blast_assay(gen, b) for b in blocks]
    gm = engine.GradeModel(expl)
    held = np.setdiff1d(np.arange(world.N_BLOCKS), [s["block"] for s in expl])
    pv = gm.predict(held)
    truth = gen["cu"][held]
    grade = {"gp": engine.score_grade(truth, pv["cu"], pv["p10"], pv["p90"]), "idw": engine.score_grade(truth, engine.idw(expl, held)),
             "nearest": engine.score_grade(truth, engine.nearest_hole(expl, held)),
             "as_rmse": (round(float(np.sqrt(np.mean((pv["as"] - gen["as"][held]) ** 2))), 1), round(float(np.sqrt(np.mean((engine.idw(expl, held, var="as") - gen["as"][held]) ** 2))), 1)),
             "bwi_rmse": (round(float(np.sqrt(np.mean((pv["bwi"] - gen["bwi"][held]) ** 2))), 2), round(float(np.sqrt(np.mean((engine.idw(expl, held, var="bwi") - gen["bwi"][held]) ** 2))), 2))}
    gm.condition(samples)
    events = [e for r in hist for e in r["haul"]]
    kinds, ages = {s["id"]: s["kind"] for s in gen["shovels"]}, {t["id"]: t["age_h"] for t in gen["trucks"]}
    test = np.array([e["dispatched_min"] >= SPLIT for e in events])
    cyc, cyc_m = engine.train_cycle(events, kinds, ages, test)
    fuel, fuel_m = engine.train_fuel(events, test)
    windows = sorted((w for r in hist for w in r["telemetry"]), key=lambda w: (w["truck"], w["at_min"]))
    downs = [b for r in hist for b in r["breakdowns"]]
    anomaly = engine.train_anomaly([w for w in windows if w["at_min"] < SPLIT], [b for b in downs if b["at_min"] < SPLIT])
    load_min = {s: float(np.mean([e["load_min"] for e in events if e["shovel"] == s])) for s in kinds}
    # stockpiles as the service tracks them: the survey, plus every load at its block's estimate, less reclaim
    allb = sorted({e["block"] for e in events if e["dest"] in ("hg", "lg")})
    est = engine.block_estimates(gm.predict(allb), allb)
    piles = world.stock_survey(gen, world.initial_state(gen))
    for r in hist:
        for e in r["haul"]:
            if e["dest"] in piles:
                p, g = piles[e["dest"]], est[e["block"]]
                n = p["tonnes"] + e["payload_t"]
                for k in ("cu", "cu_sd", "as", "as_sd", "bwi"):
                    p[k] = (p[k] * p["tonnes"] + g[k] * e["payload_t"]) / n
                p["tonnes"] = n
        for h in r["plant"]:
            for k, v in h["reclaim_by_pile"].items():
                piles[k]["tonnes"] -= v
    # plant hours with the estimated hardness of what was fed
    bw = []
    for r in hist:
        for h in r["plant"]:
            fed = [(e["payload_t"], est_bwi(gm, e["block"])) for e in r["haul"] if e["dest"] == "crusher" and h["hour_min"] <= e["ended_min"] < h["hour_min"] + 60]
            fed += [(v, piles[k]["bwi"]) for k, v in h["reclaim_by_pile"].items()]
            tt = sum(t for t, _ in fed)
            bw.append(sum(t * b for t, b in fed) / tt if tt else world.MILL_BASE_BWI)
    ph = [h for r in hist for h in r["plant"]]
    rows = [{"feed_tph": h["delivered_t"] + h["reclaim_t"], "bin_start_t": h["bin_start_t"], "bwi_s": b, "processed_t": h["processed_t"], "outage": h["outage_min"]}
            for h, b in zip(ph, engine.smooth_bwi(bw))]
    plant, plant_m = engine.train_plant(rows, np.array([h["hour_min"] >= SPLIT for h in ph]))
    return {"gm": gm, "grade": grade, "cycle": cyc, "cycle_m": cyc_m, "fuel": fuel, "fuel_m": fuel_m, "anomaly": anomaly, "load_min": load_min,
            "piles": piles, "plant_m": plant_m, "windows": windows, "downs": downs, "kinds": kinds}


_BWI = {}


def est_bwi(gm, b):
    if (id(gm), b) not in _BWI:
        _BWI[(id(gm), b)] = float(gm.predict([b])["bwi"][0])
    return _BWI[(id(gm), b)]


def anomaly_eval(gen, sv, st):
    """Six more shifts with eight failures each told to the generator (every kind, random trucks and times): enough events to
    score. The normal was learned on the history's first ten shifts."""
    rng = np.random.default_rng([gen["seed"], 77])
    state, windows, downs = dict(st, down_until={}), [], []
    for n in range(6):
        shift = state["shift"]
        up = [t["id"] for t in gen["trucks"]]
        told = [{"kind": "breakdown", "shift": shift, "truck": str(t), "at_min": float(rng.uniform(150, 700)), "failure": str(rng.choice(["cooling", "oil", "tyre", "electrical"], p=[0.35, 0.35, 0.2, 0.1]))}
                for t in rng.choice(up, 8, replace=False)]
        r = world.run_shift(gen, state, [(0, world.legacy_plan(gen, state, "fixed"))], told, natural=False)
        windows += r["telemetry"]
        downs += r["breakdowns"]
        state = dict(r["end_state"], down_until={})
    windows.sort(key=lambda w: (w["truck"], w["at_min"]))
    return {rule: engine.score_alarms(engine.alarms(sv["anomaly"], windows, rule), downs, windows) for rule in ("model", "static")}


SCENARIOS = [("dyke ahead of S1, three breakdowns", "S1", 3), ("dyke ahead of S2, three breakdowns", "S2", 3), ("no disruption", None, 0)]


def dispatch_eval(gen, sv, st, name, zone_on, n_breaks, rng):
    """One disrupted shift: four hours on the shift's baseline plan, then each method re-plans from the service's estimates and the
    generator plays out the remaining eight hours under it, on the same random draws."""
    st = dict(st, down_until={})
    trucks = [t["id"] for t in gen["trucks"]]
    told = []
    if zone_on:
        z = world.zone_ahead_of(gen, st, zone_on)
        z["assays_at_min"] = 150.0
        told.append(z)
    for t, at_, f in zip(rng.choice(trucks, n_breaks, replace=False), rng.uniform(40, 230, n_breaks), rng.choice(["tyre", "cooling", "oil"], n_breaks)):
        told.append({"kind": "breakdown", "shift": st["shift"], "truck": str(t), "at_min": float(at_), "failure": str(f)})
    sh0 = [{"id": s["id"], "kind": s["kind"], "rate_tph": s["rate_tph"], "load_min": sv["load_min"][s["id"]], "seq": s["seq"], "pos": st["shovels"][s["id"]]["pos"],
            "remaining": st["shovels"][s["id"]]["remaining"]} for s in gen["shovels"]]
    blocks = sorted({b for s in sh0 for b in s["seq"][s["pos"]:s["pos"] + 80]})
    est = engine.block_estimates(sv["gm"].predict(blocks), blocks)
    tr = engine.Travel(sv["cycle"], sv["kinds"], sv["load_min"])
    tr.face_shovel = {b: s["id"] for s in sh0 for b in s["seq"]}
    inp = engine.dispatch_inputs(sh0, est, tr, sv["fuel"], [{"shovel": None, "trucks": trucks}], sv["piles"], 12)
    base = engine.heuristic_dispatch(inp)
    base["block_class"] = {str(b): est[b]["cls"] for b in blocks}
    r4 = world.run_shift(gen, st, [(0, base)], told, until=240, natural=False)
    s240 = r4["end_state"]
    # the service at minute 240: the assays that came back, the trucks that are up, where the shovels are, what the piles hold
    arrived = world.assays_due(gen, st, told, 0, 240)
    gm = engine.GradeModel.from_kernels(sv["gm"].kernels, sv["gm"].samples + arrived) if arrived else sv["gm"]
    est = engine.block_estimates(gm.predict(blocks), blocks)
    classes = {str(b): est[b]["cls"] for b in blocks}
    down = {b["truck"] for b in r4["breakdowns"]}
    up = [t for t in trucks if t not in down]
    sh = [dict(s, pos=s240["shovels"][s["id"]]["pos"], remaining=s240["shovels"][s["id"]]["remaining"]) for s in sh0]
    piles = {k: dict(v) for k, v in sv["piles"].items()}
    for e in r4["haul"]:
        if e["dest"] in piles:
            p, g = piles[e["dest"]], est.get(e["block"]) or engine.block_estimates(gm.predict([e["block"]]), [e["block"]])[e["block"]]
            n = p["tonnes"] + e["payload_t"]
            for k in ("cu", "cu_sd", "as", "as_sd", "bwi"):
                p[k] = (p[k] * p["tonnes"] + g[k] * e["payload_t"]) / n
            p["tonnes"] = n
    for h in r4["plant"]:
        for k, v in h["reclaim_by_pile"].items():
            piles[k]["tonnes"] -= v
    groups = {}
    for t in up:
        groups.setdefault(base["assign"].get(t), []).append(t)
    inp2 = engine.dispatch_inputs(sh, est, tr, sv["fuel"], [{"shovel": k, "trucks": v} for k, v in sorted(groups.items(), key=str)], piles, 8)
    inp2["waste_tph_min"] = engine.waste_floor(inp2, {t: s for t, s in base["assign"].items() if t in up})
    t0 = time.perf_counter()
    opt = engine.optimize_dispatch(inp2)
    solve_ms = (time.perf_counter() - t0) * 1000
    rates = opt["targets"]
    pit = engine.pit_feed_by_hour(sh, rates, opt["route"], est, 8)
    mill = []
    for h in pit:
        tt = sum(v[0] for v in h.values())
        mill.append(world.mill_tph(sum(v[0] * v[5] for v in h.values()) / tt if tt else 14.0))
    blends = {"robust": engine.solve_blend(pit, piles, mill, z=1.28), "mean": engine.solve_blend(pit, piles, mill, z=0.0)}
    hours = 4

    def sched(b):
        return {"mode": "schedule", "hours": [{}] * hours + [{k: v for k, v in h["reclaim_tph"].items() if v > 0} for h in b["hours"]]}
    replan = engine.heuristic_dispatch(engine.dispatch_inputs(sh, est, tr, sv["fuel"], [{"shovel": None, "trucks": up}], piles, 8))
    plans = {"baseline plan, kept": dict(base, block_class=classes),
             "heuristic re-plan": dict(replan, block_class=classes),
             "nearest free shovel": dict(base, mode="nearest", block_class=classes),
             "MIP + robust blend": {"mode": "fixed", "assign": opt["assign"], "targets": rates, "route": opt["route"], "block_class": classes, "reclaim": sched(blends["robust"])},
             "MIP + mean-only blend": {"mode": "fixed", "assign": opt["assign"], "targets": rates, "route": opt["route"], "block_class": classes, "reclaim": sched(blends["mean"])},
             "MIP, proportional reclaim": {"mode": "fixed", "assign": opt["assign"], "targets": rates, "route": opt["route"], "block_class": classes, "reclaim": {"mode": "proportional"}},
             "MIP rates by need-based dispatch": {"mode": "targets", "targets": rates, "route": opt["route"], "block_class": classes, "reclaim": sched(blends["robust"])}}
    out = {}
    for pname, pl in plans.items():
        r = world.run_shift(gen, st, [(0, base), (240, pl)], told, natural=False)
        t_ = st["shift"] * world.SHIFT_MIN
        plant = [h for h in r["plant"] if h["hour_min"] - t_ >= 240]
        haul = [e for e in r["haul"] if e["ended_min"] - t_ >= 240]
        v = engine.shift_value(plant, haul, s240["stock"], r["end_state"]["stock"], s240["bin"], r["end_state"]["bin"])
        v["dev"] = float(np.mean([abs(h["truth"]["feed_cu"] - world.TARGET_CU) for h in plant if h["truth"]["feed_cu"] is not None]))
        v["as_over"] = sum(1 for h in plant if (h["truth"]["feed_as"] or 0) > world.AS_LIMIT)
        v["idle_hours"] = sum(1 for h in plant if h["processed_t"] < 100)
        v["to_hg_pile_t"] = sum(e["payload_t"] for e in haul if e["dest"] == "hg")
        v["waste_t"] = sum(e["payload_t"] for e in haul if e["dest"] == "dump")
        v["net_value_sf90"] = engine.shift_value(plant, haul, s240["stock"], r["end_state"]["stock"], s240["bin"], r["end_state"]["bin"], factor=0.9)["net_value_usd"]
        out[pname] = v
    # the twin's paired prediction of the MIP plan against the plan kept, for the same eight hours
    ctx = {"minutes": 480, "trucks": [(t, "goline") for t in up], "shovels": sh, "est": est,
           "travel_split": lambda frm, face, dest: tr.split(frm, face, dest, tr.face_shovel.get(int(face))),
           "fuel": lambda frm, face, dest, payload, idle: engine.fuel_litres(sv["fuel"], frm, face, dest, payload, idle), "resid_sd": sv["cycle"].resid_sd_,
           "stock": {k: [v["tonnes"], v["cu"], v["as"], v["bwi"]] for k, v in piles.items()},
           "bin": [s240["bin"][0], s240["bin"][1] / max(s240["bin"][0], 1), s240["bin"][2] / max(s240["bin"][0], 1), s240["bin"][3] / max(s240["bin"][0], 1)]}
    tw = engine.twin(ctx, {"kept": dict(base, block_class=classes), "mip": dict(plans["MIP + robust blend"], reclaim={"mode": "schedule", "hours": sched(blends["robust"])["hours"][hours:]})}, reps=10, seed=gen["seed"])
    return {"name": name, "results": out, "solve_ms": solve_ms, "gap": opt["gap"], "twin_net_diff": tw["mip"]["vs_kept"]["net_value_usd"]["mean"],
            "true_net_diff": out["MIP + robust blend"]["net_value_usd"] - out["baseline plan, kept"]["net_value_usd"], "up": len(up)}


def scale_eval():
    """Solve time of the dispatch MIP against fleet size: shovels and trucks scaled from one mine's real inputs."""
    gen = world.make_mine(SEEDS[0])
    hist, st = world.history(gen, 4)
    events = [e for r in hist for e in r["haul"]]
    kinds = {s["id"]: s["kind"] for s in gen["shovels"]}
    cyc, _ = engine.train_cycle(events, kinds, {t["id"]: t["age_h"] for t in gen["trucks"]}, np.array([e["dispatched_min"] >= 2 * world.SHIFT_MIN for e in events]))
    fuel, _ = engine.train_fuel(events, np.zeros(len(events), bool))
    gm = engine.GradeModel(world.drill_holes(gen))
    sh = [{"id": s["id"], "kind": s["kind"], "rate_tph": s["rate_tph"], "load_min": world.LOAD_NOMINAL[s["kind"]], "seq": s["seq"], "pos": st["shovels"][s["id"]]["pos"],
           "remaining": st["shovels"][s["id"]]["remaining"]} for s in gen["shovels"]]
    blocks = sorted({b for s in sh for b in s["seq"][s["pos"]:s["pos"] + 80]})
    est = engine.block_estimates(gm.predict(blocks), blocks)
    tr = engine.Travel(cyc, kinds, {s["id"]: s["load_min"] for s in sh})
    base = engine.dispatch_inputs(sh, est, tr, fuel, [{"shovel": None, "trucks": []}], world.stock_survey(gen, st), 8)
    out = []
    for n_shovels, n_trucks, per_truck in ((6, 28, False), (12, 100, False), (20, 200, False), (20, 200, True)):
        rng = np.random.default_rng(n_trucks)
        S = []
        for k in range(n_shovels):
            s = dict(base["shovels"][k % 6])
            s = {**s, "id": f"X{k + 1:02d}", "travel": {d: v * rng.uniform(0.85, 1.25) for d, v in s["travel"].items()}}
            S.append(s)
        trucks = [f"T{i:03d}" for i in range(n_trucks)]
        if per_truck:
            groups = [{"shovel": S[i % n_shovels]["id"], "trucks": [t]} for i, t in enumerate(trucks)]
        else:
            groups = [{"shovel": S[i]["id"], "trucks": trucks[i::n_shovels]} for i in range(n_shovels)]
        inp = {**base, "shovels": S, "groups": groups, "mill_tph": base["mill_tph"] * n_shovels / 6}
        times, res = [], None
        for _ in range(3):
            res = engine.optimize_dispatch(inp, time_limit_s=30)
            times.append(res["solve_ms"])
        out.append({"shovels": n_shovels, "trucks": n_trucks, "per_truck": per_truck, "solve_ms": float(np.median(times)), "max_ms": max(times), "gap": res["gap"],
                    "variables": res["variables"], "constraints": res["constraints"]})
    return out


def main():
    p = print
    t_all = time.perf_counter()
    res = {}
    for seed in SEEDS:
        gen = world.make_mine(seed)
        hist, st = world.history(gen, HISTORY)
        sv = service_view(gen, hist, st)
        rng = np.random.default_rng([seed, 5])
        tw = [w for w in sv["windows"] if w["at_min"] >= SPLIT]
        tb = [b for b in sv["downs"] if b["at_min"] >= SPLIT]
        res[seed] = {"grade": sv["grade"], "cycle": sv["cycle_m"], "fuel": sv["fuel_m"], "plant": sv["plant_m"],
                     "anomaly_history": {r: engine.score_alarms(engine.alarms(sv["anomaly"], tw, r), tb, tw) for r in ("model", "static")},
                     "anomaly": anomaly_eval(gen, sv, st), "dispatch": [dispatch_eval(gen, sv, st, *sc, rng) for sc in SCENARIOS]}
        print(f"seed {seed} done in {time.perf_counter() - t_all:.0f}s", file=sys.stderr, flush=True)
    scale = scale_eval()
    p("# Evaluation\n")
    p(f"Three held-out mines (seeds {', '.join(map(str, SEEDS))}): each a different orebody, shovel panels and fleet. Each runs {HISTORY} shifts of history under "
      f"its legacy dispatch; the models are trained on shifts 0-{TEST_FROM - 1} exactly as the service trains them and scored on shifts {TEST_FROM}-{HISTORY - 1}. "
      "Truth comes from the generator, which the service never reads. `python -m mine.evaluate` reproduces this file.\n")
    p("## Grade estimation (exploration holes only, scored on every block without a hole)\n")
    p("| Mine | Blocks | Kriging RMSE (%Cu) | IDW² RMSE | Nearest hole RMSE | Kriging: class wrong at the cut-offs | IDW² | Nearest | 80% interval coverage | As RMSE ppm (kriging / IDW²) | BWi RMSE (kriging / IDW²) |")
    p("|---|---|---|---|---|---|---|---|---|---|---|")
    for s, r in res.items():
        g = r["grade"]
        p(f"| {s} | {g['gp']['blocks']:,} | {g['gp']['rmse']} | {g['idw']['rmse']} | {g['nearest']['rmse']} | {g['gp']['misclassified']:.1%} | {g['idw']['misclassified']:.1%} | "
          f"{g['nearest']['misclassified']:.1%} | {g['gp']['coverage_80']:.0%} | {g['as_rmse'][0]} / {g['as_rmse'][1]} | {g['bwi_rmse'][0]} / {g['bwi_rmse'][1]} |")
    cov = [r["grade"]["gp"]["coverage_80"] for r in res.values()]
    p("\nA block's class (high grade, low grade, waste at 0.45 and 0.25 %Cu) decides where it is hauled, so the misclassification rate is the number that "
      f"costs money. The 80% interval is the posterior's 10th to 90th percentile; it held {min(cov):.0%}-{max(cov):.0%} of the true grades, so the stated "
      "spread is a little wider than it needs to be on these mines.\n")
    p("## Truck cycle time (blueprint bar: MAPE under 10%)\n")
    p("| Mine | Test cycles | Model MAPE | Physics baseline MAPE | On wet shifts: model | baseline | Fuel model MAPE |\n|---|---|---|---|---|---|---|")
    for s, r in res.items():
        c = r["cycle"]
        p(f"| {s} | {c['test_cycles']:,} | {c['mape_pct']}% | {c['baseline_mape_pct']}% | {c['mape_pct_wet']}% | {c['baseline_mape_pct_wet']}% | {r['fuel']['mape_pct']}% |")
    p("\nThe baseline is the haul profile over the manufacturer's speed-on-grade curve at nominal payload on a dry road, plus nominal loading and dumping: it "
      "knows the geometry exactly and nothing else. The model learns queues (from what the dispatcher saw when it sent the truck), wet roads, payload and "
      "truck age. Most of the remaining error is queueing that had not formed yet when the truck was dispatched.\n")
    p("## Engine anomaly detection\n")
    p("Scored on six further shifts per mine with eight failures told to the generator in each (cooling and oil failures have a precursor; tyres and "
      "electrics do not), because the history's four test shifts hold only a handful. A precursor failure counts as detected when an alarm fires on that "
      "truck in the three hours before it; any other alarm is false.\n")
    p("| Mine | Rule | Detected / precursor failures | Median lead (min) | False alarms | per 1,000 truck-hours |\n|---|---|---|---|---|---|")
    for s, r in res.items():
        for rule, name in (("model", "Per-truck normal, 2 windows > 4 sd"), ("static", "Manufacturer thresholds")):
            a = r["anomaly"][rule]
            p(f"| {s} | {name} | {a['detected']} / {a['precursor_failures']} | {a['median_lead_min'] if a['median_lead_min'] is None else round(a['median_lead_min'])} | {a['false_alarms']} | {a['false_per_1000_truck_hours']} |")
    p("\nOn the history's own test shifts: " + "; ".join(f"mine {s}: model {r['anomaly_history']['model']['detected']}/{r['anomaly_history']['model']['precursor_failures']}, "
                                                    f"{r['anomaly_history']['model']['false_per_1000_truck_hours']} false per 1,000 h, thresholds {r['anomaly_history']['static']['detected']}/"
                                                    f"{r['anomaly_history']['static']['precursor_failures']}, {r['anomaly_history']['static']['false_per_1000_truck_hours']}" for s, r in res.items()) + ".")
    p("The thresholds' false alarms are hot afternoons on hard-working trucks and one-window sensor glitches; the per-truck normal knows the duty and the air "
      "temperature, and the two-window rule ignores glitches. Tyre and electrical failures have no precursor and neither rule sees them coming.\n")
    p("## Mill throughput forecast\n")
    p("| Mine | Test hours | Mean t/h | Forecast MAE (t/h) | Trailing 12-hour mean MAE |\n|---|---|---|---|---|")
    for s, r in res.items():
        q = r["plant"]
        p(f"| {s} | {q['test_hours']} | {q['mean_tph']:,} | {q['mae_tph']} | {q['baseline_mae_tph']} |")
    p("\nOne fitted parameter on top of the mill's hardness curve, fed the estimator's hardness of the bin's blend and what the bin and the feed can supply. Unplanned mill trips "
      "fall in the test hours too, and nothing here forecasts them.\n")
    p("## Dispatch, blend and the economic objective\n")
    p("Each mine runs its next shift three times: a dyke (true grade at 30% over a 45 m radius) ahead of S1 with three breakdowns in the first four hours, the same "
      "ahead of S2, and an undisturbed shift. Four hours in, each method re-plans from the service's estimates (the lab's blast-hole assays have come back), and "
      "the generator plays out the last eight hours under it on the same random draws. Net value: mill value less fuel and rehandle, plus the change in what "
      "the stockpiles and the bin are worth. All differences are against the baseline plan kept.\n")
    names = list(res[SEEDS[0]]["dispatch"][0]["results"])
    p("| Mine | Scenario | Trucks up | " + " | ".join(names) + " |\n|---|---|---|" + "---|" * len(names))
    for s, r in res.items():
        for d in r["dispatch"]:
            ref = d["results"]["baseline plan, kept"]["net_value_usd"]
            cells = [f"${ref / 1e6:.2f}M" if n == "baseline plan, kept" else f"{(d['results'][n]['net_value_usd'] - ref) / 1e3:+,.0f}k" for n in names]
            p(f"| {s} | {d['name']} | {d['up']} | " + " | ".join(cells) + " |")
    allrows = [d for r in res.values() for d in r["dispatch"]]
    disrupted = [d for d in allrows if d["name"] != "no disruption"]

    def stat(rows, a, b="baseline plan, kept", key="net_value_usd"):
        diffs = [d["results"][a][key] - d["results"][b][key] for d in rows]
        return np.mean(diffs), sum(x > 0 for x in diffs), len(diffs)
    p("\n| Over the disrupted shifts (" + str(len(disrupted)) + ") | Net value vs plan kept | Better in | With stockpiled ore at 90% | Copper (t) | Fuel (L) | Tonnes moved | Waste moved (t) | High grade to its stockpile (t) | Hours in the grade window (of 8) | Hours over the As limit |")
    p("|---|---|---|---|---|---|---|---|---|---|---|")
    for n in names:
        nv, k, tot = stat(disrupted, n)
        p(f"| {n} | {nv / 1e3:+,.0f}k | {k} of {tot} | {stat(disrupted, n, key='net_value_sf90')[0] / 1e3:+,.0f}k | {stat(disrupted, n, key='copper_t')[0]:+.1f} | {stat(disrupted, n, key='fuel_l')[0]:+,.0f} | "
          f"{stat(disrupted, n, key='moved_t')[0]:+,.0f} | {stat(disrupted, n, key='waste_t')[0]:+,.0f} | {np.mean([d['results'][n]['to_hg_pile_t'] for d in disrupted]):,.0f} | "
          f"{np.mean([d['results'][n]['hours_in_window'] for d in disrupted]):.1f} | {np.mean([d['results'][n]['as_over'] for d in disrupted]):.1f} |")
    nv, k, tot = stat(disrupted, "MIP + robust blend", "heuristic re-plan")
    nv2, k2, tot2 = stat(disrupted, "MIP + robust blend", "nearest free shovel")
    calm = [d for d in allrows if d["name"] == "no disruption"]
    nv3, k3, tot3 = stat(calm, "MIP + robust blend")
    p(f"\nAgainst the strongest baselines: the MIP with the robust blend beats the heuristic re-plan by {nv / 1e3:+,.0f}k a shift on average (better in {k} of {tot}) "
      f"and nearest-free-shovel dispatch by {nv2 / 1e3:+,.0f}k (better in {k2} of {tot2}). On the undisturbed shifts it changes the plan kept by {nv3 / 1e3:+,.0f}k "
      f"(better in {k3} of {tot3}).")
    dev = {n: np.mean([d["results"][n]["dev"] for d in allrows]) for n in ("MIP + robust blend", "MIP + mean-only blend", "MIP, proportional reclaim", "baseline plan, kept")}
    p(f"Blend assay deviation (mean |hourly mill feed − {world.TARGET_CU} %Cu|, tolerance {world.TOL_CU}): " + ", ".join(f"{n} {v:.3f}" for n, v in dev.items()) + ".")
    tw = [(d["twin_net_diff"], d["true_net_diff"]) for d in allrows]
    p("The twin's paired prediction of the MIP plan against the plan kept, next to what the generator then did: " + ", ".join(f"{a / 1e3:+,.0f}k vs {b / 1e3:+,.0f}k" for a, b in tw) + ".\n")
    p("## Dispatch solve time (blueprint bar: under 10 s for 200 vehicles)\n")
    p("| Shovels | Trucks | Formulation | Variables | Constraints | Solve (median of 3) | Worst | Optimality gap |\n|---|---|---|---|---|---|---|---|")
    for x in scale:
        p(f"| {x['shovels']} | {x['trucks']} | {'one group per truck' if x['per_truck'] else 'trucks counted per current shovel'} | {x['variables']:,} | {x['constraints']:,} | "
          f"{x['solve_ms'] / 1000:.2f} s | {x['max_ms'] / 1000:.2f} s | {x['gap']:.2%} |")
    p("\nSCIP through OR-Tools on the machine in docs/performance.md, the shovels' inputs replicated from a real mine's with their travel times perturbed. "
      "Trucks on the same shovel are interchangeable, so counting them is exact; the per-truck formulation is the same problem with 200 times the integer "
      f"variables, shown for what it costs. Evaluation run time {time.perf_counter() - t_all:.0f} s.\n")
    return res


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
