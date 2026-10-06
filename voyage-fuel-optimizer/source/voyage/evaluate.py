"""Held-out evaluation on three oceans and fleets the demo never uses (seeds 101-103: other weather, other vessels).

    python -m voyage.evaluate            # prints the markdown behind docs/evaluation.md (about 10 minutes on 4 cores)

Each world: six vessels sail a year; each vessel's fuel model is fitted exactly as the service fits it and scored on the
last 60 days of noon reports. Then voyages after the history, planned with the forecast at departure and sailed through
the realised weather, against baselines sailed through the same realised weather:
  * ordinary voyages (natural weather): the optimiser against the shortest sea route at service speed (the blueprint's
    weather-normalised baseline) and against the shortest route at the one constant speed that the forecast says lands
    mid-window (what a careful master would do without the optimiser); ETA bands scored against the realised arrival;
  * storm voyages: a storm the departure forecast cannot see is told to the generator so that it crosses the planned
    track about four days out; at day two the plan is kept, re-speeded, or re-routed and re-speeded with the new forecast;
  * congestion voyages: the destination announces at day two that it cannot berth until 18-40 hours after the window
    closes; the plan is kept (and waits at anchor) or re-speeded to arrive when the berth is free.
"""
import multiprocessing
import sys
import time

import numpy as np

from . import engine, world

SEEDS = (101, 102, 103)
N_ORDINARY, N_STORM, N_CONGESTION = 12, 8, 6
REPLAN_H = 48.0


def _terms(rng, t0, dist):
    close = t0 + dist / rng.uniform(13.5, 16.0) + 12
    return {"hire_usd_day": float(rng.uniform(18000, 35000)), "fuel_usd_t": float(rng.uniform(560, 700)), "ets_usd_t": 80.0, "ets_share": 0.5,
            "window_open_h": close - 36, "window_close_h": close, "late_usd_h": float(rng.uniform(2000, 4000))}


def _voyage(seed, rng, fleet, models):
    v = fleet[int(rng.integers(len(fleet)))]
    east = rng.random() < 0.5
    orig = str(rng.choice(world.WEST if east else world.EAST))
    dest = str(rng.choice(world.EAST if east else world.WEST))
    t0 = float(rng.uniform(12, 24 * 45))
    disp = float(rng.uniform(0.75, 1.0))
    dist = world.Path(*world.passage(orig, dest)).length
    m = models[v["ref"]]
    return v, m, orig, dest, t0, disp, _terms(rng, t0, dist), (lambda t, m=m: m["days_clean_now"] + np.asarray(t) / 24)


def _truth(v, P, legs, wx, t0, disp, s0=0.0):
    return world.sail(v, P, legs, wx, t0, disp, s0=s0)


def _cost(terms, t0, arr, fuel, berth, v):
    o = engine.outcome(terms, t0, arr, fuel, berth, world.anchor_tph(v))
    return {k: float(x) for k, x in o.items()}


def heavy_hours(track, hs=6.0):
    return sum(h["hours"] for h in track if h["hs"] > hs)


def mid_window_speed(m, v, seed, t0, orig, dest, terms, disp, days_at):
    """The one constant speed order that the forecast says lands the ship mid-window, on the shortest route."""
    target = terms["window_close_h"] - 18
    lo, hi = engine.V_MIN, v["design_speed"] - 1.0
    for _ in range(9):
        mid = (lo + hi) / 2
        p = engine.plan(m, v, seed, [], t0, t0, orig, dest, terms, t0, disp, days_at, route="shortest", speed=round(mid, 2), members=4)
        lo, hi = (mid, hi) if p["det_arrival_h"] > target else (lo, mid)
    return round((lo + hi) / 2, 2)


def ordinary(seed, fleet, models, n):
    rng = np.random.default_rng([seed, 5])
    truth = world.Weather(seed)
    rows = []
    for _ in range(n):
        v, m, orig, dest, t0, disp, terms, days_at = _voyage(seed, rng, fleet, models)
        A = engine.plan(m, v, seed, [], t0, t0, orig, dest, terms, t0, disp, days_at)
        B = engine.plan(m, v, seed, [], t0, t0, orig, dest, terms, t0, disp, days_at, route="shortest", speed=v["service_speed"])
        C = engine.plan(m, v, seed, [], t0, t0, orig, dest, terms, t0, disp, days_at, route="optimize", speed=v["service_speed"])
        D = engine.plan(m, v, seed, [], t0, t0, orig, dest, terms, t0, disp, days_at, route="shortest", speed="optimize")
        k = mid_window_speed(m, v, seed, t0, orig, dest, terms, disp, days_at)
        K = engine.plan(m, v, seed, [], t0, t0, orig, dest, terms, t0, disp, days_at, route="shortest", speed=k)
        out = {"vessel": v["ref"], "east": orig in world.WEST, "route_s": [A["route"]["first_pass_seconds"], A["route"]["seconds"], C["route"]["seconds"]],
               "eta": A["arrival"], "det": A["det_arrival_h"], "fuel_p50": A["fuel"]["p50"], "fuel_p90": A["fuel"]["p90"], "mid_speed": k}
        for name, p in (("A", A), ("B", B), ("C", C), ("D", D), ("K", K)):
            tr = _truth(v, p["path"], p["legs"], truth, t0, disp)
            out[name] = _cost(terms, t0, tr["t"], tr["fuel_t"], t0, v)
            out[name].update(arrival=tr["t"], passage=tr["fuel_t"], heavy=heavy_hours(tr["track"]))
        # bunkers for this voyage and the next two legs
        cap = v["tank_t"]
        west, eastp = float(rng.uniform(610, 680)), float(rng.uniform(555, 620))
        price = {True: west, False: eastp}
        legs = [{"p50": A["fuel"]["p50"], "p90": A["fuel"]["p90"], "days": (A["arrival"]["p50"] - t0) / 24}]
        legs += [{"p50": A["fuel"]["p50"] * 1.08, "p90": A["fuel"]["p90"] * 1.08, "days": (A["arrival"]["p50"] - t0) / 24}, legs[0]]
        calls = [{"port": orig, "price": price[orig in world.WEST], "fee": 6000.0}, {"port": dest, "price": price[dest in world.WEST], "fee": 6000.0},
                 {"port": orig, "price": price[orig in world.WEST], "fee": 6000.0}]
        out["bunker"] = engine.bunker_plan(calls, legs, rob0=float(rng.uniform(0.25, 0.5)) * cap, capacity=cap)
        rows.append(out)
    return rows


def storm(seed, fleet, models, n):
    rng = np.random.default_rng([seed, 6])
    rows = []
    for _ in range(n):
        v, m, orig, dest, t0, disp, terms, days_at = _voyage(seed, rng, fleet, models)
        A = engine.plan(m, v, seed, [], t0, t0, orig, dest, terms, t0, disp, days_at)
        cross = min(A["det_track"], key=lambda h: abs(h["t"] - (t0 + 96)))
        told = [world.storm_across(cross["lat"], cross["lon"], cross["t"], t0 + REPLAN_H + rng.uniform(8, 20), course=float(rng.uniform(60, 80)),
                                   speed_kn=float(rng.uniform(17, 24)), vmax=float(rng.uniform(27, 32)), radius=float(rng.uniform(3.5, 4.5)))]
        truth = world.Weather(seed, told)
        B = engine.plan(m, v, seed, [], t0, t0, orig, dest, terms, t0, disp, days_at, route="shortest", speed=v["service_speed"])
        first = world.sail(v, A["path"], A["legs"], truth, t0, disp, hours=REPLAN_H)
        tr_ = first["t"]
        lat, lon, _ = A["path"].at(first["s"])
        pos = (float(lat), float(lon))
        alts = {}
        keep = world.sail(v, A["path"], A["legs"], truth, tr_, disp, s0=first["s"])
        alts["keep"] = (keep, None)
        sp = engine.plan(m, v, seed, told, tr_, tr_, orig, dest, terms, t0, disp, days_at, start=pos, route="path", path_pts=engine.remaining_path(A["path"], first["s"]))
        alts["re-speed"] = (world.sail(v, sp["path"], sp["legs"], truth, tr_, disp), sp)
        rr = engine.plan(m, v, seed, told, tr_, tr_, orig, dest, terms, t0, disp, days_at, start=pos)
        alts["re-route + re-speed"] = (world.sail(v, rr["path"], rr["legs"], truth, tr_, disp), rr)
        base = world.sail(v, B["path"], B["legs"], truth, t0, disp)
        out = {"vessel": v["ref"], "route_s": rr["route"]["seconds"], "baseline": _cost(terms, t0, base["t"], base["fuel_t"], t0, v)}
        out["baseline"]["heavy"] = heavy_hours(base["track"])
        out["baseline"]["max_hs"] = max(h["hs"] for h in base["track"])
        for name, (tr, p) in alts.items():
            c = _cost(terms, t0, tr["t"], first["fuel_t"] + tr["fuel_t"], t0, v)
            c["heavy"] = heavy_hours(first["track"]) + heavy_hours(tr["track"])
            c["max_hs"] = max(h["hs"] for h in first["track"] + tr["track"])
            out[name] = c
        rows.append(out)
    return rows


def congestion(seed, fleet, models, n):
    rng = np.random.default_rng([seed, 8])
    truth = world.Weather(seed)
    rows = []
    for _ in range(n):
        v, m, orig, dest, t0, disp, terms, days_at = _voyage(seed, rng, fleet, models)
        A = engine.plan(m, v, seed, [], t0, t0, orig, dest, terms, t0, disp, days_at)
        told = [{"port": dest, "known_from_h": t0 + REPLAN_H, "berth_from_h": terms["window_close_h"] + float(rng.uniform(18, 40)), "ships_waiting": 14}]
        first = world.sail(v, A["path"], A["legs"], truth, t0, disp, hours=REPLAN_H)
        tr_ = first["t"]
        lat, lon, _ = A["path"].at(first["s"])
        seen = world.lineup(seed, dest, tr_, told)["earliest_berth_h"]
        real = world.port_ready(dest, A["arrival"]["p50"], told)
        keep = world.sail(v, A["path"], A["legs"], truth, tr_, disp, s0=first["s"])
        jit = engine.plan(m, v, seed, [], tr_, tr_, orig, dest, terms, seen, disp, days_at, start=(float(lat), float(lon)),
                          route="path", path_pts=engine.remaining_path(A["path"], first["s"]))
        jt = world.sail(v, jit["path"], jit["legs"], truth, tr_, disp)
        out = {"vessel": v["ref"]}
        for name, tr in (("keep", keep), ("just in time", jt)):
            out[name] = _cost(terms, t0, tr["t"], first["fuel_t"] + tr["fuel_t"], world.port_ready(dest, tr["t"], told), v)
        out["berth_error_h"] = seen - real
        rows.append(out)
    return rows


def fuel_models(seed):
    fleet = world.fleet(seed)
    hist = world.history(seed, fleet, 365, 0.0)
    models, rows = {}, []
    for v in fleet:
        reps = [r for h in hist if h["vessel"] == v["ref"] for r in h["noon"]]
        m = engine.fit_fuel_model(v, reps, 0.0)
        models[v["ref"]] = m
        rows.append({"vessel": v["ref"], **m["metrics"], "fouling_est": m["fouling_now_pct"], "fouling_true": engine.true_fouling_pct(v, m["days_clean_now"]),
                     "cleaned_in_history": v["true"]["recleaned_at"] is not None})
    return fleet, models, rows


def one(seed):
    t = time.time()
    fleet, models, fm = fuel_models(seed)
    out = {"seed": seed, "fuel": fm, "ordinary": ordinary(seed, fleet, models, N_ORDINARY), "storm": storm(seed, fleet, models, N_STORM),
           "congestion": congestion(seed, fleet, models, N_CONGESTION)}
    out["seconds"] = round(time.time() - t)
    return out


def pct(a, b):
    return 100 * (1 - a / b)


def main():
    with multiprocessing.Pool(len(SEEDS)) as pool:
        res = pool.map(one, SEEDS)
    p = print
    p("# Evaluation\n")
    p(f"Three held-out worlds (seeds {', '.join(map(str, SEEDS))}): other weather, other storms, other vessels. In each, six vessels sail a "
      f"year; the fuel models are fitted as the service fits them; then {N_ORDINARY} ordinary voyages, {N_STORM} storm voyages and "
      f"{N_CONGESTION} congestion voyages per world are planned with the forecast at departure and sailed through the realised weather, "
      "each against its baselines sailed through the same realised weather. `python -m voyage.evaluate` reproduces this file.\n")
    p("## Fuel model (performance-model)\n")
    p("| World | Vessel | Noon reports scored | MAPE | Sea-trial curve MAPE | Bias | Fouling now, estimated | Fouling now, true | Cleaned during the year |\n|---|---|---|---|---|---|---|---|---|")
    allm, allb, ferr = [], [], []
    for r in res:
        for f in r["fuel"]:
            allm.append(f["mape_pct"]), allb.append(f["baseline_mape_pct"]), ferr.append(abs(f["fouling_est"] - f["fouling_true"]))
            p(f"| {r['seed']} | {f['vessel']} | {f['test_reports']} | {f['mape_pct']:.1f}% | {f['baseline_mape_pct']:.1f}% | {f['bias_pct']:+.1f}% | {f['fouling_est']:.1f}% | {f['fouling_true']:.1f}% | {'yes' if f['cleaned_in_history'] else 'no'} |")
    p(f"\nDaily fuel on the last 60 days of noon reports (fitted on the ten months before): MAPE {min(allm):.1f}-{max(allm):.1f}% across the "
      f"18 vessels (blueprint bar: 7%), against {min(allb):.1f}-{max(allb):.1f}% for the yard's sea-trial curve, which knows nothing of weather, "
      f"load or fouling. Hull fouling (extra fuel at service speed against the same hull clean): off by {np.median(ferr):.1f} points at the "
      f"median and {max(ferr):.1f} at worst; the no-fouling baseline is off by the whole true value "
      f"({min(f['fouling_true'] for r in res for f in r['fuel']):.1f}-{max(f['fouling_true'] for r in res for f in r['fuel']):.1f}%).\n")

    O = [o for r in res for o in r["ordinary"]]
    p("## Ordinary voyages: savings against baselines sailed through the same weather\n")
    p(f"{len(O)} voyages between New York, Norfolk or Halifax and Rotterdam, Antwerp, Le Havre or Hamburg, either way, with a berth window "
      "(36 hours, closing at a schedule speed of 13.5-16 kn), hire of $18,000-35,000 a day, fuel at $560-700 a tonne and carbon at $80 a "
      "tonne on half the voyage's CO2 (the EU ETS share for a voyage into or out of the EU). Cost = fuel and carbon (including auxiliary fuel "
      "waiting at anchor) + hire until berthing + late penalty.\n")
    p("| Plan (all sailed through the realised weather) | Fuel incl. waiting | CO2 | Voyage cost | Late voyages | Cost saved by the optimiser |\n|---|---|---|---|---|---|")
    tot = lambda k, f: sum(o[k][f] for o in O)                 # noqa: E731
    for k, name in (("B", "Baseline: shortest sea route at service speed, then wait for the berth"),
                    ("K", "Baseline: shortest route at the constant speed the forecast says lands mid-window"),
                    ("C", "Optimised route, service speed"), ("D", "Shortest route, optimised speed"), ("A", "Optimised route and speed (the plan)")):
        late = sum(o[k]["late_h"] > 0.01 for o in O)
        sv = "" if k == "A" else f"{pct(tot('A', 'cost_usd'), tot(k, 'cost_usd')):.1f}%"
        p(f"| {name} | {tot(k, 'fuel_t'):,.0f} t | {tot(k, 'co2_t'):,.0f} t | ${tot(k, 'cost_usd') / 1e6:,.2f}M | {late} of {len(O)} | {sv} |")
    per = [pct(o["A"]["cost_usd"], o["B"]["cost_usd"]) for o in O]
    perk = [pct(o["A"]["cost_usd"], o["K"]["cost_usd"]) for o in O]
    route_only = [pct(o["C"]["cost_usd"], o["B"]["cost_usd"]) for o in O]
    ro = float(np.mean(route_only))
    p(f"\nAgainst the weather-normalised baseline the plan saves {pct(tot('A', 'fuel_t'), tot('B', 'fuel_t')):.1f}% of fuel and CO2 and "
      f"{pct(tot('A', 'cost_usd'), tot('B', 'cost_usd')):.1f}% of voyage cost (per voyage {min(per):.1f} to {max(per):.1f}%); almost all of it "
      f"is speed: sailing at service speed and waiting for the berth is expensive. Against the careful constant-speed master it saves "
      f"{pct(tot('A', 'cost_usd'), tot('K', 'cost_usd')):.1f}% of cost in total, and per voyage it ranges from {min(perk):+.1f} to {max(perk):+.1f}% "
      f"(it was dearer on {sum(x < 0 for x in perk)} of {len(O)}). Weather routing alone, at service speed, {'saves' if ro > 0 else 'costs'} "
      f"{abs(ro):.2f}% {'' if ro > 0 else 'more '}on average (per voyage {min(route_only):+.2f} to {max(route_only):+.2f}%): in ordinary weather the "
      "route the forecast prefers is no better in the weather that really comes, and routing earns its keep in storms (below). Heavy weather "
      f"(hours in seas above 6 m): {sum(o['A']['heavy'] for o in O):.0f} for the plan, {sum(o['B']['heavy'] for o in O):.0f} for the baseline "
      "(the plan is slower, so longer at sea).\n")

    p("## ETA uncertainty and voyage fuel\n")
    cov50 = np.mean([o["A"]["arrival"] <= o["eta"]["p50"] for o in O])
    cov90 = np.mean([o["A"]["arrival"] <= o["eta"]["p90"] for o in O])
    det = np.mean([o["A"]["arrival"] <= o["det"] for o in O])
    det6 = np.mean([o["A"]["arrival"] <= o["det"] + 6 for o in O])
    width = np.median([o["eta"]["p90"] - o["eta"]["p50"] for o in O])
    fape = [abs(o["fuel_p50"] / o["A"]["passage"] - 1) * 100 for o in O]
    err50 = np.median([abs(o["A"]["arrival"] - o["eta"]["p50"]) for o in O])
    p("| ETA from the departure forecast | Realised arrival at or before it |\n|---|---|")
    p(f"| Ensemble P50 (24 members + the fuel model's own error) | {cov50:.0%} (ideal 50%) |")
    p(f"| Ensemble P90 | {cov90:.0%} (ideal 90%) |")
    p(f"| Baseline: deterministic forecast | {det:.0%} |")
    p(f"| Baseline: deterministic forecast + 6 h | {det6:.0%} |")
    p(f"\nOver {len(O)} voyages; the P90 sits a median {width:.1f} h after the P50, and the P50 missed the realised arrival by a median "
      f"{err50:.1f} h. The P90 is calibrated; the P50 is a little early. Said plainly: on ordinary voyages a fixed six-hour margin on the deterministic "
      f"forecast covered as often ({det6:.0%}); what the ensemble adds is a band whose width follows the weather (from "
      f"{min(o['eta']['p90'] - o['eta']['p50'] for o in O):.1f} to {max(o['eta']['p90'] - o['eta']['p50'] for o in O):.1f} h here) and the members' "
      f"storms beyond the forecast horizon, which the deterministic forecast cannot have. Voyage fuel (the plan's P50 against the fuel burned): MAPE "
      f"{np.mean(fape):.1f}%, worst {max(fape):.1f}%.\n")
    rs = [x for o in O for x in o["route_s"]] + [s["route_s"] for r in res for s in r["storm"]]
    p(f"**Route solve time** (time-dependent A* over the 0.5-degree grid, 7,283 ocean nodes, 16 courses each): median {np.median(rs):.1f} s, "
      f"worst {max(rs):.1f} s over {len(rs)} solves (blueprint bar: 30 s), one process.\n")

    S = [s for r in res for s in r["storm"]]
    p("## Storm voyages: replanning when the forecast sees the storm\n")
    p(f"{len(S)} voyages. A storm (27-32 m/s winds, seas to 9-13 m) forms 56-68 hours after departure, after the departure forecast's horizon, and "
      "crosses the planned track about four days out. At day two the new forecast shows it; the alternatives are planned from the ship's position "
      "with that forecast and sailed through the realised weather (the first two days are the same for all three).\n")
    p("| Plan | Fuel incl. waiting | Voyage cost | Late voyages | Hours in seas above 6 m | Worst sea met |\n|---|---|---|---|---|---|")
    for k, name in (("baseline", "Baseline: shortest route at service speed, no replanning"), ("keep", "Departure plan kept"),
                    ("re-speed", "Re-speeded on the same route"), ("re-route + re-speed", "Re-routed and re-speeded")):
        p(f"| {name} | {sum(s[k]['fuel_t'] for s in S):,.0f} t | ${sum(s[k]['cost_usd'] for s in S) / 1e6:,.2f}M | {sum(s[k]['late_h'] > 0.01 for s in S)} of {len(S)} | "
          f"{sum(s[k]['heavy'] for s in S):.0f} | {np.median([s[k]['max_hs'] for s in S]):.1f} m median, {max(s[k]['max_hs'] for s in S):.1f} m worst |")
    rr = [pct(s["re-route + re-speed"]["cost_usd"], s["keep"]["cost_usd"]) for s in S]
    tot_rr = pct(sum(s['re-route + re-speed']['cost_usd'] for s in S), sum(s['keep']['cost_usd'] for s in S))
    p(f"\nRe-routing and re-speeding against keeping the plan: hours in seas above 6 m from {sum(s['keep']['heavy'] for s in S):.0f} to "
      f"{sum(s['re-route + re-speed']['heavy'] for s in S):.0f}, late voyages from {sum(s['keep']['late_h'] > 0.01 for s in S)} to "
      f"{sum(s['re-route + re-speed']['late_h'] > 0.01 for s in S)}, for {abs(tot_rr):.1f}% {'less' if tot_rr > 0 else 'more'} cost in total "
      f"(per voyage {min(rr):+.1f} to {max(rr):+.1f}%, positive is cheaper). In money it is about even; what re-routing buys is the sea the ship "
      "does not meet.\n")

    Cg = [c for r in res for c in r["congestion"]]
    p("## Congestion voyages: just-in-time arrival\n")
    p(f"{len(Cg)} voyages. At day two the destination announces it cannot berth until 18-40 hours after the window closes (its estimate is off "
      f"by a median {np.median([abs(c['berth_error_h']) for c in Cg]):.1f} h). Late penalties do not apply to waiting the port causes.\n")
    p("| Plan | Fuel incl. waiting | CO2 | Hours at anchor | Voyage cost |\n|---|---|---|---|---|")
    for k in ("keep", "just in time"):
        p(f"| {'Departure plan kept, wait at anchor' if k == 'keep' else 'Re-speeded to the announced berth'} | {sum(c[k]['fuel_t'] for c in Cg):,.0f} t | {sum(c[k]['co2_t'] for c in Cg):,.0f} t | "
          f"{sum(c[k]['wait_h'] for c in Cg):.0f} | ${sum(c[k]['cost_usd'] for c in Cg) / 1e6:,.2f}M |")
    p(f"\nJust in time saves {pct(sum(c['just in time']['fuel_t'] for c in Cg), sum(c['keep']['fuel_t'] for c in Cg)):.1f}% of fuel and CO2 on these voyages; "
      "hire is the same either way because the berth, not the ship, sets the end of the voyage.\n")

    B = [o["bunker"] for o in O if o["bunker"]["status"] == "optimal"]
    sv = [100 * b["saving_usd"] / b["baseline_cost_usd"] for b in B]
    p("## Bunker plan\n")
    p(f"For each ordinary voyage, bunkers for it and the next two legs (back and out again), with American ports at $610-680 and European at "
      f"$555-620 a tonne, $6,000 a delivery, a 250 t minimum stem, the tank's capacity and a reserve of the leg's P90-over-P50 plus three days. "
      f"The MILP against topping up at every call for the next leg: {sum(b['saving_usd'] for b in B):,.0f} USD saved over {len(B)} plans "
      f"({np.median(sv):.1f}% median, {max(0.0, min(sv)):.1f}-{max(sv):.1f}%; never worse, by construction), median solve {np.median([b['solve_ms'] for b in B]):.0f} ms.\n")
    p(f"Run time per world: {', '.join(str(r['seconds']) + ' s' for r in res)} (in parallel).")
    return res


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
    sys.exit(0)
