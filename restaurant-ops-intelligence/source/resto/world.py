"""A synthetic fast-casual chain: 50 stores, a 12-item menu built from 15 purchased ingredients and 6 prepped components,
and the kitchen and supply chain that turn demand into sales, waste and stockouts, day by day in 15-minute slots.

Demand is item by item, store by store, slot by slot, in two channels (dine-in, delivery): a store's volume and format
(downtown stores live on weekday lunches, suburban ones on dinners and weekends), the hour shape, the store's item mix,
rain (it cuts dine-in and lifts delivery), local events, promotions with an elasticity per item, a shared shock per store
and day, and count noise on top. The kitchen preps components before each window and throws away what is left when the
hold time runs out; an item whose component or ingredient has run out is unavailable (86'd) for the rest of the window,
and that demand is lost and never appears in the sales. Ingredients arrive as lots from three suppliers with lead times and
delivery days; a lot can spoil before its printed date, more likely when it is old and the walk-in is warm; what reaches
its date is thrown away. Some stores lose stock nobody records (theft) or portion more than the recipe says.

The service sees what a real one would: sales by 15-minute slot and when an item was 86'd, deliveries, the closing count
and the walk-in's lot check, waste logged by the staff, cooler temperatures, the weather service's forecast, the events and
promotions calendar, and supplier notices. The demand that was lost, the hazard, the theft and the portioning are the
generator's truth; tests and the evaluation read them, the service never does.

Every random draw is keyed by (seed, day, purpose), so the same days can be re-run under another prep and ordering policy
with the same customers, the same spoilage draws and the same weather: that is what makes the policy comparison paired.
"""
import copy

import numpy as np

SLOTS = 48                                   # 15-minute slots, 10:00-22:00
OPEN_HOUR = 10
LUNCH_RUSH = range(4, 16)                    # 11:00-14:00
WINDOW_SLOTS = (range(20), range(20, 48))  # hot-held components: made at 10:00 for lunch and at 15:00 for dinner
CHANNELS = ("dine_in", "delivery")
REGIONS = ("Harbor", "Uptown", "Riverside", "Midtown", "Lakeside")
REGION_XY = {"Harbor": (0.18, 0.62), "Uptown": (0.45, 0.22), "Riverside": (0.8, 0.35), "Midtown": (0.47, 0.6), "Lakeside": (0.78, 0.8)}
FORMATS = ("downtown", "suburban", "campus")
REGION_FORMATS = {"Harbor": (.6, .3, .1), "Uptown": (.7, .2, .1), "Riverside": (.2, .6, .2), "Midtown": (.4, .3, .3), "Lakeside": (.1, .8, .1)}
DOW_PROFILE = {"downtown": (1.18, 1.2, 1.2, 1.18, 1.1, .62, .52), "suburban": (.86, .88, .9, .95, 1.15, 1.3, 1.2),
               "campus": (1.05, 1.08, 1.08, 1.05, .98, .85, .82)}
STORES_PER_REGION = 10

# name: (unit, $ per unit, shelf life in days, supplier, case size, storage)
INGREDIENTS = {
    "chicken": ("kg", 9.5, 5, "protein", 5.0, "cold"),
    "beef": ("kg", 11.0, 4, "protein", 5.0, "cold"),
    "salmon": ("kg", 26.0, 3, "protein", 2.0, "cold"),
    "rice": ("kg", 2.4, 365, "broadline", 10.0, "dry"),
    "beans": ("kg", 3.0, 365, "broadline", 5.0, "dry"),
    "tortilla": ("ea", 0.22, 14, "broadline", 50.0, "dry"),
    "bun": ("ea", 0.45, 6, "broadline", 24.0, "ambient"),
    "cheese": ("kg", 10.5, 21, "broadline", 2.5, "cold"),
    "fries": ("kg", 3.2, 180, "broadline", 10.0, "frozen"),
    "chips": ("kg", 5.0, 60, "broadline", 2.0, "dry"),
    "lettuce": ("kg", 4.2, 5, "produce", 2.0, "cold"),
    "tomato": ("kg", 4.6, 6, "produce", 5.0, "cold"),
    "avocado": ("ea", 1.25, 4, "produce", 24.0, "cold"),
    "cilantro": ("kg", 12.0, 4, "produce", 0.5, "cold"),
    "lime": ("ea", 0.2, 14, "produce", 50.0, "cold"),
}
ING = list(INGREDIENTS)
N_ING = len(ING)
COST = np.array([INGREDIENTS[i][1] for i in ING])
SHELF = np.array([INGREDIENTS[i][2] for i in ING])
CASE = np.array([INGREDIENTS[i][4] for i in ING])
AGES = 30                                     # lot ages tracked; longer-lived stock sits in the last bucket and never expires here
PERISHABLE = np.array([INGREDIENTS[i][5] in ("cold", "ambient") and INGREDIENTS[i][2] < AGES for i in ING])
# supplier: (lead days, delivery weekdays, price factor)
SUPPLIERS = {"produce": (1, (0, 1, 2, 3, 4, 5), 1.0), "protein": (2, (0, 2, 4), 1.0), "broadline": (2, (1, 4), 1.0),
             "backup": (1, (0, 1, 2, 3, 4, 5, 6), 1.35)}                  # cash-and-carry: any day, at a premium
REGULAR = ("produce", "protein", "broadline")
SUPPLIER_OF = np.array([REGULAR.index(INGREDIENTS[i][3]) for i in ING])

# prepped in the kitchen: (unit, hold: 'window' (discarded at 15:00 / close) or 'day' (discarded at close), raw per unit at spec, labor min per unit)
COMPONENTS = {
    "grilled_chicken": ("kg", "window", {"chicken": 1 / 0.75}, 5.0),
    "seasoned_beef": ("kg", "window", {"beef": 1 / 0.8}, 4.0),
    "cooked_rice": ("kg", "window", {"rice": 0.4}, 2.0),
    "guacamole": ("kg", "day", {"avocado": 7.0, "lime": 2.0, "cilantro": 0.02}, 8.0),
    "pico": ("kg", "day", {"tomato": 0.85, "cilantro": 0.05, "lime": 2.0}, 6.0),
    "chopped_lettuce": ("kg", "day", {"lettuce": 1 / 0.85}, 4.0),
}
COMP = list(COMPONENTS)
N_COMP = len(COMP)
WINDOW_COMP = np.array([COMPONENTS[c][1] == "window" for c in COMP])
RAW_PER_COMP = np.zeros((N_COMP, N_ING))
for _c, (_u, _h, _raw, _l) in COMPONENTS.items():
    for _i, _q in _raw.items():
        RAW_PER_COMP[COMP.index(_c), ING.index(_i)] = _q
TRUE_RAW_PER_COMP = RAW_PER_COMP.copy()
TRUE_RAW_PER_COMP[COMP.index("guacamole"), ING.index("avocado")] = 7.0 * 0.70 / 0.65   # the avocados yield less flesh than the spec assumes
COMP_COST = RAW_PER_COMP @ COST
LABOR_MIN = np.array([COMPONENTS[c][3] for c in COMP])

# name: (price, delivery affinity, chain mix share, recipe {component or ingredient: qty per item})
ITEMS = {
    "chicken_bowl": (11.5, 1.2, .16, {"grilled_chicken": .12, "cooked_rice": .20, "beans": .08, "pico": .05, "chopped_lettuce": .03, "cheese": .03}),
    "beef_burrito": (11.0, 1.3, .12, {"seasoned_beef": .12, "cooked_rice": .12, "beans": .06, "cheese": .04, "pico": .04, "tortilla": 1}),
    "salmon_bowl": (15.5, 1.0, .05, {"salmon": .145, "cooked_rice": .20, "guacamole": .05, "chopped_lettuce": .03}),
    "chicken_tacos": (10.0, .8, .09, {"grilled_chicken": .10, "tortilla": 3, "pico": .06, "guacamole": .03}),
    "beef_tacos": (10.5, .8, .07, {"seasoned_beef": .10, "tortilla": 3, "pico": .06, "cheese": .03}),
    "garden_salad": (9.0, 1.1, .05, {"chopped_lettuce": .15, "pico": .08, "guacamole": .05, "cheese": .02}),
    "chicken_salad": (11.0, 1.1, .06, {"chopped_lettuce": .12, "grilled_chicken": .10, "pico": .05, "cheese": .02}),
    "chips_guac": (5.5, .9, .08, {"chips": .09, "guacamole": .10}),
    "burger": (12.0, .9, .08, {"bun": 1, "beef": .19, "cheese": .02, "chopped_lettuce": .02, "tomato": .03}),
    "chicken_sandwich": (11.0, .9, .07, {"bun": 1, "chicken": .2, "chopped_lettuce": .02, "tomato": .02}),
    "fries": (4.0, .7, .10, {"fries": .18}),
    "quesadilla": (9.5, 1.2, .07, {"tortilla": 1, "cheese": .08, "grilled_chicken": .05}),
}
ITEM = list(ITEMS)
N_ITEM = len(ITEM)
PRICE = np.array([ITEMS[i][0] for i in ITEM])
AFFINITY = np.array([ITEMS[i][1] for i in ITEM])
MIX0 = np.array([ITEMS[i][2] for i in ITEM])
ITEM_COMP = np.zeros((N_ITEM, N_COMP))
ITEM_RAW = np.zeros((N_ITEM, N_ING))
for _n, (_p, _a, _m, _rec) in ITEMS.items():
    for _k, _q in _rec.items():
        if _k in COMPONENTS:
            ITEM_COMP[ITEM.index(_n), COMP.index(_k)] = _q
        else:
            ITEM_RAW[ITEM.index(_n), ING.index(_k)] = _q
ITEM_THEORETICAL_RAW = ITEM_RAW + ITEM_COMP @ RAW_PER_COMP          # recipe raw per item, at spec yields
ITEM_FOOD_COST = ITEM_THEORETICAL_RAW @ COST
PORTIONED = ["grilled_chicken", "seasoned_beef", "guacamole", "cheese", "salmon", "beef", "chicken"]   # what a heavy hand over-portions

RAIN_EFFECT = (-0.5, 0.6)                     # per unit rain intensity: dine-in falls, delivery rises
EVENT_LIFT, EVENT_SLOTS = 1.6, range(28, 44)   # a local event near the store, 17:00-21:00
DAY_SD, SLOT_SHAPE_K = 0.08, 12.0             # store-day shock (lognormal sd) and slot-level gamma-Poisson shape
COUNT_SD = 0.015                              # closing count error, fraction of on-hand
NATURAL_LOSS = 1.01                           # spillage and tasting everywhere: 1% over recipe
HAZARD_TEMP = 0.6                             # per °C above 3.5 on the logit of spoiling today
COLD = np.array([INGREDIENTS[i][5] == "cold" for i in ING])
HAZARD_BASE = np.array([-7.5 if i in ("cheese", "lime") else -6.5 for i in ING])


def hazard(ing_idx, age, temp):
    """Probability that a lot of this ingredient, `age` days after receipt, spoils today with the walk-in at `temp` °C."""
    ing_idx, age, temp = np.asarray(ing_idx), np.asarray(age, float), np.asarray(temp, float)
    z = HAZARD_BASE[ing_idx] + 5.5 * age / SHELF[ing_idx] + np.where(COLD[ing_idx], HAZARD_TEMP * (temp - 3.5), 0.0)
    return np.where(PERISHABLE[ing_idx], 1 / (1 + np.exp(-z)), 0.0)


def _shape(fmt, weekend, channel, shift, tilt):
    t = OPEN_HOUR + (np.arange(SLOTS) + 0.5) / 4
    w = {("downtown", 0): (.62, .28, .10), ("downtown", 1): (.40, .45, .15), ("suburban", 0): (.38, .50, .12),
         ("suburban", 1): (.40, .48, .12), ("campus", 0): (.45, .40, .15), ("campus", 1): (.45, .40, .15)}[(fmt, weekend)]
    lw, dw, bw = w[0] * tilt, w[1] / tilt, w[2]
    lc, ls, dc, ds = 12.25 + 0.5 * weekend + shift, 0.75 + 0.25 * weekend, 18.5, 1.0
    if channel == 1:
        lw, dw, dc = lw - 0.1, dw + 0.1, 19.0
    g = lambda c, s: np.exp(-0.5 * ((t - c) / s) ** 2) / s       # noqa: E731
    y = lw * g(lc, ls) / g(lc, ls).sum() + dw * g(dc, ds) / g(dc, ds).sum() + bw / SLOTS
    return y / y.sum()


def chain(seed, horizon=84):
    """The chain's fixed facts and calendar for `horizon` days: stores, demand parameters, weather, events, promotions,
    cooler excursions, supplier hiccups in the history, and the stores with shrinkage. Pure data, deterministic in seed."""
    rng = np.random.default_rng([seed, 1])
    L = len(REGIONS) * STORES_PER_REGION
    region = np.repeat(np.arange(len(REGIONS)), STORES_PER_REGION)
    fmt = np.array([rng.choice(len(FORMATS), p=REGION_FORMATS[REGIONS[r]]) for r in region])
    xy = np.array([np.array(REGION_XY[REGIONS[r]]) + rng.normal(0, 0.06, 2) for r in region]).clip(0.04, 0.96)
    base = rng.lognormal(np.log(820), 0.3, L)
    dshare = rng.uniform(0.15, 0.4, L)
    dow = np.array([np.array(DOW_PROFILE[FORMATS[f]]) * rng.lognormal(0, 0.04, 7) for f in fmt])
    shift, tilt = rng.normal(0, 0.15, L), rng.lognormal(0, 0.1, L)
    shapes = np.array([[[_shape(FORMATS[fmt[l]], wk, c, shift[l], tilt[l]) for wk in (0, 1)] for c in (0, 1)] for l in range(L)])  # [L, C, 2, S]
    mix = MIX0 * rng.lognormal(0, 0.2, (L, N_ITEM))
    mix = np.stack([mix / mix.sum(1, keepdims=True), mix * AFFINITY / (mix * AFFINITY).sum(1, keepdims=True)], 1)   # [L, C, I]
    share = np.stack([1 - dshare, dshare], 1)                                                                     # [L, C]
    wk = np.array([0, 0, 0, 0, 0, 1, 1])
    lam0 = (base[:, None, None, None, None] * share[:, None, :, None, None] * mix.transpose(0, 2, 1)[:, :, :, None, None]
            * dow[:, None, None, :, None] * shapes[:, None, :, wk, :])                                               # [L, I, C, 7, S]
    # weather by region: a rain spell with a start, a length and an intensity; the forecast is the truth with error
    rain = np.zeros((len(REGIONS), horizon, SLOTS))
    for r in range(len(REGIONS)):
        for d in range(horizon):
            if rng.random() < 0.18:
                st, ln, inten = rng.uniform(10, 20), rng.uniform(1.5, 6), rng.uniform(0.3, 1.0)
                t = OPEN_HOUR + np.arange(SLOTS) / 4
                rain[r, d, (t >= st) & (t < st + ln)] = inten
    fc_err = rng.lognormal(0, 0.25, (len(REGIONS), horizon))
    events = np.zeros((L, horizon), bool)
    events[rng.random((L, horizon)) < 0.035] = True
    elasticity = rng.uniform(1.0, 3.2, N_ITEM)
    promos, used = [], set()
    for k in range(8):                                      # the history's promotions, different items
        item = int(rng.choice([i for i in range(N_ITEM) if i not in used]))
        used.add(item)
        start = int(rng.integers(2, 50))
        promos.append({"id": f"P{k + 1:02d}", "item": ITEM[item], "discount": float(rng.choice([0.1, 0.15, 0.2, 0.25, 0.3])), "start": start,
                       "end": start + int(rng.integers(4, 8)), "regions": sorted(str(x) for x in rng.choice(REGIONS, int(rng.integers(2, 4)), replace=False))})
    promos.append({"id": "P09", "item": "chicken_tacos", "discount": 0.2, "start": 56, "end": 63, "regions": ["Midtown", "Lakeside"]})   # taco week, on the calendar
    cooler = 3.2 + rng.normal(0, 0.35, L)[:, None] + rng.normal(0, 0.25, (L, horizon))
    excursions = []
    for l in range(L):
        for d in range(2, 50):                               # every history excursion is over before the last week
            if rng.random() < 0.012:
                ln, add = int(rng.integers(2, 5)), rng.uniform(3, 5)
                cooler[l, d:d + ln] += add
                excursions.append({"store": l, "start": d, "days": ln, "add": round(float(add), 2)})
    delays = [{"supplier": str(rng.choice(["produce", "protein"])), "due": int(d), "days": 1,
               "regions": sorted(str(x) for x in rng.choice(REGIONS, 2, replace=False))} for d in rng.choice(np.arange(10, 46), 2, replace=False)]
    shrink = rng.choice(L, 4, replace=False)
    portion = np.ones((L, N_COMP + N_ING))                  # keys: components then ingredients
    theft = np.zeros((L, N_ING))
    truth_shrink = []
    for k, l in enumerate(shrink):
        if k < 2:
            ings = [str(x) for x in rng.choice(["chicken", "beef", "salmon", "cheese"], int(rng.integers(1, 3)), replace=False)]
            rate = float(rng.uniform(0.06, 0.12))
            for i in ings:
                theft[l, ING.index(i)] = rate
            truth_shrink.append({"store": int(l), "kind": "theft", "ingredients": ings, "rate": round(rate, 3)})
        else:
            f = float(rng.uniform(1.08, 1.16))
            for key in PORTIONED:
                portion[l, COMP.index(key) if key in COMPONENTS else N_COMP + ING.index(key)] = f
            truth_shrink.append({"store": int(l), "kind": "over-portioning", "factor": round(f, 3)})
    names = [f"{REGIONS[r]} {k + 1}" for r in range(len(REGIONS)) for k in range(STORES_PER_REGION)]
    return {"seed": seed, "L": L, "horizon": horizon, "region": region, "format": fmt, "xy": xy, "names": names, "lam0": lam0,
            "rain": rain, "fc_err": fc_err, "events": events, "elasticity": elasticity, "promos": promos, "cooler": cooler,
            "excursions": excursions, "delays": delays, "portion": portion, "theft": theft, "shrinkage": truth_shrink,
            "base": base, "dshare": dshare}


def store_ids(L):
    return [f"S{l + 1:02d}" for l in range(L)]


# --- what the calendar says for a day ---------------------------------------------------------------------------------
def rain_obs(ch, d):
    return ch["rain"][ch["region"], d]                                       # [L, S]


def rain_forecast(ch, d):
    """The weather service's forecast for day d (issued the day before): the truth's spell, intensity with error."""
    return np.clip(ch["rain"][:, d] * ch["fc_err"][:, d, None], 0, 1)[ch["region"]]


def event_mask(ch, d):
    out = np.zeros((ch["L"], SLOTS), bool)
    out[:, EVENT_SLOTS] = ch["events"][:, d, None]
    return out


def discounts(ch, d):
    """[L, I]: the promotion discount on each item at each store on day d."""
    out = np.zeros((ch["L"], N_ITEM))
    for p in ch["promos"]:
        if p["start"] <= d < p["end"]:
            out[np.isin(np.array(REGIONS)[ch["region"]], p["regions"]), ITEM.index(p["item"])] = p["discount"]
    return out


def demand_mean(ch, d, rain=None):
    """True expected demand [L, I, C, S] on day d (before the store-day shock and the slot noise)."""
    lam = ch["lam0"][:, :, :, d % 7, :].copy()
    r = rain_obs(ch, d) if rain is None else rain
    lam[:, :, 0, :] *= (1 + RAIN_EFFECT[0] * r)[:, None, :]
    lam[:, :, 1, :] *= (1 + RAIN_EFFECT[1] * r)[:, None, :]
    lam *= np.where(event_mask(ch, d), EVENT_LIFT, 1.0)[:, None, None, :]
    lam *= ((1 - discounts(ch, d)) ** (-ch["elasticity"]))[:, :, None, None]
    return lam


def apply_told(ch, told):
    """A copy of the chain with what the generator was told (a rainstorm) written into its weather."""
    ch = dict(ch, rain=ch["rain"].copy(), fc_err=ch["fc_err"].copy())
    for t in told:
        if t["kind"] == "rainstorm":
            for r in t["regions"]:
                ri = REGIONS.index(r)
                tt = OPEN_HOUR + np.arange(SLOTS) / 4
                ch["rain"][ri, t["day"], (tt >= t["from_hour"]) & (tt < t["to_hour"])] = t["intensity"]
                ch["fc_err"][ri, t["day"]] = t.get("forecast_factor", 1.0)
    return ch


def delays_of(ch, told):
    return list(ch["delays"]) + [{"supplier": t["supplier"], "due": t["due"], "days": t["days"], "regions": t["regions"]} for t in told if t["kind"] == "supplier_delay"]


# --- the kitchen and the walk-in ----------------------------------------------------------------------------------------
def expected_use(ch, d):
    """Noise-free usage on day d from the truth's mean demand: (components by window [L, COMP, 2], raw [L, ING]).
    Only used to give a new chain its first two weeks of 'last week' and its opening stock."""
    lam = ch["lam0"][:, :, :, d % 7, :].sum(2)                                # [L, I, S]
    comp = np.stack([np.einsum("lis,ic->lc", lam[:, :, w], ITEM_COMP) for w in WINDOW_SLOTS], 2)
    raw = np.einsum("lis,ir->lr", lam, ITEM_THEORETICAL_RAW)
    return comp, raw


def initial_state(ch):
    L = ch["L"]
    raw = np.zeros((L, N_ING, AGES))
    use, comp_use, comp_out, ing_out = {}, {}, {}, {}
    for d in range(-14, 0):
        comp_use[d], use[d] = expected_use(ch, d)
        comp_out[d], ing_out[d] = np.zeros((L, N_COMP, 2), bool), np.zeros((L, N_ING), bool)
    _, u = expected_use(ch, 0)
    raw[:, :, 1] = 0.8 * u                                                      # as of the close of day -1
    raw[:, :, 0] = 0.8 * u
    pipeline = []
    for s, (lead, days, _) in SUPPLIERS.items():
        if s == "backup":
            continue
        for due in (0, 1):
            if due % 7 in days:
                q = np.zeros((L, N_ING))
                m = SUPPLIER_OF == REGULAR.index(s)
                q[:, m] = 1.2 * expected_use(ch, due)[1][:, m] * 2
                pipeline.append({"id": f"init-{s}-{due}", "supplier": s, "due": due, "ordered_on": -1, "qty": np.round(q / CASE) * CASE, "delayed": 0})
    return {"day": 0, "raw": raw, "pipeline": pipeline, "use": use, "comp_use": comp_use, "comp_out": comp_out, "ing_out": ing_out,
            "count": raw.sum(2), "lots_est": raw.copy(), "temp": ch["cooler"][:, 0]}


class Obs:
    """What a planner can see at a moment: the last closing count and lot check, orders in the pipeline with the
    suppliers' notices applied, cooler temperatures, usage history, and the calendar (weather forecast, events, promos)."""

    def __init__(self, ch, st, d, notified_delays, lunch_sales=None):
        self.ch, self.day, self.L, self.delays = ch, d, ch["L"], notified_delays
        self.count, self.lots, self.temp = st["count"], st["lots_est"], st["temp"]
        self.use, self.comp_use, self.lunch_sales = st["use"], st["comp_use"], lunch_sales
        self.comp_out, self.ing_out = st["comp_out"], st["ing_out"]
        self.pipeline = [dict(p, due=p["due"] + expected_delay(ch, p, notified_delays)) if not p["delayed"] else p for p in st["pipeline"]]

    def conditions(self, day):
        """(rain forecast [L, S], event [L, S], discount [L, I]) for a future day; no forecast beyond two days ahead."""
        rain = rain_forecast(self.ch, day) if day - self.day <= 2 else np.zeros((self.L, SLOTS))
        return rain, event_mask(self.ch, day), discounts(self.ch, day)


def expected_delay(ch, p, delays):
    out = np.zeros(ch["L"], int)
    for dl in delays:
        if dl["supplier"] == p["supplier"] and dl["due"] == p["due"]:
            out[np.isin(np.array(REGIONS)[ch["region"]], dl["regions"])] = dl["days"]
    return out if out.any() else 0


def order_due_days(d, supplier):
    """Deliveries an order placed at the close of day d can make for `supplier`: (arrival day, the next arrival after it)."""
    lead, days, _ = SUPPLIERS[supplier]
    a = d + lead
    if a % 7 not in days:
        return None
    nxt = a + 1
    while nxt % 7 not in days:
        nxt += 1
    return a, nxt


def round_cases(q):
    """Whole cases, rounding up unless the last case would be less than a fifth used."""
    return np.maximum(0, np.ceil(q / CASE - 0.2) * CASE)


class UsualPractice:
    """How the chain ran before the system: par prep from the same window over the last two same weekdays plus 15%, and
    orders that bring stock up to last two weeks' usage over the delivery's cover plus 15%, net of the count and what is due."""
    name = "usual practice"
    BUFFER = 1.15

    BUMP = 1.1                                                                  # a window that ran out gets 10% more next time

    def typical(self, hist, ran_out, t):
        """The same weekday over the last two weeks: their mean, or, if either ran out, the larger, with 10% more."""
        a, b = hist[t - 7], hist[t - 14]
        out = ran_out[t - 7] | ran_out[t - 14]
        return np.where(out, self.BUMP * np.maximum(a, b), (a + b) / 2)

    def prep(self, ch, d, window, obs):
        last = self.typical(obs.comp_use, obs.comp_out, d)                                  # [L, COMP, 2]
        if window == 0:
            return self.BUFFER * np.where(WINDOW_COMP, last[:, :, 0], last.sum(2))
        return self.BUFFER * np.where(WINDOW_COMP, last[:, :, 1], 0.0)

    def order(self, ch, d, obs):
        u = lambda t: self.typical(obs.use, obs.ing_out, t)                             # noqa: E731
        out = []
        for s in REGULAR:
            dd = order_due_days(d, s)
            if not dd:
                continue
            a, nxt = dd
            m = SUPPLIER_OF == REGULAR.index(s)
            need = self.BUFFER * sum(u(t) for t in range(a, nxt))
            until = sum((u(t) for t in range(d + 1, a)), np.zeros((ch["L"], N_ING)))
            dated = obs.lots * (np.arange(AGES) + (a - d) < SHELF[:, None])[None]      # the day-dot labels: what is still in date on arrival
            proj = dated.sum(2) - until + pipeline_between(obs, d + 1, a - 1)
            inc = pipeline_between(obs, a, nxt - 1)
            q = np.where(m, round_cases(need - np.maximum(proj, 0) - inc), 0)
            out.append({"supplier": s, "due": a, "qty": q})
        return out


def pipeline_between(obs, lo, hi):
    tot = np.zeros((obs.L, N_ING))
    for p in obs.pipeline:
        due = p["due"]
        if np.ndim(due):
            tot += p["qty"] * ((due >= lo) & (due <= hi))[:, None]
        elif lo <= due <= hi:
            tot += p["qty"]
    return tot


def age(lots):
    out = np.zeros_like(lots)
    out[:, :, 1:] = lots[:, :, :-1]
    out[:, :, -1] += lots[:, :, -1]
    return out


def _make(qty, c, tot):
    """Prep `qty` of component c at each store from the raw on hand (less if the raw runs short); takes the raw from `tot`."""
    need = qty[:, None] * TRUE_RAW_PER_COMP[c]
    m = TRUE_RAW_PER_COMP[c] > 0
    frac = np.min(np.where(m, tot / np.maximum(need, 1e-9), np.inf), 1).clip(0, 1) if qty.any() else np.zeros(len(qty))
    made = qty * frac
    tot -= made[:, None] * TRUE_RAW_PER_COMP[c]
    return made


def _draw_demand(ch, d):
    lam = demand_mean(ch, d)
    r = np.random.default_rng([ch["seed"], d, 11])
    shock = r.lognormal(-DAY_SD ** 2 / 2, DAY_SD, ch["L"])[:, None, None, None]
    g = r.gamma(SLOT_SHAPE_K, 1 / SLOT_SHAPE_K, lam.shape)
    return r.poisson(lam * shock * g)


def step(ch, st, d, policy, told=(), pending=(), place_orders=True):
    """Run one day. `pending` are orders placed before the day starts (the planner's, outside the loop); with
    place_orders=False the day ends before the evening's orders (they are left to the planner).
    Returns (new state, the day's records). The state is copied, never modified in place."""
    st = copy.deepcopy(st)
    L, seed = ch["L"], ch["seed"]
    delays = delays_of(ch, told)
    for p in pending:
        st["pipeline"].append(dict(p, delayed=0))
    # deliveries: a supplier's late truck moves its delivery; what is due today arrives as a lot of age 0
    received = np.zeros((L, N_ING))
    by_supplier = {}
    keep = []
    for p in st["pipeline"]:
        if p["due"] == d and not p["delayed"]:
            late = expected_delay(ch, p, delays)
            if np.ndim(late) and late.any():
                p_late = dict(p, qty=p["qty"] * (late > 0)[:, None], due=d + int(late.max()), delayed=int(late.max()))
                keep.append(p_late)
                p = dict(p, qty=p["qty"] * (late == 0)[:, None])
        if p["due"] == d:
            received += p["qty"]
            by_supplier.setdefault(p["supplier"], np.zeros((L, N_ING)))
            by_supplier[p["supplier"]] += p["qty"]
        else:
            keep.append(p)
    st["pipeline"] = keep
    raw = age(st["raw"])                                                      # last night's lots are a day older
    raw[:, :, 0] += received
    tot = raw.sum(2)
    temp = ch["cooler"][:, d]
    D = _draw_demand(ch, d)                                                   # [L, I, C, S]
    disc = discounts(ch, d)
    r5 = np.random.default_rng([seed, d, 5])
    portion = ch["portion"] * NATURAL_LOSS * r5.lognormal(0, 0.03, (L, N_COMP + N_ING))
    per_comp = ITEM_COMP[None] * portion[:, None, :N_COMP]                   # [L, I, COMP] actual comp per unit sold
    per_raw = ITEM_RAW[None] * portion[:, None, N_COMP:]
    sold = np.zeros_like(D)
    unavail = np.zeros((L, N_ITEM, SLOTS), bool)
    prepped = np.zeros((L, N_COMP, 2))
    discard = np.zeros((L, N_COMP, 2))
    comp_out = np.zeros((L, N_COMP, 2), bool)
    plans = np.zeros((L, N_COMP, 2))
    comp = np.zeros((L, N_COMP))
    lunch_sales = None
    batch = np.zeros((L, N_COMP))                                             # a top-up batch: a quarter of the window's plan
    ready_at = np.full((L, N_COMP), -1)
    topups = np.zeros((L, N_COMP, 2), int)
    max_portion = (ITEM_COMP * 1.2).max(0)
    for w, slots in enumerate(WINDOW_SLOTS):
        obs = Obs(ch, st, d, delays_known(ch, told, d), lunch_sales)
        plan = np.maximum(policy.prep(ch, d, w, obs), 0)
        plans[:, :, w] = plan
        for c in range(N_COMP):
            made = _make(plan[:, c], c, tot)
            comp[:, c] += made
            prepped[:, c, w] = made
            batch[:, c] = np.where(plan[:, c] > 0, np.maximum(0.25 * plan[:, c], 8 * max_portion[c]), batch[:, c])
        ready_at[:] = -1
        for s in slots:
            due = ready_at == s                                               # a top-up batch comes off the grill
            if due.any():
                for c in np.nonzero(due.any(0))[0]:
                    made = _make(np.where(due[:, c], batch[:, c], 0), c, tot)
                    comp[:, c] += made
                    prepped[:, c, w] += made
            low = (comp < max_portion) & (ready_at < s) & (batch > 0) & (s + 2 < slots.stop)
            ready_at[low] = s + 2                                             # ran low: cook more, ready in 30 minutes
            topups[:, :, w] += low
            for i in range(N_ITEM):
                dem = D[:, i, 0, s] + D[:, i, 1, s]
                if not dem.any():
                    continue
                pc, pr = per_comp[:, i], per_raw[:, i]
                can = np.minimum(np.min(np.where(pc > 0, comp / np.maximum(pc, 1e-12), np.inf), 1),
                                 np.min(np.where(pr > 0, tot / np.maximum(pr, 1e-12), np.inf), 1))
                n = np.minimum(dem, np.floor(can + 1e-9)).astype(int)
                unavail[:, i, s] = n < dem
                d0 = np.minimum(D[:, i, 0, s], np.floor(n * D[:, i, 0, s] / np.maximum(dem, 1) + 0.5).astype(int))
                sold[:, i, 0, s], sold[:, i, 1, s] = d0, n - d0
                comp -= n[:, None] * pc
                tot -= n[:, None] * pr
            comp = np.maximum(comp, 0)
        ends = WINDOW_COMP if w == 0 else np.ones(N_COMP, bool)              # hot-held at 15:00, everything at close
        discard[:, :, w] = np.where(ends, comp, 0)
        # the kitchen ran out of it in this window (a top-up, or next to nothing left when it was thrown away); a day
        # component is judged at close, over the whole day
        made = prepped[:, :, w] if w == 0 else np.where(WINDOW_COMP, prepped[:, :, 1], prepped.sum(2))
        tops = topups[:, :, w] if w == 0 else np.where(WINDOW_COMP, topups[:, :, 1], topups.sum(2))
        comp_out[:, :, w] = ends & (made > 0) & ((discard[:, :, w] < max_portion) | (tops > 0))
        comp = np.where(ends, 0, comp)
        if w == 0:
            lunch_sales = sold[:, :, :, :20].copy()
    tot = np.maximum(tot, 0)
    # theft: stock that leaves without a record, in lumps on about a third of days
    r4 = np.random.default_rng([seed, d, 4])
    hit = r4.random((L, N_ING)) < 0.35
    exp_use = np.einsum("lics,ir->lr", demand_mean(ch, d), ITEM_THEORETICAL_RAW)
    stolen = np.minimum(tot, np.where(hit, ch["theft"] * exp_use / 0.35, 0))
    tot -= stolen
    # FIFO: today's use comes out of the oldest lots
    used = np.maximum(raw.sum(2) - tot, 0)
    rem = used.copy()
    closures = []
    for a in range(AGES - 1, -1, -1):
        take = np.minimum(raw[:, :, a], rem)
        emptied = (take > 0) & (take >= raw[:, :, a] - 1e-9)
        for l, i in zip(*np.nonzero(emptied)):
            closures.append((int(l), int(i), d - a, "used", 0.0))
        raw[:, :, a] -= take
        rem -= take
    raw[raw < 1e-9] = 0
    # the walk-in at close: a lot spoils with a hazard rising with age and temperature; a lot at its date is thrown away
    u = np.random.default_rng([seed, d, 2]).random((L, N_ING, AGES))
    ages = np.arange(AGES)
    h = hazard(np.arange(N_ING)[None, :, None], ages[None, None, :], temp[:, None, None]) * (ages < SHELF[:, None])[None]
    spoil = (raw > 0) & (u < h)
    expire = (raw > 0) & ~spoil & (ages[None, None, :] >= SHELF[None, :, None] - 1) & PERISHABLE[None, :, None]
    lot_waste = np.zeros((L, N_ING, 2))
    for kind, mask in ((0, spoil), (1, expire)):
        for l, i, a in zip(*np.nonzero(mask)):
            closures.append((int(l), int(i), d - int(a), ("spoiled", "expired")[kind], float(raw[l, i, a])))
        lot_waste[:, :, kind] = (raw * mask).sum(2)
        raw[mask] = 0
    tot = raw.sum(2)
    r3 = np.random.default_rng([seed, d, 3])
    noise = 1 + r3.normal(0, COUNT_SD, (L, N_ING))
    count = np.round(tot * noise, 3)
    # what the service learns from today: usage from the counts (yesterday's count + received - today's count - logged
    # lot waste), and component demand from the sales at recipe
    st["use"][d] = st["count"] + received - count - lot_waste.sum(2)
    ing_out = count < 0.03 * np.maximum(st["count"] + received, 1e-9)        # the walk-in ran (nearly) dry of it
    st["count"], st["lots_est"], st["temp"] = count, raw * noise[:, :, None], temp
    sales_units = sold.sum(2)                                                 # [L, I, S]
    st["comp_out"][d], st["ing_out"][d] = comp_out, ing_out
    st["comp_use"][d] = np.stack([np.einsum("lis,ic->lc", sales_units[:, :, sl], ITEM_COMP) for sl in WINDOW_SLOTS], 2)
    # orders at close
    obs = Obs(ch, st, d, delays_known(ch, told, d))
    orders = policy.order(ch, d, obs) if place_orders else []
    for k, o in enumerate(orders):
        st["pipeline"].append({"id": f"{d}-{o['supplier']}-{k}", "supplier": o["supplier"], "due": o["due"], "ordered_on": d, "qty": o["qty"], "delayed": 0})
    st["raw"], st["day"] = raw, d + 1
    revenue = (sold.sum((2, 3)) * PRICE * (1 - disc))
    lost = D.sum(2) - sold.sum(2)
    rec = {"day": d, "sold": sold.astype(np.int16), "unavailable": unavail, "topups": topups, "prep_plan": plans, "comp_out": comp_out, "revenue": revenue, "discount": disc,
           "received": received, "received_by": by_supplier, "prepped": prepped, "prep_discard": discard, "lot_waste": lot_waste,
           "closures": closures, "count": count, "lots": st["lots_est"].copy(), "temp": temp, "rain": rain_obs(ch, d),
           "rain_forecast_next": [rain_forecast(ch, d + k) for k in (1, 2)] if d + 2 < ch["horizon"] else None,
           "orders": orders,
           "truth": {"demand": D.astype(np.int16), "lost": lost, "stolen": stolen,
                     "purchases": sum(q * SUPPLIERS[s][2] for s, q in by_supplier.items()) if by_supplier else np.zeros((L, N_ING))}}
    return st, rec


def delays_known(ch, told, d):
    """The delays suppliers have announced by day d: the history's arrive as notices the day before; the told ones when told."""
    out = [dl for dl in ch["delays"] if dl["due"] - 1 <= d]
    return out + [{"supplier": t["supplier"], "due": t["due"], "days": t["days"], "regions": t["regions"]} for t in told if t["kind"] == "supplier_delay"]


def run(ch, st, day_from, day_to, policy, told=(), pending=(), last_orders=True):
    recs = []
    for d in range(day_from, day_to):
        st, rec = step(ch, st, d, policy, told, pending if d == day_from else (), last_orders or d < day_to - 1)
        recs.append(rec)
    return st, recs


def metrics(recs):
    """Waste, stockouts and spend over some days, from the generator's truth (the demand that was lost is not in the sales)."""
    waste = sum((r["prep_discard"].sum(2) @ COMP_COST).sum() + (r["lot_waste"].sum(2) @ COST).sum() for r in recs)
    purchases = sum((r["truth"]["purchases"] @ COST).sum() for r in recs)
    demand = sum(r["truth"]["demand"].sum() for r in recs)
    lost = sum(r["truth"]["lost"].sum() for r in recs)
    sold_cost = sum((r["sold"].sum((2, 3)) @ ITEM_FOOD_COST).sum() for r in recs)
    revenue = sum(r["revenue"].sum() for r in recs)
    lost_rev = sum((r["truth"]["lost"].sum(2) * PRICE).sum() for r in recs)
    prep_waste = sum((r["prep_discard"].sum(2) @ COMP_COST).sum() for r in recs)
    return {"waste_usd": round(float(waste), 2), "prep_waste_usd": round(float(prep_waste), 2), "lot_waste_usd": round(float(waste - prep_waste), 2),
            "purchases_usd": round(float(purchases), 2), "waste_pct_of_purchases": round(float(waste / max(purchases, 1)), 4),
            "demand_units": int(demand), "lost_units": int(lost), "stockout_rate": round(float(lost / max(demand, 1)), 4),
            "lost_revenue_usd": round(float(lost_rev), 2), "revenue_usd": round(float(revenue), 2), "food_cost_sold_usd": round(float(sold_cost), 2)}
