"""A synthetic warehouse and its robots: the floor the orchestrator drives, and the generator that makes things happen to it.

The layout is a grid graph. Parking lanes with robot bays and chargers at the top; a two-cell cross-aisle; three storage
blocks of single-width aisles between racks, separated by cross-aisles; pack stations at the bottom. A robot stands in an
aisle cell to pick from the rack on either side. Bays (homes, chargers, pack stations) are dead ends: only the robot that
is going there may enter one.

The floor is time-stepped (one step is one second, one cell is 1.2 m, a robot moves one cell a step or waits). It executes
exactly the moves it is commanded, and its collision checker is the source of truth for the invariant: two robots in one
cell at one time (vertex), two robots swapping cells in one step (edge swap), a robot entering a closed aisle from outside,
a paused robot moving, or a move that is not along an edge. Batteries drain with what a robot does and charge on a working
charger.

The generator decides what happens: orders arrive (Poisson, at a rate it is told; pick locations skewed to fast movers near
the pack stations), aisles get blocked (a forklift, a spill) and chargers fail when it is told so, and each battery fades
by hidden parameters. The orchestrator sees what a real one would: telemetry (cell, state of charge), orders as they
arrive, an aisle-closure report and a charger fault as they happen, and each battery's charge-cycle records. Every random
draw is keyed (seed, purpose, index), so a run can be repeated exactly under a different policy.
"""
import math

import numpy as np

PICK_S, DROP_S = 8, 5            # dwell at a pick face and at a pack station, seconds
SLA_NORMAL_S, SLA_URGENT_S = 600, 120
CELL_M = 1.2
VENDORS = {                       # invented vendor profiles: pack size and how fast its chemistry fades
    "Kestrel K5": {"capacity_wh": 1500, "fade": 0.0042, "share": 0.48},
    "Orbis L2": {"capacity_wh": 1800, "fade": 0.0034, "share": 0.32},
    "Talon R3": {"capacity_wh": 1200, "fade": 0.0055, "share": 0.20},
}
POWER_W = {"idle": 30.0, "move": 220.0, "move_loaded": 300.0, "pick": 150.0}
CHARGE_W = 1500.0
CALENDAR_FADE = 0.012            # SoH lost per year on the shelf, whatever the use


class Layout:
    """The warehouse graph. Cells are integers; `xy[c]` is (x, y); `nbrs[c]` the cells one move away."""

    def __init__(self, n_aisles=41, block_rows=12, blocks=3, n_stations=20, n_chargers=24, park_rows=4, n_robots=250, groups=4):
        self.params = dict(n_aisles=n_aisles, block_rows=block_rows, blocks=blocks, n_stations=n_stations, n_chargers=n_chargers,
                           park_rows=park_rows, n_robots=n_robots, groups=groups)
        sizes = [n_aisles // groups + (1 if g < n_aisles % groups else 0) for g in range(groups)]
        cols = ["hwy", "hwy"]                        # two-cell travel highways (no pick faces) between groups of aisles
        for na in sizes:
            for a in range(na):
                cols += ["rack", "aisle", "rack"]
            cols += ["hwy", "hwy"]
        W = len(cols)
        kind, zone = {}, {}
        y = 0
        park = list(range(y, y + park_rows))
        y += park_rows
        cross_rows = []
        block_ys = []
        for b in range(blocks + 1):
            cross_rows.append((y, y + 1))
            y += 2
            if b < blocks:
                block_ys.append(list(range(y, y + block_rows)))
                y += block_rows
        bay_row = y
        self.W, self.H = W, y + 1
        for py in park:
            for x in range(W):
                lane = x % 3 == 0 or (x % 3 == 2 and x + 1 >= W)
                kind[(x, py)] = "lane" if lane else "bay"
                zone[(x, py)] = "PARK"
        for i, rows in enumerate(cross_rows):
            for r in rows:
                for x in range(W):
                    kind[(x, r)] = "cross"
                    zone[(x, r)] = f"X{i}"
        letters = "ABCDEFGH"[:blocks]
        aisle_xs = [x for x, k in enumerate(cols) if k == "aisle"]
        hwy_xs = [x for x, k in enumerate(cols) if k == "hwy"]
        for b, ys in enumerate(block_ys):
            for yy in ys:
                for n, x in enumerate(aisle_xs):
                    kind[(x, yy)] = "aisle"
                    zone[(x, yy)] = f"{letters[b]}-{n + 1:02d}"
                for x in hwy_xs:
                    kind[(x, yy)] = "cross"
                    zone[(x, yy)] = f"H{hwy_xs.index(x) // 2 + 1}"
        station_xs = [int(round(v)) for v in np.linspace(3, W - 4, n_stations)]
        for x in station_xs:
            kind[(x, bay_row)] = "station"
            zone[(x, bay_row)] = "PACK"
        cells = sorted(kind, key=lambda p: (p[1], p[0]))
        self.xy = cells
        self.idx = {p: i for i, p in enumerate(cells)}
        self.n = len(cells)
        self.kind = [kind[p] for p in cells]
        self.zone = [zone[p] for p in cells]
        nb = [[] for _ in cells]

        def link(a, b):
            if a in self.idx and b in self.idx:
                i, j = self.idx[a], self.idx[b]
                if j not in nb[i]:
                    nb[i].append(j)
                    nb[j].append(i)
        for (x, yy), k in kind.items():
            if k == "lane":
                link((x, yy), (x, yy + 1))            # down the lane, and the last lane cell onto the top cross-aisle
            elif k == "bay":
                link((x, yy), (x - 1, yy) if x % 3 == 1 else (x + 1, yy))
            elif k == "cross":
                if kind.get((x + 1, yy)) == "cross":
                    link((x, yy), (x + 1, yy))
                if kind.get((x, yy + 1)) in ("cross", "aisle"):
                    link((x, yy), (x, yy + 1))
            elif k == "aisle":
                link((x, yy), (x, yy + 1))
            elif k == "station":
                link((x, yy), (x, yy - 1))
        self.nbrs = [tuple(sorted(v)) for v in nb]
        self.stations = [self.idx[(x, bay_row)] for x in station_xs]
        self.station_names = [f"PS-{i + 1:02d}" for i in range(n_stations)]
        bays_by_row = {py: [self.idx[(x, py)] for x in range(W) if kind[(x, py)] == "bay"] for py in park}
        near = bays_by_row[park[-1]]                  # chargers on the bay row nearest the cross-aisle, spread evenly
        pick = [near[int(i)] for i in np.linspace(0, len(near) - 1, n_chargers)]
        self.chargers = pick
        self.charger_names = [f"CH-{i + 1:02d}" for i in range(n_chargers)]
        homes = [c for py in park for c in bays_by_row[py] if c not in set(pick)]
        if len(homes) < n_robots:
            raise ValueError("not enough parking bays for the fleet")
        step = len(homes) / n_robots
        self.homes = [homes[int(i * step)] for i in range(n_robots)]
        self.bay = [k in ("bay", "station") for k in self.kind]
        self.aisles = {}
        for c, (k, z) in enumerate(zip(self.kind, self.zone)):
            if k == "aisle":
                self.aisles.setdefault(z, []).append(c)
        for z in self.aisles:
            self.aisles[z].sort(key=lambda c: self.xy[c][1])
        self.aisle_exits = {}
        for z, cs in self.aisles.items():
            x, y0 = self.xy[cs[0]]
            y1 = self.xy[cs[-1]][1]
            self.aisle_exits[z] = (self.idx[(x, y0 - 1)], self.idx[(x, y1 + 1)])
        self.picks = [c for c in range(self.n) if self.kind[c] == "aisle"]
        ys = np.array([self.xy[c][1] for c in self.picks], float)
        w = np.exp((ys - ys.max()) / (0.45 * (ys.max() - ys.min())))           # fast movers slotted near the pack stations
        self.pick_weight = w / w.sum()
        self.station_of = {c: i for i, c in enumerate(self.stations)}
        self.charger_of = {c: i for i, c in enumerate(self.chargers)}

    def location(self, c):
        """A pick cell's location code, e.g. A-14-07 (block A, aisle 14, position 7 from the top)."""
        z = self.zone[c]
        return f"{z}-{self.aisles[z].index(c) + 1:02d}"

    def cell_of_location(self, code):
        try:
            z, pos = code.rsplit("-", 1)
            return self.aisles[z][int(pos) - 1]
        except (KeyError, ValueError, IndexError):
            return None

    def grid(self):
        """One character per cell for the UI: '#' rack, 'a' aisle, 'x' cross-aisle, 'l' parking lane, 'b' bay, 'c' charger, 's' station."""
        rows = [["#"] * self.W for _ in range(self.H)]
        code = {"aisle": "a", "cross": "x", "lane": "l", "bay": "b", "station": "s"}
        for c, (x, y) in enumerate(self.xy):
            rows[y][x] = code[self.kind[c]]
        for c in self.chargers:
            x, y = self.xy[c]
            rows[y][x] = "c"
        for y in range(self.H):                       # cells that are neither graph nodes nor racks (beside the station row)
            for x in range(self.W):
                if rows[y][x] == "#" and not any(lo <= y <= lo + self.params["block_rows"] - 1 for lo in self.block_starts()):
                    rows[y][x] = " "
        return ["".join(r) for r in rows]

    def block_starts(self):
        return sorted({self.xy[cs[0]][1] for cs in self.aisles.values()})

    def edges(self):
        return [(a, b) for a in range(self.n) for b in self.nbrs[a] if a < b]


# --- the fleet and its batteries -------------------------------------------------------------------------------------------
def fleet(seed, layout):
    """Robots with a vendor, a home bay, a battery with hidden fade parameters, and a state of charge mid-shift."""
    rng = np.random.default_rng([seed, 11])
    names = list(VENDORS)
    p = np.array([VENDORS[v]["share"] for v in names])
    out = []
    for i, home in enumerate(layout.homes):
        v = names[rng.choice(len(names), p=p)]
        out.append({"id": f"R-{i + 1:03d}", "vendor": v, "home": home, "capacity_wh": VENDORS[v]["capacity_wh"],
                    "fade_mult": float(np.exp(rng.normal(0, 0.18))),             # this pack against its vendor's chemistry
                    "knee": bool(rng.random() < 0.12),                             # some packs fade faster past ~86% (unmodelled)
                    "days": int(rng.integers(90, 1000)), "cycles_per_day": float(rng.uniform(0.9, 1.6)),
                    "duty": float(rng.uniform(0.0, 1.0)),                          # how hard this robot's work usually is
                    "soc": float(rng.uniform(0.17, 0.95))})
    return out


def stress(dod, temp_c):
    """Fade weight of one charge cycle: deeper and hotter cycles age a cell more."""
    return dod ** 1.3 * math.exp(0.05 * (temp_c - 25.0))


def battery_history(seed, robots):
    """Each robot's charge cycles up to today: depth of discharge, pack temperature and the capacity measured at the end of
    the cycle (noisy). Returns (rows, true SoH today per robot). The fade law and its parameters are the generator's truth."""
    rows, soh_now = [], {}
    for k, r in enumerate(robots):
        rng = np.random.default_rng([seed, 23, k])
        a = VENDORS[r["vendor"]]["fade"] * r["fade_mult"]
        n = int(r["days"] * r["cycles_per_day"])
        day = np.sort(rng.uniform(0, r["days"], n))
        dod = np.clip(rng.beta(4, 4, n) * (0.55 + 0.4 * r["duty"]) + 0.1, 0.1, 0.95)
        temp = rng.normal(27 + 5 * r["duty"], 2.0, n)
        s = np.cumsum([stress(d, tc) for d, tc in zip(dod, temp)])
        soh = 1 - a * np.sqrt(s) - CALENDAR_FADE * day / 365
        if r["knee"]:
            past = soh < 0.86
            if past.any():
                i0 = int(np.argmax(past))
                soh[i0:] -= 2.2 * a * (np.sqrt(s[i0:]) - np.sqrt(s[i0]))
        meas = soh * r["capacity_wh"] + rng.normal(0, 0.006 * r["capacity_wh"], n)
        for i in range(n):
            rows.append((r["id"], i + 1, float(day[i] - r["days"]), float(dod[i]), float(temp[i]), float(meas[i])))
        soh_now[r["id"]] = float(soh[-1]) if n else 1.0
    return rows, soh_now


# --- orders ----------------------------------------------------------------------------------------------------------------
def arrivals(seed, layout, wave, t):
    """Orders released in second t of a wave: Poisson at the wave's rate, pick locations skewed to fast movers."""
    if not wave or t < wave["from_t"]:
        return []
    rng = np.random.default_rng([seed, 31, wave["id"], t])
    n = rng.poisson(wave["orders_per_hour"] / 3600.0)
    out = []
    for i in range(n):
        c = layout.picks[int(rng.choice(len(layout.picks), p=layout.pick_weight))]
        out.append({"id": f"W{wave['id']}-{t:05d}-{i}", "pick": c, "priority": "normal", "released": t, "due": t + SLA_NORMAL_S})
    return out


# --- the floor ---------------------------------------------------------------------------------------------------------------
class Floor:
    """The physical warehouse at time t: where every robot is, what each battery holds, which aisles are closed and which
    chargers work. `step(next_cells)` moves every robot one step as commanded and checks the result."""

    def __init__(self, layout, robots, soh, seed):
        self.L, self.seed, self.t = layout, seed, 0
        self.ids = [r["id"] for r in robots]
        self.pos = [r["home"] for r in robots]
        self.cap = [r["capacity_wh"] * soh[r["id"]] for r in robots]          # usable Wh today (true, hidden)
        self.soc = [r["soc"] for r in robots]
        self.closed = {}                    # cell -> zone, while an aisle is closed
        self.paused = set()
        self.charger_up = [True] * len(layout.chargers)
        self.told = []                      # what the generator was told (simulation truth)
        self.wave = None
        self.violations = []                # (t, kind, robots, cell)
        self.checked = 0                    # robot-steps checked
        self.moved = [0] * len(robots)
        self.moved_loaded = [0] * len(robots)
        self.loaded = [False] * len(robots)
        self.dwelling = [False] * len(robots)
        self.flat = 0                       # robot-steps spent with an empty battery

    # what the generator is told -------------------------------------------------------------------------------------------
    def tell(self, events):
        for e in events:
            self.told.append(dict(e))

    def set_wave(self, orders_per_hour, wave_id):
        self.wave = {"id": wave_id, "orders_per_hour": orders_per_hour, "from_t": self.t} if orders_per_hour else None

    # what the orchestrator observes at the start of step t -----------------------------------------------------------------
    def observe(self):
        t, events = self.t, []
        for e in self.told:
            if e["kind"] == "aisle_blocked" and e["at"] == t:
                cells = self.L.aisles[e["zone"]]
                for c in cells:
                    self.closed[c] = e["zone"]
                events.append({"kind": "aisle_closed", "zone": e["zone"], "cells": list(cells), "t": t})
            if e["kind"] == "aisle_blocked" and e.get("until") == t:
                for c in self.L.aisles[e["zone"]]:
                    self.closed.pop(c, None)
                events.append({"kind": "aisle_reopened", "zone": e["zone"], "cells": list(self.L.aisles[e["zone"]]), "t": t})
            if e["kind"] == "charger_fault" and e["at"] == t:
                i = self.L.charger_names.index(e["charger"])
                self.charger_up[i] = False
                events.append({"kind": "charger_fault", "charger": i, "t": t})
            if e["kind"] == "charger_fault" and e.get("until") == t:
                i = self.L.charger_names.index(e["charger"])
                self.charger_up[i] = True
                events.append({"kind": "charger_restored", "charger": i, "t": t})
        return {"t": t, "pos": list(self.pos), "soc": [round(s, 5) for s in self.soc], "events": events,
                "orders": arrivals(self.seed, self.L, self.wave, t)}

    def pause(self, i, on=True):
        (self.paused.add if on else self.paused.discard)(i)

    # one step ---------------------------------------------------------------------------------------------------------------
    def step(self, nxt, loaded=None, dwelling=None):
        """Move every robot to nxt[i] (its cell at t+1), check the result, account energy. Returns violations this step."""
        L, t, pos = self.L, self.t, self.pos
        loaded = loaded or self.loaded
        dwelling = dwelling or [False] * len(pos)
        found = []
        moved = list(nxt)
        for i, (a, b) in enumerate(zip(pos, nxt)):
            if i in self.paused and a != b:
                found.append((t, "paused_robot_moved", [self.ids[i]], b))
                moved[i] = a
            elif a != b and b not in L.nbrs[a]:
                found.append((t, "not_an_edge", [self.ids[i]], b))
                moved[i] = a
        seen = {}
        for i, b in enumerate(moved):
            if b in seen:
                found.append((t, "vertex", [self.ids[seen[b]], self.ids[i]], b))
            seen[b] = i
        going = {(a, b): i for i, (a, b) in enumerate(zip(pos, moved)) if a != b}
        for (a, b), i in going.items():
            j = going.get((b, a))
            if j is not None and i < j:
                found.append((t, "edge_swap", [self.ids[i], self.ids[j]], a))
        for i, (a, b) in enumerate(zip(pos, moved)):
            if b in self.closed and self.closed.get(a) != self.closed[b]:
                found.append((t, "entered_closed_aisle", [self.ids[i]], b))
        for i, (a, b) in enumerate(zip(pos, moved)):
            on_charger = L.charger_of.get(b)
            if a != b:
                self.moved[i] += 1
                self.moved_loaded[i] += bool(loaded[i])
                w = POWER_W["move_loaded" if loaded[i] else "move"]
            else:
                w = POWER_W["pick"] if dwelling[i] else POWER_W["idle"]
            if on_charger is not None and a == b and self.charger_up[on_charger] and self.soc[i] < 1.0:
                w = -CHARGE_W
            self.soc[i] = min(1.0, max(0.0, self.soc[i] - w / 3600.0 / self.cap[i]))
            if self.soc[i] <= 0:
                self.flat += 1
        self.pos = moved
        self.loaded = list(loaded)
        self.checked += len(pos)
        self.violations += found
        self.t += 1
        return found
