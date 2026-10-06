"""A synthetic fab: lots of 25 wafers move through five process steps, each wafer through one chamber per step; every
wafer-step leaves a sensor summary (SECS/GEM-style trace statistics), and every wafer ends with a die-level test map.

Faults are physical: a chamber's sensor drifts, and the drift raises the failure probability of dies in a particular
region of the wafer. An etch chamber running hot rings the edge, a worn CMP pad hits the centre, a litho focus drift
makes a donut, a depo flow or implant dose fault raises defects everywhere. Scratches and particle clusters happen on
their own. The generator knows the truth (which pattern, which chamber); the service only sees sensors and test maps.

Every random draw is keyed by (seed, lot, wafer), so a lot can be re-run with a different recipe or route and the same
wafer sees the same randomness: that is what makes the counterfactual a paired comparison.
"""
import numpy as np

# --- the fab ---------------------------------------------------------------------------------------------------------
STEPS = ["litho", "etch", "depo", "cmp", "implant"]            # process order
TOOLS = {"litho": (4, "A"), "etch": (4, "ABC"), "depo": (3, "AB"), "cmp": (3, "A"), "implant": (2, "A")}
SENSORS = {   # name: (setpoint by product, noise sd); the first sensor of each step is the one its faults move
    "litho": {"focus_nm": ({"P1": 0.0, "P2": 0.0}, 4.0), "dose_mj": ({"P1": 32.0, "P2": 30.0}, 0.15)},
    "etch": {"temp_c": ({"P1": 60.0, "P2": 65.0}, 0.15), "pressure_mt": ({"P1": 40.0, "P2": 38.0}, 0.3), "rf_w": ({"P1": 900.0, "P2": 950.0}, 4.0)},
    "depo": {"flow_sccm": ({"P1": 120.0, "P2": 120.0}, 0.4), "temp_c": ({"P1": 400.0, "P2": 410.0}, 0.5)},
    "cmp": {"pressure_psi": ({"P1": 3.0, "P2": 3.2}, 0.04), "speed_rpm": ({"P1": 90.0, "P2": 90.0}, 0.5)},
    "implant": {"dose_pct": ({"P1": 100.0, "P2": 100.0}, 0.25), "energy_kev": ({"P1": 30.0, "P2": 35.0}, 0.1)},
}
PRIMARY = {s: next(iter(SENSORS[s])) for s in STEPS}
PRODUCTS = {"P1": 0.6, "P2": 0.4}
LOTS_PER_DAY = 8
WAFERS = 25
HOURS_PER_STEP = 2.0
QUALIFICATION_LOTS = 56          # the first week: every chamber qualified and clean; its baselines come from here
PATTERNS = ["none", "edge-ring", "center", "donut", "random-high", "scratch", "cluster"]
# fault kind: (step, sign of the primary-sensor move, pattern it causes, deviation at which defects start, gain, cap)
FAULTS = {
    "etch_temp_drift": ("etch", +1, "edge-ring", 0.8, 0.16, 0.65),
    "cmp_pad_wear": ("cmp", -1, "center", 0.10, 1.4, 0.55),
    "litho_focus_drift": ("litho", +1, "donut", 12.0, 0.014, 0.55),
    "depo_flow_fault": ("depo", +1, "random-high", 0.9, 0.035, 0.14),
    "implant_dose_fault": ("implant", -1, "random-high", 0.7, 0.045, 0.14),
}
BINS = {"pass": 1, "random": 3, "pattern": 4, "leakage": 5, "planarity": 6, "handling": 7}
PATTERN_BIN = {"edge-ring": 5, "center": 6, "donut": 4, "random-high": 3, "scratch": 7, "cluster": 7}


def chambers():
    """[(chamber name, tool name, step)] in a fixed order, e.g. ('ETCH-03/B', 'ETCH-03', 'etch')."""
    out = []
    for s in STEPS:
        n, letters = TOOLS[s]
        for t in range(1, n + 1):
            for ch in letters:
                out.append((f"{s.upper()}-{t:02d}/{ch}", f"{s.upper()}-{t:02d}", s))
    return out


CHAMBERS = chambers()
CHAMBER_STEP = {c: s for c, _, s in CHAMBERS}


def _dies(radius=13):
    """Die centres on a 300 mm-style wafer: a square grid clipped to a circle, ~530 dies."""
    xs, ys = np.meshgrid(np.arange(-radius, radius + 1), np.arange(-radius, radius + 1))
    keep = (xs + 0.5) ** 2 + (ys + 0.5) ** 2 <= radius ** 2
    x, y = xs[keep].astype(float) + 0.5, ys[keep].astype(float) + 0.5          # die centres
    return xs[keep], ys[keep], np.hypot(x, y) / radius, np.arctan2(y, x)       # grid indices (-13..12) and polar position


DIE_X, DIE_Y, DIE_R, DIE_TH = _dies()
N_DIES = len(DIE_R)


def offsets(seed):
    """Each chamber's fixed calibration offset on each sensor (what a chamber baseline learns)."""
    rng = np.random.default_rng([seed, 99])
    return {c: {k: float(rng.normal(0, sd * 0.8)) for k, (_, sd) in SENSORS[s].items()} for c, _, s in CHAMBERS}


def pattern_profile(pattern, amp, rng):
    """Extra failure probability per die for one pattern at amplitude `amp`."""
    r, th = DIE_R, DIE_TH
    if pattern == "edge-ring":
        return amp / (1 + np.exp(-(r - 0.82) / 0.035))
    if pattern == "center":
        return amp * np.exp(-(r / 0.32) ** 2)
    if pattern == "donut":
        return amp * np.exp(-((r - 0.56) / 0.09) ** 2)
    if pattern == "random-high":
        return np.full(N_DIES, amp)
    if pattern == "scratch":      # a chord across the wafer
        a, off = rng.uniform(0, np.pi), rng.uniform(-0.5, 0.5)
        d = np.abs(np.cos(a) * r * np.cos(th) + np.sin(a) * r * np.sin(th) - off)
        span = np.abs(-np.sin(a) * r * np.cos(th) + np.cos(a) * r * np.sin(th))
        return 0.85 * ((d < 0.045) & (span < rng.uniform(0.35, 0.8)))
    if pattern == "cluster":
        cx, cy = rng.uniform(-0.6, 0.6, 2)
        return 0.85 * np.exp(-((r * np.cos(th) - cx) ** 2 + (r * np.sin(th) - cy) ** 2) / (2 * 0.13 ** 2))
    return np.zeros(N_DIES)


def deviation(fault, lot_idx):
    """How far the fault has moved its sensor at this lot (natural units, >= 0)."""
    if lot_idx < fault["start_lot"] or (fault.get("end_lot") is not None and lot_idx >= fault["end_lot"]):
        return 0.0
    return min(fault["max"], fault["rate_per_lot"] * (lot_idx - fault["start_lot"] + 1))


def random_faults(seed, n_lots, n_faults, first_lot=QUALIFICATION_LOTS):
    """A history's excursions: kinds in rotation on random chambers, each lasting 1-2.5 days (then the chamber is fixed)."""
    rng = np.random.default_rng([seed, 7])
    starts = np.sort(rng.choice(np.arange(first_lot, n_lots - 10), n_faults, replace=False))
    kinds = [k for _ in range(n_faults // len(FAULTS) + 1) for k in rng.permutation(list(FAULTS))]   # every kind recurs
    out = []
    for st, kind in zip(starts, kinds):
        kind = str(kind)
        step = FAULTS[kind][0]
        options = [c for c, _, s in CHAMBERS if s == step]
        ch = str(rng.choice(options))
        mx = {"etch_temp_drift": 3.6, "cmp_pad_wear": 0.45, "litho_focus_drift": 45, "depo_flow_fault": 4.0, "implant_dose_fault": 3.2}[kind]
        out.append({"kind": kind, "chamber": ch, "start_lot": int(st), "end_lot": int(min(st + rng.integers(8, 20), n_lots - 4)),     # every history excursion is fixed before the history ends
                    "rate_per_lot": float(mx / rng.uniform(6, 14)), "max": float(mx)})
    return out


def run(seed, lot_from, lot_to, faults=(), adjust=None, route_around=None, only=None):
    """Generate lots lot_from..lot_to-1. Returns a list of lot dicts.

    adjust: {chamber: {sensor: offset}} applied to the recipe setpoint (a counterfactual recipe change).
    route_around: a chamber taken offline; its wafers go to the tool's other chambers.
    only: a set of lot indices to generate (counterfactual re-runs of particular lots)."""
    adjust, off = adjust or {}, offsets(seed)
    tool_chambers = {}
    for c, t, s in CHAMBERS:
        tool_chambers.setdefault(t, []).append(c)
    tools_by_step = {s: sorted({t for c, t, st in CHAMBERS if st == s}) for s in STEPS}
    lots = []
    for li in range(lot_from, lot_to):
        if only is not None and li not in only:
            continue
        rng = np.random.default_rng([seed, li])
        product = "P1" if rng.random() < PRODUCTS["P1"] else "P2"
        start_h = li * 24.0 / LOTS_PER_DAY
        lot_quality = float(rng.lognormal(0, 0.18))          # incoming-material variation no sensor sees
        route = {s: str(rng.choice(tools_by_step[s])) for s in STEPS}
        wafers = []
        for w in range(WAFERS):
            wr = np.random.default_rng([seed, li, w])
            u = wr.random(N_DIES)                              # one uniform per die, reused by every counterfactual
            p = 0.028 * lot_quality + 0.05 * np.clip((DIE_R - 0.9) / 0.1, 0, 1)
            contrib, steps = {}, []
            for k, s in enumerate(STEPS):
                cs = tool_chambers[route[s]]
                ch = cs[w % len(cs)]
                if ch == route_around and len(cs) > 1:
                    ch = [c for c in cs if c != route_around][w % (len(cs) - 1)]
                sens = {}
                for name, (sp, sd) in SENSORS[s].items():
                    sens[name] = sp[product] + off[ch][name] + adjust.get(ch, {}).get(name, 0.0) + wr.normal(0, sd)
                active = [f for f in faults if f["chamber"] == ch]
                if not active and adjust.get(ch, {}).get(PRIMARY[s]):           # a recipe offset on a healthy chamber is itself a deviation
                    active = [{"kind": next(k for k, v in FAULTS.items() if v[0] == s), "chamber": ch, "start_lot": 10 ** 9, "rate_per_lot": 0, "max": 0}]
                for f in active:
                    fs, sign, pattern, thresh, gain, cap = FAULTS[f["kind"]]
                    dev = deviation(f, li)
                    sens[PRIMARY[s]] += sign * dev                 # the drift shows on the sensor ...
                    eff = abs(sens[PRIMARY[s]] - SENSORS[s][PRIMARY[s]][0][product] - off[ch][PRIMARY[s]])   # ... the physics follows the sensor; process windows are two-sided
                    amp = float(np.clip(gain * (eff - thresh), 0, cap))
                    if amp > 0:
                        contrib[pattern] = contrib.get(pattern, 0) + pattern_profile(pattern, amp, wr)
                steps.append({"step": s, "chamber": ch, "recipe": f"{s.upper()}-{product}-R3", "at_h": start_h + k * HOURS_PER_STEP,
                              "sensors": {kk: round(float(v), 4) for kk, v in sens.items()}})
            for pat, prob in (("scratch", 0.012), ("cluster", 0.02)):
                if wr.random() < prob:
                    contrib[pat] = pattern_profile(pat, 1, wr)
            total = p + sum(contrib.values()) if contrib else p
            fail = u < np.clip(total, 0, 0.98)
            extra = {k: float(v.sum()) for k, v in contrib.items()}
            # what an engineer would label: 12 extra fails is visible when concentrated in a ring or a spot; spread evenly it takes ~40
            visible = {k: v for k, v in extra.items() if v >= (40 if k == "random-high" else 12)}
            truth = max(visible, key=visible.get) if visible else "none"
            bins = np.full(N_DIES, BINS["pass"], dtype=np.int16)
            if fail.any():
                cause = np.full(N_DIES, BINS["random"], dtype=np.int16)
                best = np.zeros(N_DIES)
                for k, v in contrib.items():
                    better = v > np.maximum(best, p)
                    cause[better], best[better] = PATTERN_BIN[k], v[better]
                bins[fail] = cause[fail]
            wafers.append({"slot": w + 1, "steps": steps, "bins": bins, "yield": float(1 - fail.mean()), "truth_pattern": truth,
                           "truth_causes": sorted({f["chamber"] for f in faults for st in steps if st["chamber"] == f["chamber"] and deviation(f, li) > 0})})
        lots.append({"index": li, "lot": f"L{seed % 1000:03d}-{li:05d}", "product": product, "start_h": start_h, "route": route, "wafers": wafers})
    return lots
