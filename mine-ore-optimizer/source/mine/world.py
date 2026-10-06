"""A synthetic open-pit copper mine: a 3D block model whose true grade, arsenic and hardness are spatially correlated random
fields, exploration drill holes and blast holes sampled from it, six shovels digging along their panels on six benches, a haul
road network (bench roads, a ramp up the east wall, surface roads to the crusher, two stockpiles and the waste dump), a truck
fleet whose cycle times follow the physics (power-limited climbing with the payload, rolling resistance, wet roads, queues at
the shovels and at the crusher), a surge bin and a mill whose throughput depends on the ore's hardness, and engine telemetry.

The generator knows the truth (every block's grade, what a breakdown's precursor looks like). The service sees what a real
operation sees: assays with laboratory error, the dispatch system's haul log (payload scales, GPS distances, ECU fuel), engine
telemetry, the crusher's on-belt analyser and the mill's throughput. It never reads the fields.

Every random draw is keyed by (seed, shift, truck, cycle) or (seed, shift, shovel, load), so a shift can be re-run under a
different dispatch plan and each truck's k-th cycle sees the same randomness: that is what makes a plan comparison paired.
"""
import heapq
import math

import numpy as np
from scipy import ndimage

# --- geometry (public: the mine's survey) ---------------------------------------------------------------------------------
NX, NY, NZ = 80, 60, 6                       # 10 m x 10 m x 15 m blocks: an 800 m x 600 m pit, six benches
BLOCK_M, BENCH_M, DENSITY = 10.0, 15.0, 2.7
BLOCK_T = BLOCK_M * BLOCK_M * BENCH_M * DENSITY            # 4,050 t
N_BLOCKS = NX * NY * NZ
TOP_RL = 1200.0
RAMP_GRADE = 0.09
RAMP_LEN = BENCH_M / RAMP_GRADE                             # 167 m of ramp per bench
EXIT = (830.0, 640.0)
NODES = {"exit": EXIT, "goline": (900.0, 690.0), "crusher": (1190.0, 770.0), "hg": (1080.0, 860.0), "lg": (1180.0, 930.0), "dump": (560.0, 1020.0)}
SURFACE = {"crusher": (1300.0, 0.02), "hg": (900.0, 0.0), "lg": (1100.0, 0.0), "dump": (2100.0, 0.03)}   # from the pit exit: length m, grade
DESTS = ("crusher", "hg", "lg", "dump")
CUTOFF = {"LG": 0.25, "HG": 0.45}                          # %Cu: below LG is waste; the mine's cut-off policy


def ramp_xy(k):
    """Where bench k meets the ramp that switchbacks up the east wall."""
    return 815.0, 40.0 + 95.0 * k


def block_id(i, j, k):
    return k * NX * NY + j * NX + i


def block_ijk(b):
    return b % NX, (b // NX) % NY, b // (NX * NY)


def block_xy(b):
    i, j, _ = block_ijk(b)
    return (i + 0.5) * BLOCK_M, (j + 0.5) * BLOCK_M


# --- equipment (public: the fleet register) ------------------------------------------------------------------------------
TRUCK_EMPTY_T, PAYLOAD_T, POWER_KW = 166.0, 220.0, 1900.0
SHOVEL_KINDS = {"rope": {"passes": 4, "pass_min": 0.55}, "hydraulic": {"passes": 6, "pass_min": 0.47}}
SPOT_MIN, DUMP_MIN = 0.6, {"crusher": 1.0, "hg": 0.8, "lg": 0.8, "dump": 0.8}
# id, kind, bench, what the mine plan puts it on: the shovels snake along 32 x 8-block panels row by row. The plan places
# them on the resource model: the rope shovels on the core and the pre-strip, the others on transition and waste.
SHOVELS = [("S1", "rope", 3, "core"), ("S2", "hydraulic", 2, 0.45), ("S3", "hydraulic", 4, 0.33),
           ("S4", "hydraulic", 1, 0.20), ("S5", "rope", 0, "waste"), ("S6", "hydraulic", 2, "waste")]
PANEL = (32, 8)
N_TRUCKS = 28
LOAD_NOMINAL = {k: SPOT_MIN + v["passes"] * v["pass_min"] for k, v in SHOVEL_KINDS.items()}
RATED_TPH = {k: round(0.85 * 60 * PAYLOAD_T / v) for k, v in LOAD_NOMINAL.items()}      # planning dig rate

# --- plant (public: the concentrator's contract and metallurgy) ----------------------------------------------------------
BIN_T = 5000.0                    # surge bin live capacity
LOADER_TPH = 1500.0               # stockpile reclaim by front-end loader into the bin
MILL_BASE_TPH, MILL_BASE_BWI = 4300.0, 13.5
PRICE, PROC_COST, FUEL_PRICE, REHANDLE = 9800.0, 10.5, 1.15, 1.4      # $/t Cu, $/t milled, $/L, $/t reclaimed
AS_LIMIT, AS_PENALTY = 260.0, 0.03                                    # ppm in feed; $/t milled per ppm above it (smelter penalty)
TARGET_CU, TOL_CU = 0.58, 0.10                                        # the plant's feed-grade window (%Cu)
SHIFT_MIN, START_DELAY = 720, 15.0


def mill_tph(bwi):
    return MILL_BASE_TPH * (MILL_BASE_BWI / max(bwi, 6.0)) ** 0.9


def recovery(cu):
    """Flotation recovery falls away below the design head grade."""
    return 0.91 - 0.32 * max(0.0, 0.50 - cu) / 0.50


def value_per_t(cu, as_ppm):
    """Net smelter value of a tonne milled at this head grade and arsenic, after processing."""
    return cu / 100 * recovery(cu) * PRICE - PROC_COST - AS_PENALTY * max(0.0, as_ppm - AS_LIMIT)


def ambient(abs_min):
    """Air temperature: a hot site, coolest at 04:00 (shift 0 starts 06:00)."""
    hour = (6 + abs_min / 60) % 24
    return 25 + 9 * math.sin(2 * math.pi * (hour - 10) / 24)


# --- the orebody (truth) -------------------------------------------------------------------------------------------------
def make_mine(seed, n_trucks=N_TRUCKS, shovels=SHOVELS):
    rng = np.random.default_rng([seed, 1])

    def grf(sig):
        f = ndimage.gaussian_filter(rng.normal(size=(NZ, NY, NX)), sig, mode="reflect")
        return (f - f.mean()) / f.std()
    a, b, c = grf((1.2, 5, 6)), grf((1.2, 4, 4)), grf((1.5, 7, 7))
    k, j, i = np.meshgrid(np.arange(NZ), np.arange(NY), np.arange(NX), indexing="ij")
    cx, cy = NX * rng.uniform(0.42, 0.52), NY * rng.uniform(0.42, 0.52)
    r2 = ((i - cx) / (NX * 0.45)) ** 2 + ((j - cy) / (NY * 0.45)) ** 2
    log_cu = np.log(0.42) + 0.5 * a - 0.85 * r2 + 0.06 * k                 # a porphyry: richer at the core and with depth
    cu = np.exp(log_cu + rng.normal(0, 0.10, a.shape))                     # plus a nugget no drill hole sees
    side = 1 if rng.random() < 0.5 else -1
    as_ = np.exp(np.log(150) + 0.3 * a + 0.5 * b + 1.1 * side * (i / NX - 0.5))   # an arsenic-bearing (enargite) flank
    bwi = np.clip(13.5 + 1.5 * c + 0.4 * a, 9, 19)
    trng = np.random.default_rng([seed, 2])
    trucks = []
    for t in range(n_trucks):
        age = float(trng.uniform(4000, 60000))
        trucks.append({"id": f"T{t + 1:02d}", "model": "793F", "payload_t": PAYLOAD_T, "age_h": round(age),
                       "eff": float(1.0 - 0.07 * age / 60000 + trng.normal(0, 0.01)), "operator": float(trng.lognormal(0, 0.04)),
                       "off": {"coolant_c": float(trng.normal(0, 2.0)), "oil_kpa": float(trng.normal(0, 12)), "exhaust_c": float(trng.normal(0, 15))}})
    shv, taken = [], set()
    cols, rows = PANEL
    for sid, kind, bench, aim in shovels:
        best = None
        for i0 in range(0, NX - cols + 1, 4):
            for j0 in range(0, NY - rows + 1, 2):
                cells = {(ii, jj) for ii in range(i0, i0 + cols) for jj in range(j0, j0 + rows)}
                if cells & {c for bk, c in taken if bk == bench}:
                    continue
                g = float(cu[bench, j0:j0 + rows, i0:i0 + cols].mean())
                score = -g if aim == "core" else g if aim == "waste" else abs(g - aim)
                if best is None or score < best[0]:
                    best = (score, i0, j0, cells)
        _, i0, j0, cells = best
        taken |= {(bench, c) for c in cells}
        seq = []
        for rr in range(rows):
            cols_ = range(i0, i0 + cols) if rr % 2 == 0 else range(i0 + cols - 1, i0 - 1, -1)
            seq += [block_id(ii, j0 + rr, bench) for ii in cols_]
        shv.append({"id": sid, "kind": kind, "bench": bench, "rate_tph": RATED_TPH[kind], "load_min": LOAD_NOMINAL[kind], "seq": seq})
    return {"seed": seed, "cu": cu.ravel(), "as": as_.ravel(), "bwi": bwi.ravel(), "trucks": trucks, "shovels": shv}


def true_grades(mine, told=()):
    """The fields with any told low-grade zone applied: (cu, as, bwi) per block."""
    cu = mine["cu"].copy()
    for z in told:
        if z["kind"] == "low_grade_zone":
            ids = np.arange(N_BLOCKS)
            ii, jj, kk = ids % NX, (ids // NX) % NY, ids // (NX * NY)
            d = np.hypot((ii + 0.5) * BLOCK_M - z["x"], (jj + 0.5) * BLOCK_M - z["y"]) / z["radius_m"]
            w = np.clip(1.3 - d, 0, 1) * (kk == z["bench"])                  # full strength inside, tapering at the edge
            cu *= 1 - (1 - z["factor"]) * w
    return cu, mine["as"], mine["bwi"]


def drill_holes(mine, spacing=6):
    """Exploration holes on a jittered grid, vertical through every bench; one composite per bench, assayed with lab error."""
    rng = np.random.default_rng([mine["seed"], 3])
    out = []
    for ii in range(spacing // 2, NX, spacing):
        for jj in range(spacing // 2, NY, spacing):
            hi, hj = int(np.clip(ii + rng.integers(-2, 3), 0, NX - 1)), int(np.clip(jj + rng.integers(-2, 3), 0, NY - 1))
            for k in range(NZ):
                b = block_id(hi, hj, k)
                out.append({"hole": f"DH{hi:02d}{hj:02d}", "kind": "exploration", "block": b, "cu": round(float(mine["cu"][b] * rng.lognormal(0, 0.08)), 4),
                            "as": round(float(mine["as"][b] * rng.lognormal(0, 0.10)), 1), "bwi": round(float(mine["bwi"][b] + rng.normal(0, 0.4)), 2)})
    return out


BLAST_BLOCKS = 12                                          # a blast pattern: 12 consecutive blocks of a shovel's sequence


def blasts_ready(mine, state):
    """Blocks whose blast-hole assays are back at the start of a shift: the blast being dug and the next one."""
    out = {}
    for s in mine["shovels"]:
        c = state["shovels"][s["id"]]["pos"] // BLAST_BLOCKS
        out[s["id"]] = s["seq"][: (c + 2) * BLAST_BLOCKS]
    return out


def blasts_assayed(mine, state):
    """Blocks with blast-hole assays on file at the start of a shift: every blast up to the one being dug."""
    return {s["id"]: s["seq"][: (state["shovels"][s["id"]]["pos"] // BLAST_BLOCKS + 1) * BLAST_BLOCKS] for s in mine["shovels"]}


LAB_MIN = 90.0                                            # the next blast's assays come back from the lab 90 minutes into a shift


def next_blast(mine, state, shovel):
    """The blast a shovel digs after the one it is in at the start of the shift."""
    s = next(x for x in mine["shovels"] if x["id"] == shovel)
    c = state["shovels"][shovel]["pos"] // BLAST_BLOCKS
    return s["seq"][(c + 1) * BLAST_BLOCKS:(c + 2) * BLAST_BLOCKS]


def zone_ahead_of(mine, state, shovel, radius_m=45.0, factor=0.3):
    """A low-grade zone (a barren dyke the drill holes missed) centred on the start of a shovel's next blast."""
    blocks = next_blast(mine, state, shovel)[:8]
    x, y = np.mean([block_xy(b) for b in blocks], 0)
    return {"kind": "low_grade_zone", "shovel": shovel, "bench": int(block_ijk(blocks[0])[2]), "x": round(float(x), 1), "y": round(float(y), 1),
            "radius_m": radius_m, "factor": factor}


def assays_due(mine, state, told, a, b):
    """Blast-hole assays that come back from the lab between local minutes a and b of the shift: every shovel's next blast at
    LAB_MIN, or later when the generator was told the lab is behind on it."""
    t0 = state["shift"] * SHIFT_MIN
    out = []
    for s in mine["shovels"]:
        at = LAB_MIN
        for z in told:
            if z["kind"] == "low_grade_zone" and z.get("shovel") == s["id"] and z.get("assays_at_min") is not None:
                at = z["assays_at_min"]
        if a <= at < b:
            out += [dict(blast_assay(mine, blk, [z for z in told if z["kind"] == "low_grade_zone"]), at_min=t0 + at) for blk in next_blast(mine, state, s["id"])]
    return out


def blast_assay(mine, b, told=()):
    """One blast-hole sample per block (coarser than a drill core: larger error)."""
    cu, as_, bwi = true_grades(mine, told) if told else (mine["cu"], mine["as"], mine["bwi"])
    rng = np.random.default_rng([mine["seed"], 4, b])
    return {"hole": f"BH{b}", "kind": "blasthole", "block": int(b), "cu": round(float(cu[b] * rng.lognormal(0, 0.12)), 4),
            "as": round(float(as_[b] * rng.lognormal(0, 0.14)), 1), "bwi": round(float(bwi[b] + rng.normal(0, 0.6)), 2)}


# --- haul roads and truck physics ------------------------------------------------------------------------------------------
def face_segments(b):
    """Face (the block a shovel is digging) to the pit exit: bench road to the ramp, then the ramp. [(length m, grade, kind)]"""
    x, y = block_xy(b)
    k = block_ijk(b)[2]
    rx, ry = ramp_xy(k)
    return [(1.15 * (abs(x - rx) + abs(y - ry)), 0.0, "bench"), (RAMP_LEN * (k + 1), RAMP_GRADE, "ramp")]


def route(frm, to):
    """Segments between a face (int block id) or 'goline', and a destination; uphill grades positive in the direction of travel."""
    if isinstance(frm, (int, np.integer)):
        L, g = SURFACE[to]
        return face_segments(frm) + [(L, g, "surface")]
    if frm == "goline":
        return [(120.0, 0.0, "surface")] + [(L, -g, kind) for L, g, kind in reversed(face_segments(to))]
    L, g = SURFACE[frm]
    return [(L, -g, "surface")] + [(L2, -g2, kind) for L2, g2, kind in reversed(face_segments(to))]


CAP_KMH = {"bench": 24.0, "ramp": 34.0, "surface": 45.0}


def segment(L, grade, kind, gross_t, wet, eff=1.0):
    """-> (minutes, litres, power fraction) for one segment, from the truck's power curve and rolling resistance."""
    rr = 0.022 + (0.012 if wet else 0.0) + (0.008 if kind == "bench" else 0.0)
    resist = grade + rr
    cap = CAP_KMH[kind] * (0.85 if wet else 1.0)
    if grade < -0.02 and gross_t > TRUCK_EMPTY_T + 50:
        cap = min(cap, 20.0)                                          # retarding a loaded truck downhill
    v = cap / 3.6 if resist <= 0.004 else min(cap / 3.6, POWER_KW * 1000 * 0.85 * eff / (gross_t * 1000 * 9.81 * resist))
    minutes = L / v / 60 + (0.35 if kind == "bench" else 0.25)       # acceleration and corners
    work = gross_t * 1000 * 9.81 * max(resist, 0.0) * L
    power = min(1.0, gross_t * 1000 * 9.81 * max(resist, 0.0) * v / (POWER_KW * 1000))
    return minutes, work / (0.33 * 36e6), power


def travel(segs, gross_t, wet, eff=1.0, noise=1.0):
    t = fuel = 0.0
    parts = []
    for L, g, kind in segs:
        m, f, p = segment(L, g, kind, gross_t, wet, eff)
        m *= noise
        parts.append((m, p, L / max(m, 1e-6) * 0.06))                  # minutes, power fraction, km/h
        t += m
        fuel += f
    return t, fuel, parts


# --- the shift: an event simulation of trucks, shovels, the crusher, the bin and the mill -------------------------------------
def initial_state(mine):
    return {"shift": 0, "shovels": {s["id"]: {"pos": 0, "remaining": BLOCK_T} for s in mine["shovels"]},
            "stock": {"hg": [150000.0, 150000 * 0.56, 150000 * 170.0, 150000 * 13.6], "lg": [420000.0, 420000 * 0.33, 420000 * 160.0, 420000 * 13.4]},
            "bin": [2500.0, 2500 * 0.6, 2500 * 160.0, 2500 * 13.5], "down_until": {}}


def stock_survey(mine, state):
    """The stockpile survey and sampling campaign the mine starts with: tonnes by drone survey, grades by trenching, with error."""
    rng = np.random.default_rng([mine["seed"], 6])
    out = {}
    for k, (t, cu_t, as_t, bwi_t) in state["stock"].items():
        out[k] = {"tonnes": round(t * rng.normal(1, 0.02)), "cu": round(cu_t / t * rng.lognormal(0, 0.05), 4), "cu_sd": round(0.06 * cu_t / t, 4),
                  "as": round(as_t / t * rng.lognormal(0, 0.06), 1), "as_sd": round(0.08 * as_t / t, 1), "bwi": round(bwi_t / t + rng.normal(0, 0.3), 2)}
    return out


def natural_events(mine, shift, trucks_up):
    """What happens on its own in a history shift: wet roads, truck breakdowns (some with a precursor), mill trips."""
    rng = np.random.default_rng([mine["seed"], 5, shift])
    wet = bool(rng.random() < 0.2)
    downs = []
    for _ in range(rng.poisson(0.9)):
        if not trucks_up:
            break
        kind = str(rng.choice(["tyre", "cooling", "oil", "electrical"], p=[0.3, 0.3, 0.25, 0.15]))
        downs.append({"kind": "breakdown", "truck": str(rng.choice(trucks_up)), "at_min": float(rng.uniform(60, 700)), "failure": kind})
    trips = [{"at_min": float(rng.uniform(30, 650)), "minutes": float(rng.uniform(20, 60))} for _ in range(rng.poisson(0.7))]
    return wet, downs, trips


PRECURSOR_MIN = {"cooling": 120.0, "oil": 90.0}


def run_shift(mine, state, plans, told=(), until=SHIFT_MIN, natural=True, record=True):
    """Simulate one 12-hour shift from its start-of-shift state under a plan schedule [(minute, plan)], up to `until` minutes.

    A plan: {"mode": "fixed" | "targets" | "nearest", "assign": {truck: shovel}, "targets": {shovel: t/h},
             "route": {shovel: {"HG": dest, "LG": dest, "W": "dump"}}, "block_class": {block: "HG" | "LG" | "W"},
             "reclaim": {"mode": "proportional"} | {"mode": "schedule", "hours": [{"hg": t/h, "lg": t/h}, ...]}}
    The generator does what the plan says, with the ore-control classes the plan gives it; the truth only decides what happens.
    Returns the haul log, engine telemetry, plant hours, assays that arrived, breakdowns and the end-of-shift state.
    """
    seed, shift = mine["seed"], state["shift"]
    t0 = shift * SHIFT_MIN
    cu_tr, as_tr, bwi_tr = true_grades(mine, [z for z in told if z["kind"] == "low_grade_zone"])
    trucks = {t["id"]: t for t in mine["trucks"]}
    tix = {t["id"]: n for n, t in enumerate(mine["trucks"])}
    shovels = {s["id"]: s for s in mine["shovels"]}
    six = {s["id"]: n for n, s in enumerate(mine["shovels"])}
    up = [t for t in trucks if state["down_until"].get(t, -1) <= t0]
    if natural:
        wet, downs, trips = natural_events(mine, shift, up)
    else:
        wet, downs, trips = False, [], []
    downs = downs + [{"kind": "breakdown", "truck": z["truck"], "at_min": z["at_min"], "failure": z["failure"]}
                     for z in told if z["kind"] == "breakdown" and z["shift"] == shift]
    trips = trips + [{"at_min": z["at_min"], "minutes": z["minutes"]} for z in told if z["kind"] == "mill_trip" and z["shift"] == shift]
    fail_at = {}
    for d in sorted(downs, key=lambda d: d["at_min"]):
        if d["truck"] in up and d["truck"] not in fail_at:
            fail_at[d["truck"]] = d
    plans = sorted(plans, key=lambda p: p[0])

    def plan_at(t):
        return [p for m, p in plans if m <= t][-1]

    sh = {s: {"pos": v["pos"], "remaining": v["remaining"], "queue": [], "busy": False, "loads": 0, "loaded_t": 0.0, "enroute": 0} for s, v in state["shovels"].items()}
    stock = {k: list(v) for k, v in state["stock"].items()}
    binv = list(state["bin"])
    ev, seq = [], [0]

    def push(t, kind, *a):
        seq[0] += 1
        heapq.heappush(ev, (t, seq[0], kind, a))
    T = {tid: {"k": 0, "node": "goline", "down": False, "seg": [], "s": None} for tid in up}
    for n, tid in enumerate(sorted(up)):
        push(START_DELAY + 0.7 * n, "dispatch", tid)
    for m in range(0, SHIFT_MIN, 5):
        push(float(m), "tick")
    haul, hours, crusher_q, crusher = [], {}, [], {"busy": False}
    plan_start = {}

    def rng_for(tid, k):
        return np.random.default_rng([seed, shift, 7, tix[tid], k])

    def face(s):
        return shovels[s]["seq"][min(sh[s]["pos"], len(shovels[s]["seq"]) - 1)]

    def seg_log(tid, start, parts, payload):
        tt = start
        for m, p, v in parts:
            T[tid]["seg"].append((tt, tt + m, p, v, payload))
            tt += m

    def dispatch_choice(tid, t):
        p = plan_at(t)
        mode = p["mode"]
        if mode == "fixed":
            return p["assign"].get(tid)
        frm = T[tid]["node"]
        best, score = None, None
        for s in shovels:
            if mode == "targets" and p["targets"].get(s, 0) <= 0:
                continue
            tt = travel(route(frm, face(s)), TRUCK_EMPTY_T, wet)[0]
            if mode == "nearest":                   # earliest expected start of loading
                wait = (len(sh[s]["queue"]) + sh[s]["enroute"] + sh[s]["busy"]) * shovels[s]["load_min"]
                val = -(max(tt, wait))
            else:                                   # the shovel furthest behind its target rate, counting trucks on the way
                key = id(p)
                if key not in plan_start:
                    plan_start[key] = (t, {s2: sh[s2]["loaded_t"] for s2 in sh})
                ps, base = plan_start[key]
                due = p["targets"][s] * (t - ps + tt) / 60
                done = sh[s]["loaded_t"] - base[s] + (sh[s]["enroute"] + len(sh[s]["queue"])) * PAYLOAD_T
                val = (due - done) / p["targets"][s] - 0.002 * tt
            if score is None or val > score:
                best, score = s, val
        return best

    def broken(tid, t):
        f = fail_at.get(tid)
        return f is not None and t >= f["at_min"]

    def start_load(s, t):
        while sh[s]["queue"]:
            tid, arr = sh[s]["queue"].pop(0)
            if broken(tid, t):
                T[tid]["down"] = True
                continue
            sh[s]["busy"] = True
            r = np.random.default_rng([seed, shift, 8, six[s], sh[s]["loads"]])
            sh[s]["loads"] += 1
            kind = SHOVEL_KINDS[shovels[s]["kind"]]
            lt = SPOT_MIN + kind["passes"] * kind["pass_min"] * float(r.lognormal(0, 0.08))
            T[tid]["c"].update(queue_load=t - arr, load=lt)
            seg_log(tid, t, [(lt, 0.08, 0.0)], 0.0)
            push(t + lt, "loaded", tid, s)
            return

    def try_crusher(t):
        while crusher_q and not crusher["busy"]:
            tid, arr = crusher_q[0]
            if broken(tid, t):
                crusher_q.pop(0)
                T[tid]["down"] = True
                continue
            if binv[0] + T[tid]["c"]["payload"] > BIN_T:
                return
            crusher_q.pop(0)
            crusher["busy"] = True
            T[tid]["c"]["queue_dump"] = t - arr
            seg_log(tid, t, [(DUMP_MIN["crusher"], 0.1, 0.0)], T[tid]["c"]["payload"])
            push(t + DUMP_MIN["crusher"], "dumped", tid, "crusher")

    def hour(t):
        h = int(t // 60)
        return hours.setdefault(h, {"hour": h, "delivered_t": 0.0, "reclaim_t": 0.0, "processed_t": 0.0, "cu_t": 0.0, "as_t": 0.0, "bwi_t": 0.0,
                                    "bin_start_t": binv[0], "outage_min": 0.0, "by_pile": {}, "copper_t": 0.0, "value": 0.0})

    def add(acc, t_, cu, as_, bwi):
        acc[0] += t_
        acc[1] += t_ * cu
        acc[2] += t_ * as_
        acc[3] += t_ * bwi

    while ev:
        t, _, kind, a = heapq.heappop(ev)
        if t >= until:
            break
        if kind == "tick":
            hr = hour(t)
            dt = 5.0
            p = plan_at(t)
            rc = p.get("reclaim", {"mode": "proportional"})
            if rc["mode"] == "schedule":
                hh = int(t // 60)
                rates = rc["hours"][hh] if hh < len(rc["hours"]) else {}
            else:                                                          # keep the bin fed: reclaim in proportion to the piles
                tot = sum(v[0] for v in stock.values())
                rates = {k: LOADER_TPH * v[0] / tot for k, v in stock.items()} if binv[0] < 0.6 * BIN_T and tot > 0 else {}
            for k, rate in rates.items():
                take = min(rate * dt / 60, stock[k][0], max(0.0, 0.92 * BIN_T - binv[0]))
                if take > 0:
                    f = take / stock[k][0]
                    moved = [x * f for x in stock[k]]
                    stock[k] = [x - y for x, y in zip(stock[k], moved)]
                    binv = [x + y for x, y in zip(binv, moved)]
                    hr["reclaim_t"] += take
                    hr["by_pile"][k] = hr["by_pile"].get(k, 0.0) + take
            out_min = sum(max(0.0, min(t + dt, tr["at_min"] + tr["minutes"]) - max(t, tr["at_min"])) for tr in trips)
            hr["outage_min"] += out_min
            if binv[0] > 1e-6:
                bw = binv[3] / binv[0]
                proc = min(binv[0], mill_tph(bw) * (dt - out_min) / 60)
                if proc > 0:
                    f = proc / binv[0]
                    cu, as_ = binv[1] / binv[0], binv[2] / binv[0]
                    binv = [x * (1 - f) for x in binv]
                    hr["processed_t"] += proc
                    hr["cu_t"] += proc * cu
                    hr["as_t"] += proc * as_
                    hr["bwi_t"] += proc * bw
                    hr["copper_t"] += proc * cu / 100 * recovery(cu)
                    hr["value"] += proc * value_per_t(cu, as_)
            try_crusher(t)
            continue
        tid = a[0]
        if T[tid]["down"]:
            continue
        if broken(tid, t):
            T[tid]["down"] = True
            if kind == "arrive":
                sh[a[1]]["enroute"] -= 1
            if kind == "loaded":
                sh[a[1]]["busy"] = False
                start_load(a[1], t)
            if kind == "dumped" and a[1] == "crusher":
                crusher["busy"] = False
                try_crusher(t)
            continue
        if kind == "dispatch":
            s = dispatch_choice(tid, t)
            if s is None:
                continue
            k = T[tid]["k"]
            r = rng_for(tid, k)
            n_e, n_l, n_f = float(r.lognormal(0, 0.05)), float(r.lognormal(0, 0.05)), float(r.lognormal(0, 0.04))
            payload = float(np.clip(r.normal(PAYLOAD_T * 0.985, 0.035 * PAYLOAD_T), 180, 240))
            tr = trucks[tid]
            et, ef, parts = travel(route(T[tid]["node"], face(s)), TRUCK_EMPTY_T, wet, tr["eff"], n_e * tr["operator"])
            seg_log(tid, t, parts, 0.0)
            T[tid]["c"] = {"truck": tid, "shovel": s, "from": T[tid]["node"], "dispatched": t, "empty": et, "fuel": ef, "payload": payload,
                           "n_l": n_l, "n_f": n_f, "queue_at_dispatch": len(sh[s]["queue"]) + int(sh[s]["busy"]), "enroute_at_dispatch": sh[s]["enroute"],
                           "to_crusher_at_dispatch": sum(1 for x in T.values() if x.get("c") and x["c"].get("dest") == "crusher" and x["c"].get("loaded_at") and not x["down"])}
            sh[s]["enroute"] += 1
            push(t + et, "arrive", tid, s)
        elif kind == "arrive":
            s = a[1]
            sh[s]["enroute"] -= 1
            sh[s]["queue"].append((tid, t))
            if not sh[s]["busy"]:
                start_load(s, t)
        elif kind == "loaded":
            s = a[1]
            c = T[tid]["c"]
            b = face(s)
            p = plan_at(t)
            cls = p["block_class"].get(str(b), "W")
            dest = p["route"].get(s, {}).get(cls, "dump" if cls == "W" else "lg")
            if dest == "crusher|hg":                                    # direct feed unless the bin is backing up
                dest = "hg" if binv[0] > 0.9 * BIN_T or len(crusher_q) >= 3 else "crusher"
            c.update(block=int(b), cls=cls, dest=dest, loaded_at=t, cu=float(cu_tr[b]), as_=float(as_tr[b]), bwi=float(bwi_tr[b]))
            sh[s]["remaining"] -= c["payload"]
            sh[s]["loaded_t"] += c["payload"]
            if sh[s]["remaining"] <= 0:
                sh[s]["pos"] += 1
                sh[s]["remaining"] += BLOCK_T
            sh[s]["busy"] = False
            start_load(s, t)
            tr = trucks[tid]
            ht, hf, parts = travel(route(int(b), dest), TRUCK_EMPTY_T + c["payload"], wet, tr["eff"], c["n_l"] * tr["operator"])
            seg_log(tid, t, parts, c["payload"])
            c.update(haul=ht, fuel=c["fuel"] + hf)
            push(t + ht, "at_dest", tid)
        elif kind == "at_dest":
            c = T[tid]["c"]
            if c["dest"] == "crusher":
                crusher_q.append((tid, t))
                try_crusher(t)
            else:
                c["queue_dump"] = 0.0
                seg_log(tid, t, [(DUMP_MIN[c["dest"]], 0.1, 0.0)], c["payload"])
                push(t + DUMP_MIN[c["dest"]], "dumped", tid, c["dest"])
        elif kind == "dumped":
            c = T[tid]["c"]
            dest = a[1]
            if dest == "crusher":
                crusher["busy"] = False
                add(binv, c["payload"], c["cu"], c["as_"], c["bwi"])
                hour(t)["delivered_t"] += c["payload"]
            elif dest in stock:
                add(stock[dest], c["payload"], c["cu"], c["as_"], c["bwi"])
            idle = c["queue_load"] + c["load"] + c["queue_dump"] + DUMP_MIN[dest]
            fuel = (c["fuel"] + 35.0 * idle / 60) * c["n_f"]
            if record:
                haul.append({"truck": tid, "shovel": c["shovel"], "block": c["block"], "cls": c["cls"], "dest": dest, "from": c["from"],
                             "payload_t": round(c["payload"], 1), "dispatched_min": round(t0 + c["dispatched"], 2), "ended_min": round(t0 + t, 2),
                             "empty_min": round(c["empty"], 3), "queue_load_min": round(c["queue_load"], 3), "load_min": round(c["load"], 3),
                             "haul_min": round(c["haul"], 3), "queue_dump_min": round(c["queue_dump"], 3), "dump_min": DUMP_MIN[dest],
                             "cycle_min": round(t - c["dispatched"], 3), "fuel_l": round(fuel, 2), "queue_at_dispatch": c["queue_at_dispatch"],
                             "enroute_at_dispatch": c["enroute_at_dispatch"], "to_crusher_at_dispatch": c["to_crusher_at_dispatch"], "wet": wet,
                             "truth": {"cu": round(c["cu"], 4), "as": round(c["as_"], 1), "bwi": round(c["bwi"], 2)}})
            T[tid]["k"] += 1
            T[tid]["node"] = dest
            T[tid]["c"] = None
            push(t, "dispatch", tid)
            if dest == "crusher":
                try_crusher(t)
    end = min(until, SHIFT_MIN)
    plant = []
    for h in sorted(hours):
        r = hours[h]
        if (h + 1) * 60 > end:
            continue
        pt = r["processed_t"]
        rng = np.random.default_rng([seed, shift, 9, h])
        plant.append({"hour_min": t0 + h * 60, "delivered_t": round(r["delivered_t"], 1), "reclaim_t": round(r["reclaim_t"], 1), "reclaim_by_pile": {k: round(v, 1) for k, v in r["by_pile"].items()}, "processed_t": round(pt, 1),
                      "bin_start_t": round(r["bin_start_t"], 1), "outage_min": round(r["outage_min"], 1),
                      "feed_cu": round(r["cu_t"] / pt * float(rng.lognormal(0, 0.015)), 4) if pt else None,           # on-belt analyser
                      "feed_as": round(r["as_t"] / pt * float(rng.lognormal(0, 0.03)), 1) if pt else None,
                      "truth": {"feed_cu": round(r["cu_t"] / pt, 4) if pt else None, "feed_as": round(r["as_t"] / pt, 1) if pt else None,
                                "feed_bwi": round(r["bwi_t"] / pt, 2) if pt else None, "copper_t": round(r["copper_t"], 2), "value": round(r["value"], 0)}})
    telemetry = engine_telemetry(mine, shift, T, fail_at, end, wet) if record else []
    end_state = {"shift": shift + 1, "shovels": {s: {"pos": v["pos"], "remaining": v["remaining"]} for s, v in sh.items()},
                 "stock": stock, "bin": binv, "down_until": dict(state["down_until"])}
    for tid, f in fail_at.items():
        if f["at_min"] < end:
            end_state["down_until"][tid] = t0 + f["at_min"] + 600
    return {"shift": shift, "wet": wet, "haul": haul, "plant": plant, "telemetry": telemetry, "end_state": end_state, "until": end,
            "breakdowns": [{"truck": tid, "at_min": round(t0 + f["at_min"], 1), "failure": f["failure"]} for tid, f in fail_at.items() if f["at_min"] < end],
            "trucks_up_at_start": sorted(up), "mill_trips": [tr for tr in trips if tr["at_min"] < end]}


def engine_telemetry(mine, shift, T, fail_at, end, wet, window=10):
    """10-minute engine summaries per truck: coolant, oil pressure, exhaust, fuel rate, with the duty the truck was doing.
    A cooling fault heats the coolant for two hours before the engine shuts down; a failing oil pump loses pressure for 90
    minutes; tyres and electrics fail without warning. Sensors occasionally glitch for one window."""
    t0 = shift * SHIFT_MIN
    out = []
    trucks = {t["id"]: t for t in mine["trucks"]}
    for tid in trucks:
        if tid not in T:
            out += [{"truck": tid, "at_min": t0 + w * window, "state": "down"} for w in range(int(end // window))]
    for tid, st in T.items():
        tr = trucks[tid]
        f = fail_at.get(tid)
        segs = st["seg"]
        for w in range(int(end // window)):
            a, b = w * window, (w + 1) * window
            if f and a >= f["at_min"]:
                out.append({"truck": tid, "at_min": t0 + a, "state": "down"})
                continue
            cover = pw = sp = mv = pl = lt = 0.0
            for s0, s1, p, v, payload in segs:
                o = max(0.0, min(b, s1) - max(a, s0))
                if o <= 0:
                    continue
                cover += o
                pw += o * p
                if v > 0:
                    sp += o * v
                    mv += o
                if payload > 0:
                    pl += o * payload
                    lt += o
            pf = pw / window
            amb = ambient(t0 + (a + b) / 2)
            r = np.random.default_rng([mine["seed"], shift, 10, int(tid[1:]), w])
            off = tr["off"]
            cool = 82 + 16 * pf + 0.35 * (amb - 22) + 0.003 * tr["age_h"] / 100 + off["coolant_c"] + r.normal(0, 1.1)
            oil = 395 + 85 * pf - 0.9 * (amb - 22) + off["oil_kpa"] + r.normal(0, 9)
            exh = 340 + 300 * pf + 1.2 * (amb - 22) + off["exhaust_c"] + r.normal(0, 14)
            fuel = 38 + 330 * pf + r.normal(0, 8)
            if f and f["failure"] in PRECURSOR_MIN:
                lead = PRECURSOR_MIN[f["failure"]]
                frac = float(np.clip((b - (f["at_min"] - lead)) / lead, 0, 1))
                if f["failure"] == "cooling":
                    cool += 17 * frac ** 1.3
                else:
                    oil -= 150 * frac ** 1.2
            if r.random() < 0.004:
                cool += 16                                                         # a sensor glitch, one window
            if r.random() < 0.004:
                oil -= 160
            if r.random() < 0.003:
                exh += 260
            out.append({"truck": tid, "at_min": t0 + a, "state": "working" if cover >= 1 else "idle", "duty": round(pf, 3), "speed_kmh": round(sp / mv, 1) if mv else 0.0,
                        "payload_t": round(pl / lt, 1) if lt else 0.0, "loaded_frac": round(lt / window, 2), "ambient_c": round(amb, 1),
                        "coolant_c": round(cool, 1), "oil_kpa": round(oil, 1), "exhaust_c": round(exh, 1), "fuel_lph": round(fuel, 1)})
    return out


# --- what the mine did before the service: its legacy dispatch -----------------------------------------------------------
def legacy_plan(mine, state, mode):
    """The mine's own shift plan before the service: ore control from blast-hole assays at the cut-offs, trucks split in
    proportion to each shovel's dig rate (or dispatched to the nearest free shovel), cut-off routing, proportional reclaim."""
    t0 = state["shift"] * SHIFT_MIN
    up = sorted(t["id"] for t in mine["trucks"] if state["down_until"].get(t["id"], -1) <= t0)
    classes = {}
    ready = blasts_ready(mine, state)
    for s in mine["shovels"]:
        pos = state["shovels"][s["id"]]["pos"]
        for b in ready[s["id"]][pos:]:
            v = blast_assay(mine, b)["cu"]
            classes[str(b)] = "HG" if v >= CUTOFF["HG"] else "LG" if v >= CUTOFF["LG"] else "W"
    rates = {s["id"]: s["rate_tph"] for s in mine["shovels"]}
    share = np.array(list(rates.values()), float) / sum(rates.values()) * len(up)
    n = np.floor(share).astype(int)
    for i in np.argsort(-(share - n))[: len(up) - n.sum()]:
        n[i] += 1
    assign, it = {}, iter(up)
    for sid, k in zip(rates, n):
        for _ in range(k):
            assign[next(it)] = sid
    route_ = {s["id"]: {"HG": "crusher|hg", "LG": "lg", "W": "dump"} for s in mine["shovels"]}
    return {"mode": mode, "assign": assign, "targets": rates, "route": route_, "block_class": classes, "reclaim": {"mode": "proportional"}}


def history(mine, n_shifts):
    """The mine's recent past: n shifts under its legacy dispatch (fixed assignment and nearest-shovel on alternate shifts)."""
    state, out = initial_state(mine), []
    for n in range(n_shifts):
        plan = legacy_plan(mine, state, "fixed" if n % 2 == 0 else "nearest")
        res = run_shift(mine, state, [(0, plan)])
        res["plan"] = plan
        out.append(res)
        state = res["end_state"]
    state = dict(state, down_until={})          # the workshop returns every truck for the new week: the history ends clean
    return out, state
