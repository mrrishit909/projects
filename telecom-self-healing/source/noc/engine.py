"""Analysis, all of it on what the service stores (topology, counters, alarms, the configuration change log), never on the
generator's internals.

    Topology        which elements can explain an alarm: a transport alarm is explained by its element or anything upstream
                    of it on the current routing (a link alarm also by the router at the link's near end); a handover alarm
                    by its cell or the neighbour it fails towards; a local alarm (VSWR, temperature, congestion) by its cell
    Correlator      groups alarms into incidents as they arrive: an alarm joins an open incident whose root explains it;
                    the rest are covered greedily by the element that explains the most alarmed elements while leaving the
                    fewest of its own cells silent; a new incident absorbs earlier ones its root explains. Baselines:
                    de-duplication (same element and alarm type) and grouping by site
    rank            every element that explains part of an incident, scored by coverage x specificity on the topology, its
                    own alarms (a cause alarm such as mains failure or a microwave downshift counts more than a symptom), its
                    own telemetry, a configuration change just before, and whether it alarmed first; baseline: the element
                    with the most alarms
    AnomalyModel    per cell and per day type and 15-minute slot: a seasonal median of six counters, residuals scaled by
                    their robust spread, and a pooled covariance; a cell is anomalous when its Mahalanobis distance passes
                    the 99.9th percentile of clean training data. Baseline: the vendor's static thresholds
    Forecaster      per cell: a seasonal profile (median by day type and slot over clean weeks) x weekly growth x the
                    recent level, decaying to the profile over the horizon; baseline: seasonal naive (same slot last week)
    twin            link loads over the horizon for a routing, from the cell forecast and each link's measured capacity
    policy_check    a plan against the declared envelope: peak load, number of elements changed, protected sites,
                    allowed actions, no routing loops
    optimise        every subset of the possible reroutes (up to the envelope's size) through the twin; the feasible plan
                    with the fewest changes and the lowest peak wins; baselines: do nothing, reroute everything
"""
import hashlib
import itertools
import json
import math
import uuid
import warnings

import numpy as np
from scipy.stats import chi2, norm

from . import world

TRANSPORT = {"S1_LATENCY_HIGH", "PACKET_LOSS_HIGH", "CELL_UNAVAILABLE", "LINK_BER_HIGH", "LINK_UTIL_HIGH", "MW_CAPACITY_DEGRADED",
             "LINK_DOWN", "POWER_MAINS_FAIL", "NODE_UNREACHABLE"}
HANDOVER = {"HO_FAILURE_RATE_HIGH"}
MIXED = {"CALL_DROP_RATE_HIGH", "KPI_ANOMALY"}       # KPI_ANOMALY: raised by this service, not by an element
CAUSE_ALARMS = {"POWER_MAINS_FAIL", "MW_CAPACITY_DEGRADED", "LINK_BER_HIGH"}     # name a fault on their own element
HOLD = 4                    # an incident stays open for an hour after its last alarm
LAMBDA = 0.5                # how much a silent cell counts against a candidate root
WEIGHTS = {"topology": 4.0, "own_cause": 1.5, "own_symptom": 0.5, "anomalous": 1.0, "config_change": 1.5, "first": 0.75}
CORRELATOR_VERSION = "topology-cover-1"
RANKER_VERSION = "rca-topology-evidence-1"
ANOMALY_VERSION = "cell-mahalanobis-1"
FORECAST_VERSION = "cell-seasonal-level-1"


def family(typ):
    return "transport" if typ in TRANSPORT else "handover" if typ in HANDOVER else "mixed" if typ in MIXED else "local"


def feature_hash(x):
    return hashlib.sha256(json.dumps([round(float(v), 4) for v in np.ravel(x)]).encode()).hexdigest()[:16]


# --- topology ----------------------------------------------------------------------------------------------------------
class Topology:
    def __init__(self, net, rerouted=()):
        self.net, self.rerouted = net, set(rerouted)
        self.paths = world.paths(net, rerouted)
        self.site = {s["id"]: s for s in net["sites"]}
        self.cell_site = {c["id"]: c["site"] for c in net["cells"]}
        self.up = {}
        for s, chain in self.paths.items():
            for i, el in enumerate(chain):
                if el.startswith(("L-", "A-")):
                    self.up.setdefault(el, [el, chain[i - 1]] + chain[i + 1:])     # a link alarm: the link or its near-end router
                else:
                    self.up.setdefault(el, chain[i:])
        for l in net["links"]:          # standby links and uplinks
            if l["id"] not in self.up:
                self.up[l["id"]] = [l["id"], l["a"]] + self.up.get(l["b"], [l["b"]])
        for c in net["cells"]:
            self.up[c["id"]] = [c["id"]] + self.paths[c["site"]]
        self.desc = {}
        for c in net["cells"]:
            for el in self.up[c["id"]]:
                self.desc.setdefault(el, set()).add(c["id"])
        self.nbrs = {}
        for a, b, _ in net["neighbours"]:
            self.nbrs.setdefault(a, set()).add(b)
            self.nbrs.setdefault(b, set()).add(a)

    def kind(self, el):
        return "cell" if el in self.cell_site else "link" if el.startswith(("L-", "A-")) else "router" if el.startswith(("CSR-", "AGG-")) else "core"

    def explainers(self, element, typ, related=None):
        fam = family(typ)
        if fam == "transport":
            return list(self.up.get(element, [element]))
        if fam == "handover":
            return [element] + ([related] if related else [])
        if fam == "mixed":
            return list(self.up.get(element, [element])) + ([related] if related else [])
        return [element]

    def site_of(self, el):
        return site_of(self.cell_site, el)


def site_of(cell_site, el):
    """The site an element belongs to (a link belongs to its near-end site; routers above sites belong to themselves)."""
    if el in cell_site:
        return cell_site[el]
    if el.startswith("CSR-"):
        return el[4:]
    if el.startswith(("L-", "A-")):
        return el.split("-")[1]
    return el


# --- correlation -------------------------------------------------------------------------------------------------------
class Correlator:
    """Incremental: feed(t, alarms) once per interval. Alarms are dicts with id, t, element, type, related."""

    def __init__(self, topo, evidence=None, configs=None):
        self.topo = topo
        self.evidence = evidence if evidence is not None else {}     # element -> set of intervals it looked anomalous
        self.configs = configs if configs is not None else {}        # element -> [intervals of configuration changes]
        self.incidents = {}
        self.alarm_incident = {}
        self._n = 0

    def _new_id(self):
        self._n += 1
        return str(uuid.uuid4())

    def add_incident(self, inc):
        """Restore an open incident (from the database)."""
        self.incidents[inc["id"]] = inc
        for a in inc["alarms"]:
            self.alarm_incident[a["id"]] = inc["id"]

    def open(self, t):
        return [i for i in self.incidents.values() if i["status"] == "open" and i["last"] >= t - HOLD]

    def feed(self, t, alarms):
        changed = set()
        for inc in self.incidents.values():
            if inc["status"] == "open" and inc["last"] < t - HOLD:
                inc["status"], inc["resolved_at"] = "resolved", inc["last"] + HOLD
                changed.add(inc["id"])
        rest = []
        open_ = self.open(t)
        for a in alarms:
            ex = set(self.topo.explainers(a["element"], a["type"], a.get("related")))
            fits = [i for i in open_ if i["root"] in ex]
            if fits:      # prefer an incident that already holds this kind of alarm, then the most specific root
                fam = family(a["type"])
                inc = min(fits, key=lambda i: (fam not in {family(x["type"]) for x in i["alarms"]}, len(self.topo.desc.get(i["root"], ())) or 1))
                self._attach(inc, a, t)
                changed.add(inc["id"])
            else:
                rest.append(a)
        for root, group in cover(self.topo, rest):
            inc = {"id": self._new_id(), "root": root, "alarms": [], "opened": t, "last": t, "status": "open", "merged_into": None}
            self.incidents[inc["id"]] = inc
            for a in group:
                self._attach(inc, a, t)
            changed.add(inc["id"])
            for other in self.open(t):        # absorb the earlier incidents this root explains (a storm that started small)
                if other is inc or other["status"] != "open":
                    continue
                if all(root in self.topo.explainers(x["element"], x["type"], x.get("related")) for x in other["alarms"]):
                    for x in other["alarms"]:
                        self._attach(inc, x, x["t"])
                    inc["opened"] = min(inc["opened"], other["opened"])
                    other["status"], other["merged_into"], other["alarms"] = "merged", inc["id"], []
                    changed.add(other["id"])
        for iid in changed:
            inc = self.incidents[iid]
            if inc["status"] != "merged" and inc["alarms"]:
                self.rerank(inc)
        return changed

    def _attach(self, inc, a, t):
        inc["alarms"].append(a)
        inc["last"] = max(inc["last"], t)
        self.alarm_incident[a["id"]] = inc["id"]

    def rerank(self, inc):
        inc["ranking"] = rank(self.topo, inc["alarms"], self.evidence, self.configs)
        inc["root"] = inc["ranking"][0]["element"]
        inc["confidence"] = inc["ranking"][0]["confidence"]


def incident_kind(topo, root, alarms):
    types = {a["type"] for a in alarms}
    k = topo.kind(root)
    if k == "router" and "POWER_MAINS_FAIL" in types:
        return "power"
    if k == "cell":
        if types & HANDOVER:
            return "handover"
        if types == {"KPI_ANOMALY"}:
            return "silent"
        if types & TRANSPORT:
            return "transport"
        return "congestion" if "RRC_CONGESTION" in types else "radio"
    return "transport"


def units(topo, alarms):
    """Alarms grouped by (element, family): an element flapping thirty times is one unit of evidence."""
    out = {}
    for a in alarms:
        u = out.setdefault((a["element"], family(a["type"])), {"element": a["element"], "family": family(a["type"]), "ex": set(), "alarms": []})
        u["ex"] |= set(topo.explainers(a["element"], a["type"], a.get("related")))
        u["alarms"].append(a)
    return list(out.values())


def _silent(topo, e, covered, alarmed_cells):
    if topo.kind(e) == "cell":
        if any(u["family"] in ("handover", "mixed") for u in covered):
            return len(topo.nbrs.get(e, set()) - alarmed_cells)
        return 0
    return len(topo.desc.get(e, set()) - alarmed_cells)


def cover(topo, alarms):
    """Greedy cover of new alarms: -> [(root element, alarms)]."""
    us = units(topo, alarms)
    out = []
    while us:
        alarmed_cells = {u["element"] for u in us if u["element"] in topo.cell_site}
        cands = set().union(*(u["ex"] for u in us))
        best, best_key = None, None
        for e in cands:
            cov = [u for u in us if e in u["ex"]]
            gain = len(cov) - (LAMBDA * _silent(topo, e, cov, alarmed_cells) if len(cov) > 1 else 0)
            key = (gain, -len(topo.desc.get(e, ())), e)
            if best_key is None or key > best_key:
                best, best_key = e, key
        cov = [u for u in us if best in u["ex"]]
        out.append((best, [a for u in cov for a in u["alarms"]]))
        us = [u for u in us if best not in u["ex"]]
    return out


def rank(topo, alarms, evidence=None, configs=None, weights=None):
    """Every element that explains part of an incident, best first, with its evidence and a confidence (softmax)."""
    w = weights or WEIGHTS
    evidence, configs = evidence or {}, configs or {}
    us = units(topo, alarms)
    alarmed_cells = {u["element"] for u in us if u["element"] in topo.cell_site}
    t0, t1 = min(a["t"] for a in alarms), max(a["t"] for a in alarms)
    first_min = min(a["t"] * 15 + a.get("minute", 0) for a in alarms)
    counts = {}
    for a in alarms:
        counts[a["element"]] = counts.get(a["element"], 0) + 1
    rows = []
    for e in set().union(*(u["ex"] for u in us)):
        cov_units = [u for u in us if e in u["ex"]]
        cov = len(cov_units) / len(us)
        if topo.kind(e) == "cell" and any(u["family"] in ("handover", "mixed") for u in cov_units):
            pool = topo.nbrs.get(e, set()) | {e}
        else:
            pool = topo.desc.get(e, set())
        spec = len(pool & alarmed_cells) / len(pool) if pool else 0.0
        own = [a for a in alarms if a["element"] == e]
        own_cause = any(a["type"] in CAUSE_ALARMS for a in own)
        own_symptom = bool(own) and not own_cause
        anomalous = any(t0 - 2 <= x <= t1 for x in evidence.get(e, ()))
        changed = [x for x in configs.get(e, ()) if t0 - 12 <= x <= t0 + 4]
        first = bool(own) and min(a["t"] * 15 + a.get("minute", 0) for a in own) <= first_min
        f = {"topology": cov * spec, "own_cause": float(own_cause), "own_symptom": float(own_symptom), "anomalous": float(anomalous),
             "config_change": float(bool(changed)), "first": float(first)}
        score = sum(w[k] * v for k, v in f.items())
        rows.append({"element": e, "kind": topo.kind(e), "score": round(score, 3), "features": {k: round(v, 3) for k, v in f.items()},
                     "evidence": {"explains": f"{len(cov_units)} of {len(us)} alarmed elements", "coverage": round(cov, 3),
                                  "alarmed_cells_below": f"{len(pool & alarmed_cells)} of {len(pool)}", "specificity": round(spec, 3),
                                  "own_alarms": len(own), "own_alarm_types": sorted({a["type"] for a in own}), "telemetry_anomalous": anomalous,
                                  "config_change_at": changed[-1] if changed else None, "alarmed_first": first}})
    rows.sort(key=lambda r: (-r["score"], len(topo.desc.get(r["element"], ())), r["element"]))
    s = np.array([r["score"] for r in rows])
    p = np.exp(s - s.max())
    for r, v in zip(rows, p / p.sum()):
        r["confidence"] = round(float(v), 3)
    return rows


def rank_by_count(alarms):
    """Baseline: the elements with the most alarms first."""
    counts = {}
    for a in alarms:
        counts[a["element"]] = counts.get(a["element"], 0) + 1
    return [e for e, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def baseline_groups(topo, alarms, by="dedup", gap=4):
    """Baselines for the reduction ratio: alarms grouped by (element, type) or by site, a group closing after `gap` quiet intervals."""
    key = (lambda a: (a["element"], a["type"])) if by == "dedup" else (lambda a: topo.site_of(a["element"]))
    last, n = {}, 0
    for a in sorted(alarms, key=lambda a: (a["t"], a.get("minute", 0))):
        k = key(a)
        if k not in last or a["t"] - last[k] > gap:
            n += 1
        last[k] = a["t"]
    return n


# --- anomaly detection --------------------------------------------------------------------------------------------------
FEATURES = ["log_dl", "log_users", "latency_ms", "loss_pct", "ho_success_pct", "drop_pct"]
FLOORS = np.array([0.03, 0.03, 0.3, 0.01, 0.15, 0.02])
STATIC = {"latency_ms": 25.0, "loss_pct": 0.5, "ho_success_pct": 95.0, "drop_pct": 1.5}


def features(cell_vals):
    """[..., 8 cell KPIs] -> [..., 6 features]."""
    k = world.CELL_KPIS.index
    v = np.asarray(cell_vals, float)
    return np.stack([np.log1p(v[..., k("dl_mbps")]), np.log1p(v[..., k("users")]), v[..., k("latency_ms")], v[..., k("loss_pct")],
                     v[..., k("ho_success_pct")], v[..., k("drop_pct")]], -1)


def slot_key(t):
    """day type (0 weekday, 1 weekend) and 15-minute slot."""
    t = np.asarray(t)
    return ((t // world.PER_DAY) % 7 >= 5).astype(int), t % world.PER_DAY


def seasonal_median(X, ts, clean):
    """X [T, C, F], clean [T, C] -> median [2, 96, C, F] over clean intervals (NaN where none)."""
    dt, sl = slot_key(ts)
    Xc = np.where(clean[..., None], X, np.nan)
    out = np.full((2, world.PER_DAY) + X.shape[1:], np.nan)
    for d in (0, 1):
        for s in range(world.PER_DAY):
            m = (dt == d) & (sl == s)
            if m.any():
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    out[d, s] = np.nanmedian(Xc[m], 0)
    return out


def quiet_mask(topo, alarm_rows, t0, t1, pad=4):
    """[T, C] True where neither the cell, its neighbours nor anything upstream of it raised a fault alarm within `pad`
    intervals: the intervals the models may learn "normal" from. Local alarms (congestion, VSWR, temperature) do not count:
    a cell that is congested every evening is congested normally, and dropping those evenings would bias its baseline.
    alarm_rows: (t, element, type) as the service stores them."""
    cells = [c["id"] for c in topo.net["cells"]]
    els = sorted({e for c in cells for e in topo.up[c]} | set(cells))
    ei = {e: j for j, e in enumerate(els)}
    A = np.zeros((t1 - t0, len(els)), bool)
    for t, e, typ in alarm_rows:
        if t0 <= t < t1 and e in ei and family(typ) != "local":
            A[t - t0, ei[e]] = True
    cs = np.cumsum(np.vstack([np.zeros((1, len(els))), A]), 0)       # dilate in time by +-pad
    lo = np.clip(np.arange(t1 - t0) - pad, 0, t1 - t0)
    hi = np.clip(np.arange(t1 - t0) + pad + 1, 0, t1 - t0)
    D = (cs[hi] - cs[lo]) > 0
    inc = np.zeros((len(els), len(cells)))
    for k, c in enumerate(cells):
        for e in set(topo.up[c]) | topo.nbrs.get(c, set()):
            if e in ei:
                inc[ei[e], k] = 1
    return (D.astype(float) @ inc) == 0


def _fill(med):
    """Slots with no clean interval take the neighbouring slots' value for the same cell (then the day type's median)."""
    out = med.copy()
    for d in (0, 1):
        for s in range(world.PER_DAY):
            hole = np.isnan(out[d, s])
            if hole.any():
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    near = np.nanmean(np.stack([med[d, (s + k) % world.PER_DAY] for k in (-2, -1, 1, 2)]), 0)
                out[d, s] = np.where(hole, near, out[d, s])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        day = np.nanmedian(out, 1, keepdims=True)
    out = np.where(np.isnan(out), np.broadcast_to(day, out.shape), out)
    return np.where(np.isnan(out), np.nanmedian(out), out)


# harmful direction per feature: traffic and users falling, latency/loss/drops rising, handover success falling
HARM = np.array([-1, -1, 1, 1, -1, 1])


class AnomalyModel:
    def fit(self, cell_vals, ts, clean, q=0.9999):
        """cell_vals [T, C, 8] for training intervals ts; clean [T, C] from quiet_mask (visible to the service)."""
        X = features(cell_vals)
        self.med = _fill(seasonal_median(X, ts, clean))
        R = self.residual(X, ts)
        Rm = np.where(clean[..., None], R, np.nan)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            center = np.nanmedian(Rm, 0)
            self.scale = np.maximum(1.4826 * np.nanmedian(np.abs(Rm - center), 0), FLOORS)
        self.scale = np.where(np.isnan(self.scale), FLOORS, self.scale)
        Z = np.clip((R / self.scale)[clean], -8, 8)
        self.cov = np.cov(Z.T) + 1e-3 * np.eye(len(FEATURES))
        self.inv = np.linalg.inv(self.cov)
        d2 = np.einsum("nf,fg,ng->n", Z, self.inv, Z)
        # silent faults (a sleeping cell raises no alarm) slip into any "clean" set and fatten the tail, so the threshold is the
        # chi-square quantile scaled by the median distance, not an empirical tail quantile
        k = len(FEATURES)
        self.threshold = float(np.median(d2) * chi2.ppf(q, k) / chi2.ppf(0.5, k))
        zmax = np.abs(Z).max(1)
        self.diag_threshold = float(np.median(zmax) * norm.ppf(1 - (1 - q) / (2 * k)) / norm.ppf(1 - 0.5 / (2 * k)))
        return self

    def residual(self, X, ts):
        dt, sl = slot_key(ts)
        return X - self.med[dt, sl]

    def score(self, cell_vals, ts):
        """-> (d2 [T, C], z [T, C, F]); only deviations in the harmful direction count (a cell busier or faster than usual is
        not a fault); a cell that is down scores infinity."""
        cell_vals = np.asarray(cell_vals, float)
        X = features(cell_vals)
        Z = np.clip(self.residual(X, ts) / self.scale, -8, 8)
        Zh = np.where(Z * HARM > 0, Z, 0)
        d2 = np.einsum("...f,fg,...g->...", Zh, self.inv, Zh)
        down = cell_vals[..., world.CELL_KPIS.index("available")] < 0.5
        return np.where(down, np.inf, d2), Z

    def flag(self, cell_vals, ts, diagonal=False):
        """Anomalous at an interval (single reading). The service acts on two in a row (`persistent`)."""
        d2, Z = self.score(cell_vals, ts)
        if diagonal:
            down = np.asarray(cell_vals)[..., world.CELL_KPIS.index("available")] < 0.5
            return (np.where(Z * HARM > 0, np.abs(Z), 0).max(-1) > self.diag_threshold) | down
        return d2 > self.threshold

    @staticmethod
    def explain(z):
        """The features that moved most."""
        order = np.argsort(-np.abs(z))[:3]
        return [{"feature": FEATURES[i], "z": round(float(z[i]), 1)} for i in order if abs(z[i]) >= 2]


def persistent(flags):
    """[T, C] -> flagged at t and t-1."""
    f = np.asarray(flags)
    return np.vstack([np.zeros((1,) + f.shape[1:], bool), f[1:] & f[:-1]])


def derived_alarms(flags_prev, flags_now, vendor_alarmed, standing):
    """KPI_ANOMALY for a cell anomalous two intervals running with no vendor alarm of its own; raised once per episode.
    `standing` (set of cell indices) is updated in place. -> indices to raise."""
    raise_ = []
    for c in np.nonzero(flags_now & flags_prev & ~vendor_alarmed)[0]:
        if c not in standing:
            raise_.append(int(c))
            standing.add(int(c))
    for c in list(standing):
        if not flags_now[c]:
            standing.discard(c)
    return raise_


def static_flags(cell_vals):
    v = np.asarray(cell_vals, float)
    k = world.CELL_KPIS.index
    return ((v[..., k("latency_ms")] > STATIC["latency_ms"]) | (v[..., k("loss_pct")] > STATIC["loss_pct"])
            | ((v[..., k("ho_success_pct")] < STATIC["ho_success_pct"]) & (v[..., k("available")] > 0.5))
            | (v[..., k("drop_pct")] > STATIC["drop_pct"]) | (v[..., k("available")] < 0.5))


# --- traffic forecast ----------------------------------------------------------------------------------------------------
class Forecaster:
    def fit(self, dl, ts, clean):
        """dl [T, C] delivered Mbps per cell for training intervals ts (consecutive); clean [T, C]."""
        self.t_end = int(ts[-1]) + 1
        weeks = (np.asarray(ts) - ts[0]) // world.PER_WEEK
        tot = np.array([np.nanmean(np.where(clean[weeks == w], dl[weeks == w], np.nan)) for w in np.unique(weeks)])
        self.growth = float(np.clip(np.exp(np.polyfit(np.arange(len(tot)), np.log(tot), 1)[0]), 0.97, 1.03)) if len(tot) > 1 else 1.0
        adj = dl / self.growth ** ((np.asarray(ts)[:, None] - self.t_end) / world.PER_WEEK)      # in today's terms
        self.profile = _fill(seasonal_median(adj[..., None], ts, clean))[..., 0]
        return self

    def expected(self, ts):
        dt, sl = slot_key(ts)
        return self.profile[dt, sl] * self.growth ** ((np.asarray(ts)[:, None] - self.t_end) / world.PER_WEEK)

    def forecast(self, recent, recent_ts, horizon, up=None):
        """recent [k, C] delivered traffic in the last k intervals -> [horizon, C] from the interval after recent_ts[-1].
        `up` [C]: cells currently in service (a cell that is down is forecast to come back at its profile)."""
        recent = np.asarray(recent, float)
        exp_recent = self.expected(recent_ts)
        ratio = np.where(exp_recent > 1, recent / np.maximum(exp_recent, 1e-9), np.nan)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            level = np.nanmedian(ratio, 0)
        level = np.clip(np.where(np.isnan(level), 1.0, level), 0.7, 1.4)
        if up is not None:
            level = np.where(up, level, 1.0)
        ts = np.arange(recent_ts[-1] + 1, recent_ts[-1] + 1 + horizon)
        decay = np.exp(-np.arange(1, horizon + 1) / 12.0)[:, None]
        return self.expected(ts) * (1 + 0.5 * (level - 1) * decay), ts


def seasonal_naive(dl_last_week):
    return np.asarray(dl_last_week)


def wape(pred, actual):
    return float(np.abs(pred - actual).sum() / max(np.abs(actual).sum(), 1e-9))


# --- digital twin, policy and the optimiser ------------------------------------------------------------------------------
def incidence(net, rerouted):
    """sites x links: 1 where a site's traffic crosses the link. Raises ValueError on a routing loop."""
    p = world.paths(net, rerouted)
    li = {l["id"]: j for j, l in enumerate(net["links"])}
    si = {s["id"]: i for i, s in enumerate(net["sites"])}
    M = np.zeros((len(si), len(li)))
    for s, chain in p.items():
        for el in chain:
            if el in li:
                M[si[s], li[el]] = 1
    return M


def twin(net, rerouted, cell_forecast, capacity):
    """Link utilisation [H, L] over the horizon for a routing, from the per-cell traffic forecast and each link's capacity now."""
    si = {s["id"]: i for i, s in enumerate(net["sites"])}
    cs = np.array([si[c["site"]] for c in net["cells"]])
    S = np.zeros((len(net["cells"]), len(si)))
    S[np.arange(len(cs)), cs] = 1
    offered = np.asarray(cell_forecast) @ S @ incidence(net, rerouted)
    return offered / np.maximum(np.asarray(capacity, float), 1e-9)


def subtree_sites(net, site_id, rerouted=()):
    """A site and every site whose traffic crosses it."""
    return {s for s, chain in world.paths(net, rerouted).items() if f"CSR-{site_id}" in chain}


def affected_links(net, actions, current_rerouted=()):
    """Links whose traffic a plan changes: the old and new paths of every site it moves (and of the sites behind them)."""
    sites = {a["site"] for a in actions if a["type"] == "reroute_site"}
    if not sites:
        return set()
    before, after = world.paths(net, current_rerouted), world.paths(net, set(current_rerouted) | sites)
    moved = {x for s in sites for x in subtree_sites(net, s, current_rerouted)}
    return {el for x in moved for el in before[x] + after[x] if el.startswith(("L-", "A-"))}


def policy_check(net, actions, util, envelope, current_rerouted=(), horizon_ts=None, link_ids=None):
    """-> list of violations (empty = inside the envelope). A plan answers for the links whose traffic it changes."""
    out = []
    allowed = set(envelope["allowed_actions"])
    for a in actions:
        if a["type"] not in allowed:
            out.append({"rule": "allowed_actions", "detail": f"{a['type']} is not an action the envelope allows"})
    if len(actions) > envelope["max_elements_changed"]:
        out.append({"rule": "max_elements_changed", "detail": f"the plan changes {len(actions)} elements; the envelope allows {envelope['max_elements_changed']}"})
    protected = set(envelope.get("protected_sites", []))
    site_of_cell = {c["id"]: c["site"] for c in net["cells"]}
    for a in actions:
        if a["type"] == "reroute_site":
            hit = sorted(subtree_sites(net, a["site"], current_rerouted) & protected)
            if hit:
                out.append({"rule": "protected_sites", "detail": f"rerouting {a['site']} moves the traffic of protected site {', '.join(hit)}"})
        if a["type"] == "rollback_config" and site_of_cell.get(a["element"]) in protected:
            out.append({"rule": "protected_sites", "detail": f"{a['element']} is on protected site {site_of_cell[a['element']]}"})
    if util is not None:      # the twin runs on a forecast, so the plan must leave the forecast's margin of error
        lim = envelope["max_link_utilisation"] - envelope.get("forecast_margin", 0.0)
        watch = affected_links(net, actions, current_rerouted)
        peak = util.max(0)
        for j in np.argsort(-peak):
            if peak[j] <= lim:
                break
            if link_ids[j] not in watch:
                continue
            at = int(np.argmax(util[:, j]))
            out.append({"rule": "max_link_utilisation", "detail": f"{link_ids[j]} peaks at {peak[j]:.0%} (limit {lim:.0%}: the envelope's {envelope['max_link_utilisation']:.0%} less the forecast margin)",
                        "link": link_ids[j], "peak": round(float(peak[j]), 3), "at_interval": int(horizon_ts[at]) if horizon_ts is not None else at})
    return out


def reroute_options(net, root, rerouted=()):
    """Sites behind the root element that have a standby link to a parent outside the affected subtree."""
    topo = Topology(net, rerouted)
    behind = sorted({topo.cell_site[c] for c in topo.desc.get(root, set())})
    out = []
    for s in behind:
        site = topo.site[s]
        if site["alt_parent"] and s not in rerouted and site["alt_parent"] not in behind:
            out.append(s)
    return out


def optimise(net, root, cell_forecast, capacity, envelope, rerouted=(), horizon_ts=None):
    """Constrained search over the reroutes behind `root`. -> {"options", "do_nothing", "candidates", "best"}; best is None
    when doing nothing is already inside the envelope, or when no plan is (then the incident goes to a person with no plan)."""
    link_ids = [l["id"] for l in net["links"]]
    options = reroute_options(net, root, rerouted)
    cands = []

    def evaluate(sites):
        actions = [{"type": "reroute_site", "site": s, "via": net_site(net, s)["alt_link"]} for s in sites]
        try:
            util = twin(net, set(rerouted) | set(sites), cell_forecast, capacity)
        except ValueError as e:
            return {"actions": actions, "feasible": False, "violations": [{"rule": "routing", "detail": str(e)}], "peak": None}
        v = policy_check(net, actions, util, envelope, rerouted, horizon_ts, link_ids)
        watch = affected_links(net, actions, rerouted) or set(link_ids)
        peak = np.where([l in watch for l in link_ids], util.max(0), 0)
        excess = float(np.clip(util[:, [l in watch for l in link_ids]] - envelope["max_link_utilisation"] + envelope.get("forecast_margin", 0.0), 0, None).sum())
        worst = int(np.argmax(peak))
        root_j = link_ids.index(root) if root in link_ids else worst
        return {"actions": actions, "feasible": not v, "violations": v, "peak": round(float(peak.max()), 3), "worst_link": link_ids[worst],
                "root_link_peak": round(float(peak[root_j]), 3), "excess": round(excess, 3), "changes": len(actions)}
    root_path = [el for el in Topology(net, rerouted).up.get(root, [root]) if el in link_ids]
    lim = envelope["max_link_utilisation"] - envelope.get("forecast_margin", 0.0)
    nothing = evaluate(())
    u0 = twin(net, rerouted, cell_forecast, capacity)
    over = [link_ids[j] for j in range(len(link_ids)) if link_ids[j] in root_path and u0[:, j].max() > lim]
    nothing["feasible"] = not over          # doing nothing is enough when the incident's own path stays inside the envelope
    nothing["peak"] = round(float(max((u0[:, link_ids.index(l)].max() for l in root_path), default=0)), 3)
    nothing["violations"] = [{"rule": "max_link_utilisation", "detail": f"{l} peaks at {u0[:, link_ids.index(l)].max():.0%} (limit {lim:.0%})"} for l in over]
    for k in range(1, min(len(options), envelope["max_elements_changed"]) + 1):
        for combo in itertools.combinations(options, k):
            cands.append(evaluate(combo))
    feasible = [c for c in cands if c["feasible"]]
    best = min(feasible, key=lambda c: (c["changes"], c["peak"])) if feasible else None
    if nothing["feasible"]:
        best = None
    return {"options": options, "do_nothing": nothing, "candidates": sorted(cands, key=lambda c: (not c["feasible"], c["changes"], c["peak"] or 9)),
            "best": best, "root_path": root_path}


def net_site(net, s):
    return next(x for x in net["sites"] if x["id"] == s)
