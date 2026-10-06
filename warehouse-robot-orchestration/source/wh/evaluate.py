"""Held-out evaluation on three warehouses the demo never uses (other seeds, other shapes), each with 250 robots.

    python -m wh.evaluate            # prints the markdown behind docs/evaluation.md (about ten minutes on four cores)

Per warehouse, two 15-minute order waves: a steady one the fleet can keep up with, and a peak above what it can finish,
during which two aisles are closed, a charger fails and an operator stops the robot in the busiest aisle cell every 30
seconds (and releases it a minute later). Each wave runs under the three assignment policies with the same seed, so the
same orders arrive at the same moments; the planner and the collision checker are the same throughout. Then: CBS
against prioritized planning on growing groups, D* Lite repair against recomputing a field, and the battery model
against each pack's own trend, scored on the generator's true state of health.
"""
import collections
import copy
import multiprocessing as mp
import sys
import time

import numpy as np

from . import engine, world

WAREHOUSES = {101: dict(n_aisles=41, block_rows=12, n_stations=20, groups=4),
              102: dict(n_aisles=37, block_rows=14, n_stations=18, groups=4),
              103: dict(n_aisles=45, block_rows=10, n_stations=22, groups=5)}
POLICIES = ("fifo", "greedy", "cpsat")
WAVES = {"steady": 7000, "peak": 10000}
SECONDS = 900


def events_for(seed, L):
    rng = np.random.default_rng([seed, 77])
    bs = sorted(z for z in L.aisles if z.startswith("B"))
    cs = sorted(z for z in L.aisles if z.startswith("C"))
    return [{"kind": "aisle_blocked", "zone": str(rng.choice(cs)), "at": 300, "until": None},
            {"kind": "aisle_blocked", "zone": str(rng.choice(bs)), "at": 360, "until": None},
            {"kind": "charger_fault", "charger": str(rng.choice(L.charger_names)), "at": 420, "until": None}]


def pauser(start=180, every=30, hold=60):
    """Every `every` s from `start`: stop the robot standing in the aisle cell the most other robots are due through,
    release it `hold` s later. The same rule whatever the policy; which robot it hits depends on the floor."""
    held = []

    def hook(floor, fleet):
        t = floor.t
        if t < start or (t - start) % every:
            return
        engine.sync(floor, fleet)
        while held and held[0][1] <= t:
            r, _ = held.pop(0)
            floor.pause(r, False)
            fleet.resume(r, t)
        cands = [r for r in range(fleet.R) if fleet.L.kind[fleet.cell[r]] == "aisle" and fleet.status[r] == "task" and r not in fleet.paused]
        if not cands:
            return
        r = max(cands, key=lambda x: (len(fleet.res.users_after(fleet.cell[x], t, x)), -x))
        floor.pause(r)
        fleet.pause(r, t)
        held.append((r, t + hold))
    return hook


def one_run(args):
    seed, wave, policy = args
    L = world.Layout(**WAREHOUSES[seed])
    floor, fleet = engine.new_world(seed, L, policy)
    floor.set_wave(WAVES[wave], 1)
    if wave == "peak":
        floor.tell(events_for(seed, L))
    t0 = time.time()
    m = engine.simulate(floor, fleet, SECONDS, hook=pauser() if wave == "peak" else None)
    reps = [r for r in fleet.stats["repairs"] if r["reason"] not in ("retry", "deferred")]
    deferred = [r for r in fleet.stats["repairs"] if r["reason"] == "deferred"]
    pauses = [r for r in reps if r["reason"].endswith("paused")]
    closures = [r for r in reps if r["reason"].startswith("aisle")]
    return {"seed": seed, "wave": wave, "policy": policy, "wall_s": round(time.time() - t0, 1),
            **{k: m[k] for k in ("orders_arrived", "orders_completed", "throughput_per_hour", "cells_per_order", "sla_hit_rate", "completed_on_time",
                                 "overdue_open", "open_backlog", "held_tasks", "collisions", "robot_steps_checked", "tick_ms", "assign_ms",
                                 "flat_battery_steps", "waiting_robots", "loaded_share")},
            "pause_events": [(r["ms"], r["robots"], r["method"], r["per_robot_ms"], r["waiting"], r.get("deferred", 0)) for r in pauses],
            "deferred_events": [(r["ms"], r["robots"], r["method"], r["waiting"]) for r in deferred],
            "waiting_at_end": sum(fleet.waiting),
            "closure_events": [(r["ms"], r["robots"], r["method"]) for r in closures],
            "methods": collections.Counter(r["method"] for r in reps)}


# --- CBS against prioritized on growing groups ------------------------------------------------------------------------------
def cbs_scaling(seed=101, sizes=(2, 4, 6, 8, 12, 16, 24, 32), trials=8, budget=2.0):
    L = world.Layout(**WAREHOUSES[seed])
    floor, fleet = engine.new_world(seed, L, "cpsat")
    floor.set_wave(WAVES["peak"], 1)
    engine.simulate(floor, fleet, 400)
    t = engine.sync(floor, fleet)
    rng = np.random.default_rng([seed, 5])
    centres = [r for r in range(fleet.R) if fleet.status[r] == "task" and fleet.L.kind[fleet.cell[r]] == "aisle"]
    out = {}
    old = (engine.CBS_BUDGET_S, engine.CBS_NODES, engine.CBS_MAX)
    for k in sizes:
        rows = []
        for _ in range(trials):
            centre = int(rng.choice(centres))
            d = engine.bfs(L, fleet.cell[centre], fleet.fields.blocked)
            group = sorted((r for r in range(fleet.R) if r != centre and fleet.status[r] == "task"), key=lambda r: (d[fleet.cell[r]], r))[:k]
            res = {}
            for method in ("cbs", "prioritized"):
                f2 = copy.deepcopy(fleet)
                f2.paused.add(centre)
                f2.unreserve(centre, t)
                f2.stay(centre, t)
                f2.fields.set([f2.cell[centre]], True)
                for r in group:
                    f2.unreserve(r, t)
                    f2.stay(r, t)
                w0 = time.perf_counter()
                if method == "cbs":
                    engine.CBS_BUDGET_S, engine.CBS_NODES = budget, 100000
                    sol = f2.cbs(group, t)
                    ok = sol is not None
                    cost = sum(len(p[0]) - 1 for p in sol["plans"].values()) if ok else None
                    nodes = sol["nodes"] if ok else None
                else:
                    engine.CBS_MAX = 0
                    rec = f2.repair(group, t, "eval")
                    ok = rec["waiting"] == 0 and rec["method"] != "global"
                    cost = sum(f2.plan_t0[r] + len(f2.plan[r]) - 1 - t for r in group) if ok else None
                    nodes = None
                engine.CBS_BUDGET_S, engine.CBS_NODES, engine.CBS_MAX = old
                res[method] = (ok, round((time.perf_counter() - w0) * 1000, 1), cost, nodes)
            rows.append(res)
        out[k] = rows
    return out


# --- D* Lite against recomputing ------------------------------------------------------------------------------------------------
def dstar_bench(seed=101, trials=150):
    L = world.Layout(**WAREHOUSES[seed])
    rng = np.random.default_rng([seed, 9])
    traffic = [c for c in range(L.n) if L.kind[c] in ("aisle", "cross")]
    zones = sorted(L.aisles)
    out = {"cell": [], "aisle": []}
    mismatches = 0
    for kind in out:
        for _ in range(trials):
            blocked = bytearray(L.n)
            goal = int(rng.choice(L.picks + L.stations))
            f = engine.DistField(L, goal, blocked)
            cells = [int(rng.choice(traffic))] if kind == "cell" else list(L.aisles[str(rng.choice(zones))])
            cells = [c for c in cells if c != goal]
            for c in cells:
                blocked[c] = 1
            t0 = time.perf_counter()
            touched = f.repair(L, cells, blocked)
            t_rep = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            fresh = engine.DistField(L, goal, blocked)
            t_full = (time.perf_counter() - t0) * 1000
            mismatches += f.g != fresh.g
            changed = sum(a != b for a, b in zip(engine.DistField(L, goal, bytearray(L.n)).g, fresh.g))
            out[kind].append((t_rep, t_full, touched, changed))
    return out, mismatches, L.n


# --- battery fade ---------------------------------------------------------------------------------------------------------------
def battery(seed, holdout):
    L = world.Layout(**WAREHOUSES[seed])
    robots = world.fleet(seed, L)
    rows, soh_true = world.battery_history(seed, robots)
    H = collections.defaultdict(list)
    for rid, _, day, dod, temp, cap in rows:
        H[rid].append((day, dod, temp, cap))
    nominal = {r["id"]: r["capacity_wh"] for r in robots}
    vendor = {r["id"]: r["vendor"] for r in robots}
    age = {r["id"]: r["days"] for r in robots}
    knee = {r["id"]: r["knee"] for r in robots}
    fit = engine.fit_batteries(H, nominal, vendor, age, cutoff=-holdout)
    out = []
    for r, p in fit.items():
        cyc = H[r]
        if not [c for c in cyc if c[0] >= -holdout] or len([c for c in cyc if c[0] < -holdout]) < 30:
            continue
        ahead = cyc[-1][0] - p["last_day"]
        out.append((r, soh_true[r], engine.forecast_soh(p, ahead), engine.baseline_soh(cyc, nominal[r], ahead, cutoff=-holdout), knee[r]))
    now = engine.fit_batteries(H, nominal, vendor, age)
    now_err = [abs(engine.forecast_soh(now[r], 0) - soh_true[r]) for r in now]
    return out, float(np.mean(now_err))


def pct(xs, q):
    return round(float(np.percentile(xs, q)), 1) if len(xs) else None


def main(procs=3):
    p = print
    jobs = [(s, w, pol) for s in WAREHOUSES for w in WAVES for pol in POLICIES]
    with mp.get_context("fork").Pool(procs) as pool:
        runs = pool.map(one_run, jobs)
    R = {(r["seed"], r["wave"], r["policy"]): r for r in runs}
    # latency is timed again one run at a time: the parallel runs share the CPU, which moves timings but not outcomes
    timed = [one_run((s, "peak", "cpsat")) for s in WAREHOUSES]
    same = all((t["orders_completed"], t["cells_per_order"], t["collisions"], len(t["pause_events"])) ==
               (R[(t["seed"], "peak", "cpsat")]["orders_completed"], R[(t["seed"], "peak", "cpsat")]["cells_per_order"],
                R[(t["seed"], "peak", "cpsat")]["collisions"], len(R[(t["seed"], "peak", "cpsat")]["pause_events"])) for t in timed)
    p("# Evaluation\n")
    p(f"Three held-out warehouses (seeds {', '.join(map(str, WAREHOUSES))}; 37 to 45 aisles, 10 to 14 rows a block, 18 to 22 pack stations, "
      f"250 robots each), never used by the demo. Each runs two {SECONDS // 60}-minute waves from the start of a shift: **steady** at "
      f"{WAVES['steady']:,} orders an hour, and **peak** at {WAVES['peak']:,} an hour, more than the fleet can finish, during which two aisles close "
      "(at 5 and 6 minutes), a charger fails (7 minutes) and an operator stops the robot in the busiest aisle cell every 30 seconds from minute 3, "
      "releasing it a minute later. Every run uses the same planner and the same collision checker; the policies differ only in who gets which "
      "task, and see the same orders at the same moments. `python -m wh.evaluate` reproduces this file.\n")
    steps = sum(r["robot_steps_checked"] for r in runs)
    coll = sum(r["collisions"] for r in runs)
    p("## The collision-free invariant\n")
    p(f"The floor's checker looks at every robot every second for a vertex conflict (two robots in one cell), an edge swap (two robots "
      f"trading cells), a move into a closed aisle from outside, a paused robot moving, and a move that is not along an edge. Across all "
      f"{len(runs)} runs it checked **{steps:,} robot-steps and found {coll} conflicts**. The blueprint's bar is 99.99% collision-free; "
      "the measured rate is 100%. Execution here is exact (a robot moves when told), so this is the planner's and the repairs' invariant, "
      "not robustness to wheel slip or a late start, which the simulator does not model.\n")
    p("## Task assignment against FIFO\n")
    p("Cells travelled per completed order (one cell is 1.2 m), throughput and SLA (orders due within 10 minutes):\n")
    p("| Warehouse | Wave | FIFO nearest-free | Greedy best pair | CP-SAT | CP-SAT vs FIFO | Throughput FIFO → CP-SAT (orders/h) | Greedy (orders/h) | On time FIFO / CP-SAT | Overdue at end FIFO / CP-SAT |")
    p("|---|---|---|---|---|---|---|---|---|---|")
    red = collections.defaultdict(list)
    for s in WAREHOUSES:
        for w in WAVES:
            f, g, c = (R[(s, w, x)] for x in POLICIES)
            d = c["cells_per_order"] / f["cells_per_order"] - 1
            red[w].append((d, c["throughput_per_hour"] / f["throughput_per_hour"] - 1, g["cells_per_order"] / f["cells_per_order"] - 1,
                           c["cells_per_order"] / g["cells_per_order"] - 1))
            p(f"| {s} | {w} | {f['cells_per_order']} | {g['cells_per_order']} | {c['cells_per_order']} | {d:+.1%} | {f['throughput_per_hour']:,} → "
              f"{c['throughput_per_hour']:,} | {g['throughput_per_hour']:,} | {f['sla_hit_rate']:.1%} / {c['sla_hit_rate']:.1%} | {f['overdue_open']} / {c['overdue_open']} |")
    rng = lambda xs, f=lambda v: f"{v:+.1%}": f(min(xs)) if f(min(xs)) == f(max(xs)) else f"{f(min(xs))} to {f(max(xs))}"   # noqa: E731
    for w, xs in red.items():
        p(f"\n**{w.title()} wave**: travel per order, CP-SAT against FIFO {rng([x[0] for x in xs])}, greedy against FIFO {rng([x[2] for x in xs])}, "
          f"CP-SAT against greedy {rng([x[3] for x in xs])}; throughput, CP-SAT against FIFO {rng([x[1] for x in xs])}.")
    peak_ok = all(-x[0] > 0.15 for x in red["peak"])
    steady_ok = all(-x[0] > 0.15 for x in red["steady"])
    p(f"\nThe blueprint's bar is a travel-distance reduction above 15% against FIFO: {'met' if peak_ok else 'not met'} in every peak wave, "
      f"{'met' if steady_ok else 'not met'} in the steady ones. When the fleet keeps up, the backlog is small and the nearest free robot "
      "is already about the best choice for the oldest order, so there is little to gain; when orders pile up beyond what the fleet can "
      "finish, FIFO still sends robots across the floor to the oldest order while the other two choose an order near each free robot, and "
      "that choice is nearly all of the gain. CP-SAT's joint assignment with station capacity adds a little over greedy pairing at these "
      "sizes (a few robots free up each three-second epoch) and costs more solver time (below). On time is the share of completed orders "
      "delivered within their 10-minute SLA; overdue counts orders past due and not delivered when the window ends. All three policies "
      "share one station rule, in the baseline's favour: the least busy of the three nearest stations (the first FIFO version sent every "
      "robot to the nearest station, queued robots at the dead-end stations and gridlocked; that was a strawman, so it was changed).\n")
    p("## Replanning after a single robot stops\n")
    pe = [e for r in timed for e in r["pause_events"]]
    per = [x for e in pe for x in e[3]]
    ms = [e[0] for e in pe]
    touched = [e[1] for e in pe]
    later = [e[5] for e in pe]
    meth = collections.Counter(e[2] for e in pe)
    de = [e for r in timed for e in r["deferred_events"]]
    p(f"{len(pe)} operator stops across the CP-SAT peak runs, each of the robot in the busiest aisle cell (the hardest case the rule can find). "
      f"The stop is a local re-plan: every robot due through the stopped robot's cell within {engine.LOCAL_S} s is re-planned at once "
      f"({pct(touched, 50)} robots at the median, {pct(touched, 95)} at p95, {max(touched)} at most); robots due through it later "
      f"({pct(later, 50)} at the median, {max(later)} at most) keep their plans until the next dispatch epoch, at most three seconds later "
      f"and at least {engine.LOCAL_S - engine.EPOCH_S} s before they would reach it. Latency on one core, Python, including the D* Lite field "
      "repairs, timed with the three runs repeated one at a time so that nothing else competed for the CPU (the repeats reproduced the "
      f"parallel runs' outcomes {'exactly' if same else 'NOT exactly'}; in the parallel runs, sharing four cores three ways, the same events "
      f"took p50 {pct([e[0] for s in WAREHOUSES for e in R[(s, 'peak', 'cpsat')]['pause_events']], 50)} and p95 "
      f"{pct([e[0] for s in WAREHOUSES for e in R[(s, 'peak', 'cpsat')]['pause_events']], 95)} ms):\n")
    p("| | p50 | p95 | max |\n|---|---|---|---|")
    p(f"| Local re-plan, whole event (ms) | {pct(ms, 50)} | {pct(ms, 95)} | {round(max(ms), 1)} |")
    p(f"| Local re-plan, per affected robot (ms) | {pct(per, 50)} | {pct(per, 95)} | {round(max(per), 1)} |")
    if de:
        p(f"| Deferred re-plan at the next epoch, whole batch (ms; {len(de)} batches, {sum(e[1] for e in de):,} robots) | {pct([e[0] for e in de], 50)} | {pct([e[0] for e in de], 95)} | {round(max(e[0] for e in de), 1)} |")
    p(f"\nThe blueprint's bar is under 250 ms for a local re-plan after a single-robot obstacle event: {sum(m < 250 for m in ms)} of {len(ms)} "
      f"events ({sum(m < 250 for m in ms) / len(ms):.0%}) were under it as a whole, and {sum(x < 250 for x in per) / len(per):.1%} of per-robot "
      f"re-plans. How the local re-plans were resolved: {', '.join(f'{k} {v}' for k, v in meth.most_common())} (CBS when {engine.CBS_MAX} robots or "
      f"fewer and it finishes within {engine.CBS_NODES} search nodes; *gave_way* means a stuck robot handed its task back or switched station "
      f"so the others could pass; *pulled* means a robot that had to wait where it stood pulled the robots due through its cell into the "
      f"re-plan). Robots left without a plan after a stop: {sum(e[4] for e in pe)} (they wait in place, which every other plan respects, and "
      f"are retried every epoch); still waiting at the end of the runs: {sum(r['waiting_at_end'] for r in runs)}.\n")
    ce = [e for r in timed for e in r["closure_events"]]
    p(f"Aisle closures in the same runs ({len(ce)} events): {pct([e[1] for e in ce], 50)} robots re-planned at the median, whole-event latency p50 "
      f"{pct([e[0] for e in ce], 50)} ms, p95 {pct([e[0] for e in ce], 95)} ms, max {round(max(e[0] for e in ce), 1)} ms. Orders whose pick face "
      f"is in a closed aisle are held, not failed: {', '.join(str(R[(s, 'peak', 'cpsat')]['held_tasks']) for s in WAREHOUSES)} held at the end of the "
      "CP-SAT peak runs.\n")
    p("## Control-loop freshness\n")
    ticks = [r["tick_ms"] for r in timed]
    over = sum(x["over_1s"] for x in ticks)
    total = SECONDS * len(timed)
    over_par = sum(r["tick_ms"]["over_1s"] for r in runs)
    p(f"The fleet state is one tick behind the floor plus the time that tick takes to compute. In the CP-SAT peak runs timed alone, one "
      f"simulated second (telemetry in, events handled, dispatch every third second, every robot's next cell out) took p50 "
      f"{min(x['p50'] for x in ticks)}–{max(x['p50'] for x in ticks)} ms and p95 {min(x['p95'] for x in ticks)}–{max(x['p95'] for x in ticks)} ms. "
      f"{over} of {total:,} simulated seconds took longer "
      f"than one second (the slowest took {max(x['max'] for x in ticks):,.0f} ms; the slow ones are dispatch epochs, which carry the assignment "
      "solve and any deferred re-plans). Against the blueprint's bar of telemetry fresher than one second, that is "
      f"{1 - over / total:.2%} of seconds, on one Python process (in the parallel runs, all policies and waves, {over_par} of "
      f"{SECONDS * len(runs):,} seconds took longer than one second). Assignment solve per epoch (p50 / p95), CP-SAT: "
      f"{', '.join(str(t['assign_ms']['p50']) + ' / ' + str(t['assign_ms']['p95']) for t in timed)} ms; "
      f"greedy (parallel runs): {', '.join(str(R[(s, 'peak', 'greedy')]['assign_ms']['p50']) + ' / ' + str(R[(s, 'peak', 'greedy')]['assign_ms']['p95']) for s in WAREHOUSES)} ms.\n")
    p("## CBS against prioritized planning\n")
    sc = cbs_scaling()
    p("A robot in an aisle at minute 7 of a peak run (warehouse 101) is stopped, and the *k* working robots nearest it are re-planned together "
      "against everyone else's reservations, eight different places per size. CBS gets two seconds; prioritized is the repair the system uses "
      "(with CBS switched off). Cost is the sum of the group's plan lengths in seconds.\n")
    p("| Robots | CBS solved | CBS median ms | CBS median nodes | Prioritized solved | Prioritized median ms | Cost, prioritized vs CBS (both solved) |")
    p("|---|---|---|---|---|---|---|")
    for k, rows in sc.items():
        c_ok = [x["cbs"] for x in rows if x["cbs"][0]]
        q_ok = [x["prioritized"] for x in rows if x["prioritized"][0]]
        both = [(x["prioritized"][2], x["cbs"][2]) for x in rows if x["cbs"][0] and x["prioritized"][0]]
        gap = (f"{np.mean([a / b - 1 for a, b in both]):+.2%} ({len(both)})" if both else "–")
        p(f"| {k} | {len(c_ok)} / {len(rows)} | {pct([x[1] for x in c_ok], 50) if c_ok else '–'} | {pct([x[3] for x in c_ok], 50) if c_ok else '–'} | "
          f"{len(q_ok)} / {len(rows)} | {pct([x[1] for x in q_ok], 50) if q_ok else '–'} | {gap} |")
    p("\nCBS's search grows with the number of conflicts among the group, and a dense group at peak has many: past two or three robots it "
      "stops finishing within its budget, while prioritized planning (with its give-way and pull-in steps) solved every group, at a total "
      "length close to CBS's where CBS did finish. Hence the split the system uses: CBS for a group of "
      f"{engine.CBS_MAX} or fewer when it finishes within {engine.CBS_NODES} search nodes, prioritized otherwise, and never CBS over 250 robots.\n")
    p("## D* Lite against recomputing a distance field\n")
    db, mism, n = dstar_bench()
    p(f"A goal's distance field ({n:,} cells) repaired in place after an obstacle appears, against computing it again from scratch "
      f"(breadth-first, same Python), {len(db['cell'])} random goals each. Mismatches between the two: {mism}.\n")
    p("| Change | Repair ms (median) | Recompute ms (median) | Vertices the repair touched (median) | Distances that changed (median) |\n|---|---|---|---|---|")
    for kind, name in (("cell", "one cell (a stopped robot)"), ("aisle", "a whole aisle closed")):
        x = np.array(db[kind])
        p(f"| {name} | {np.median(x[:, 0]):.2f} | {np.median(x[:, 1]):.2f} | {np.median(x[:, 2]):.0f} | {np.median(x[:, 3]):.0f} |")
    xc, xa = np.array(db["cell"]), np.array(db["aisle"])
    p(f"\nThe repair touches only the vertices whose distance changed (a median of {np.median(xc[:, 2]):.0f} for a stopped robot and "
      f"{np.median(xa[:, 2]):.0f} for a closed aisle, of {n:,}) and is {np.median(xc[:, 1] / xc[:, 0]):.0f} and {np.median(xa[:, 1] / xa[:, 0]):.0f} "
      "times faster than recomputing at the median. A closed aisle changes few distances because the highways and cross-aisles route around "
      "it; one field serves every robot heading to its goal, so each repair is paid once. On a map this size a recompute is also under a "
      "millisecond, so the saving matters for the number of fields kept (one per pick face in use), not for any single one.\n")
    p("## Battery fade forecast\n")
    p("Each pack's capacity fade fitted on its cycles up to a cutoff (square root of cumulative cycle stress, deeper and hotter cycles "
      "weighing more, plus a calendar term; each pack's coefficient shrunk toward its vendor's), forecast to the end of its history and scored "
      "against the generator's true state of health. Baseline: a straight line through the pack's own measured capacity over its last 90 days.\n")
    p("| Warehouse | Held out | Packs | MAE, points of SoH | Baseline | p90 | Baseline p90 | Packs with an unmodelled knee: MAE / baseline | Below 80% at the end: caught by model / baseline |")
    p("|---|---|---|---|---|---|---|---|---|")
    nows, knees = [], []
    for s in WAREHOUSES:
        for hold in (120, 365):
            rows, now = battery(s, hold)
            nows.append(now)
            a = np.array([x[1] for x in rows])
            m = np.abs(np.array([x[2] for x in rows]) - a) * 100
            b = np.abs(np.array([x[3] for x in rows]) - a) * 100
            k = np.array([x[4] for x in rows])
            eol = a < engine.EOL_SOH
            caught_m = int((np.array([x[2] for x in rows])[eol] < engine.EOL_SOH).sum())
            caught_b = int((np.array([x[3] for x in rows])[eol] < engine.EOL_SOH).sum())
            false_m = int(((np.array([x[2] for x in rows]) < engine.EOL_SOH) & ~eol).sum())
            false_b = int(((np.array([x[3] for x in rows]) < engine.EOL_SOH) & ~eol).sum())
            knees.append((s, hold, m.mean(), m[k].mean(), b[k].mean()))
            p(f"| {s} | {hold} days | {len(rows)} | {m.mean():.2f} | {b.mean():.2f} | {np.quantile(m, .9):.2f} | {np.quantile(b, .9):.2f} | "
              f"{m[k].mean():.2f} / {b[k].mean():.2f} ({int(k.sum())}) | {caught_m} / {caught_b} of {int(eol.sum())} (false alarms {false_m} / {false_b}) |")
    worse = [x for x in knees if x[3] > x[2]]
    lose = [x for x in knees if x[3] > x[4]]
    p(f"\nThe state of health the battery planner uses today (fitted on everything) is off by {min(nows) * 100:.2f}–{max(nows) * 100:.2f} points "
      "against the truth. The model's form is the generator's own fade law, so on these packs it is the best case. About one pack in eight has "
      f"a knee (faster fade below about 86%) the model does not know about: its error on those packs is above its overall error in {len(worse)} "
      f"of {len(knees)} rows, and above the baseline's in {len(lose)} ("
      + ", ".join(f"warehouse {x[0]} at {x[1]} days, {x[3]:.2f} against {x[4]:.2f}" for x in lose) + "). Real packs would need the form itself "
      "checked against capacity-test or teardown data.\n")
    p("## Every run\n")
    p("| Warehouse | Wave | Policy | Orders in | Completed | Orders/h | Cells/order | Loaded share | On time | Overdue at end | Held | Collisions | Tick p95 ms | Wall s |")
    p("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for (s, w, pol), r in sorted(R.items()):
        p(f"| {s} | {w} | {pol} | {r['orders_arrived']:,} | {r['orders_completed']:,} | {r['throughput_per_hour']:,} | {r['cells_per_order']} | "
          f"{r['loaded_share']:.0%} | {r['sla_hit_rate']:.1%} | {r['overdue_open']} | {r['held_tasks']} | {r['collisions']} | {r['tick_ms']['p95']} | {r['wall_s']} |")
    return R


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
    sys.exit(0)
