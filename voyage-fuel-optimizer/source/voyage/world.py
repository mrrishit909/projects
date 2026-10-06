"""A synthetic North Atlantic and a small fleet sailing it.

The ocean is a 0.5-degree grid from 30N to 60N and 76W to 3W, with coastlines drawn coarsely. Its weather is a smooth
westerly flow with travelling meanders, plus storms: lows that form off North America, run east-north-east for three to
six days and carry a cyclonic wind field and a sea of their own. Waves follow the wind. The Gulf Stream and North
Atlantic Current are a fixed jet along their usual path. Everything is a function of (seed, time), so any hour can be
re-evaluated, and a storm can be added by telling the generator (`told`).

Forecasts: a forecast issued at hour t_i is the truth with errors that grow with lead time (storm tracks drift, storms
strengthen or weaken, the meanders run ahead or behind), and it does not contain storms that form more than 48 hours
after it was issued. Ensemble members are the forecast with independent errors of the same size, so the truth is
statistically one more member: that is what makes an ETA band computable and checkable.

Ships: each vessel has its own true speed-power curve (roughly cubic in speed through the water, exponent 2.9-3.3),
displacement, added resistance in waves (head seas worst) and wind, hull fouling that grows with days since the last
cleaning, an engine whose specific consumption rises at low load, and auxiliary consumption. In heavy head seas the
master slows down further, and power is capped at 90% of MCR. The service never sees these parameters: it sees noon reports,
AIS positions, hourly engine samples and the yard's sea-trial curve (calm water, clean hull, design draft). A speed
order is an engine setting (the power for that speed in calm water), so weather costs time, not extra fuel per hour.
"""
import functools
import math
import zlib

import numpy as np

LAT0, LAT1, LON0, LON1, RES = 30.0, 60.0, -76.0, -3.0, 0.5
NLAT, NLON = int(round((LAT1 - LAT0) / RES)) + 1, int(round((LON1 - LON0) / RES)) + 1
KN_PER_MS = 1.9438
CO2_PER_T_FUEL = 3.114            # IMO conversion factor for heavy fuel oil, t CO2 per t fuel
HS_SEEN_AHEAD_H = 48              # a forecast contains storms that form up to 48 h after it is issued
DAY0 = 0                          # hour 0 of the simulation is the epoch the API maps to a date

# --- geography -----------------------------------------------------------------------------------------------------
LAND = [   # (lon, lat) polygons, coarse on purpose
    [(-100, 25), (-81, 25), (-80.5, 30), (-79, 33), (-75.6, 35.2), (-75.9, 36.8), (-74.9, 38.8), (-74.1, 40.0), (-73.9, 40.55),
     (-72, 40.85), (-71.8, 41.1), (-70.0, 41.3), (-69.9, 41.9), (-70.6, 42.5), (-70.6, 43.1), (-69, 43.9), (-67, 44.6), (-66, 43.9),
     (-65.4, 43.4), (-63.5, 44.6), (-61, 45.2), (-60, 45.9), (-60.5, 47), (-59.3, 47.6), (-55.7, 47.6), (-55.5, 46.9), (-54, 46.8),
     (-53.6, 46.6), (-52.7, 46.7), (-52.6, 47.6), (-53, 48.3), (-53.5, 49.2), (-55.5, 49.8), (-55.6, 51.5), (-56, 52), (-55.7, 53),
     (-57.5, 54.5), (-60.5, 55.5), (-61.5, 57), (-63, 58.5), (-64.5, 60.5), (-100, 60.5)],
    [(-10, 25), (-10, 29), (-9.8, 30.5), (-9.3, 32.5), (-8.5, 33.3), (-6.8, 34.1), (-5.9, 35.8), (-6.3, 36.6), (-7.4, 37.2), (-8.9, 37.0),
     (-8.8, 38.5), (-9.5, 38.8), (-8.9, 40.5), (-8.9, 42.0), (-9.3, 42.9), (-8.3, 43.6), (-7.0, 43.6), (-4.5, 43.45), (-1.8, 43.4),
     (-1.3, 44.5), (-1.2, 46.0), (-2.2, 47.1), (-3.0, 47.5), (-4.4, 47.8), (-4.8, 48.3), (-4.6, 48.6), (-3.0, 48.85), (-1.9, 48.7),
     (-1.6, 49.65), (-1.2, 49.4), (0.1, 49.5), (1.5, 50.1), (1.6, 50.9), (2.5, 51.1), (3.6, 51.5), (4.5, 52.4), (4.7, 53.0), (6, 53.5),
     (8.5, 53.6), (8.7, 55), (8.1, 56.6), (10, 58), (20, 58), (20, 25)],
    [(-10.4, 51.6), (-9.5, 51.4), (-6.3, 52.1), (-6.0, 53.3), (-5.6, 54.6), (-7.2, 55.3), (-8.5, 55.2), (-10.0, 54.2), (-10.2, 53.4),
     (-9.8, 52.7)],
    [(-5.7, 50.0), (-3.5, 50.3), (-1.0, 50.7), (1.4, 51.2), (1.7, 52.6), (0.2, 53.5), (-0.4, 54.5), (-1.6, 55.6), (-2.0, 57.6),
     (-3.0, 58.6), (-5.0, 58.6), (-6.3, 57.6), (-5.7, 56.0), (-5.0, 54.8), (-3.1, 53.9), (-4.6, 53.3), (-4.2, 52.3), (-5.3, 51.8),
     (-4.2, 51.5), (-3.0, 51.2), (-4.5, 50.9)],
    [(-25, 63.5), (-24, 60.5), (-12, 60.5), (-12, 63.5)],          # keeps routes south of Iceland and the Faroes
]
CHANNEL = [(49.7, -3.0), (50.2, -0.5), (50.65, 0.9), (51.05, 1.65)]       # Ushant approach to the Dover Strait, (lat, lon)
PORTS = {   # code: name, side, ocean end of the passage (a grid node), coastal waypoints from there to the pilot station
    "USNYC": ("New York", "W", (40.5, -73.5), [(40.45, -73.83)]),
    "USORF": ("Norfolk", "W", (36.5, -75.5), [(36.93, -75.95)]),
    "CAHAL": ("Halifax", "W", (44.0, -63.0), [(44.45, -63.5)]),
    "NLRTM": ("Rotterdam", "E", (48.5, -5.5), CHANNEL + [(51.6, 2.9), (52.0, 3.95)]),
    "BEANR": ("Antwerp", "E", (48.5, -5.5), CHANNEL + [(51.45, 3.0), (51.4, 3.4)]),
    "FRLEH": ("Le Havre", "E", (48.5, -5.5), [(49.7, -3.0), (50.0, -1.0), (49.55, -0.05)]),
    "DEHAM": ("Hamburg", "E", (48.5, -5.5), CHANNEL + [(52.6, 3.4), (53.9, 6.6), (54.0, 8.1)]),
}
WEST, EAST = [p for p, v in PORTS.items() if v[1] == "W"], [p for p, v in PORTS.items() if v[1] == "E"]


def _inside(lon, lat, poly):
    x, y = np.asarray(lon, float), np.asarray(lat, float)
    inside = np.zeros(np.broadcast(x, y).shape, bool)
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        cross = ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1)
        inside ^= cross
    return inside


def is_land(lat, lon):
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    return np.any([_inside(lon, lat, p) for p in LAND], axis=0)


def nm(lat1, lon1, lat2, lon2):
    """Great-circle distance in nautical miles (vectorised)."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * 3440.065 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def bearing(lat1, lon1, lat2, lon2):
    """Initial course in degrees from north, clockwise."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    return (np.degrees(np.arctan2(np.sin(dl) * np.cos(p2), np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl))) + 360) % 360


class Grid:
    """Ocean nodes on the 0.5-degree lattice and 16-neighbour edges (the knight moves give 22.5-degree course steps)."""

    def __init__(self):
        la, lo = np.meshgrid(LAT0 + RES * np.arange(NLAT), LON0 + RES * np.arange(NLON), indexing="ij")
        ocean = ~is_land(la, lo)
        # a node is usable only if the sea around it is too (no threading single cells between coastline vertices)
        self.ocean = ocean
        self.idx = -np.ones((NLAT, NLON), int)
        ii, jj = np.nonzero(ocean)
        self.idx[ii, jj] = np.arange(len(ii))
        self.ii, self.jj = ii, jj
        self.lat, self.lon = LAT0 + RES * ii, LON0 + RES * jj
        moves = [(a, b) for a in (-2, -1, 0, 1, 2) for b in (-2, -1, 0, 1, 2) if (a, b) != (0, 0) and math.gcd(abs(a), abs(b)) == 1]
        nb = -np.ones((len(ii), len(moves)), int)
        for k, (a, b) in enumerate(moves):
            i2, j2 = ii + a, jj + b
            ok = (i2 >= 0) & (i2 < NLAT) & (j2 >= 0) & (j2 < NLON)
            tgt = np.where(ok, self.idx[np.clip(i2, 0, NLAT - 1), np.clip(j2, 0, NLON - 1)], -1)
            # the straight line between the two nodes must stay at sea (checked at three interior points)
            for f in (0.25, 0.5, 0.75):
                tgt = np.where((tgt >= 0) & ~is_land(self.lat + f * a * RES, self.lon + f * b * RES), tgt, -1)
            nb[:, k] = tgt
        self.nb = nb
        safe = np.maximum(nb, 0)
        self.dist = np.where(nb >= 0, nm(self.lat[:, None], self.lon[:, None], self.lat[safe], self.lon[safe]), np.inf)
        self.course = np.where(nb >= 0, bearing(self.lat[:, None], self.lon[:, None], self.lat[safe], self.lon[safe]), 0.0)
        self.n = len(ii)

    def node(self, lat, lon):
        """Nearest ocean node."""
        d = (self.lat - lat) ** 2 + ((self.lon - lon) * math.cos(math.radians(lat))) ** 2
        return int(np.argmin(d))


_GRID = None


def grid():
    global _GRID
    if _GRID is None:
        _GRID = Grid()
    return _GRID


@functools.lru_cache(maxsize=256)
def _shortest(a, b):
    return tuple(shortest_sea_route_uncached(a, b))


def shortest_sea_route(a, b):
    return list(_shortest(int(a), int(b)))


def shortest_sea_route_uncached(a, b):
    """Node list of the shortest-distance path (the great-circle route where land allows), by Dijkstra."""
    import heapq
    g = grid()
    best = np.full(g.n, np.inf)
    prev = -np.ones(g.n, int)
    best[a] = 0
    heap = [(0.0, a)]
    while heap:
        d, u = heapq.heappop(heap)
        if u == b:
            break
        if d > best[u]:
            continue
        for v, w in zip(g.nb[u], g.dist[u]):
            if v >= 0 and d + w < best[v]:
                best[v], prev[v] = d + w, u
                heapq.heappush(heap, (d + w, v))
    out = [b]
    while out[-1] != a:
        out.append(int(prev[out[-1]]))
    return out[::-1]


def gc_points(a, b, step_nm):
    """Points along the great circle from a to b (lat, lon), about every step_nm, both ends included."""
    p1, l1, p2, l2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = float(nm(a[0], a[1], b[0], b[1]))
    n = max(1, int(math.ceil(d / step_nm)))
    delta = d / 3440.065
    if delta < 1e-9:
        return [a, b]
    out = []
    for k in range(n + 1):
        f = k / n
        A, B = math.sin((1 - f) * delta) / math.sin(delta), math.sin(f * delta) / math.sin(delta)
        x = A * math.cos(p1) * math.cos(l1) + B * math.cos(p2) * math.cos(l2)
        y = A * math.cos(p1) * math.sin(l1) + B * math.cos(p2) * math.sin(l2)
        z = A * math.sin(p1) + B * math.sin(p2)
        out.append((math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))))
    return out


def smooth(points, tol_nm=None):
    """Replace a lattice path by great-circle legs that stay at sea: from each point, the farthest later point that a great
    circle reaches without touching land (and, with tol_nm, without passing more than tol_nm from the points it skips, so a
    weather route keeps its shape). Removes the lattice's zig-zags and its rhumb-line bias."""
    pts = [tuple(map(float, p)) for p in points]
    out, i = [pts[0]], 0
    while i < len(pts) - 1:
        best = i + 1
        for j in range(i + 2, len(pts)):
            line = np.array(gc_points(pts[i], pts[j], 10.0))
            if is_land(line[1:-1, 0], line[1:-1, 1]).any():
                break
            if tol_nm is not None:
                skipped = np.array(pts[i + 1:j])
                dev = nm(skipped[:, None, 0], skipped[:, None, 1], line[None, :, 0], line[None, :, 1]).min(axis=1).max()
                if dev > tol_nm:
                    break
            best = j
        out += gc_points(pts[i], pts[best], 60.0)[1:]
        i = best
    return out


@functools.lru_cache(maxsize=512)
def _smoothed(points, tol_nm):
    return tuple(smooth(points, tol_nm))


def passage(orig, dest, nodes=None, start=None, tol_nm=30.0):
    """The full path (lat, lon arrays) from a port's pilot station (or a position at sea, `start`) to another's: coastal
    waypoints, the ocean leg, coastal waypoints. The ocean leg is the given lattice nodes smoothed into great-circle legs
    within tol_nm of them, or by default the shortest sea route smoothed without limit (the great circle where land allows)."""
    g = grid()
    o, d = PORTS[orig], PORTS[dest]
    if nodes is None:
        nodes, tol_nm = shortest_sea_route(g.node(*o[2]), g.node(*d[2])), None
    ocean = ([tuple(start)] if start is not None else []) + [(float(g.lat[n]), float(g.lon[n])) for n in nodes]
    ocean = list(_smoothed(tuple((round(a, 5), round(b, 5)) for a, b in ocean), tol_nm))
    head = [] if start is not None else list(reversed(o[3]))
    pts = head + ocean + list(d[3])
    clean = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - clean[-1][0]) > 1e-6 or abs(p[1] - clean[-1][1]) > 1e-6:
            clean.append(p)
    return np.array([p[0] for p in clean]), np.array([p[1] for p in clean])


class Path:
    """A polyline with cumulative distance and per-segment course; positions are interpolated along it."""

    def __init__(self, lat, lon):
        self.lat, self.lon = np.asarray(lat, float), np.asarray(lon, float)
        seg = nm(self.lat[:-1], self.lon[:-1], self.lat[1:], self.lon[1:])
        self.s = np.concatenate([[0.0], np.cumsum(seg)])
        self.course = bearing(self.lat[:-1], self.lon[:-1], self.lat[1:], self.lon[1:])
        self.length = float(self.s[-1])

    def at(self, s):
        s = np.clip(np.asarray(s, float), 0, self.length)
        k = np.clip(np.searchsorted(self.s, s, side="right") - 1, 0, len(self.s) - 2)
        f = (s - self.s[k]) / np.maximum(self.s[k + 1] - self.s[k], 1e-9)
        return self.lat[k] + f * (self.lat[k + 1] - self.lat[k]), self.lon[k] + f * (self.lon[k + 1] - self.lon[k]), self.course[k]


# --- ocean currents (fixed) ----------------------------------------------------------------------------------------
GULF_STREAM = np.array([(-80, 30.5), (-79.5, 32), (-77, 34), (-75, 35.5), (-72, 37), (-68, 38.5), (-63, 39.8), (-58, 40.5), (-52, 41.5),
                        (-46, 43), (-40, 45), (-33, 47), (-25, 49), (-15, 51), (-5, 53)], float)       # (lon, lat)
GS_SPEED = np.array([2.6, 2.8, 2.8, 2.6, 2.2, 1.9, 1.6, 1.3, 1.0, 0.8, 0.6, 0.5, 0.45, 0.4, 0.3])        # knots at the core
GS_WIDTH = np.array([0.5, 0.5, 0.55, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.3, 1.6, 1.9, 2.2, 2.4, 2.5])         # degrees (Gaussian sd)


def current(lat, lon):
    """(east, north) surface current in knots."""
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    best_d = np.full(np.broadcast(lat, lon).shape, np.inf)
    ce, cn = np.zeros_like(best_d), np.zeros_like(best_d)
    cosl = np.cos(np.radians(lat))
    for k in range(len(GULF_STREAM) - 1):
        (x1, y1), (x2, y2) = GULF_STREAM[k], GULF_STREAM[k + 1]
        dx, dy = (x2 - x1) * math.cos(math.radians((y1 + y2) / 2)), y2 - y1
        L2 = dx * dx + dy * dy
        px, py = (lon - x1) * cosl, lat - y1
        f = np.clip((px * dx + py * dy) / L2, 0, 1)
        d = np.hypot(px - f * dx, py - f * dy)
        sp = GS_SPEED[k] + f * (GS_SPEED[k + 1] - GS_SPEED[k])
        w = GS_WIDTH[k] + f * (GS_WIDTH[k + 1] - GS_WIDTH[k])
        better = d < best_d
        L = math.sqrt(L2)
        mag = sp * np.exp(-0.5 * (d / w) ** 2)
        ce, cn, best_d = np.where(better, mag * dx / L, ce), np.where(better, mag * dy / L, cn), np.where(better, d, best_d)
    return ce, cn


# --- weather -------------------------------------------------------------------------------------------------------
STORM_LIFE_MAX = 6 * 24


def _season(t):
    """1 in mid-winter (around 20 January), 0 in mid-summer."""
    doy = (np.asarray(t, float) / 24.0 + 278) % 365          # hour 0 is 5 October
    return 0.5 + 0.5 * np.cos(2 * np.pi * (doy - 20) / 365)


def key(text):
    """A stable integer for a string (Python's hash() is salted per process)."""
    return zlib.crc32(str(text).encode())


@functools.lru_cache(maxsize=20000)
def storms_born(seed, day):
    """The storms that form on a given day (Poisson, more in winter). Cached; callers copy before changing."""
    rng = np.random.default_rng([seed, 31, day + 100000])
    rate = 0.20 + 0.25 * float(_season(day * 24 + 12))
    out = []
    for k in range(rng.poisson(rate)):
        speed_kn = rng.uniform(15, 26)
        course = rng.uniform(55, 85)
        vmax = rng.uniform(14, 27) * (0.85 + 0.3 * float(_season(day * 24)))
        out.append({"id": f"{day}.{k}", "t0": day * 24 + rng.uniform(0, 24), "lat0": rng.uniform(35, 48), "lon0": rng.uniform(-72, -50),
                    "vlat": speed_kn * math.cos(math.radians(course)) / 60, "vlon_kn": speed_kn * math.sin(math.radians(course)),
                    "life": rng.uniform(3, 6) * 24, "vmax": vmax, "radius": rng.uniform(3.0, 4.5), "hmax": 0.0125 * vmax ** 2 + rng.uniform(0, 1.0)})
    return tuple(out)


def storms_for(seed, t_lo, t_hi, told=()):
    out = []
    for d in range(int(math.floor((t_lo - STORM_LIFE_MAX) / 24)) - 1, int(math.ceil(t_hi / 24)) + 1):
        out += storms_born(seed, d)
    out += [dict(s) for s in told if s["t0"] - 1 <= t_hi and s["t0"] + s["life"] + 1 >= t_lo]
    return [s for s in out if s["t0"] <= t_hi and s["t0"] + s["life"] >= t_lo]


BG_WAVES = [(40.0, 6.0), (24.0, 9.0), (15.0, 11.0)]         # meander wavelength (degrees of longitude), eastward drift (degrees a day)


def bg_params(seed):
    rng = np.random.default_rng([seed, 41])
    return {"amp": rng.uniform(2.5, 5.0, 3), "phase": rng.uniform(0, 2 * np.pi, 3), "jet": rng.uniform(46, 50)}


class Weather:
    """A view of the weather: the truth (issued=None) or a forecast issued at hour `issued` (member 0 is the control,
    1.. are ensemble members). Errors grow linearly with lead time and are keyed by (seed, issued, member, storm)."""
    POS_ERR = 0.55       # storm position error, degrees per day of lead, per axis
    INT_ERR = 0.10       # storm intensity error, log-scale per day of lead
    PHASE_ERR = 0.10     # meander phase error, radians per day of lead

    def __init__(self, seed, told=(), issued=None, member=0):
        self.seed, self.told, self.issued, self.member = seed, list(told), issued, member
        self.bg = bg_params(seed)

    def _errs(self, key):
        """Control error relative to the truth, plus the member's own error relative to the control."""
        if self.issued is None:
            return np.zeros(3)
        h = int(round(self.issued))
        e = np.random.default_rng([self.seed, 501, h, *key]).normal(0, 1, 3)
        if self.member:
            e = e + np.random.default_rng([self.seed, 502, h, self.member, *key]).normal(0, 1, 3)
        return e

    def _storms(self, lo_t, hi_t, include_climatology=True):
        """Storms this view contains. The truth: all of them. A forecast: those formed by 48 h after issue; an ensemble
        member adds storms of its own after that, drawn from the same climatology (the truth's later storms are one
        such draw, which the member cannot know)."""
        every = storms_for(self.seed, lo_t, hi_t, self.told)
        if self.issued is None:
            return every
        cutoff = self.issued + HS_SEEN_AHEAD_H
        out = [s for s in every if s["t0"] <= cutoff]
        if self.member and include_climatology:
            alt = (self.seed * 7919 + int(round(self.issued)) * 104729 + self.member * 15485863) % (2 ** 61)
            out += [dict(s, id=f"m{self.member}:{s['id']}") for s in storms_for(alt, lo_t, hi_t) if s["t0"] > cutoff]
        return out

    def _skey(self, s):
        return [key(s["id"])]

    def at(self, lat, lon, t):
        """-> dict of arrays: hs (m), wind east/north (m/s), wave direction (degrees the waves travel toward)."""
        lat, lon, t = np.broadcast_arrays(np.asarray(lat, float), np.asarray(lon, float), np.asarray(t, float))
        lead_d = np.maximum(0.0, t - self.issued) / 24.0 if self.issued is not None else np.zeros_like(t)
        bg, seas = self.bg, _season(t)
        u = (5.0 + 5.0 * seas) * np.exp(-((lat - bg["jet"]) / 9.0) ** 2) + 1.0
        v = np.zeros_like(u)
        ph_err = self._errs([0])
        for k, (wl, drift) in enumerate(BG_WAVES):
            ph = 2 * np.pi * (lon - drift * t / 24.0) / wl + bg["phase"][k] + self.PHASE_ERR * ph_err[k] * lead_d
            env = np.sin(np.pi * np.clip((lat - 28) / 34, 0, 1))
            u = u + 0.4 * bg["amp"][k] * np.cos(ph) * env
            v = v + bg["amp"][k] * np.sin(ph) * env
        wind2 = u * u + v * v
        hs2 = (0.5 + 0.024 * wind2) ** 2
        lo_t, hi_t = float(t.min()), float(t.max())
        for s in self._storms(lo_t, hi_t):
            age = t - s["t0"]
            act = (age >= 0) & (age <= s["life"])
            if not act.any():
                continue
            e = self._errs(self._skey(s))
            ld = lead_d if self.issued is not None else 0.0
            clat = s["lat0"] + s["vlat"] * age + self.POS_ERR * e[0] * ld
            clon = s["lon0"] + s["vlon_kn"] * age / (60 * np.cos(np.radians(clat))) + self.POS_ERR * e[1] * ld / np.cos(np.radians(clat))
            env = np.where(act, np.sin(np.pi * np.clip(age / s["life"], 0, 1)) ** 0.8, 0.0) * np.exp(self.INT_ERR * e[2] * ld)
            dx, dy = (lon - clon) * np.cos(np.radians(lat)), lat - clat
            r = np.hypot(dx, dy) + 1e-6
            R = s["radius"]
            vt = s["vmax"] * env * (r / R) * np.exp(1 - r / R)
            u = u - vt * dy / r                                      # cyclonic (anticlockwise) in the northern hemisphere
            v = v + vt * dx / r
            hs2 = hs2 + (s["hmax"] * env * np.exp(-(r / (1.25 * R)) ** 2)) ** 2
        hs = np.sqrt(hs2)
        return {"hs": hs, "wu": u, "wv": v, "wdir": (np.degrees(np.arctan2(u, v)) + 360) % 360}

    def storms(self, t):
        """Storm centres at hour t as this view sees them (for maps)."""
        out = []
        for s in self._storms(t, t, include_climatology=False):
            age = t - s["t0"]
            if not 0 <= age <= s["life"]:
                continue
            e = self._errs(self._skey(s))
            ld = max(0.0, t - self.issued) / 24.0 if self.issued is not None else 0.0
            clat = s["lat0"] + s["vlat"] * age + self.POS_ERR * e[0] * ld
            clon = s["lon0"] + s["vlon_kn"] * age / (60 * math.cos(math.radians(clat))) + self.POS_ERR * e[1] * ld / math.cos(math.radians(clat))
            env = math.sin(math.pi * age / s["life"]) ** 0.8 * math.exp(self.INT_ERR * e[2] * ld)
            out.append({"id": s["id"], "lat": round(clat, 2), "lon": round(clon, 2), "hs_peak": round(s["hmax"] * env, 1), "wind_peak_ms": round(s["vmax"] * env, 1)})
        return out


def relative(course, wx):
    """Encounter terms for a ship on `course` (deg): head-sea factor g in [0,1] (1 = waves from ahead) and head wind (m/s)."""
    c = np.radians(course)
    from_dir = np.radians(wx["wdir"] + 180.0)
    g = (1 + np.cos(from_dir - c)) / 2
    head = -(wx["wu"] * np.sin(c) + wx["wv"] * np.cos(c))
    return g, head


# --- vessels -------------------------------------------------------------------------------------------------------
NAMES = ["Atlantic Sage", "Northline Juniper", "Cape Harrow", "Westerly Bloom", "Morrow Bay", "Linden Reach"]
TRIAL_SPEEDS = [12.0, 14.0, 16.0, 18.0, 20.0, 22.0]


def fleet(seed, n=6):
    """Each vessel's true parameters (the generator's) and its public particulars (what the service is given)."""
    rng = np.random.default_rng([seed, 11])
    out = []
    for i in range(n):
        scale = rng.uniform(0.75, 1.3)
        vd = rng.uniform(20.5, 22.5)
        mcr = 34000 * scale * rng.uniform(0.95, 1.05)
        v = {"ref": f"V{i + 1:02d}", "name": NAMES[i % len(NAMES)], "design_speed": round(vd, 1), "mcr_kw": round(mcr),
             "service_speed": round(vd - rng.uniform(2.5, 3.5), 1), "dwt": round(62000 * scale, -2), "teu": int(round(5000 * scale, -2)),
             "tank_t": round(5200 * scale, -1),
             "true": {"p_ref": 0.80 * mcr * rng.uniform(0.94, 1.04), "n": rng.uniform(2.9, 3.3), "k_wave": 15.0 * scale ** 0.7 * rng.uniform(0.8, 1.25),
                      "k_wind": 0.035 * scale ** 0.7 * rng.uniform(0.8, 1.25), "foul_per_year": rng.uniform(0.07, 0.20), "sfoc0": rng.uniform(165, 178),
                      "aux_tph": rng.uniform(0.08, 0.12), "cleaned_at": float(-24 * rng.uniform(380, 620)),
                      "recleaned_at": float(-24 * rng.uniform(80, 200)) if rng.random() < 0.5 else None}}
        if i == 0:      # the demo's vessel: long out of dock, so the sea-trial curve is well off
            v["true"].update(cleaned_at=-24 * 560.0, recleaned_at=None, foul_per_year=0.15)
        v["sea_trial"] = [[s, round(float(power(v, s, 0.0, 0.0, 0.0, 1.0, 0.0))), round(trial_fuel_tpd(v, s), 2)] for s in TRIAL_SPEEDS]
        out.append(v)
    return out


def days_since_cleaning(v, t):
    tr = v["true"]
    last = tr["recleaned_at"] if tr["recleaned_at"] is not None and t >= tr["recleaned_at"] else tr["cleaned_at"]
    return (np.asarray(t, float) - last) / 24.0


def sfoc(v, load):
    return v["true"]["sfoc0"] * (1 + 0.55 * (np.asarray(load) - 0.8) ** 2)


def power(v, stw, hs, g, head_ms, disp, days_clean):
    """Shaft power (kW) the true ship needs at a speed through the water."""
    tr = v["true"]
    stw = np.maximum(np.asarray(stw, float), 0.0)
    calm = tr["p_ref"] * (stw / v["design_speed"]) ** tr["n"] * np.asarray(disp, float) ** (2 / 3) * (1 + tr["foul_per_year"] * np.maximum(days_clean, 0) / 365)
    wave = tr["k_wave"] * np.asarray(hs) ** 2 * (0.1 + 0.9 * np.asarray(g) ** 1.5) * stw
    wr = stw + np.asarray(head_ms) * KN_PER_MS
    wind = tr["k_wind"] * (wr * np.abs(wr) - stw ** 2) * stw
    return np.maximum(calm + wave + wind, 0.02 * v["mcr_kw"])


def fuel_tph(v, p):
    return p * sfoc(v, p / v["mcr_kw"]) * 1e-6 + v["true"]["aux_tph"]


def trial_fuel_tpd(v, s):
    """The yard's sea-trial curve: calm water, clean hull, design draft (t/day, main engine + auxiliaries)."""
    return 24 * float(fuel_tph(v, power(v, s, 0.0, 0.0, 0.0, 1.0, 0.0)))


def voluntary_cap(design_speed, hs, g):
    """The master's speed limit in heavy weather: slows by 11% of design speed per metre of head sea above 4 m."""
    return design_speed * np.maximum(0.45, 1 - 0.11 * np.maximum(0, np.asarray(hs) - 4.0) * np.asarray(g))


def achieved(v, cmd, hs, g, head, disp, days_clean):
    """Speed through the water actually made. The command is an engine setting: the power that gives `cmd` knots in calm
    water. In wind and waves the same power makes less speed (the ship slows; it does not burn more), then the master's
    heavy-weather rule caps it, and power never exceeds 90% of MCR."""
    cmd = np.asarray(cmd, float)
    target = np.minimum(power(v, cmd, 0.0, 0.0, 0.0, disp, days_clean), 0.9 * v["mcr_kw"])
    stw = cmd.copy()
    for _ in range(5):          # P grows about with the cube of speed: a cube-root update converges in a few steps
        stw = stw * (target / power(v, stw, hs, g, head, disp, days_clean)) ** (1 / 3)
    return np.minimum(np.minimum(stw, cmd), voluntary_cap(v["design_speed"], hs, g))


# --- sailing ---------------------------------------------------------------------------------------------------------
class Field:
    """Weather views sampled on a lattice along a path: every `ds` nm and every `dt` hours from t_lo to t_hi. One vectorised
    evaluation per view; sailing then reads it hour by hour. Members share the path, so an ensemble is one array."""

    def __init__(self, path, views, t_lo, t_hi, ds=10.0, dt=1.0):
        self.path, self.ds, self.dt, self.t_lo = path, ds, dt, float(t_lo)
        self.sg = np.minimum(np.arange(0, path.length + ds, ds), path.length)
        self.lat, self.lon, self.crs = path.at(self.sg)
        self.tg = self.t_lo + dt * np.arange(int(math.ceil((t_hi - t_lo) / dt)) + 2)
        hs, g, head = [], [], []
        for wx in views:
            w = wx.at(self.lat[:, None], self.lon[:, None], self.tg[None, :])
            gg, hh = relative(self.crs[:, None], w)
            hs.append(w["hs"]), g.append(gg), head.append(hh)
        self.hs, self.g, self.head = np.array(hs), np.array(g), np.array(head)        # [member, s, t]
        ce, cn = current(self.lat, self.lon)
        c = np.radians(self.crs)
        self.cur = ce * np.sin(c) + cn * np.cos(c)                                     # along-track current, knots
        self.M = len(views)

    def sample(self, s, t):
        i = np.clip(np.rint(np.asarray(s) / self.ds).astype(int), 0, len(self.sg) - 1)
        x = np.clip((np.asarray(t) - self.t_lo) / self.dt, 0, len(self.tg) - 1.001)
        j = x.astype(int)
        f = x - j
        m = np.arange(self.M) if np.ndim(s) else 0
        pick = lambda a: a[m, i, j] * (1 - f) + a[m, i, j + 1] * f          # noqa: E731
        return pick(self.hs), pick(self.g), pick(self.head), self.cur[i], i


def integrate(F, legs, t0, s0, speed_fn, rate_fn, hours=None, max_hours=24 * 40, record=False):
    """Sail every member of field F along its path from distance s0 at hour t0, commanding each leg's speed
    (`legs`: [(end distance nm, commanded speed kn)]), for `hours` or until arrival. `speed_fn(cmd, hs, g, head, t)` gives the
    speed through the water made; `rate_fn(stw, hs, g, head, t)` the fuel in t/h. -> arrival hour, fuel, distance per member
    (and member 0's hourly track when `record`)."""
    ends = np.array([e for e, _ in legs], float)
    cmds = np.array([c for _, c in legs], float)
    L = F.path.length
    M = F.M
    s, t, fuel = np.full(M, float(s0)), np.full(M, float(t0)), np.zeros(M)
    limit = t0 + (hours if hours is not None else max_hours)
    track = []
    while True:
        live = (s < L - 1e-6) & (t < limit - 1e-9)
        if not live.any():
            break
        hs, g, head, cur, i = F.sample(s, t)
        cmd = cmds[np.minimum(np.searchsorted(ends, s + 1e-6), len(cmds) - 1)]
        stw = speed_fn(cmd, hs, g, head, t)
        sog = np.maximum(2.0, stw + cur)
        step = np.minimum(1.0, limit - t)
        frac = np.clip((L - s) / np.maximum(sog * step, 1e-9), 0, 1)
        rate = rate_fn(stw, hs, g, head, t)
        burn = np.where(live, rate * step * frac, 0.0)
        if record and live[0]:
            track.append({"t": float(t[0]), "s": float(s[0]), "lat": float(F.lat[i[0]]), "lon": float(F.lon[i[0]]), "course": float(F.crs[i[0]]),
                          "cmd": float(cmd[0]), "stw": float(stw[0]), "sog": float(sog[0]), "fuel_t": float(burn[0]), "hours": float(step[0] * frac[0]),
                          "hs": float(hs[0]), "g": float(g[0]), "head_ms": float(head[0]), "current_kn": float(cur[0])})
        s = np.where(live, s + sog * step * frac, s)
        t = np.where(live, t + step * frac, t)
        fuel = fuel + burn
    return {"t": t, "s": s, "fuel_t": fuel, "arrived": s >= L - 1e-6, "track": track}


def truth_fns(v, disp):
    """Speed and fuel functions of the true ship (what really happens at sea)."""
    def speed(cmd, hs, g, head, t):
        return achieved(v, cmd, hs, g, head, disp, days_since_cleaning(v, t))

    def rate(stw, hs, g, head, t):
        return fuel_tph(v, power(v, stw, hs, g, head, disp, days_since_cleaning(v, t)))
    return speed, rate


def sail(v, path, legs, wx, t0, disp, s0=0.0, hours=None, field=None, ds=10.0):
    """The true ship on one path through one weather view (the truth, normally). -> hourly track and totals."""
    slowest = min(c for _, c in legs)
    F = field or Field(path, [wx], t0, t0 + (hours if hours is not None else (path.length - s0) / max(4.0, 0.6 * slowest) + 24), ds=ds)
    speed, rate = truth_fns(v, disp)
    r = integrate(F, legs, t0, s0, speed, rate, hours=hours, record=True)
    for h in r["track"]:
        h["power_kw"] = float(power(v, h["stw"], h["hs"], h["g"], h["head_ms"], disp, days_since_cleaning(v, h["t"])))
        h["days_clean"] = float(days_since_cleaning(v, h["t"]))
        h["disp"] = disp
    return {"track": r["track"], "s": float(r["s"][0]), "t": float(r["t"][0]), "fuel_t": float(r["fuel_t"][0]), "arrived": bool(r["arrived"][0])}


def anchor_tph(v):
    return v["true"]["aux_tph"] * 1.1


# --- port congestion -------------------------------------------------------------------------------------------------
def port_ready(port, eta, told=()):
    """The hour from which the port can really berth a ship that arrives at `eta`: any time (minus infinity), unless the
    generator was told of congestion ({port, known_from_h, berth_from_h}) that is in force by then."""
    t = -math.inf
    for c in told:
        if c["port"] == port and c["known_from_h"] <= eta:
            t = max(t, c["berth_from_h"])
    return t


def lineup(seed, port, at_h, told=()):
    """What the port publishes at hour at_h: ships waiting at anchor and its estimate of the earliest berth for a new
    arrival (a few hours off the truth). Congestion shows from the hour it becomes known."""
    rng = np.random.default_rng([seed, 61, int(at_h), key(port)])
    waiting, est = int(rng.poisson(2)), None
    for c in told:
        if c["port"] == port and c["known_from_h"] <= at_h:
            waiting += int(c.get("ships_waiting", 14))
            est = max(est or 0.0, c["berth_from_h"] + float(rng.normal(0, 3)))
    return {"port": port, "ships_waiting": waiting, "earliest_berth_h": est}


def storm_across(path_lat, path_lon, t_cross, genesis_h, course=70.0, speed_kn=20.0, vmax=30.0, radius=4.0, life_h=120.0, sid="told-1"):
    """A storm that will be centred on (path_lat, path_lon) at hour t_cross, having formed at genesis_h and run on `course`."""
    age = t_cross - genesis_h
    vlat = speed_kn * math.cos(math.radians(course)) / 60
    vlon_kn = speed_kn * math.sin(math.radians(course))
    lat0 = path_lat - vlat * age
    lon0 = path_lon - vlon_kn * age / (60 * math.cos(math.radians(path_lat)))
    return {"id": sid, "t0": float(genesis_h), "lat0": float(lat0), "lon0": float(lon0), "vlat": vlat, "vlon_kn": vlon_kn, "life": float(life_h),
            "vmax": float(vmax), "radius": float(radius), "hmax": 0.0125 * vmax ** 2 + 0.5}


# --- history: a year of voyages, noon reports and AIS ---------------------------------------------------------------------
def noon_reports(v, track, voyage_ref, seed):
    """Aggregate an hourly track into noon reports (every 24 h of steaming) as the crew would file them: log speed,
    fuel from the flow meters (about 2% noise), wave height by eye (rounded to half a metre), the relative wind's head
    component from the anemometer, a relative-direction sector for the sea, the mean draft as displacement, days since the hull was cleaned."""
    out = []
    for k in range(0, len(track) - 12, 24):
        day = track[k:k + 24]
        if len(day) < 18:
            continue
        rng = np.random.default_rng([seed, 71, key(voyage_ref), k])
        hrs = len(day)
        hs = float(np.mean([h["hs"] for h in day]))
        g = float(np.mean([h["g"] for h in day]))
        head = float(np.mean([h["head_ms"] for h in day]))
        sector = int(round(math.degrees(math.acos(np.clip(2 * g - 1, -1, 1))) / 45)) % 8     # 0 head ... 4 following
        out.append({"t": day[0]["t"], "hours": hrs, "stw": round(float(np.mean([h["stw"] for h in day])) + rng.normal(0, 0.08), 2),
                    "sog": round(float(np.mean([h["sog"] for h in day])), 2), "distance_nm": round(float(sum(h["sog"] for h in day)), 1),
                    "fuel_t": round(float(sum(h["fuel_t"] for h in day)) * float(np.exp(rng.normal(0, 0.02))), 2),
                    "hs_obs": round(max(0.0, hs * float(np.exp(rng.normal(0, 0.12)))) * 2) / 2,
                    "wave_sector": min(sector, 4), "head_wind_obs": round(head + rng.normal(0, 1.0), 1),
                    "disp": round(day[0]["disp"], 3), "days_clean": round(day[0]["days_clean"], 1),
                    "lat": round(day[-1]["lat"], 3), "lon": round(day[-1]["lon"], 3)})
    return out


def history(seed, vessels, days=365, end_h=0.0):
    """Each vessel sails a year of passages between the American and European ports ending at hour `end_h`, at speeds its
    operator chose (12-20 kn, varying day to day), loaded 70-100%, on the shortest sea route. -> voyages with tracks and
    noon reports."""
    out = []
    for vi, v in enumerate(vessels):
        rng = np.random.default_rng([seed, 81, vi])
        t = end_h - 24 * days + rng.uniform(0, 72)
        side = "W" if rng.random() < 0.5 else "E"
        port = str(rng.choice(WEST if side == "W" else EAST))
        k = 0
        while True:
            dest = str(rng.choice(EAST if side == "W" else WEST))
            path = Path(*passage(port, dest))
            base = rng.uniform(12.5, 19.5)
            legs, s = [], 0.0
            while s < path.length:
                s += 24 * base
                legs.append((min(s, path.length), float(np.clip(base + rng.normal(0, 0.9), 10.5, v["design_speed"]))))
            disp = float(rng.uniform(0.7, 1.0))
            run = sail(v, path, legs, Weather(seed), t, disp, ds=20.0)
            if run["t"] > end_h:
                break
            ref = f"H{seed % 1000:03d}-{v['ref']}-{k:03d}"
            out.append({"ref": ref, "vessel": v["ref"], "orig": port, "dest": dest, "dep_h": t, "arr_h": run["t"], "disp": disp,
                        "fuel_t": run["fuel_t"], "distance_nm": path.length, "track": run["track"],
                        "noon": noon_reports(v, run["track"], ref, seed)})
            k += 1
            t = run["t"] + rng.uniform(30, 70)                       # port stay
            port, side = dest, PORTS[dest][1]
    return out


def ais(track, seed, ref, every=1):
    """AIS-like position reports: the hourly truth with about 50 m of noise and the reported speed over ground."""
    rng = np.random.default_rng([seed, 91, key(ref)])
    return [{"t": h["t"], "lat": round(h["lat"] + rng.normal(0, 0.0005), 4), "lon": round(h["lon"] + rng.normal(0, 0.0007), 4),
             "sog": round(h["sog"] + rng.normal(0, 0.1), 1), "course": round(h["course"])} for h in track[::every]]
