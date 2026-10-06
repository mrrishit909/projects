"""The orchestrator: everything here works from what the floor reports (telemetry, orders, closures, charger faults, cycle
records), never from the generator's internals.

    DistField        D* Lite's incremental backward search (g/rhs, goal-rooted) over the static graph: the exact distance to
                     a goal around every known obstacle, repaired in place when obstacles appear or clear. Run to convergence
                     rather than stopped at one start, because one field serves every robot heading to that goal and the
                     space-time search needs it everywhere as its heuristic.
    Reservations     who is where when: cell-time, edge-time and "parked from t" reservations of every committed plan.
    st_astar         space-time search for one robot against every reservation (vertex and edge-swap conflicts) by Safe
                     Interval Path Planning, with dwell at a goal or parking forever at it.
    plan_chain       a robot's whole job as legs: to the pick face (dwell), to a pack station (dwell), home (park).
    repair           prioritized replanning of the robots an event touched; CBS when the group is small enough to solve
                     jointly within a time budget; robots that cannot move wait in place, and anyone that waiting would
                     collide with is pulled into the repair.
    cbs              Conflict-Based Search over a small group against everyone else's reservations.
    assignment       FIFO nearest-free robot (baseline), greedy best pair, and CP-SAT over robots x tasks x stations.
    battery models   state-of-health fade fitted per robot with a vendor prior; baseline: each pack's own recent trend.
    Fleet            the controller: telemetry in, events handled, battery planner, dispatch, commands out.
"""
import copy
import hashlib
import heapq
import json
import math
import time
from collections import defaultdict, deque

import numpy as np

from . import world

INF = 10 ** 9
EPOCH_S = 3                      # dispatch and battery planning run every EPOCH_S seconds
LOW_SOC, TARGET_SOC = 0.25, 0.60 # go and charge below LOW, free the charger at TARGET
CBS_MAX, CBS_NODES, CBS_BUDGET_S = 3, 16, 1.0    # evaluation: CBS solved 7 of 8 groups of two, 2 of 8 of four, none of six;
                                                 # it stops on a node count (deterministic), the time limit is only a safety net
LOCAL_S = 30                     # after a robot stops: re-plan now whoever is due through its cell within LOCAL_S, the rest next epoch
MAX_EXP = 6000                   # expansion cap of one safe-interval search
REPAIR_CAPS = (500, 2000, 2000, MAX_EXP)
H_WEIGHT = 1.3                   # weighted heuristic: an arrival at most 30% later than the best, found with far fewer expansions
WH_PER_CELL = world.POWER_W["move_loaded"] / 3600.0
PLANNER_VERSION = "mapf-prioritized-st-astar+dstar-lite+local-cbs-1"
VERSIONS = {"fifo": "assign-fifo-nearest-free-1", "greedy": "assign-greedy-best-pair-1", "cpsat": "assign-cpsat-1"}


# --- distance fields --------------------------------------------------------------------------------------------------------
class DistField:
    """Distance to `goal` from every cell, around the blocked cells. Built by BFS; repaired by D* Lite (h = 0)."""
    __slots__ = ("goal", "g", "rhs", "version", "touched")

    def __init__(self, L, goal, blocked):
        n, nbrs = L.n, L.nbrs
        g = [INF] * n
        g[goal] = 0                                   # a goal is reachable to itself even when blocked (a robot standing on it)
        dq = deque([goal])
        while dq:
            u = dq.popleft()
            du = g[u] + 1
            for w in nbrs[u]:
                if g[w] == INF and not blocked[w]:
                    g[w] = du
                    dq.append(w)
        self.goal, self.g, self.rhs, self.version, self.touched = goal, g, None, 0, 0

    def repair(self, L, changed, blocked):
        if self.rhs is None:
            self.rhs = list(self.g)
        g, rhs, nbrs, goal = self.g, self.rhs, L.nbrs, self.goal
        heap, key = [], {}

        def update(u):
            if u == goal:
                rhs[u] = 0
            elif blocked[u]:
                rhs[u] = INF
            else:
                m = INF
                for s in nbrs[u]:
                    if g[s] < m and (not blocked[s] or s == goal):
                        m = g[s]
                rhs[u] = m + 1 if m < INF else INF
            if g[u] != rhs[u]:
                k = g[u] if g[u] < rhs[u] else rhs[u]
                key[u] = k
                heapq.heappush(heap, (k, u))
            else:
                key.pop(u, None)
        for c in changed:
            update(c)
            for s in nbrs[c]:
                update(s)
        touched = 0
        while heap:
            k, u = heapq.heappop(heap)
            if key.get(u) != k:
                continue
            del key[u]
            touched += 1
            if g[u] > rhs[u]:
                g[u] = rhs[u]
                for p in nbrs[u]:
                    update(p)
            else:
                g[u] = INF
                update(u)
                for p in nbrs[u]:
                    update(p)
        self.touched = touched
        return touched


class Fields:
    """The obstacle set the planner knows (closed aisles, paused robots) and one field per goal,
    created on first use and repaired lazily with D* Lite when the obstacle set has changed since."""

    def __init__(self, L):
        self.L, self.blocked, self.log, self.cache = L, bytearray(L.n), [], {}
        self.repairs = []          # (ms, vertices touched) of every D* Lite repair

    @property
    def version(self):
        return len(self.log)

    def set(self, cells, on):
        changed = [c for c in cells if self.blocked[c] != bool(on)]
        for c in changed:
            self.blocked[c] = bool(on)
        if changed:
            self.log.append(changed)
        return changed

    def get(self, goal):
        f = self.cache.get(goal)
        if f is None:
            f = DistField(self.L, goal, self.blocked)
            f.version = self.version
            self.cache[goal] = f
        elif f.version < self.version:
            changed = set()
            for chunk in self.log[f.version:]:
                changed.update(chunk)
            t0 = time.perf_counter()
            n = f.repair(self.L, changed, self.blocked)
            self.repairs.append((round((time.perf_counter() - t0) * 1000, 3), n))
            f.version = self.version
        return f

    def __getstate__(self):
        return {"L": self.L, "blocked": self.blocked, "log": self.log, "cache": {}, "repairs": []}


def bfs(L, src, blocked):
    return DistField(L, src, blocked).g


# --- reservations -------------------------------------------------------------------------------------------------------------
class Reservations:
    """Cell-time and edge-time reservations of every committed plan, and 'parked from t' at each plan's end."""

    def __init__(self, n):
        self.n, self.v, self.e, self.park, self.ct = n, {}, {}, {}, defaultdict(set)

    def add(self, r, t0, path, park=True):
        n, v, e, ct = self.n, self.v, self.e, self.ct
        prev = None
        for i, c in enumerate(path):
            t = t0 + i
            v[t * n + c] = r
            ct[c].add(t)
            if prev is not None and prev != c:
                e[((t - 1) * n + prev) * n + c] = r
            prev = c
        if park:
            self.park[path[-1]] = (r, t0 + len(path) - 1)

    def remove(self, r, t0, path, after):
        """Drop r's reservations at times > after (and its park)."""
        n, v, e, ct = self.n, self.v, self.e, self.ct
        for i in range(max(0, after - t0 + 1), len(path)):
            c, t = path[i], t0 + i
            k = t * n + c
            if v.get(k) == r:
                del v[k]
                ct[c].discard(t)
            if i > 0 and path[i - 1] != c:
                ek = ((t - 1) * n + path[i - 1]) * n + c
                if e.get(ek) == r:
                    del e[ek]
        p = self.park.get(path[-1])
        if p and p[0] == r:
            del self.park[path[-1]]

    def free_forever(self, c, t, r):
        p = self.park.get(c)
        if p and p[0] != r:
            return False
        n, v = self.n, self.v
        return not any(tt >= t and v.get(tt * n + c) not in (None, r) for tt in self.ct.get(c, ()))

    def users_after(self, c, t, r):
        """Robots other than r that will occupy cell c at some time after t."""
        n, v = self.n, self.v
        out = {v[tt * n + c] for tt in self.ct.get(c, ()) if tt > t and v.get(tt * n + c) not in (None, r)}
        p = self.park.get(c)
        if p and p[0] != r:
            out.add(p[0])
        return out


# --- the fleet controller -------------------------------------------------------------------------------------------------------
class Fleet:
    """Robots as the orchestrator knows them, their plans and reservations, the tasks, chargers and the policies."""

    def __init__(self, L, robots, policy="cpsat", soh_est=None, epoch=EPOCH_S):
        self.L, self.N, self.R, self.policy, self.epoch = L, L.n, len(robots), policy, epoch
        self.ids = [r["id"] for r in robots]
        self.index = {r: i for i, r in enumerate(self.ids)}
        self.vendor = [r["vendor"] for r in robots]
        self.home = [r["home"] for r in robots]
        self.nominal_wh = [r["capacity_wh"] for r in robots]
        self.soh = [float((soh_est or {}).get(r["id"], 1.0)) for r in robots]
        self.cell = list(self.home)
        self.soc = [0.5] * self.R
        self.seen_t = [0] * self.R                # sim time of the robot's last telemetry
        self.status = ["idle"] * self.R           # idle | task | home | to_charger | charging | charge_wait | charged | paused
        self.task = [None] * self.R
        self.legs = [[] for _ in range(self.R)]
        self.plan_t0 = [0] * self.R
        self.plan = [[h] for h in self.home]
        self.marks = [[] for _ in range(self.R)]
        self.waiting = [False] * self.R
        self.deferred = set()                     # robots whose plans cross a new obstacle more than LOCAL_S ahead
        self.needs_charge = [False] * self.R
        self.paused = set()
        self.closed = {}                          # cell -> aisle zone, as reported
        self.fields = Fields(L)
        self.res = Reservations(L.n)
        for r, h in enumerate(self.home):
            self.res.add(r, 0, [h])
        self.tasks = {}
        self.open = set()
        self.charger_up = [True] * len(L.chargers)
        self.occupant = [None] * len(L.chargers)
        self.target = [None] * len(L.chargers)
        self.robot_charger = [None] * self.R
        self.t = 0
        self.stats = {"repairs": [], "assign_ms": [], "assignments": 0, "plan_fail": 0, "bumped": 0, "events": []}
        self.assign_log = []                      # (t, task, robot, station, policy, cost, inputs hash)
        self.version = 0                          # bumps on every state change an approval depends on

    # --- planning primitives -------------------------------------------------------------------------------------------------
    def h_field(self, goal):
        return self.fields.get(goal).g

    def st_astar(self, r, start, t0, goal, dwell, g, cons=None, max_exp=MAX_EXP):
        """The earliest way to `goal` (see sipp), or None."""
        return next(self.sipp(r, start, t0, goal, dwell, g, cons, max_exp), None)

    def boxed_in(self, r, start, goal, t0):
        """True when no path leads from start to goal even ignoring time: robots standing for good (parked from now on)
        are walls, as are closed aisles. A cheap way for a repair to reject a search that would only fail slowly."""
        park, nbrs, bay, closed, blocked = self.res.park, self.L.nbrs, self.L.bay, self.closed, self.fields.blocked
        seen, dq = {start}, deque([start])
        while dq:
            u = dq.popleft()
            for w in nbrs[u]:
                if w in seen:
                    continue
                if w == goal:
                    return False
                p = park.get(w)
                if (p and p[0] != r and p[1] <= t0 + 1) or (bay[w]) or blocked[w] or (w in closed and closed.get(u) != closed[w]):
                    continue
                seen.add(w)
                dq.append(w)
        return start != goal

    def sipp(self, r, start, t0, goal, dwell, g, cons=None, max_exp=MAX_EXP):
        """Ways to reach `goal` from (start, t0) that respect every reservation, earliest first: Safe Interval Path
        Planning, a space-time A* whose states are (cell, safe interval) so that waiting costs nothing to search. Vertex
        and edge-swap conflicts both checked. dwell: steps to stay at the goal (0 = pass through) or None to park there
        for good. Yields (cells from t0 to departure, arrival time); asking for the next one continues the search, which
        is how a chain backs off when the next leg cannot start where this one ends."""
        L, N, res = self.L, self.N, self.res
        v, e, park, ct, nbrs, bay, closed = res.v, res.e, res.park, res.ct, L.nbrs, L.bay, self.closed
        cv, ce = (cons or ({}, {}))
        hs = g[start]
        if hs >= INF:
            hs = min([g[w] for w in nbrs[start]] + [INF]) + 1
            if hs >= INF:
                return
        gp = park.get(goal)
        if gp and gp[0] != r:
            return
        cache = {}

        def safe(c):
            iv = cache.get(c)
            if iv is None:
                ts = [tt for tt in ct.get(c, ()) if tt >= t0 and v.get(tt * N + c) not in (None, r)]
                if cv and c in cv:
                    ts += [tt for tt in cv[c] if tt >= t0]
                ts.sort()
                p = park.get(c)
                pend = p[1] if p and p[0] != r else INF
                iv, a = [], t0
                for tt in ts:
                    if tt >= pend:
                        break
                    if tt > a:
                        iv.append((a, tt - 1))
                    if tt + 1 > a:
                        a = tt + 1
                if a < pend:
                    iv.append((a, pend - 1 if pend < INF else INF))
                cache[c] = iv
            return iv
        iv0 = safe(start)
        if not iv0 or iv0[0][0] != t0:
            return
        horizon = t0 + 3 * hs + 300
        hw0 = H_WEIGHT
        heap = [(t0 + hw0 * hs, hs, t0, start, 0)]
        best = {(start, 0): t0}
        parent = {(start, 0): None}
        exp = 0
        while heap:
            f, _, ta, c, i = heapq.heappop(heap)
            if best.get((c, i)) != ta:
                continue
            exp += 1
            if exp > max_exp:
                return
            a, b = safe(c)[i]
            if c == goal and (b == INF if dwell is None else ta + dwell <= b):
                hops, k = [], (c, i)
                while k is not None:
                    hops.append((k[0], best[k]))
                    k = parent[k]
                hops.reverse()
                path = [hops[0][0]]
                for (c1, a1), (c2, a2) in zip(hops, hops[1:]):
                    path += [c1] * (a2 - a1 - 1) + [c2]
                yield path + [goal] * (dwell or 0), ta
                continue
            if ta >= horizon:
                continue
            zc = closed.get(c)
            for w in nbrs[c]:
                if bay[w] and w != goal:
                    continue
                zw = closed.get(w)
                if zw is not None and zw != zc:
                    continue
                hw = g[w]
                if hw >= INF:
                    continue
                for j, (a2, b2) in enumerate(safe(w)):
                    if a2 > b + 1:
                        break
                    if b2 < ta + 1:
                        continue
                    td = max(ta, a2 - 1)
                    arr = None
                    while td <= b and td + 1 <= b2:
                        o = e.get((td * N + w) * N + c)
                        if (o is None or o == r) and not (ce and (c, w, td) in ce):
                            arr = td + 1
                            break
                        td += 1
                    if arr is None:
                        continue
                    k2 = (w, j)
                    if arr < best.get(k2, INF):
                        best[k2] = arr
                        parent[k2] = (c, i)
                        heapq.heappush(heap, (arr + hw0 * hw, hw, arr, w, j))

    def aisle_field(self, zone, exit_cell):
        """Heuristic for leaving a closed aisle through one exit: steps along the aisle; everywhere else unreachable."""
        g = [INF] * self.N
        cells = self.L.aisles[zone]
        ye = self.L.xy[exit_cell][1]
        for c in cells:
            g[c] = abs(self.L.xy[c][1] - ye)
        g[exit_cell] = 0
        return g

    def plan_chain(self, r, start, t0, legs, cons=None, tries=4, cap=MAX_EXP, quick=False):
        """Plan legs one after another from (start, t0). When a leg cannot start where the previous one ended (a robot
        queued at a dead-end station's entrance, say), the previous leg's search is asked for its next way there, up to
        `tries` times per leg. Returns (path, marks, legs with planned arrivals) or None."""

        def options(li, cur, t):
            leg = legs[li]
            goal, dwell = leg["goal"], leg["dwell"]
            if leg["kind"] == "exit":
                zone = self.closed.get(cur)
                if zone is None:
                    yield None, [cur], t                       # already outside the closed aisle
                    return
                top, bot = self.L.aisle_exits[zone]
                nxt = next((lg["goal"] for lg in legs[li + 1:]), self.home[r])
                gn = self.h_field(nxt)
                for ex in sorted((top, bot), key=lambda x: abs(self.L.xy[x][1] - self.L.xy[cur][1]) + gn[x]):
                    for seg, arr in self.sipp(r, cur, t, ex, 0, self.aisle_field(zone, ex), cons, cap):
                        yield ex, seg, arr
                return
            if cur == goal and leg.get("arr") is not None and leg["arr"] <= t and dwell:
                dwell = max(0, leg["arr"] + leg["dwell"] - t)  # already dwelling: the rest of it
            if quick and self.boxed_in(r, cur, goal, t):
                return
            for seg, arr in self.sipp(r, cur, t, goal, dwell, self.h_field(goal), cons, cap):
                yield goal, seg, arr

        def rec(li, cur, t, path, marks, out):
            if li == len(legs):
                return path, marks, out
            leg = legs[li]
            for n, (goal, seg, arr) in enumerate(options(li, cur, t)):
                if n >= tries:
                    break
                if goal is None:                               # an exit leg with nothing to do
                    return rec(li + 1, cur, t, path, marks, out)
                p2 = path + seg[1:]
                t2 = t0 + len(p2) - 1
                mark = (t2, leg["kind"], leg.get("task")) if leg["kind"] in ("pick", "drop") else (arr, leg["kind"], leg.get("charger"))
                found = rec(li + 1, goal, t2, p2, marks + [mark], out + [{**leg, "goal": goal, "arr": arr}])
                if found:
                    return found
            return None
        return rec(0, start, t0, [start], [], [])

    def unreserve(self, r, t):
        self.res.remove(r, self.plan_t0[r], self.plan[r], t)

    def commit(self, r, t, path, marks, legs):
        self.plan_t0[r], self.plan[r], self.marks[r], self.legs[r] = t, path, marks, legs
        self.res.add(r, t, path)
        self.waiting[r] = False

    def stay(self, r, t):
        """r waits where it is for good (until replanned)."""
        self.plan_t0[r], self.plan[r], self.marks[r] = t, [self.cell[r]], []
        self.res.add(r, t, [self.cell[r]])

    def try_plan(self, r, t, legs, cons=None):
        """Replace r's plan from t with a chain over `legs`; keep the old plan if no chain is found."""
        old = (self.plan_t0[r], self.plan[r], self.marks[r], self.legs[r])
        self.unreserve(r, t)
        out = self.plan_chain(r, self.cell[r], t, legs, cons)
        if out is None:
            self.res.add(r, *old[:2])
            self.stats["plan_fail"] += 1
            return False
        self.commit(r, t, *out)
        return True

    # --- repair after an event ----------------------------------------------------------------------------------------------
    def priority(self, r):
        k = self.task[r]
        tk = self.tasks.get(k) if k else None
        return (0 if tk and tk["priority"] == "urgent" else 1, 0 if tk and tk["status"] == "picked" else 1,
                tk["due"] if tk else INF, r)

    def repair(self, robots, t, reason):
        """Re-plan the robots an event touched, keeping everyone else's plan. Returns a record with the latency."""
        t_start = time.perf_counter()
        S = [r for r in dict.fromkeys(robots) if r not in self.paused]
        per = defaultdict(float)
        for r in S:
            self.unreserve(r, t)
            self.stay(r, t)
        method = "prioritized"
        if 0 < len(S) <= CBS_MAX:
            sol = self.cbs(S, t)
            if sol:
                for r, (path, marks, legs) in sol["plans"].items():
                    self.unreserve(r, t)
                    self.commit(r, t, path, marks, legs)
                method = "cbs"
                ms = (time.perf_counter() - t_start) * 1000
                rec = {"t": t, "reason": reason, "robots": len(S), "method": method, "ms": round(ms, 2),
                       "per_robot_ms": [round(ms / len(S), 2)] * len(S), "waiting": 0, "cbs_nodes": sol["nodes"]}
                self.stats["repairs"].append(rec)
                return rec
        queue = sorted(S, key=self.priority)
        members, gave_way = set(S), set()
        for rnd in range(10):
            failed = []
            cap = REPAIR_CAPS[min(rnd, len(REPAIR_CAPS) - 1)]  # cheap first tries: a robot that fails now often succeeds once others moved
            for r in queue:
                t1 = time.perf_counter()
                self.unreserve(r, t)
                out = self.plan_chain(r, self.cell[r], t, self.legs[r], cap=cap, quick=True)
                if out is None:
                    self.stay(r, t)
                    failed.append(r)
                else:
                    self.commit(r, t, *out)
                per[r] += (time.perf_counter() - t1) * 1000
            if not failed:
                queue = []
                break
            if len(failed) < len(queue) or rnd == 0:
                queue = failed
                continue
            switched = [r for r in failed if r not in gave_way and self.give_way(r)]
            if switched:                              # stuck robots change their job so they can clear the way, then go first
                gave_way |= set(switched)
                method = "prioritized+gave_way"
                queue = switched + [r for r in failed if r not in switched]
                continue
            if cap < MAX_EXP:
                queue = failed
                continue
            blockers = set()
            for r in failed:
                blockers |= self.res.users_after(self.cell[r], t, r) - members
            if not blockers or len(members) + len(blockers) > 80:
                queue = failed
                break
            for b in blockers:
                self.unreserve(b, t)
                self.stay(b, t)
                members.add(b)
            method = "prioritized+pulled"
            queue = failed + sorted(blockers, key=self.priority)
        if queue and any(self.res.users_after(self.cell[r], t, r) for r in queue):
            method = "global"
            self.replan_all(t)
            queue = [r for r in range(self.R) if self.waiting[r]]
        for r in queue:
            self.waiting[r] = True
        ms = (time.perf_counter() - t_start) * 1000
        rec = {"t": t, "reason": reason, "robots": len(members), "method": method, "ms": round(ms, 2),
               "per_robot_ms": [round(per[r], 2) for r in members if r in per], "waiting": len(queue)}
        self.stats["repairs"].append(rec)
        return rec

    def give_way(self, r):
        """A robot whose job cannot be planned changes it so it can clear the road: a loaded robot takes the next station
        near its pick that nobody is parked on, an unloaded one hands its task back to the queue and heads home.
        Returns True if its legs changed (it is re-planned by the caller)."""
        k = self.task[r]
        if k and self.tasks[k]["status"] == "picked":
            for i, lg in enumerate(self.legs[r]):
                if lg["kind"] == "drop":
                    for _, s in self.station_options(self.tasks[k]["pick"]):
                        p = self.res.park.get(self.L.stations[s])
                        if s != lg["station"] and not (p and p[0] != r):
                            self.legs[r][i] = {**lg, "goal": self.L.stations[s], "station": s, "arr": None}
                            self.tasks[k]["station"] = s
                            return True
            return False
        if k and self.tasks[k]["status"] == "assigned":
            exits = [lg for lg in self.legs[r] if lg["kind"] == "exit"]
            self.release_task(r)
            self.tasks[k]["bumped"] += 1
            self.legs[r] = exits + self.legs[r]
            return True
        return False

    def replan_all(self, t):
        """Everyone waits, then everyone is planned in priority order; a robot with no path keeps waiting. Always valid:
        a robot planned earlier avoided every later robot's cell, and a later one avoids every earlier plan."""
        for r in range(self.R):
            self.unreserve(r, t)
            self.stay(r, t)
        for r in sorted(range(self.R), key=self.priority):
            if r in self.paused or not self.legs[r]:
                continue
            self.unreserve(r, t)
            out = self.plan_chain(r, self.cell[r], t, self.legs[r])
            if out is None:
                self.stay(r, t)
                self.waiting[r] = True
            else:
                self.commit(r, t, *out)

    # --- conflict-based search over a small group ------------------------------------------------------------------------------
    @staticmethod
    def first_conflict(plans, t):
        """plans: {r: (t0, path)} -> (kind, a, b, cell or edge, time) of the earliest conflict, parked tails included."""
        items = list(plans.items())
        end = max(t0 + len(p) - 1 for t0, p in plans.values())
        pos = lambda pl, tt: pl[1][min(len(pl[1]) - 1, max(0, tt - pl[0]))]   # noqa: E731
        for tt in range(t + 1, end + 2):
            seen = {}
            for r, pl in items:
                c = pos(pl, tt)
                if c in seen:
                    return ("v", seen[c], r, c, tt)
                seen[c] = r
            for i, (a, pa) in enumerate(items):
                ua, wa = pos(pa, tt - 1), pos(pa, tt)
                if ua == wa:
                    continue
                for b, pb in items[i + 1:]:
                    if pos(pb, tt - 1) == wa and pos(pb, tt) == ua:
                        return ("e", a, b, (ua, wa), tt - 1)
        return None

    def cbs(self, S, t):
        """Conflict-Based Search: plan each robot alone against the others' reservations, then split on the earliest
        conflict between two of them with a constraint on each. Gives up after CBS_NODES nodes (or CBS_BUDGET_S, a safety net)."""
        t_end = time.perf_counter() + CBS_BUDGET_S
        for r in S:
            self.unreserve(r, t)                      # the group is planned jointly; their stays are not obstacles here

        def low(r, cons):
            cv, ce = defaultdict(set), set()
            for kind, x, tt in cons:
                if kind == "v":
                    cv[x].add(tt)
                else:
                    ce.add((x[0], x[1], tt))
            return self.plan_chain(r, self.cell[r], t, self.legs[r], (cv, ce))
        root = {r: low(r, ()) for r in S}
        if any(v is None for v in root.values()):
            for r in S:
                self.stay(r, t)
            return None
        cost = lambda sol: sum(len(p[0]) for p in sol.values())         # noqa: E731
        heap = [(cost(root), 0, {r: () for r in S}, root)]
        nodes, counter = 0, 1
        while heap and nodes < CBS_NODES and time.perf_counter() < t_end:
            _, _, cons, sol = heapq.heappop(heap)
            nodes += 1
            conf = self.first_conflict({r: (t, p[0]) for r, p in sol.items()}, t)
            if conf is None:
                for r in S:
                    self.stay(r, t)
                return {"plans": sol, "nodes": nodes}
            kind, a, b, x, tt = conf
            for who in (a, b):
                if kind == "v":
                    c = ("v", x, tt)
                else:
                    c = ("e", x if who == a else (x[1], x[0]), tt)
                nc = dict(cons)
                nc[who] = cons[who] + (c,)
                p = low(who, nc[who])
                if p is None:
                    continue
                ns = dict(sol)
                ns[who] = p
                heapq.heappush(heap, (cost(ns), counter, nc, ns))
                counter += 1
        for r in S:
            self.stay(r, t)
        return None

    # --- telemetry, milestones, events -------------------------------------------------------------------------------------------
    def expected(self, r, t):
        p, i = self.plan[r], t - self.plan_t0[r]
        return p[min(len(p) - 1, max(0, i))]

    def ingest(self, obs):
        t = obs["t"]
        self.t = t
        for r, (c, s) in enumerate(zip(obs["pos"], obs["soc"])):
            self.cell[r], self.soc[r], self.seen_t[r] = c, s, t

    def milestones(self, t):
        for r in range(self.R):
            m = self.marks[r]
            while m and m[0][0] <= t:
                _, kind, arg = m.pop(0)
                if self.legs[r]:
                    self.legs[r].pop(0)
                if kind == "pick":
                    tk = self.tasks[arg]
                    tk["status"], tk["picked_t"] = "picked", t
                elif kind == "drop":
                    tk = self.tasks[arg]
                    tk["status"], tk["done_t"] = "done", t
                    self.task[r] = None
                    self.status[r] = "home"
                    if self.soc[r] < LOW_SOC:
                        self.needs_charge[r] = True
                elif kind == "home":
                    self.status[r] = "idle"
                elif kind == "charge":
                    i = arg
                    self.status[r] = "charging"
                    self.occupant[i], self.target[i] = r, None
            if self.status[r] == "charging" and self.soc[r] >= TARGET_SOC:
                self.status[r] = "charged"
                self.needs_charge[r] = False

    def add_task(self, o, source="wave"):
        if o["id"] in self.tasks:
            return False
        tk = {"id": o["id"], "pick": o["pick"], "location": self.L.location(o["pick"]), "priority": o["priority"], "released": o["released"],
              "due": o["due"], "status": "open", "robot": None, "station": None, "assigned_t": None, "picked_t": None, "done_t": None,
              "source": source, "bumped": 0}
        if o["pick"] in self.closed:
            tk["status"] = "held"
        else:
            self.open.add(o["id"])
        self.tasks[o["id"]] = tk
        self.version += 1
        return True

    def release_task(self, r, held=False):
        """Take r's not-yet-picked task back; r goes home."""
        k = self.task[r]
        if k is None:
            return
        tk = self.tasks[k]
        if tk["status"] == "picked":
            return
        tk.update(status="held" if held else "open", robot=None, station=None)
        if not held:
            self.open.add(k)
        self.task[r] = None
        self.status[r] = "home"
        self.legs[r] = [{"goal": self.home[r], "dwell": None, "kind": "home"}]

    def on_event(self, ev, t):
        if ev["kind"] == "aisle_closed":
            return self.close_aisle(ev["zone"], ev["cells"], t)
        if ev["kind"] == "aisle_reopened":
            for c in ev["cells"]:
                self.closed.pop(c, None)
            self.fields.set([c for c in ev["cells"] if not any(self.cell[r] == c and r in self.paused for r in range(self.R))], False)
            for tk in self.tasks.values():
                if tk["status"] == "held" and tk["pick"] in set(ev["cells"]):
                    tk["status"] = "open"
                    self.open.add(tk["id"])
            self.stats["events"].append({"t": t, "kind": "aisle_reopened", "zone": ev["zone"]})
            return None
        if ev["kind"] == "charger_fault":
            return self.charger_fault(ev["charger"], t)
        if ev["kind"] == "charger_restored":
            self.charger_up[ev["charger"]] = True
            return None

    def close_aisle(self, zone, cells, t):
        cells = set(cells)
        for c in cells:
            self.closed[c] = zone
        self.fields.set(cells, True)
        held = 0
        for tk in self.tasks.values():
            if tk["pick"] in cells and tk["status"] == "open":
                tk["status"] = "held"
                self.open.discard(tk["id"])
                held += 1
        touched = set()
        for c in cells:
            touched |= self.res.users_after(c, t - 1, -1)
        for r in range(self.R):
            k = self.task[r]
            if k and self.tasks[k]["pick"] in cells and self.tasks[k]["status"] == "assigned":
                dwelling = self.cell[r] == self.tasks[k]["pick"] and self.legs[r] and self.legs[r][0].get("arr") is not None and self.legs[r][0]["arr"] <= t
                if not dwelling:
                    self.release_task(r, held=True)
                    held += 1
                    touched.add(r)
        exit_leg = {"goal": None, "dwell": 0, "kind": "exit"}
        for r in touched:
            lg = self.legs[r]
            if self.cell[r] not in cells or (lg and lg[0]["kind"] == "exit"):
                continue
            if lg and lg[0]["kind"] == "pick" and lg[0]["goal"] == self.cell[r]:
                self.legs[r] = [lg[0], dict(exit_leg)] + lg[1:]            # finish the pick it is doing, then leave
            else:
                self.legs[r] = [dict(exit_leg)] + (lg or [{"goal": self.home[r], "dwell": None, "kind": "home"}])
        rec = self.repair(touched, t, f"aisle {zone} closed")
        rec["held_tasks"] = held
        self.stats["events"].append({"t": t, "kind": "aisle_closed", "zone": zone, "robots": rec["robots"], "ms": rec["ms"], "held_tasks": held})
        self.version += 1
        return rec

    def charger_fault(self, i, t):
        self.charger_up[i] = False
        moved = []
        r = self.occupant[i]
        if r is not None:
            self.occupant[i] = None
            self.status[r] = "charge_wait"
            self.needs_charge[r] = True
            self.robot_charger[r] = None
            moved.append(r)
        r = self.target[i]
        if r is not None:
            self.target[i] = None
            self.robot_charger[r] = None
            self.status[r] = "charge_wait"
            self.needs_charge[r] = True
            self.try_plan(r, t, [{"goal": self.home[r], "dwell": None, "kind": "home"}])
            moved.append(r)
        self.stats["events"].append({"t": t, "kind": "charger_fault", "charger": self.L.charger_names[i], "robots": [self.ids[x] for x in moved]})
        self.version += 1
        return {"charger": self.L.charger_names[i], "robots_moved": [self.ids[x] for x in moved]}

    def pause(self, r, t):
        """An operator stops a robot where it is. It becomes an obstacle; everyone whose plan crosses its cell is re-planned."""
        if r in self.paused:
            return None
        self.paused.add(r)
        self.release_task(r)
        self.unreserve(r, t)
        self.stay(r, t)
        self.waiting[r] = False
        self.fields.set([self.cell[r]], True)
        before = {}
        c, N, v = self.cell[r], self.N, self.res.v
        first = {}
        for tt in self.res.ct.get(c, ()):
            o = v.get(tt * N + c)
            if tt > t and o not in (None, r):
                first[o] = min(first.get(o, INF), tt)
        local = sorted(a for a, tt in first.items() if tt <= t + LOCAL_S)
        later = sorted(a for a, tt in first.items() if tt > t + LOCAL_S)
        for a in local:
            before[a] = self.window(a, t, 40)
        self.status[r] = "paused"
        rec = self.repair(local, t, f"robot {self.ids[r]} paused")
        self.deferred |= set(later)               # their plans reach the cell more than LOCAL_S from now: re-planned next epoch
        rec["deferred"] = len(later)
        rec["paths"] = {self.ids[a]: {"before": before[a], "after": self.window(a, t, 40)} for a in local}
        self.stats["events"].append({"t": t, "kind": "pause", "robot": self.ids[r], "robots": rec["robots"], "ms": rec["ms"]})
        self.version += 1
        return rec

    def resume(self, r, t):
        if r not in self.paused:
            return None
        self.paused.discard(r)
        self.fields.set([self.cell[r]], False)
        self.status[r] = "task" if self.task[r] else "home"
        if not self.legs[r]:
            self.legs[r] = [{"goal": self.home[r], "dwell": None, "kind": "home"}]
        rec = self.repair([r], t, f"robot {self.ids[r]} resumed")
        self.version += 1
        return rec

    def window(self, r, t, n):
        return [self.expected(r, tt) for tt in range(t, t + n)]

    # --- battery planner ------------------------------------------------------------------------------------------------------------
    def usable_wh(self, r):
        return self.nominal_wh[r] * self.soh[r]

    def plan_charging(self, t):
        for r in range(self.R):
            if r in self.paused:
                continue
            if self.status[r] in ("idle", "home") and self.soc[r] < LOW_SOC:
                self.needs_charge[r] = True
                self.status[r] = "charge_wait"
        free = [i for i in range(len(self.L.chargers)) if self.charger_up[i] and self.occupant[i] is None and self.target[i] is None]
        queue = sorted((r for r in range(self.R) if self.status[r] == "charge_wait" and r not in self.paused), key=lambda r: self.soc[r])
        for r in queue:
            if not free:
                break
            d = [self.h_field(self.L.chargers[i])[self.cell[r]] for i in free]
            i = free[int(np.argmin(d))]
            if self.try_plan(r, t, [{"goal": self.L.chargers[i], "dwell": None, "kind": "charge", "charger": i}]):
                free.remove(i)
                self.target[i] = r
                self.robot_charger[r] = i
                self.status[r] = "to_charger"
        for r in range(self.R):                       # charge_wait robots not yet sent anywhere head home to wait
            if self.status[r] == "charge_wait" and not self.legs[r] and self.cell[r] != self.home[r] and self.L.charger_of.get(self.cell[r]) is None:
                self.try_plan(r, t, [{"goal": self.home[r], "dwell": None, "kind": "home"}])

    def leave_charger(self, r, t):
        i = self.robot_charger[r]
        if self.try_plan(r, t, [{"goal": self.home[r], "dwell": None, "kind": "home"}]):
            if i is not None:
                self.occupant[i] = None
            self.robot_charger[r] = None
            self.status[r] = "home"

    # --- dispatch -----------------------------------------------------------------------------------------------------------------
    def bonus(self, tk, t):
        """What serving a task now is worth beyond distance: a base that makes every robot worth using, more as the due
        time approaches, and for an urgent order more than any normal one can reach."""
        slack = tk["due"] - t
        return 1000 + (2500 if tk["priority"] == "urgent" else 0) + int(min(1500, max(0, 450 - slack)))

    def available(self):
        return [r for r in range(self.R) if self.status[r] in ("idle", "home", "charged") and not self.needs_charge[r]
                and r not in self.paused and not self.waiting[r]]

    def energy_ok(self, r, d_cells):
        need = d_cells * WH_PER_CELL + 60 * world.POWER_W["pick"] / 3600.0
        return self.soc[r] * self.usable_wh(r) - need >= 0.12 * self.usable_wh(r)

    def dispatch(self, t):
        self.plan_charging(t)
        if self.deferred:
            later = sorted(r for r in self.deferred if r not in self.paused)
            self.deferred.clear()
            self.repair(later, t, "deferred")
        stuck = [r for r in range(self.R) if self.waiting[r] and r not in self.paused and self.legs[r]]
        if stuck:                                     # robots with no plan are retried together, so they can unblock each other
            self.repair(stuck, t, "retry")
        avail = self.available()
        open_ = sorted((k for k in self.open if self.tasks[k]["released"] <= t), key=lambda k: (self.tasks[k]["priority"] != "urgent", self.tasks[k]["released"], k))
        if avail and open_:
            t0 = time.perf_counter()
            pairs, info = self.choose(avail, open_, t)
            self.stats["assign_ms"].append(round((time.perf_counter() - t0) * 1000, 2))
            for r, k, s in pairs:
                self.assign(r, k, s, t, info)
        for r in range(self.R):
            if self.status[r] == "charged":
                self.leave_charger(r, t)

    def station_options(self, pick):
        gs = [(self.h_field(s)[pick], i) for i, s in enumerate(self.L.stations)]
        gs.sort()
        return gs[:5]

    def choose(self, avail, open_, t):
        """-> [(robot, task, station index)] by the fleet's policy, and the inputs it saw."""
        park = self.res.park
        tk = {k: self.tasks[k] for k in open_[:600] if self.tasks[k]["pick"] not in park}   # a robot stopped on the pick face
        st = {k: [x for x in self.station_options(tk[k]["pick"]) if self.L.stations[x[1]] not in park] for k in tk}
        open_ = [k for k in open_[:600] if k in st and st[k] and st[k][0][0] < INF]
        dist = _Dist(self, avail)
        inbound = defaultdict(int)
        for r in range(self.R):
            for lg in self.legs[r]:
                if lg["kind"] == "drop":
                    inbound[lg["station"]] += 1
        info = {"robots": len(avail), "tasks": len(open_), "policy": self.policy,
                "inputs_hash": hashlib.sha256(json.dumps([[self.cell[r] for r in avail], open_[:400], t]).encode()).hexdigest()[:16]}
        ok = lambda r, k: dist[r][tk[k]["pick"]] < INF and self.energy_ok(r, dist[r][tk[k]["pick"]] + st[k][0][0] + 60)   # noqa: E731

        def station(k):                               # the baselines' rule: of the three nearest stations, the least busy
            s = min(st[k][:3], key=lambda ds: (inbound[ds[1]], ds[0]))[1]
            inbound[s] += 1
            return s
        if self.policy == "fifo":
            out, free = [], list(avail)
            for k in open_:
                if not free:
                    break
                cand = [r for r in free if ok(r, k)]
                if not cand:
                    continue
                r = min(cand, key=lambda r: (dist[r][tk[k]["pick"]], r))
                out.append((r, k, station(k)))
                free.remove(r)
            return out, info
        bonus = {k: self.bonus(tk[k], t) for k in open_}
        if self.policy == "greedy":
            cands = sorted(((dist[r][tk[k]["pick"]] + st[k][0][0] - bonus[k], r, k) for r in avail for k in open_ if ok(r, k)))
            out, ur, uk = [], set(), set()
            for _, r, k in cands:
                if r not in ur and k not in uk:
                    out.append((r, k, station(k)))
                    ur.add(r)
                    uk.add(k)
            return out, info
        return assign_cpsat(avail, open_, dist, tk, st, bonus, inbound, ok), info

    def assign(self, r, k, s, t, info):
        tk = self.tasks[k]
        legs = [{"goal": tk["pick"], "dwell": world.PICK_S, "kind": "pick", "task": k},
                {"goal": self.L.stations[s], "dwell": world.DROP_S, "kind": "drop", "task": k, "station": s},
                {"goal": self.home[r], "dwell": None, "kind": "home"}]
        was_charged = self.status[r] == "charged"
        if not self.try_plan(r, t, legs):
            return False
        if was_charged and self.robot_charger[r] is not None:
            self.occupant[self.robot_charger[r]] = None
            self.robot_charger[r] = None
        tk.update(status="assigned", robot=r, station=s, assigned_t=t)
        self.open.discard(k)
        self.task[r] = k
        self.status[r] = "task"
        self.stats["assignments"] += 1
        self.assign_log.append((t, k, self.ids[r], self.L.station_names[s], self.policy, info["inputs_hash"]))
        return True

    # --- the tick -------------------------------------------------------------------------------------------------------------------
    def tick(self, obs):
        """Telemetry and events at time t in; every robot's cell at t+1 out."""
        t = obs["t"]
        self.ingest(obs)
        self.milestones(t)
        for o in obs["orders"]:
            self.add_task(o)
        for ev in obs["events"]:
            self.on_event(ev, t)
        if t % self.epoch == 0:
            self.dispatch(t)
        if t % 60 == 0:
            self.rebuild(t)
        return [self.expected(r, t + 1) for r in range(self.R)]

    def flags(self, t):
        loaded = [bool(self.task[r] and self.tasks[self.task[r]]["status"] == "picked") for r in range(self.R)]
        dwell = [bool(self.legs[r] and self.legs[r][0]["kind"] == "pick" and self.cell[r] == self.legs[r][0]["goal"]) for r in range(self.R)]
        return loaded, dwell

    def rebuild(self, t):
        """Drop reservations in the past."""
        self.res = Reservations(self.N)
        for r in range(self.R):
            p, t0 = self.plan[r], self.plan_t0[r]
            i = max(0, t - t0)
            if i >= len(p):
                self.plan_t0[r], self.plan[r] = t, [p[-1]]
            else:
                self.plan_t0[r], self.plan[r] = t0 + i, p[i:]
            self.res.add(r, self.plan_t0[r], self.plan[r])


class _Dist:
    """dist[r][cell]: robot r's distance to a pick cell, read from the pick's own field (cached across epochs)."""

    def __init__(self, fleet, robots):
        self.f, self.rows = fleet, {r: _Row(fleet, fleet.cell[r]) for r in robots}

    def __getitem__(self, r):
        return self.rows[r]


class _Row:
    def __init__(self, fleet, cell):
        self.f, self.cell = fleet, cell

    def __getitem__(self, pick):
        return self.f.h_field(pick)[self.cell]


# --- assignment by CP-SAT ---------------------------------------------------------------------------------------------------------
def assign_cpsat(avail, open_, dist, tk, st, bonus, inbound, ok, per_robot=25, station_cap=2):
    """Robots x tasks x pack stations in one model: each robot at most one task, each task at most one robot and then
    exactly one station, at most `station_cap` new drops per station per epoch; maximise value (a base, urgency, closeness
    to due) minus empty travel, loaded travel and a queueing penalty for robots already inbound to the station."""
    from ortools.sat.python import cp_model
    m = cp_model.CpModel()
    x, y = {}, {}
    urgent = [k for k in open_ if tk[k]["priority"] == "urgent"]
    for r in avail:
        ranked = sorted((k for k in open_ if ok(r, k)), key=lambda k: dist[r][tk[k]["pick"]] + st[k][0][0] - bonus[k])
        for k in list(dict.fromkeys(ranked[:per_robot] + [k for k in urgent if ok(r, k)])):
            x[r, k] = m.new_bool_var(f"x{r}_{k}")
    if not x:
        return []
    tasks = sorted({k for _, k in x}, key=open_.index)
    for k in tasks:
        for d, s in st[k]:
            y[k, s] = m.new_bool_var(f"y{k}_{s}")
        m.add(sum(y[k, s] for _, s in st[k]) == sum(v for (r, kk), v in x.items() if kk == k))
        m.add_at_most_one(v for (r, kk), v in x.items() if kk == k)
    for r in avail:
        vs = [v for (rr, k), v in x.items() if rr == r]
        if vs:
            m.add_at_most_one(vs)
    for s in {s for (_, s) in y}:
        m.add(sum(v for (k, ss), v in y.items() if ss == s) <= station_cap)
    m.maximize(sum(v * (bonus[k] - dist[r][tk[k]["pick"]]) for (r, k), v in x.items())
               - sum(y[k, s] * (d + 4 * inbound[s]) for k in tasks for d, s in st[k]))
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_deterministic_time = 2.0
    if solver.solve(m) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return []
    out = []
    for (r, k), v in x.items():
        if solver.value(v):
            s = next(s for _, s in st[k] if solver.value(y[k, s]))
            out.append((r, k, s))
    out.sort(key=lambda p: (tk[p[1]]["priority"] != "urgent", tk[p[1]]["due"]))
    return out


# --- running the floor under the controller ------------------------------------------------------------------------------------
def pct(xs, q):
    return round(float(np.percentile(xs, q)), 2) if len(xs) else None


def counters(fleet, floor):
    done = [tk for tk in fleet.tasks.values() if tk["status"] == "done"]
    return {"t": floor.t, "moved": sum(floor.moved), "moved_loaded": sum(floor.moved_loaded), "violations": len(floor.violations),
            "checked": floor.checked, "repairs": len(fleet.stats["repairs"]), "assign": len(fleet.stats["assign_ms"]),
            "done": len(done), "arrived": len(fleet.tasks), "flat": floor.flat, "plan_fail": fleet.stats["plan_fail"],
            "dstar": len(fleet.fields.repairs)}


def simulate(floor, fleet, seconds, bucket=30, heat=None, hook=None):
    """Run `seconds` steps: the floor reports, the fleet decides, the floor moves and checks. Returns what happened in the
    window, measured, plus a heat map of cell visits. `hook(floor, fleet)` runs before each step (operator actions)."""
    start = counters(fleet, floor)
    t_from = floor.t
    heat = heat if heat is not None else [0] * fleet.L.n
    ticks, buckets = [], []
    b = {"t": t_from, "arrived": 0, "done": 0, "moving": 0, "violations": 0}
    done_before = {k for k, tk in fleet.tasks.items() if tk["status"] == "done"}
    for _ in range(seconds):
        if hook:
            hook(floor, fleet)
        w0 = time.perf_counter()
        obs = floor.observe()
        n_tasks = len(fleet.tasks)
        cmd = fleet.tick(obs)
        loaded, dwell = fleet.flags(obs["t"])
        found = floor.step(cmd, loaded, dwell)
        ticks.append((time.perf_counter() - w0) * 1000)
        b["arrived"] += len(fleet.tasks) - n_tasks
        b["moving"] += sum(a != c for a, c in zip(obs["pos"], cmd))
        b["violations"] += len(found)
        for c in cmd:
            heat[c] += 1
        if floor.t % bucket == 0:
            b["done"] = sum(1 for tk in fleet.tasks.values() if tk["status"] == "done" and b["t"] < tk["done_t"] <= floor.t)
            b["moving"] = round(b["moving"] / bucket, 1)
            b["t_end"] = floor.t
            buckets.append(b)
            b = {"t": floor.t, "arrived": 0, "done": 0, "moving": 0, "violations": 0}
    sync(floor, fleet)                    # count what finished on the window's last second in this window, not in neither
    return measure(fleet, floor, start, t_from, ticks, buckets, done_before, heat)


def measure(fleet, floor, start, t_from, ticks, buckets, done_before, heat):
    end = counters(fleet, floor)
    hours = max(1, floor.t - t_from) / 3600
    done = [tk for k, tk in fleet.tasks.items() if tk["status"] == "done" and k not in done_before]
    on_time = [tk for tk in done if tk["done_t"] <= tk["due"]]
    overdue = [tk for tk in fleet.tasks.values() if tk["status"] != "done" and tk["due"] < floor.t]
    urgent = [tk for tk in fleet.tasks.values() if tk["priority"] == "urgent"]
    reps = [r for r in fleet.stats["repairs"][start["repairs"]:] if r["reason"] not in ("retry", "deferred")]
    deferred = [r for r in fleet.stats["repairs"][start["repairs"]:] if r["reason"] == "deferred"]
    retries = [r for r in fleet.stats["repairs"][start["repairs"]:] if r["reason"] == "retry"]
    per = [x for r in reps for x in r["per_robot_ms"]]
    moved = end["moved"] - start["moved"]
    return {
        "from_t": t_from, "to_t": floor.t, "policy": fleet.policy,
        "orders_arrived": end["arrived"] - start["arrived"], "orders_completed": len(done),
        "throughput_per_hour": round(len(done) / hours), "completed_on_time": len(on_time),
        "sla_hit_rate": round(len(on_time) / len(done), 4) if done else None, "overdue_open": len(overdue),
        "open_backlog": sum(1 for tk in fleet.tasks.values() if tk["status"] in ("open", "assigned")),
        "held_tasks": sum(1 for tk in fleet.tasks.values() if tk["status"] == "held"),
        "urgent": [{"id": tk["id"], "location": tk["location"], "released": tk["released"], "due": tk["due"], "done_t": tk["done_t"],
                    "status": tk["status"], "robot": fleet.ids[tk["robot"]] if tk["robot"] is not None else None} for tk in urgent],
        "distance_cells": moved, "distance_m": round(moved * world.CELL_M), "loaded_share": round((end["moved_loaded"] - start["moved_loaded"]) / max(1, moved), 3),
        "cells_per_order": round(moved / len(done), 1) if done else None,
        "collisions": end["violations"] - start["violations"], "robot_steps_checked": end["checked"] - start["checked"],
        "violations": [{"t": v[0], "kind": v[1], "robots": v[2], "cell": v[3]} for v in floor.violations[start["violations"]:][:20]],
        "flat_battery_steps": end["flat"] - start["flat"],
        "repairs": [{k: v for k, v in r.items() if k != "paths"} for r in reps][:200],
        "replan": {"events": len(reps), "robots": sum(r["robots"] for r in reps), "event_ms_p50": pct([r["ms"] for r in reps], 50),
                   "event_ms_p95": pct([r["ms"] for r in reps], 95), "robot_ms_p50": pct(per, 50), "robot_ms_p95": pct(per, 95),
                   "methods": dict(sorted({m: sum(1 for r in reps if r["method"] == m) for m in {r["method"] for r in reps}}.items()))},
        "tick_ms": {"p50": pct(ticks, 50), "p95": pct(ticks, 95), "max": round(max(ticks), 1) if ticks else None, "over_1s": sum(x > 1000 for x in ticks)},
        "assign_ms": {"p50": pct(fleet.stats["assign_ms"][start["assign"]:], 50), "p95": pct(fleet.stats["assign_ms"][start["assign"]:], 95)},
        "dstar_repairs": {"n": end["dstar"] - start["dstar"], "ms_p50": pct([x[0] for x in fleet.fields.repairs[start["dstar"]:]], 50),
                          "touched_p50": pct([x[1] for x in fleet.fields.repairs[start["dstar"]:]], 50)},
        "plan_failures": end["plan_fail"] - start["plan_fail"], "waiting_retries": len(retries),
        "deferred_replans": {"events": len(deferred), "robots": sum(r["robots"] for r in deferred), "ms_p50": pct([r["ms"] for r in deferred], 50),
                             "ms_p95": pct([r["ms"] for r in deferred], 95)},
        "status": dict(sorted(_count(fleet.status).items())), "waiting_robots": sum(fleet.waiting),
        "buckets": buckets, "heat": heat,
    }


def _count(xs):
    out = defaultdict(int)
    for x in xs:
        out[x] += 1
    return out


def new_world(seed, layout=None, policy="cpsat", soh_est=None):
    """A floor and a fleet at the start of a shift: robots at home, charge levels mid-shift."""
    L = layout or world.Layout()
    robots = world.fleet(seed, L)
    _, soh = world.battery_history(seed, robots)
    floor = world.Floor(L, robots, soh, seed)
    fleet = Fleet(L, robots, policy, soh_est)
    for i, r in enumerate(robots):
        fleet.soc[i] = r["soc"]
    return floor, fleet


def sync(floor, fleet):
    """Bring the fleet's view up to the floor's clock before an out-of-band command (pause, resume, new tasks, a plan):
    between ticks the last telemetry the fleet saw is one step old."""
    fleet.ingest({"t": floor.t, "pos": list(floor.pos), "soc": list(floor.soc)})
    fleet.milestones(floor.t)
    return floor.t


def fork(floor, fleet, policy=None, keep_future=False):
    """A copy to project forward. Unless keep_future, the copy's generator knows nothing ahead: no new orders, no events."""
    f2 = copy.deepcopy(floor)
    if not keep_future:
        f2.told, f2.wave = [], None
    fl2 = copy.deepcopy(fleet)
    if policy:
        fl2.policy = policy
    return f2, fl2


# --- battery degradation ---------------------------------------------------------------------------------------------------
BATTERY_VERSION = "soh-sqrt-stress-vendor-prior-1"
EOL_SOH = 0.80


def battery_features(cycles):
    """cycles: [(day, dod, temp_c, capacity_wh)] sorted by day (day 0 = today, negative = past). -> arrays day, sqrt of
    cumulative cycle stress (deeper and hotter cycles weigh more), measured capacity."""
    day = np.array([c[0] for c in cycles], float)
    s = np.cumsum([world.stress(c[1], c[2]) for c in cycles])
    return day, np.sqrt(s), np.array([c[3] for c in cycles], float), s


def fit_batteries(histories, nominal, vendor, age_days, cutoff=0.0):
    """Fit fade = 1 - capacity/nominal = theta_r * sqrt(stress) + kappa_v * age_years on cycles before `cutoff` (days
    from today): a calendar rate and a stress coefficient pooled per vendor, then each pack's own coefficient shrunk
    toward its vendor's (more cycles, less shrinkage). Returns {robot: params}."""
    pooled = defaultdict(lambda: [[], []])
    data = {}
    for r, cyc in histories.items():
        cyc = [c for c in cyc if c[0] < cutoff]
        if len(cyc) < 10:
            continue
        day, x, cap, s = battery_features(cyc)
        age = (age_days[r] + day) / 365.0
        y = 1 - cap / nominal[r]
        data[r] = (x, age, y, day, s)
        pooled[vendor[r]][0].append(np.column_stack([x, age]))
        pooled[vendor[r]][1].append(y)
    prior = {}
    for v, (X, Y) in pooled.items():
        X, Y = np.vstack(X), np.concatenate(Y)
        coef, *_ = np.linalg.lstsq(X, Y, rcond=None)
        prior[v] = (float(coef[0]), max(0.0, float(coef[1])))
    out = {}
    for r, (x, age, y, day, s) in data.items():
        th_v, kap = prior[vendor[r]]
        resid = y - kap * age
        lam = 0.25 * float(np.sum(x ** 2)) / max(1, len(x)) * 40          # worth about 40 cycles of evidence
        theta = float((np.sum(x * resid) + lam * th_v) / (np.sum(x ** 2) + lam))
        recent = day >= day.max() - 60
        rate = float((s[-1] - s[recent][0]) / max(1.0, day[-1] - day[recent][0])) if recent.sum() > 1 else 0.0
        out[r] = {"theta": theta, "kappa": kap, "theta_vendor": th_v, "stress_now": float(s[-1]), "stress_per_day": rate,
                  "age_years": float(age[-1]), "last_day": float(day[-1]), "cycles": int(len(x))}
    return out


def forecast_soh(p, days_ahead):
    """State of health `days_ahead` after the last fitted cycle, assuming the pack keeps its recent duty."""
    s = p["stress_now"] + p["stress_per_day"] * days_ahead
    return float(1 - p["theta"] * math.sqrt(max(s, 0.0)) - p["kappa"] * (p["age_years"] + days_ahead / 365.0))


def baseline_soh(cycles, nominal, days_ahead, cutoff=0.0, window=90):
    """Baseline: a straight line through the pack's own measured capacity over its last `window` days, extended."""
    cyc = [c for c in cycles if c[0] < cutoff]
    day = np.array([c[0] for c in cyc], float)
    cap = np.array([c[3] for c in cyc], float) / nominal
    keep = day >= day.max() - window
    if keep.sum() < 3:
        return float(cap[-1])
    slope, icept = np.polyfit(day[keep], cap[keep], 1)
    return float(icept + slope * (day[keep].max() + days_ahead))


def days_to_eol(p, horizon=1500):
    """Days from the last fitted cycle until the forecast crosses EOL_SOH, or None within the horizon."""
    if forecast_soh(p, 0) <= EOL_SOH:
        return 0
    lo, hi = 0, horizon
    if forecast_soh(p, hi) > EOL_SOH:
        return None
    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (mid, hi) if forecast_soh(p, mid) > EOL_SOH else (lo, mid)
    return hi


def battery_backtest(histories, nominal, vendor, age_days, holdout=120):
    """The model and the baseline fitted on everything but the last `holdout` days of each pack, scored on what the pack
    measured at the end (mean of its last five cycles, which damps the measurement noise)."""
    fit = fit_batteries(histories, nominal, vendor, age_days, cutoff=-holdout)
    err_m, err_b, rows = [], [], []
    for r, p in fit.items():
        cyc = histories[r]
        tail = [c for c in cyc if c[0] >= -holdout]
        if len(tail) < 5:
            continue
        actual = float(np.mean([c[3] for c in cyc[-5:]])) / nominal[r]
        ahead = cyc[-1][0] - p["last_day"]
        m, b = forecast_soh(p, ahead), baseline_soh(cyc, nominal[r], ahead, cutoff=-holdout)
        err_m.append(abs(m - actual))
        err_b.append(abs(b - actual))
        rows.append((r, actual, m, b))
    eol_true = {r for r, a, _, _ in rows if a < EOL_SOH}
    eol_m = {r for r, _, m, _ in rows if m < EOL_SOH}
    eol_b = {r for r, _, _, b in rows if b < EOL_SOH}
    score = lambda pred: {"precision": round(len(pred & eol_true) / len(pred), 3) if pred else None,          # noqa: E731
                          "recall": round(len(pred & eol_true) / len(eol_true), 3) if eol_true else None}
    return {"packs": len(rows), "holdout_days": holdout, "mae_points": round(100 * float(np.mean(err_m)), 2),
            "baseline_mae_points": round(100 * float(np.mean(err_b)), 2),
            "p90_points": round(100 * float(np.quantile(err_m, 0.9)), 2), "baseline_p90_points": round(100 * float(np.quantile(err_b, 0.9)), 2),
            "below_eol_at_end": len(eol_true), "eol_model": score(eol_m), "eol_baseline": score(eol_b)}


# --- recompute: alternatives projected forward ---------------------------------------------------------------------------------
def preemption(fleet, t, tasks, bump_cost=20):
    """Who should take each of `tasks` (urgent, open) if robots already heading to an ordinary pick may be taken off it:
    a small CP-SAT assignment over available robots and robots on their way to a normal pick (not yet picked), minimising
    distance plus `bump_cost` cells for every robot taken off its task. -> [(robot, task, station, bumped task or None)]."""
    from ortools.sat.python import cp_model
    cands = []
    for r in range(fleet.R):
        if r in fleet.paused or fleet.waiting[r] or fleet.needs_charge[r]:
            continue
        k = fleet.task[r]
        if fleet.status[r] in ("idle", "home", "charged"):
            cands.append((r, None))
        elif k and fleet.tasks[k]["status"] == "assigned" and fleet.tasks[k]["priority"] != "urgent":
            cands.append((r, k))
    m = cp_model.CpModel()
    x = {}
    for r, bumped in cands:
        for k in tasks:
            d = fleet.h_field(fleet.tasks[k]["pick"])[fleet.cell[r]]
            if d < INF and fleet.energy_ok(r, d + 120):
                x[r, k] = (m.new_bool_var(f"x{r}_{k}"), d + (bump_cost if bumped else 0))
    for k in tasks:
        m.add(sum(v for (r, kk), (v, _) in x.items() if kk == k) == 1)
    for r, _ in cands:
        vs = [v for (rr, k), (v, _) in x.items() if rr == r]
        if vs:
            m.add_at_most_one(vs)
    m.minimize(sum(v * c for v, c in x.values()))
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    solver.parameters.max_deterministic_time = 2.0
    if solver.solve(m) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return []
    bumped_of = dict(cands)
    out = []
    for (r, k), (v, _) in x.items():
        if solver.value(v):
            out.append((r, k, fleet.station_options(fleet.tasks[k]["pick"])[0][1], bumped_of[r]))
    return out


def apply_preemption(fleet, t, pairs):
    done = []
    for r, k, s, bumped in pairs:
        if bumped:
            fleet.release_task(r)
            fleet.tasks[bumped]["bumped"] += 1
            fleet.stats["bumped"] += 1
        if fleet.assign(r, k, s, t, {"inputs_hash": "preemption"}):
            done.append((fleet.ids[r], k, bumped))
    fleet.version += 1
    return done


def project(floor, fleet, horizon, watch, change=None):
    """Run a copy forward `horizon` seconds with nothing new arriving (the copy knows no future orders or events) and
    report what happens to the tasks in `watch`."""
    f2, fl2 = fork(floor, fleet)
    applied = change(fl2) if change else None
    m = simulate(f2, fl2, horizon)
    rows = []
    for k in watch:
        tk = fl2.tasks[k]
        rows.append({"id": k, "priority": tk["priority"], "location": tk["location"], "due": tk["due"], "done_t": tk["done_t"],
                     "robot": fl2.ids[tk["robot"]] if tk["robot"] is not None else None,
                     "on_time": tk["done_t"] is not None and tk["done_t"] <= tk["due"],
                     "late_by": (tk["done_t"] or (floor.t + horizon)) - tk["due"] if not (tk["done_t"] is not None and tk["done_t"] <= tk["due"]) else 0})
    return {"tasks": rows, "completed": m["orders_completed"], "collisions": m["collisions"], "distance_cells": m["distance_cells"],
            "applied": applied}
