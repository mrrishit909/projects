"""The floor, the planner, the assignment and the battery model, without a database."""
import collections
import random

import numpy as np

from wh import engine, world

SMALL = dict(n_aisles=13, block_rows=8, blocks=2, n_stations=6, n_chargers=6, n_robots=40, groups=2)


def test_layout_is_a_warehouse():
    L = world.Layout()
    assert (L.n, len(L.picks), len(L.homes), len(L.chargers), len(L.stations), len(L.aisles)) == (3452, 1476, 250, 24, 20, 123)
    assert all(len(L.nbrs[c]) == 1 for c in L.homes + L.chargers + L.stations)            # bays are dead ends
    seen, todo = {0}, [0]
    while todo:
        for w in L.nbrs[todo.pop()]:
            if w not in seen:
                seen.add(w)
                todo.append(w)
    assert len(seen) == L.n
    assert all(L.cell_of_location(L.location(c)) == c for c in L.picks[::37]) and L.cell_of_location("Z-99-01") is None
    assert world.fleet(3, L) == world.fleet(3, L) and world.arrivals(3, L, {"id": 1, "orders_per_hour": 9000, "from_t": 0}, 17) == \
        world.arrivals(3, L, {"id": 1, "orders_per_hour": 9000, "from_t": 0}, 17)


def test_the_checker_catches_every_kind_of_conflict():
    L = world.Layout(**SMALL)
    robots = world.fleet(1, L)
    floor = world.Floor(L, robots, {r["id"]: 1.0 for r in robots}, 1)
    a, b = L.aisles["A-03"][2:4]                                   # two neighbours in one aisle
    assert b in L.nbrs[a]
    far = next(c for c in L.picks if L.zone[c] != L.zone[a])
    floor.pos = [a, b, far] + floor.pos[3:]
    stay = list(floor.pos)
    kinds = lambda found: sorted(v[1] for v in found)           # noqa: E731
    assert floor.step([b, a] + stay[2:]) and kinds(floor.violations[-1:]) == ["edge_swap"]
    floor.pos = [a, b, far] + stay[3:]
    assert kinds(floor.step([b, b] + stay[2:])) == ["vertex"]
    floor.pos = [a, b, far] + stay[3:]
    assert kinds(floor.step([a, b, a] + stay[3:])) == ["not_an_edge"]
    floor.pos = [a, b, far] + stay[3:]
    floor.pause(1)
    assert kinds(floor.step([a, a] + stay[2:])) == ["paused_robot_moved"]
    floor.pause(1, False)
    zone = L.zone[far]
    for c in L.aisles[zone]:
        floor.closed[c] = zone
    outside = next(w for w in L.nbrs[L.aisles[zone][0]] if w not in floor.closed)
    floor.pos = [a, b, outside] + stay[3:]
    assert kinds(floor.step([a, b, L.aisles[zone][0]] + stay[3:])) == ["entered_closed_aisle"]
    floor.pos = [a, b, far] + stay[3:]
    assert floor.step([a, b, next(w for w in L.nbrs[far] if w in floor.closed)] + stay[3:]) == []   # moving inside a closed aisle is leaving it


def test_dstar_lite_repair_equals_recomputing():
    L = world.Layout(**SMALL)
    rng = random.Random(4)
    traffic = [c for c in range(L.n) if L.kind[c] in ("aisle", "cross")]
    for _ in range(25):
        blocked = bytearray(L.n)
        goal = rng.choice(L.picks + L.stations)
        f = engine.DistField(L, goal, blocked)
        for _ in range(6):                                          # block and clear, cells and whole aisles
            cells = rng.sample(traffic, 3) if rng.random() < .5 else list(L.aisles[rng.choice(sorted(L.aisles))])
            on = rng.random() < .7
            for c in cells:
                blocked[c] = on
            f.repair(L, cells, blocked)
            assert f.g == engine.DistField(L, goal, blocked).g


def test_prioritized_planning_is_conflict_free_and_waits_for_a_station():
    L = world.Layout(**SMALL)
    robots = world.fleet(2, L)
    fleet = engine.Fleet(L, robots)
    rng = random.Random(7)
    plans = {}
    for r in range(fleet.R):                                       # everyone gets a job at once, planned one after another
        pick, s = rng.choice(L.picks), rng.randrange(len(L.stations))
        legs = [{"goal": pick, "dwell": world.PICK_S, "kind": "pick", "task": f"T{r}"},
                {"goal": L.stations[s], "dwell": world.DROP_S, "kind": "drop", "task": f"T{r}", "station": s},
                {"goal": fleet.home[r], "dwell": None, "kind": "home"}]
        assert fleet.try_plan(r, 0, legs), r
        plans[r] = (0, fleet.plan[r])
    assert engine.Fleet.first_conflict(plans, 0) is None
    st = collections.Counter(lg["goal"] for r in range(fleet.R) for lg in fleet.legs[r] if lg["kind"] == "drop")
    busiest = st.most_common(1)[0][0]
    visits = sorted((t0 + i, r) for r, (t0, p) in plans.items() for i, c in enumerate(p) if c == busiest)
    assert len({r for _, r in visits}) > 1 and len({t for t, _ in visits}) == len(visits)       # robots took turns at a shared dead end


def test_cbs_finds_what_independent_plans_miss():
    """Two robots at opposite ends of one single-width aisle, each heading out the other end: planned alone they meet
    head-on; CBS splits on that conflict until one steps aside."""
    L = world.Layout(**SMALL)
    robots = world.fleet(3, L)
    fleet = engine.Fleet(L, robots)
    aisle = L.aisles[sorted(L.aisles)[2]]
    a, b = 0, 1                                                     # two robots at the ends of one aisle, each heading for the other end
    for r, c in ((a, aisle[0]), (b, aisle[-1])):
        fleet.res.remove(r, 0, fleet.plan[r], -1)
        fleet.cell[r] = c
        fleet.plan[r] = [c]
        fleet.res.add(r, 0, [c])
    fleet.legs[a] = [{"goal": L.aisle_exits[L.zone[aisle[0]]][1], "dwell": None, "kind": "home"}]
    fleet.legs[b] = [{"goal": L.aisle_exits[L.zone[aisle[0]]][0], "dwell": None, "kind": "home"}]
    for r in (a, b):
        fleet.unreserve(r, 0)
    alone = {r: (0, fleet.plan_chain(r, fleet.cell[r], 0, fleet.legs[r])[0]) for r in (a, b)}
    assert engine.Fleet.first_conflict(alone, 0) is not None      # planned alone, they meet head-on in the aisle
    for r in (a, b):
        fleet.stay(r, 0)
    budget = engine.CBS_BUDGET_S, engine.CBS_NODES
    engine.CBS_BUDGET_S, engine.CBS_NODES = 5.0, 2000
    try:
        sol = fleet.cbs([a, b], 0)
    finally:
        engine.CBS_BUDGET_S, engine.CBS_NODES = budget
    assert sol and engine.Fleet.first_conflict({r: (0, p[0]) for r, p in sol["plans"].items()}, 0) is None and sol["nodes"] > 1


def test_cpsat_assignment_is_optimal_and_keeps_its_constraints():
    floor, fleet = engine.new_world(5)
    floor.set_wave(12000, 1)
    engine.simulate(floor, fleet, 150)
    t = engine.sync(floor, fleet)
    avail = [r for r in range(fleet.R) if fleet.status[r] in ("task", "home")][:12]
    open_ = sorted(fleet.open, key=lambda k: fleet.tasks[k]["released"])[:120]
    fleet.tasks[open_[-1]]["priority"] = "urgent"
    dist = engine._Dist(fleet, avail)
    tk = {k: fleet.tasks[k] for k in open_}
    st = {k: fleet.station_options(tk[k]["pick"]) for k in open_}
    bonus = {k: fleet.bonus(tk[k], t) for k in open_}
    inbound = collections.defaultdict(int)
    ok = lambda r, k: True                                          # noqa: E731
    pairs = engine.assign_cpsat(avail, open_, dist, tk, st, bonus, inbound, ok)
    assert len(pairs) == len(avail) and len({k for _, k, _ in pairs}) == len(pairs) and open_[-1] in {k for _, k, _ in pairs}
    assert max(collections.Counter(s for *_, s in pairs).values()) <= 2
    value = lambda ps: sum(bonus[k] - dist[r][tk[k]["pick"]] - next(d for d, x in st[k] if x == s) for r, k, s in ps)   # noqa: E731
    greedy, ur, uk = [], set(), set()
    for _, r, k in sorted((dist[r][tk[k]["pick"]] + st[k][0][0] - bonus[k], r, k) for r in avail for k in open_):
        if r not in ur and k not in uk and sum(1 for *_, s in greedy if s == st[k][0][1]) < 2:
            greedy.append((r, k, st[k][0][1]))
            ur.add(r)
            uk.add(k)
    assert value(pairs) >= value(greedy)


def test_a_disrupted_shift_is_collision_free_and_repeatable():
    def shift():
        L = world.Layout(**SMALL)
        floor, fleet = engine.new_world(9, L)
        floor.set_wave(2500, 1)
        zone = sorted(L.aisles)[5]
        floor.tell([{"kind": "aisle_blocked", "zone": zone, "at": 60, "until": 150}, {"kind": "charger_fault", "charger": L.charger_names[0], "at": 70}])
        engine.simulate(floor, fleet, 90)
        t = engine.sync(floor, fleet)
        r = next(r for r in range(fleet.R) if fleet.status[r] == "task" and fleet.L.kind[fleet.cell[r]] == "aisle")
        floor.pause(r)
        rec = fleet.pause(r, t)
        m = engine.simulate(floor, fleet, 60)
        floor.pause(r, False)
        fleet.resume(r, engine.sync(floor, fleet))
        m2 = engine.simulate(floor, fleet, 90)
        return rec, m, m2, floor, fleet
    rec, m, m2, floor, fleet = shift()
    assert floor.violations == [] and floor.checked == 240 * 40 and m["orders_completed"] + m2["orders_completed"] > 50
    assert rec["waiting"] == 0 and fleet.stats["events"][0]["kind"] == "aisle_closed" and any(e["kind"] == "aisle_reopened" for e in fleet.stats["events"])
    assert not any(tk["status"] == "held" for tk in fleet.tasks.values())          # the aisle reopened and its orders went back to the queue
    rec2, *_, floor2, fleet2 = shift()
    assert [tk["done_t"] for tk in fleet.tasks.values()] == [tk["done_t"] for tk in fleet2.tasks.values()] and floor.moved == floor2.moved


def test_battery_model_beats_each_packs_own_trend():
    L = world.Layout()
    robots = world.fleet(55, L)
    rows, truth = world.battery_history(55, robots)
    H = collections.defaultdict(list)
    for rid, _, day, dod, temp, cap in rows:
        H[rid].append((day, dod, temp, cap))
    nominal, vendor, age = ({r["id"]: r[k] for r in robots} for k in ("capacity_wh", "vendor", "days"))
    bt = engine.battery_backtest(H, nominal, vendor, age)
    assert bt["packs"] > 200 and bt["mae_points"] < bt["baseline_mae_points"]
    fit = engine.fit_batteries(H, nominal, vendor, age)
    p = fit["R-001"]
    assert all(a >= b for a, b in zip(*[[engine.forecast_soh(p, d) for d in range(0, 721, 60)][i:] for i in (0, 1)]))
    assert np.mean([abs(engine.forecast_soh(fit[r], 0) - truth[r]) for r in fit]) < 0.005


def test_preemption_projects_on_a_copy_that_knows_no_future():
    floor, fleet = engine.new_world(7)
    floor.set_wave(9000, 1)
    floor.tell([{"kind": "aisle_blocked", "zone": "C-14", "at": 400, "until": None}])
    engine.simulate(floor, fleet, 240)
    t = engine.sync(floor, fleet)
    ids = []
    for i, loc in enumerate(["A-03-02", "A-19-03", "A-38-02"]):
        fleet.add_task({"id": f"U{i}", "pick": fleet.L.cell_of_location(loc), "priority": "urgent", "released": t, "due": t + 120}, source="api")
        ids.append(f"U{i}")
    pairs = engine.preemption(fleet, t, ids)
    assert sorted(k for _, k, _, _ in pairs) == ids
    f2, fl2 = engine.fork(floor, fleet)
    assert f2.told == [] and f2.wave is None and floor.told and fleet.tasks["U0"]["status"] == "open"
    proj = engine.project(floor, fleet, 200, ids)
    assert len(proj["tasks"]) == 3 and proj["collisions"] == 0 and fleet.tasks["U0"]["status"] == "open"     # the original never moved
