"""A synthetic metro radio access network: a core router, four aggregation routers (one per cluster), hub sites on fibre or
microwave backhaul to their aggregation router, tail sites on microwave behind the hubs, and three sectors of two cells
(LTE 1800 and NR 3500) on every site. Some sites have a standby microwave link to a hub elsewhere: the rerouting options.

Every 15 minutes each cell reports its counters (traffic delivered, PRB utilisation, connected users, latency, packet loss,
handover success, call drops, availability) and each link its own (utilisation, current capacity, latency, loss, errored
seconds); the network elements raise vendor alarms on thresholds, checked minute by minute, so a value hovering near a
threshold flaps and floods the alarm list, as real ones do.

Faults are physical and propagate down the topology: a degraded microwave link loses capacity and drops packets, and every
cell behind it sees the loss and the queueing; a site that loses mains power runs on battery for an hour, then it and every
site behind it go dark; a wrong neighbour table on one cell makes handovers into it fail from all its neighbours. The
generator knows the truth (which fault caused which alarm and which cell is impaired); the service only sees counters,
alarms and the configuration change log.

Every random draw is keyed by (seed, interval, purpose), so the same interval can be re-run with a different routing and
see the same traffic and noise: that is what makes a counterfactual a paired comparison.
"""
import math

import numpy as np

STEP_MIN = 15
PER_DAY = 96
PER_WEEK = 7 * PER_DAY
HISTORY_DAYS = 28
CLUSTERS = ["NE", "NW", "SW", "SE"]
CELL_KPIS = ["dl_mbps", "prb_util", "users", "latency_ms", "loss_pct", "ho_success_pct", "drop_pct", "available"]
LINK_KPIS = ["util", "capacity_mbps", "latency_ms", "loss_pct", "errored_s"]
BANDS = {"L": 100.0, "N": 400.0}          # cell capacity in Mbps: LTE 1800 (20 MHz), NR 3500 (100 MHz)
SECTORS = {"A": 30.0, "B": 150.0, "C": 270.0}
CAP = {"uplink": 20000.0, "hub_fibre": 10000.0, "hub_mw": 3000.0, "tail_mw": 1000.0, "alt_hub": 2000.0, "alt_tail": 1000.0}
# hourly traffic shape (peak = 1) by area and day type; interpolated to 15 minutes
PROFILE = {
    ("residential", 0): [.25, .18, .14, .12, .12, .15, .25, .40, .50, .50, .52, .55, .60, .58, .56, .58, .65, .75, .88, .97, 1.0, .95, .75, .45],
    ("residential", 1): [.35, .25, .18, .14, .12, .12, .15, .25, .40, .55, .65, .72, .75, .75, .74, .75, .78, .82, .90, .97, 1.0, .95, .80, .55],
    ("business", 0): [.10, .07, .06, .05, .06, .10, .25, .55, .80, .92, .97, 1.0, .95, .97, 1.0, .97, .90, .75, .55, .40, .32, .25, .18, .12],
    ("business", 1): [.10, .08, .06, .05, .05, .07, .10, .15, .22, .30, .35, .38, .40, .40, .38, .36, .35, .33, .30, .28, .25, .20, .15, .12],
}
PROFILE[("mixed", 0)] = [(a + b) / 2 for a, b in zip(PROFILE[("residential", 0)], PROFILE[("business", 0)])]
PROFILE[("mixed", 1)] = [(a + b) / 2 for a, b in zip(PROFILE[("residential", 1)], PROFILE[("business", 1)])]
GROWTH_PER_WEEK = 1.004
BATTERY_INTERVALS = 4                     # a site on battery lasts an hour
# vendor alarm thresholds, checked every minute: (kpi, comparison, threshold, alarm type, severity)
CELL_ALARMS = [("latency_ms", ">", 25.0, "S1_LATENCY_HIGH", "major"), ("loss_pct", ">", 0.5, "PACKET_LOSS_HIGH", "major"),
               ("ho_success_pct", "<", 95.0, "HO_FAILURE_RATE_HIGH", "major"), ("drop_pct", ">", 1.5, "CALL_DROP_RATE_HIGH", "minor"),
               ("prb_util", ">", 0.95, "RRC_CONGESTION", "minor")]
LINK_ALARMS = [("loss_pct", ">", 0.3, "LINK_BER_HIGH", "major"), ("util", ">", 0.9, "LINK_UTIL_HIGH", "minor")]
BACKGROUND = [("VSWR_HIGH", "minor"), ("BOARD_TEMP_HIGH", "warning"), ("GPS_SYNC_DEGRADED", "minor")]
FAULT_KINDS = ["backhaul_degradation", "fibre_degradation", "rain_fade", "site_power_outage", "handover_misconfig", "sleeping_cell"]
MAX_FLAPS = 4                             # the element damps an alarm after four raises in an interval


def interval_of(day, hour, minute=0):
    return day * PER_DAY + hour * 4 + minute // STEP_MIN


# --- the network -------------------------------------------------------------------------------------------------------
def network(seed):
    """Topology, capacities, traffic bases and neighbour relations for one metro. Deterministic in the seed."""
    rng = np.random.default_rng([seed, 1])
    nodes = {"CORE-01": {"id": "CORE-01", "kind": "core", "x": 0.0, "y": 0.0}}
    links, sites = [], []
    for k, cl in enumerate(CLUSTERS):
        ang = math.radians(45 + 90 * k) + rng.normal(0, 0.12)
        agg = f"AGG-{cl}"
        ax, ay = 4.6 * math.cos(ang), 4.6 * math.sin(ang)
        nodes[agg] = {"id": agg, "kind": "agg", "x": round(ax, 2), "y": round(ay, 2), "cluster": cl}
        links.append({"id": f"L-{agg}-CORE", "a": agg, "b": "CORE-01", "medium": "fibre", "capacity": CAP["uplink"], "role": "uplink"})
        for h in range(3):
            ha = ang + math.radians((h - 1) * 55) + rng.normal(0, 0.1)
            hr = 2.4 + rng.normal(0, 0.3)
            hub = {"x": ax + hr * math.cos(ha), "y": ay + hr * math.sin(ha), "role": "hub", "cluster": cl, "parent": agg,
                   "medium": "fibre" if rng.random() < 0.45 else "mw"}
            sites.append(hub)
            for _ in range(int(rng.integers(2, 4))):
                ta = rng.uniform(0, 2 * math.pi)
                tr = 1.2 + rng.uniform(0, 0.6)
                sites.append({"x": hub["x"] + tr * math.cos(ta), "y": hub["y"] + tr * math.sin(ta), "role": "tail", "cluster": cl,
                              "parent_ref": hub, "medium": "mw"})
    for i, s in enumerate(sites):
        s["id"] = f"S{i + 1:02d}"
        s["x"], s["y"] = round(s["x"], 2), round(s["y"], 2)
        d = math.hypot(s["x"], s["y"])
        s["area"] = str(rng.choice(["business", "mixed", "residential"], p=[.6, .3, .1] if d < 4.0 else [.1, .3, .6]))
    for s in sites:
        if s["role"] == "tail":
            s["parent"] = s.pop("parent_ref")["id"]
        s["csr"] = f"CSR-{s['id']}"
        parent_csr = s["parent"] if s["parent"].startswith("AGG") else f"CSR-{s['parent']}"
        s["link"] = f"L-{s['id']}-{s['parent']}"
        cap = CAP["hub_fibre"] if s["medium"] == "fibre" else CAP["hub_mw"] if s["role"] == "hub" else CAP["tail_mw"]
        links.append({"id": s["link"], "a": s["csr"], "b": parent_csr, "medium": s["medium"], "capacity": cap, "role": "primary"})
    hubs = [s for s in sites if s["role"] == "hub"]
    for s in sites:      # a standby microwave link to a hub elsewhere: to another cluster for a hub, to another hub for a tail
        own_hub = s["id"] if s["role"] == "hub" else s["parent"]
        options = [(math.hypot(h["x"] - s["x"], h["y"] - s["y"]), h["id"]) for h in hubs
                   if h["id"] != own_hub and (s["role"] == "tail" or h["cluster"] != s["cluster"])]
        options = [o for o in sorted(options) if o[0] < (4.8 if s["role"] == "hub" else 3.2)]
        s["alt_parent"], s["alt_link"] = None, None
        if options and rng.random() < 0.8:
            s["alt_parent"] = options[0][1]
            s["alt_link"] = f"A-{s['id']}-{s['alt_parent']}"
            links.append({"id": s["alt_link"], "a": s["csr"], "b": f"CSR-{s['alt_parent']}", "medium": "mw",
                          "capacity": CAP["alt_hub"] if s["role"] == "hub" else CAP["alt_tail"], "role": "alternate"})
    protected = rng.choice([s["id"] for s in sites if s["role"] == "tail"], 3, replace=False)
    for s in sites:
        s["protected"] = s["id"] in set(protected.tolist())
        s["label"] = "hospital" if s["protected"] else ""
    cells = []
    for s in sites:
        boost = 1.25 if s["area"] == "business" else 1.0
        for sec, az in SECTORS.items():
            for band, cap in BANDS.items():
                base = cap * (rng.uniform(0.38, 0.62) if band == "L" else rng.uniform(0.17, 0.33)) * boost
                cells.append({"id": f"{s['id']}-{sec}-{band}", "site": s["id"], "sector": f"{s['id']}-{sec}", "band": band, "capacity": cap,
                              "azimuth": az, "base": round(float(base), 2)})
    neighbours = _neighbours(sites, cells)
    for n in nodes.values():
        n.setdefault("cluster", None)
    return {"seed": seed, "nodes": nodes, "sites": sites, "links": links, "cells": cells, "neighbours": neighbours}


def _neighbours(sites, cells):
    """[(cell, neighbour cell, share of the cell's handovers)]: same band, co-site sectors and facing sectors within 2.6 km."""
    pos = {s["id"]: (s["x"], s["y"]) for s in sites}
    by_sector = {}
    for c in cells:
        by_sector.setdefault((c["sector"], c["band"]), c)
    out = []
    for c in cells:
        x, y = pos[c["site"]]
        cand = []
        for (sec, band), o in by_sector.items():
            if band != c["band"] or o["id"] == c["id"]:
                continue
            ox, oy = pos[o["site"]]
            d = math.hypot(ox - x, oy - y)
            if o["site"] == c["site"]:
                cand.append((0.4, o["id"]))
            elif d < 2.6:
                bearing = math.degrees(math.atan2(ox - x, oy - y)) % 360
                if abs((bearing - c["azimuth"] + 180) % 360 - 180) < 75:
                    cand.append((d, o["id"]))
        cand = sorted(cand)[:6]
        w = np.array([1 / (d + 0.3) for d, _ in cand])
        out += [(c["id"], o, round(float(v), 4)) for (_, o), v in zip(cand, w / w.sum())]
    return out


def paths(net, rerouted=()):
    """{site: [elements from its router up to the core]} for a routing in which `rerouted` sites use their standby link.
    Raises ValueError on a loop (two sites rerouted through each other)."""
    rerouted = set(rerouted)
    by = {s["id"]: s for s in net["sites"]}
    out = {}
    for s in net["sites"]:
        chain, cur, seen = [s["csr"]], s, set()
        while True:
            if cur["id"] in seen:
                raise ValueError(f"routing loop through {cur['id']}")
            seen.add(cur["id"])
            alt = cur["id"] in rerouted and cur["alt_parent"]
            parent, link = (cur["alt_parent"], cur["alt_link"]) if alt else (cur["parent"], cur["link"])
            chain.append(link)
            if parent.startswith("AGG"):
                chain += [parent, f"L-{parent}-CORE", "CORE-01"]
                break
            chain.append(f"CSR-{parent}")
            cur = by[parent]
        out[s["id"]] = chain
    return out


# --- traffic -----------------------------------------------------------------------------------------------------------
def _shape_table():
    out = {}
    for key, hourly in PROFILE.items():
        h = np.array(hourly + hourly[:1])
        q = np.arange(PER_DAY) / 4
        out[key] = np.interp(q, np.arange(25), h)
    return out


SHAPES = _shape_table()


def is_weekend(t):
    return (t // PER_DAY) % 7 >= 5


def demand(net, seed, t, area_idx=None):
    """Offered traffic per cell (Mbps) at interval t: base x daily/weekly shape x growth x keyed noise."""
    cells = net["cells"]
    if area_idx is None:
        area = {s["id"]: s["area"] for s in net["sites"]}
        area_idx = [area[c["site"]] for c in cells]
    we = int(is_weekend(t))
    shape = np.array([SHAPES[(a, we)][t % PER_DAY] for a in area_idx])
    base = np.array([c["base"] for c in cells])
    z = np.random.default_rng([seed, t, 11]).standard_normal(len(cells))
    zh = np.random.default_rng([seed, t // 4, 12]).standard_normal(len(cells))
    zd = np.random.default_rng([seed, t // PER_DAY, 13]).standard_normal(len(cells))
    return base * shape * GROWTH_PER_WEEK ** (t / PER_WEEK) * np.exp(0.06 * z + 0.06 * zh + 0.04 * zd)


# --- faults --------------------------------------------------------------------------------------------------------------
def random_faults(net, seed, t_from, t_to, n):
    """A history's faults, every kind recurring, each lasting 1-6 hours and over before t_to minus six hours."""
    rng = np.random.default_rng([seed, 7])
    mw = [l["id"] for l in net["links"] if l["medium"] == "mw" and l["role"] == "primary"]
    fibre = [l["id"] for l in net["links"] if l["medium"] == "fibre" and l["role"] == "primary"]
    starts = np.sort(rng.choice(np.arange(t_from, t_to - 48), n, replace=False))
    kinds = [k for _ in range(n // len(FAULT_KINDS) + 1) for k in rng.permutation(FAULT_KINDS)]
    out = []
    for i, (st, kind) in enumerate(zip(starts, kinds)):
        st, kind = int(st), str(kind)
        dur = int(rng.integers(4, 25))
        f = {"id": f"H{i + 1:02d}", "kind": kind, "start": st, "end": min(st + dur, t_to - 24)}
        if kind == "backhaul_degradation":
            f.update(element=str(rng.choice(mw)), cap_factor=round(float(rng.uniform(0.4, 0.75)), 2), loss_pct=round(float(rng.uniform(0.4, 1.2)), 2))
        elif kind == "fibre_degradation":
            f.update(element=str(rng.choice(fibre)), cap_factor=1.0, loss_pct=round(float(rng.uniform(0.25, 1.5)), 2), latency_ms=round(float(rng.uniform(2, 8)), 1))
        elif kind == "rain_fade":      # a storm cell over one cluster: two or three microwave links fade at once
            cl = str(rng.choice(CLUSTERS))
            pool = [l for l in mw if _cluster_of_link(net, l) == cl] or mw
            for j, el in enumerate(rng.choice(pool, min(len(pool), int(rng.integers(2, 4))), replace=False)):
                out.append({"id": f"H{i + 1:02d}{'abc'[j]}", "kind": "rain_fade", "start": st, "end": min(st + dur, t_to - 24), "element": str(el),
                            "cap_factor": round(float(rng.uniform(0.45, 0.8)), 2), "loss_pct": round(float(rng.uniform(0.3, 1.0)), 2)})
            continue
        elif kind == "site_power_outage":
            f.update(element=f"CSR-{rng.choice([s['id'] for s in net['sites']])}")
        elif kind == "sleeping_cell":      # up, no alarm, but users cannot attach: the failure thresholds never see
            f.update(element=str(rng.choice([c["id"] for c in net["cells"]])), traffic_factor=round(float(rng.uniform(0.03, 0.25)), 2))
        else:
            f.update(element=str(rng.choice([c["id"] for c in net["cells"]])), fail_share=round(float(rng.uniform(0.55, 0.85)), 2))
        out.append(f)
    return out


def _cluster_of_link(net, link_id):
    csr = next(l["a"] for l in net["links"] if l["id"] == link_id)
    return next(s["cluster"] for s in net["sites"] if s["csr"] == csr)


def active(f, t):
    return f["start"] <= t and (f.get("end") is None or t < f["end"])


# --- the clock ------------------------------------------------------------------------------------------------------------
class Sim:
    """Generates intervals for one network. Static structure is precomputed once; `step(t, told)` is one 15-minute interval."""

    def __init__(self, net, seed):
        self.net, self.seed = net, seed
        self.cells, self.sites, self.links = net["cells"], net["sites"], net["links"]
        self.C, self.S, self.L = len(self.cells), len(self.sites), len(self.links)
        self.site_ix = {s["id"]: i for i, s in enumerate(self.sites)}
        self.link_ix = {l["id"]: i for i, l in enumerate(self.links)}
        self.cell_ix = {c["id"]: i for i, c in enumerate(self.cells)}
        self.cell_site = np.array([self.site_ix[c["site"]] for c in self.cells])
        self.cap_cell = np.array([c["capacity"] for c in self.cells])
        self.nominal = np.array([l["capacity"] for l in self.links])
        self.mw = np.array([l["medium"] == "mw" for l in self.links])
        area = {s["id"]: s["area"] for s in self.sites}
        self.area_idx = [area[c["site"]] for c in self.cells]
        self.nbr = {}
        for a, b, w in net["neighbours"]:
            self.nbr.setdefault(self.cell_ix[a], []).append((self.cell_ix[b], w))
        self._routes = {}
        self._prev_cap, self._prev_down, self._prev_batt, self._prev_dark, self._last_on = {}, {}, {}, {}, {}

    def routing(self, rerouted):
        key = tuple(sorted(rerouted))
        if key not in self._routes:
            p = paths(self.net, key)
            M = np.zeros((self.S, self.L))
            for s, chain in p.items():
                for el in chain:
                    if el in self.link_ix:
                        M[self.site_ix[s], self.link_ix[el]] = 1
            parent_site = {}
            for s, chain in p.items():
                up = chain[2] if len(chain) > 2 else None
                parent_site[s] = up[4:] if up and up.startswith("CSR-") else None
            # the sites each site's traffic crosses on its way up (itself included)
            up_sites = {s: [el[4:] for el in chain if el.startswith("CSR-")] for s, chain in p.items()}
            active_links = {el for chain in p.values() for el in chain if el in self.link_ix}
            self._routes[key] = (M, up_sites, active_links)
        return self._routes[key]

    def step(self, t, told=()):
        """One interval -> dict(cell [C,8], link [L,5], alarms, config, impaired [C] bool, cause [C] fault id or '')."""
        faults = [f for f in told if f.get("kind") in FAULT_KINDS and active(f, t)]
        rerouted = sorted({c["site"] for c in told if c.get("kind") == "reroute" and c["start"] <= t})
        restored = {c["element"]: c["start"] for c in told if c.get("kind") == "config_restore"}
        M, up_sites, active_links = self.routing(rerouted)
        D = demand(self.net, self.seed, t, self.area_idx)
        burst = [f for f in told if f.get("kind") == "traffic_burst" and active(f, t)]
        for f in burst:
            for el in f["cells"]:
                D[self.cell_ix[el]] *= f["factor"]
        cap = self.nominal.copy()
        ber, lat_x = np.zeros(self.L), np.zeros(self.L)
        link_cause = np.array([""] * self.L, dtype=object)
        link_effect = np.zeros(self.L)
        power_down, on_battery, site_cause = np.zeros(self.S, bool), np.zeros(self.S, bool), np.array([""] * self.S, dtype=object)
        ho_bad, asleep = {}, {}
        for f in faults:
            ramp = min(1.0, (t - f["start"] + 1) / 2)
            if f["kind"] in ("backhaul_degradation", "rain_fade", "fibre_degradation"):
                i = self.link_ix[f["element"]]
                cap[i] *= 1 - (1 - f.get("cap_factor", 1.0)) * ramp
                ber[i] += f["loss_pct"] * ramp
                lat_x[i] += f.get("latency_ms", 0.0) * ramp
                eff = f["loss_pct"] + (1 - f.get("cap_factor", 1.0))
                if eff > link_effect[i]:
                    link_effect[i], link_cause[i] = eff, f["id"]
            elif f["kind"] == "site_power_outage":
                i = self.site_ix[f["element"][4:]]
                site_cause[i] = f["id"]
                if t - f["start"] < BATTERY_INTERVALS:
                    on_battery[i] = True
                else:
                    power_down[i] = True
            elif f["kind"] == "sleeping_cell":
                asleep[self.cell_ix[f["element"]]] = (f["traffic_factor"], f["id"])
            elif f["kind"] == "handover_misconfig" and not (f["element"] in restored and restored[f["element"]] <= t):
                ho_bad[self.cell_ix[f["element"]]] = (f["fail_share"], f["id"])
        for x, (factor, _) in asleep.items():
            D[x] *= factor
        # a site is dark if it, or any site its traffic crosses, has no power
        site_ids = [s["id"] for s in self.sites]
        dark = np.array([any(power_down[self.site_ix[u]] for u in up_sites[s]) for s in site_ids])
        dark_cause = np.array([next((site_cause[self.site_ix[u]] for u in up_sites[s] if power_down[self.site_ix[u]]), "") for s in site_ids], dtype=object)
        avail = ~dark[self.cell_site]
        offered_site = np.bincount(self.cell_site, weights=D * avail, minlength=self.S)
        offered = M.T @ offered_site
        link_down = np.zeros(self.L, bool)
        down_cause = np.array([""] * self.L, dtype=object)
        for s in site_ids:          # the links into and out of a dark site lose signal
            if power_down[self.site_ix[s]]:
                for l in self.links:
                    if l["a"] == f"CSR-{s}" or l["b"] == f"CSR-{s}":
                        link_down[self.link_ix[l["id"]]] = True
                        down_cause[self.link_ix[l["id"]]] = site_cause[self.site_ix[s]]
        rho = np.where(cap > 0, offered / np.maximum(cap, 1e-9), 0)
        served = np.minimum(1.0, 1 / np.maximum(rho, 1e-9))
        loss_l = ber + np.where(rho > 1, 100 * (1 - 1 / np.maximum(rho, 1e-9)), 0.15 * np.clip((rho - 0.85) / 0.15, 0, 1))
        loss_l = np.minimum(loss_l, 60)
        lat_l = np.where(self.mw, 0.4, 0.3) + 0.4 / np.maximum(0.03, 1 - np.minimum(rho, 0.97)) + lat_x
        idle = np.array([l["id"] not in active_links for l in self.links])
        # per site: along its path
        site_served = np.exp(M @ np.log(np.maximum(served, 1e-9)))
        site_loss = 100 * (1 - np.exp(M @ np.log(np.maximum(1 - loss_l / 100, 1e-9))))
        site_lat = M @ lat_l
        fault_loss_site = 100 * (1 - np.exp(M @ np.log(np.maximum(1 - ber / 100, 1e-9))))
        # the fault's share of congestion: what the link would carry at nominal capacity
        rho_nom = offered / self.nominal
        fault_cong = (rho > 1) & (rho_nom <= 1) & (link_cause != "")
        site_fault_cong = (M @ fault_cong.astype(float)) > 0
        rs = np.random.default_rng([self.seed, t, 17])
        z = rs.standard_normal((5, self.C))
        prb = np.minimum(1.0, D / self.cap_cell)
        ssite = self.cell_site
        dl = D * site_served[ssite] * avail
        users = D / 1.6 * np.exp(0.05 * z[0]) * avail
        latency = (7 + 9 * prb ** 2 + site_lat[ssite] + 0.8 * z[1]) * avail
        radio_loss = 0.3 * np.clip((prb - 0.9) / 0.1, 0, 1)
        loss = (site_loss[ssite] + radio_loss + 0.02 * np.abs(z[2])) * avail
        ho_eff = np.zeros(self.C)
        ho_cause = np.array([""] * self.C, dtype=object)
        worst_target = {}
        for x, (share, fid) in ho_bad.items():
            ho_eff[x] += 100 * share * 0.4
            ho_cause[x] = fid
            for n, w in self.nbr.get(x, []):
                worst_target.setdefault(x, n)
            for c, lst in self.nbr.items():
                for n, w in lst:
                    if n == x:
                        e = 100 * share * w
                        if e > ho_eff[c] - 1e-9:
                            ho_cause[c] = fid
                            worst_target[c] = x
                        ho_eff[c] += e
        ho = np.clip(98.6 - 3 * np.clip((prb - 0.9) / 0.1, 0, 1) - ho_eff + 0.4 * z[3], 0, 100) * avail
        drop = (0.35 + 0.25 * loss + 0.06 * np.maximum(0, 100 - ho) + 0.05 * np.abs(z[4])) * avail
        cell = np.stack([dl, prb * avail, users, latency, loss, np.where(avail, ho, 0), drop, avail.astype(float)], 1)
        cap_rep = np.where(link_down, 0, cap)
        util = np.where(link_down | idle, 0, np.minimum(1, rho))
        err = np.random.default_rng([self.seed, t, 19]).poisson(0.3 + 60 * ber).astype(float)
        link = np.stack([util, cap_rep, np.where(link_down | idle, 0, lat_l), np.where(link_down | idle, 0, np.where(idle, 0, loss_l)), np.where(link_down, 900, np.where(idle, 0, err))], 1)
        # --- truth: which cells a fault impaired, and through which fault
        path_cause = np.array([max(((link_effect[j], link_cause[j]) for j in np.nonzero(M[i])[0] if link_cause[j]), default=(0, ""))[1] for i in range(self.S)], dtype=object)
        impaired = np.zeros(self.C, bool)
        cause = np.array([""] * self.C, dtype=object)
        transport = ((fault_loss_site[ssite] >= 0.25) | site_fault_cong[ssite]) & avail
        impaired |= transport
        cause[transport] = path_cause[ssite][transport]
        hob = (ho_eff >= 3) & avail
        impaired |= hob
        cause[hob] = ho_cause[hob]
        for x, (_, fid) in asleep.items():
            if avail[x]:
                impaired[x], cause[x] = True, fid
        out = ~avail
        impaired |= out
        cause[out] = dark_cause[ssite][out]
        alarms = self._alarms(t, cell, link, avail, ssite, path_cause, link_cause, ho_cause, worst_target, dark, dark_cause, on_battery, site_cause, link_down, down_cause, idle)
        return {"t": t, "cell": cell.astype(np.float32), "link": link.astype(np.float32), "alarms": alarms, "config": self._config(t, told),
                "impaired": impaired, "cause": cause, "rerouted": rerouted, "offered_link": offered, "capacity_link": cap}

    def _alarms(self, t, cell, link, avail, ssite, path_cause, link_cause, ho_cause, worst_target, dark, dark_cause, on_battery, site_cause, link_down, down_cause, idle):
        """Vendor alarms: thresholds checked minute by minute on noisy readings; a raise each time a reading crosses into alarm."""
        rng = np.random.default_rng([self.seed, t, 21])
        out = []

        def flaps(v, op, thr, rel_sd, key):
            noise = np.exp(rel_sd * rng.standard_normal((15, len(v))))
            m = v[None, :] * noise
            on = m > thr if op == ">" else m < thr
            last = self._last_on.get(key)
            prev = np.concatenate([(last if last is not None else np.zeros(len(v), bool))[None, :], on[:-1]], 0)
            self._last_on[key] = on[-1]
            return on & ~prev
        for k, (kpi, op, thr, typ, sev) in enumerate(CELL_ALARMS):
            v = cell[:, CELL_KPIS.index(kpi)].astype(float)
            ups = flaps(v, op, thr, 0.12 if kpi != "ho_success_pct" else 0.006, typ) & avail[None, :]
            for c in np.nonzero(ups.any(0))[0]:
                mins = np.nonzero(ups[:, c])[0][:MAX_FLAPS]
                if typ in ("HO_FAILURE_RATE_HIGH",):
                    why, rel = ho_cause[c], (self.cells[worst_target[c]]["id"] if c in worst_target else None)
                elif typ == "CALL_DROP_RATE_HIGH":
                    why, rel = ho_cause[c] or path_cause[ssite[c]], (self.cells[worst_target[c]]["id"] if c in worst_target else None)
                elif typ == "RRC_CONGESTION":
                    why, rel = "", None
                else:
                    why, rel = path_cause[ssite[c]], None
                for m in mins:
                    out.append((t, int(m), self.cells[c]["id"], typ, sev, rel, why))
        for kpi, op, thr, typ, sev in LINK_ALARMS:
            v = np.where(idle | link_down, 0, link[:, LINK_KPIS.index(kpi)].astype(float))
            ups = flaps(v, op, thr, 0.12, typ)
            for j in np.nonzero(ups.any(0))[0]:
                for m in np.nonzero(ups[:, j])[0][:MAX_FLAPS]:
                    out.append((t, int(m), self.links[j]["id"], typ, sev, None, link_cause[j]))
        for j, l in enumerate(self.links):
            if l["medium"] == "mw" and not idle[j] and not link_down[j] and link[j, 1] < 0.9 * l["capacity"] and self._prev_cap.get(j, l["capacity"]) >= 0.9 * l["capacity"]:
                out.append((t, int(rng.integers(0, 15)), l["id"], "MW_CAPACITY_DEGRADED", "major", None, link_cause[j]))
            if link_down[j] and not self._prev_down.get(j, False):
                out.append((t, 0, l["id"], "LINK_DOWN", "critical", None, down_cause[j]))
            self._prev_cap[j], self._prev_down[j] = float(link[j, 1]), bool(link_down[j])
        for i, s in enumerate(self.sites):
            if on_battery[i] and not self._prev_batt.get(i, False):
                out.append((t, int(rng.integers(0, 15)), s["csr"], "POWER_MAINS_FAIL", "major", None, site_cause[i]))
            if dark[i] and not self._prev_dark.get(i, False):
                out.append((t, 0, s["csr"], "NODE_UNREACHABLE", "critical", None, dark_cause[i]))
                for c in np.nonzero(ssite == i)[0]:
                    out.append((t, 0, self.cells[c]["id"], "CELL_UNAVAILABLE", "critical", None, dark_cause[i]))
            self._prev_batt[i], self._prev_dark[i] = bool(on_battery[i]), bool(dark[i])
        for k, (typ, sev) in enumerate(BACKGROUND):     # noise from the field: one-off alarms with no fault behind them
            for c in np.nonzero(rng.random(self.C) < 0.00035)[0]:
                out.append((t, int(rng.integers(0, 15)), self.cells[c]["id"], typ, sev, None, ""))
        return out

    def _config(self, t, told):
        """The configuration change log: routine parameter changes on random cells, and whatever the generator was told."""
        out = []
        rng = np.random.default_rng([self.seed, t, 31])
        if rng.random() < 4 / PER_DAY:
            c = self.cells[int(rng.integers(self.C))]
            p = str(rng.choice(["cio_db", "e_tilt_deg", "p_max_dbm"]))
            old = {"cio_db": 0.0, "e_tilt_deg": 4.0, "p_max_dbm": 43.0}[p]
            out.append((t, c["id"], p, old, old + float(rng.choice([-2, -1, 1, 2])), "oss-optimiser"))
        for f in told:
            if f.get("kind") == "handover_misconfig" and f["start"] == t:
                out.append((t, f["element"], "nbr_pci_map", "v41", "v42", "change CHG-" + str(1000 + t % 9000)))
        return out

    def run(self, t0, t1, told=()):
        self._prev_cap, self._prev_down, self._prev_batt, self._prev_dark, self._last_on = {}, {}, {}, {}, {}
        if t0 > 0:             # alarm edges need the state just before t0
            self.step(t0 - 1, told)
        return [self.step(t, told) for t in range(t0, t1)]


def run(net, seed, t0, t1, told=()):
    return Sim(net, seed).run(t0, t1, told)
