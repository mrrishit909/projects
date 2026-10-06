"""Models, planners and analysis, all fitted on what the service stores (sales by 15-minute slot with the slots an item was
86'd, the calendar, closing counts, lot checks, logged waste, cooler temperatures), never on the generator's internals.

    DemandModel      15-minute hierarchical demand forecast: store x channel x weekday level, store x channel x day-type
                     hour shape shrunk toward the store format's, store x channel item mix shrunk toward the chain's, rain by
                     channel, local events, and a promotion elasticity per item shrunk toward the pooled one; a store-day
                     shock and slot-level overdispersion give prediction intervals at every level of the hierarchy, which
                     add up exactly (chain = sum of stores = sum of items = sum of slots). Baseline: seasonal naive (the
                     same slot last week) with empirical error quantiles
    consumption      recipes x a learned usage ratio per store and ingredient (and component), from counts and prep logs;
                     baseline: recipes alone, or last week's usage
    HazardModel      discrete-time spoilage hazard of a lot from its age, the walk-in's temperature and the ingredient
                     (logistic regression on lot-days); baseline: the printed shelf life
    shrinkage        actual against theoretical usage per store and ingredient, judged against the chain's normal for
                     that ingredient with its standard error; baseline: a fixed variance threshold
    SystemPolicy     prep to a quantile of each component's window demand (updated at 15:00 from the lunch actually
                     sold) and base-stock orders net of the stock the hazard model expects to survive, with a backup
                     order when a delayed truck would leave a store short; baseline: world.UsualPractice
"""
import hashlib
import json

import numpy as np
from scipy.stats import gamma, nbinom, norm
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from . import world as W

FORECAST_VERSION = "demand-hier-nb-1"
HAZARD_VERSION = "spoilage-hazard-logit-1"
PLANNER_VERSION = "prep-quantile+base-stock-1"
Q_LO, Q_HI = 0.05, 0.95                        # the 90% prediction interval
KAPPA_SHAPE, KAPPA_MIX = 25.0, 40.0           # prior strength, in expected units, toward the format's shape and the chain's mix
TAU_ELASTICITY = 0.6                          # prior sd of an item's elasticity around the pooled one


def feature_hash(*arrays):
    h = hashlib.sha256()
    for a in arrays:
        h.update(np.ascontiguousarray(np.round(np.asarray(a, float), 4)).tobytes())
    return h.hexdigest()[:16]


# --- demand ------------------------------------------------------------------------------------------------------------
def history_arrays(recs, ch_meta):
    """World records (what the POS, the calendar and the weather service delivered) -> the arrays the model is fitted on."""
    days = [r["day"] for r in recs]
    Y = np.stack([r["sold"] for r in recs], 3).astype(np.float32)                    # [L, I, C, D, S]
    avail = ~np.stack([r["unavailable"] for r in recs], 2)                              # [L, I, D, S]
    rain = np.stack([r["rain"] for r in recs], 1)                                       # [L, D, S]
    event = np.stack([W.event_mask(ch_meta, d) for d in days], 1)
    disc = np.stack([r["discount"] for r in recs], 2)                                   # [L, I, D]
    return {"Y": Y, "avail": avail, "rain": rain, "event": event, "disc": disc, "dow": np.array(days) % 7,
            "format": ch_meta["format"], "days": np.array(days)}


class DemandModel:
    version = FORECAST_VERSION

    def fit(self, h, iters=8):
        Y, avail, rain, event, disc, dow, fmt = h["Y"], h["avail"], h["rain"], h["event"], h["disc"], h["dow"], h["format"]
        L, I, C, _, S = Y.shape
        wk = (dow >= 5).astype(int)
        M = avail[:, :, None].astype(np.float32)
        Ym = Y * M
        xp = -np.log1p(-disc)                                                            # promotion: log price ratio
        self.fmt = np.asarray(fmt)
        lvl, shape, mix = np.ones((L, C, 7)), np.ones((L, C, 2, S)), np.full((L, C, I), 1.0 / I)
        a_rain, b_event, eps = np.zeros(C), 0.0, np.zeros(I)
        dowmask = [dow == k for k in range(7)]
        for it in range(iters):
            X = self._cov(rain, event, xp, a_rain, b_event, eps)
            sh = shape[:, :, wk, :]                                                      # [L, C, D, S]
            mx = mix.transpose(0, 2, 1)[:, :, :, None, None]                            # [L, I, C, 1, 1]
            # level per store, channel and weekday
            den = (sh[:, None] * mx * X * M).sum((1, 4))                                 # [L, C, D]
            num = Ym.sum((1, 4))
            for k in range(7):
                lvl[:, :, k] = num[:, :, dowmask[k]].sum(-1) / np.maximum(den[:, :, dowmask[k]].sum(-1), 1e-9)
            lv = lvl[:, :, dow][:, None, :, :, None]                                     # [L, 1, C, D, 1]
            # hour shape per store, channel and day type, shrunk toward the store format's
            mu_ns = lv * mx * X * M
            for t in (0, 1):
                n_ = Ym[:, :, :, wk == t].sum((1, 3))                                    # [L, C, S]
                d_ = mu_ns[:, :, :, wk == t].sum((1, 3))
                prior = np.zeros_like(n_)
                for f in np.unique(self.fmt):
                    m = self.fmt == f
                    prior[m] = n_[m].sum(0) / np.maximum(d_[m].sum(0), 1e-9)
                s_ = (n_ + KAPPA_SHAPE * prior) / (d_ + KAPPA_SHAPE)
                shape[:, :, t, :] = s_ * S / s_.sum(-1, keepdims=True)
            sh = shape[:, :, wk, :]
            # item mix per store and channel, shrunk toward the chain's
            mu_nm = lv * sh[:, None] * X * M
            n_ = Ym.sum((3, 4)).transpose(0, 2, 1)                                       # [L, C, I]
            d_ = mu_nm.sum((3, 4)).transpose(0, 2, 1)
            prior = n_.sum(0) / np.maximum(d_.sum(0), 1e-9)
            m_ = (n_ + KAPPA_MIX * prior) / (d_ + KAPPA_MIX)
            mix = m_ / m_.sum(-1, keepdims=True)
            mx = mix.transpose(0, 2, 1)[:, :, :, None, None]
            mu0 = lv * sh[:, None] * mx                                                  # no covariates
            # rain by channel (multiplier 1 + a r), events (1 + b), promotions exp(eps x)
            Xe, Xp = 1 + b_event * event[:, None, None], np.exp(eps[None, :, None] * xp)[:, :, None, :, None]
            for c in range(C):
                r = rain[:, None]
                base_c = (mu0[:, :, c] * Xe[:, :, 0] * Xp[:, :, 0]) * M[:, :, 0]
                for _ in range(3):
                    mu = base_c * (1 + a_rain[c] * r)
                    g = (r / (1 + a_rain[c] * r))
                    a_rain[c] += ((Ym[:, :, c] - mu) * g).sum() / max((mu * g * g).sum(), 1e-9)
                    a_rain[c] = float(np.clip(a_rain[c], -0.95, 3))
            Xr = np.stack([1 + a_rain[c] * rain for c in range(C)], 1)[:, None]          # [L, 1, C, D, S]
            ev = event[:, None, None]
            mu_e = (mu0 * Xr * Xp * M)
            b_event = float(Ym[ev.repeat(I, 1).repeat(C, 2)].sum() / max(mu_e[ev.repeat(I, 1).repeat(C, 2)].sum(), 1e-9) - 1) if event.any() else 0.0
            Xe = 1 + b_event * event[:, None, None]
            mu_p = mu0 * Xr * Xe * M                                                     # without the promotion term
            x5 = xp[:, :, None, :, None]
            e_pool = float(eps.mean()) if it else 0.0
            for _ in range(4):                                                           # pooled elasticity first
                mu = mu_p * np.exp(e_pool * x5)
                e_pool += float(((Ym - mu) * x5).sum() / max((mu * x5 * x5).sum(), 1e-9))
            for i in range(I):
                e = eps[i] if it else e_pool
                for _ in range(4):
                    mu = mu_p[:, i] * np.exp(e * x5[:, i])
                    g = ((Ym[:, i] - mu) * x5[:, i]).sum() - (e - e_pool) / TAU_ELASTICITY ** 2
                    hh = (mu * x5[:, i] ** 2).sum() + 1 / TAU_ELASTICITY ** 2
                    e += g / hh
                eps[i] = e
            self.promo_exposure = (mu_p * (x5 > 0)).sum((0, 2, 3, 4))                    # expected units on promotion, per item
        self.lvl, self.shape, self.mix, self.a_rain, self.b_event, self.eps, self.e_pool = lvl, shape, mix, a_rain, b_event, eps, e_pool
        # dispersion: per-cell overdispersion c (NB) and the shared store-day shock sigma^2, by the method of moments
        mu = self.mean_hist(h) * M
        cells_mu2 = (mu ** 2).sum()
        c_tot = float(((Ym - mu) ** 2 - Ym).sum() / cells_mu2)
        T, Mu = Ym.sum((1, 2, 4)), mu.sum((1, 2, 4))                                    # store-day totals [L, D]
        mu2_day = (mu ** 2).sum()
        # E[sum (T - Mu)^2 - T] = a * sum mu^2 + s2 * sum Mu^2 ; c_tot = s2 + a
        lhs = float(((T - Mu) ** 2 - T).sum())
        s2 = (lhs - c_tot * mu2_day) / max(float((Mu ** 2).sum()) - mu2_day, 1e-9)
        n = len(h["dow"]) / 7                                                            # training days per weekday
        self.sigma2 = float(np.clip(s2 * (n + 1) / max(n - 1, 1), 1e-4, 0.5))          # in-sample residuals understate it; plus the level's own error
        self.a = float(max(c_tot - self.sigma2, 1e-4))
        self.c = self.sigma2 + self.a
        return self

    @staticmethod
    def _cov(rain, event, xp, a_rain, b_event, eps):
        Xr = np.stack([1 + a_rain[c] * rain for c in range(len(a_rain))], 1)[:, None]   # [L, 1, C, D, S]
        Xe = (1 + b_event * event)[:, None, None]
        Xp = np.exp(eps[None, :, None] * xp)[:, :, None, :, None]
        return Xr * Xe * Xp

    def mean_hist(self, h):
        wk = (h["dow"] >= 5).astype(int)
        X = self._cov(h["rain"], h["event"], -np.log1p(-h["disc"]), self.a_rain, self.b_event, self.eps)
        return (self.lvl[:, :, h["dow"]][:, None, :, :, None] * self.shape[:, :, wk, :][:, None] * self.mix.transpose(0, 2, 1)[:, :, :, None, None] * X)

    def mean(self, day, rain, event, disc):
        """Expected demand [L, I, C, S] on a day, given the conditions as known (rain forecast [L, S], events [L, S], discounts [L, I])."""
        dow = day % 7
        Xr = np.stack([1 + self.a_rain[c] * rain for c in range(2)], 1)                  # [L, C, S]
        mu = (self.lvl[:, :, dow][:, None, :, None] * self.shape[:, :, int(dow >= 5), :][:, None] * self.mix.transpose(0, 2, 1)[:, :, :, None]
              * Xr[:, None] * (1 + self.b_event * event)[:, None, None] * np.exp(self.eps * -np.log1p(-disc))[:, :, None, None])
        return mu

    # intervals --------------------------------------------------------------------------------------------------------
    def interval_cells(self, mu, q=(Q_LO, Q_HI)):
        """Per-cell predictive quantiles (negative binomial with var = mu + c mu^2)."""
        n = 1 / self.c
        p = n / (n + np.maximum(mu, 1e-9))
        return [nbinom.ppf(qq, n, p) for qq in q]

    def agg_var(self, mean, sum_mu2, sigma2=None):
        """Variance of a sum within one store-day: Poisson + overdispersion + the shared shock."""
        s2 = self.sigma2 if sigma2 is None else sigma2
        return mean + self.a * sum_mu2 + s2 * mean ** 2

    @staticmethod
    def nb_quantiles(mean, var, q=(Q_LO, Q_HI)):
        mean, var = np.maximum(np.asarray(mean, float), 1e-9), np.asarray(var, float)
        n = mean ** 2 / np.maximum(var - mean, 1e-6)
        p = n / (n + mean)
        return [nbinom.ppf(qq, n, p) for qq in q]

    def summary(self):
        return {"rain_effect": {"dine_in": round(float(self.a_rain[0]), 3), "delivery": round(float(self.a_rain[1]), 3)},
                "event_lift": round(float(1 + self.b_event), 3), "elasticity": {W.ITEM[i]: round(float(e), 2) for i, e in enumerate(self.eps)},
                "pooled_elasticity": round(float(self.e_pool), 2), "store_day_shock_sd": round(float(np.sqrt(self.sigma2)), 3),
                "slot_overdispersion": round(float(self.a), 4)}


def slot_interval(m, mu_c):
    """90% interval of an item's demand in a slot, both channels together (mu_c: [L, I, C, ...])."""
    mean = mu_c.sum(2)
    return DemandModel.nb_quantiles(mean, m.agg_var(mean, (mu_c ** 2).sum(2)))


def window_interval(m, mu_c):
    """90% interval of an item's demand over a window of slots (the last axis), both channels."""
    mean = mu_c.sum((2, -1))
    return DemandModel.nb_quantiles(mean, m.agg_var(mean, (mu_c ** 2).sum((2, -1))))


def pit_coverage(m, mu_c, y, lo=Q_LO, hi=Q_HI):
    """Calibration of the 90% interval for counts: the share of the randomised PIT that falls inside [5%, 95%], in
    expectation (Czado, Gneiting & Held 2009). A literal interval on whole numbers covers more than its level."""
    mean = np.maximum(mu_c.sum(2), 1e-9)
    var = m.agg_var(mean, (mu_c ** 2).sum(2))
    n = mean ** 2 / np.maximum(var - mean, 1e-6)
    p = n / (n + mean)
    f1, f0 = nbinom.cdf(y, n, p), nbinom.cdf(y - 1, n, p)
    return np.clip(np.minimum(f1, hi) - np.maximum(f0, lo), 0, None) / np.maximum(f1 - f0, 1e-12)


def seasonal_naive(Y_hist, avail_hist):
    """Same item, store and slot last week (sales, channels summed), with empirical 90% error quantiles by forecast level
    learned from the training weeks."""
    tot = Y_hist.sum(2)                                                                  # [L, I, D, S]
    f, y = tot[:, :, :-7], tot[:, :, 7:]
    bins = np.array([0, 1, 2, 3, 5, 8, 13, 21, 10 ** 6])
    k = np.digitize(f, bins) - 1
    q = {}
    for b in range(len(bins) - 1):
        e = (y - f)[k == b]
        q[b] = (float(np.quantile(e, Q_LO)), float(np.quantile(e, Q_HI))) if e.size > 50 else (-2.0 * bins[b] - 2, 2.0 * bins[b] + 2)
    return bins, q


def naive_interval(fc, bins, q):
    k = np.digitize(fc, bins) - 1
    lo, hi = np.zeros_like(fc, dtype=float), np.zeros_like(fc, dtype=float)
    for b, (a, c) in q.items():
        lo[k == b], hi[k == b] = a, c
    return np.maximum(fc + lo, 0), fc + hi


# --- the consumption model ----------------------------------------------------------------------------------------------
def usage_ratios(theoretical, actual, prior_n=10.0):
    """Learned ratio actual/theoretical usage per store and ingredient ([D, L, K] arrays), shrunk toward the chain median."""
    t, a = theoretical.sum(0), actual.sum(0)
    store = a / np.maximum(t, 1e-9)
    chain = np.median(store, 0)
    w = t / np.maximum(theoretical.mean(0), 1e-9) / (t / np.maximum(theoretical.mean(0), 1e-9) + prior_n)
    return np.where(t > 0, w * store + (1 - w) * chain, 1.0), chain


# --- spoilage hazard ------------------------------------------------------------------------------------------------------
def hazard_features(ing, age, temp):
    ing, age, temp = np.asarray(ing), np.asarray(age, float), np.asarray(temp, float)
    frac = age / W.SHELF[ing]
    cold = W.COLD[ing].astype(float)
    onehot = (ing[:, None] == np.nonzero(W.PERISHABLE)[0][None]).astype(float)
    return np.column_stack([frac, frac ** 2, cold * (temp - 3.5), cold * (temp - 3.5) * frac, onehot])


class HazardModel:
    version = HAZARD_VERSION

    def fit(self, ing, age, temp, spoiled):
        self.clf = LogisticRegression(C=10.0, max_iter=2000).fit(hazard_features(ing, age, temp), spoiled)
        return self

    def p(self, ing, age, temp):
        ing = np.asarray(ing)
        out = np.zeros(ing.shape)
        m = W.PERISHABLE[ing] & (np.asarray(age) < W.SHELF[ing])
        if m.any():
            out[m] = self.clf.predict_proba(hazard_features(ing[m], np.asarray(age)[m], np.broadcast_to(temp, ing.shape)[m]))[:, 1]
        return out


def lot_days(lots, temps, until, with_day=False):
    """Lots [(store, ing, received_day, closed_day or None, status)] and cooler temps [L, days] -> the lot-days at risk:
    (store, ing, age, temp, spoiled that day). A lot is at risk from its receipt until the day it was used up (exclusive:
    used before the evening check), spoiled (inclusive), or reached its date (inclusive: it survived that evening's check
    and was then thrown away)."""
    rows, days = [], []
    for l, i, r, closed, status in lots:
        if not W.PERISHABLE[i]:
            continue
        end = until if closed is None else closed
        last = end if status in ("spoiled", "expired") else end - 1
        for d in range(max(r, 0), min(last, until - 1) + 1):
            rows.append((l, i, d - r, temps[l, d], int(status == "spoiled" and d == closed)))
            days.append(d)
    out = np.array(rows, float).reshape(-1, 5)
    return (out, np.array(days)) if with_day else out


def evaluate_hazard(model, rows):
    ing, age, temp, y = rows[:, 1].astype(int), rows[:, 2], rows[:, 3], rows[:, 4]
    p = model.p(ing, age, temp)
    rule = (age >= W.SHELF[ing] - 1).astype(float)                                       # the printed date: risk only on the last day
    base_rate = np.full_like(p, y.mean())
    ll = lambda pp: float(-np.mean(y * np.log(np.clip(pp, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - pp, 1e-6, 1))))   # noqa: E731
    k = max(1, int(0.05 * len(p)))
    top = np.argsort(-p)[:k]
    age_only = age / W.SHELF[ing]
    top_age = np.argsort(-age_only)[:k]
    return {"lot_days": int(len(y)), "spoiled": int(y.sum()), "auc": round(float(roc_auc_score(y, p)), 3) if 0 < y.sum() < len(y) else None,
            "auc_age_only": round(float(roc_auc_score(y, age_only)), 3) if 0 < y.sum() < len(y) else None,
            "auc_printed_date": round(float(roc_auc_score(y, rule)), 3) if 0 < y.sum() < len(y) else None,
            "log_loss": round(ll(p), 4), "log_loss_base_rate": round(ll(base_rate), 4),
            "brier": round(float(np.mean((p - y) ** 2)), 5), "brier_base_rate": round(float(np.mean((base_rate - y) ** 2)), 5),
            "caught_top5pct": round(float(y[top].sum() / max(y.sum(), 1)), 3), "caught_top5pct_age_only": round(float(y[top_age].sum() / max(y.sum(), 1)), 3),
            "caught_printed_date": round(float(y[rule > 0].sum() / max(y.sum(), 1)), 3), "printed_date_flags": round(float(rule.mean()), 3)}


# --- shrinkage ---------------------------------------------------------------------------------------------------------------
def shrinkage_scan(theoretical, actual, z_flag=4.0, min_excess=0.03, threshold=0.04):
    """theoretical, actual: [D, L, ING] daily usage. Per store and ingredient: the mean variance (actual/theoretical - 1)
    against the chain's median for that ingredient, in standard errors of the chain's typical daily scatter.
    Returns (rows, the threshold baseline's flags)."""
    t = theoretical.sum(0)
    v = actual.sum(0) / np.maximum(t, 1e-9) - 1                                          # [L, ING]
    daily = (actual - theoretical) / np.maximum(theoretical.mean(0, keepdims=True), 1e-9)
    se = np.median(daily.std(0, ddof=1), 0) / np.sqrt(theoretical.shape[0])           # the chain's typical day-to-day scatter (a thief's lumps would inflate their own)
    norm = np.median(v, 0)
    excess = v - norm
    z = excess / np.maximum(se, 1e-9)
    flags = (z > z_flag) & (excess > min_excess) & (t > 0)
    corr = np.zeros_like(v)
    for l, i in zip(*np.nonzero(flags)):
        a, b = actual[:, l, i] - theoretical[:, l, i] * (1 + norm[i]), theoretical[:, l, i]
        corr[l, i] = np.corrcoef(a, b)[0, 1] if a.std() > 0 and b.std() > 0 else 0.0
    return {"variance": v, "chain_norm": norm, "excess": excess, "z": z, "flags": flags, "corr": corr}, (v > threshold) & (t > 0)


def classify_shrinkage(scan, l):
    """A flagged store: over-portioning shows on several portioned ingredients in step with sales; theft shows on one or two
    high-value ingredients in lumps that do not follow sales."""
    f = np.nonzero(scan["flags"][l])[0]
    if not len(f):
        return None
    portioned = [i for i in f if W.ING[i] in W.PORTIONED or W.ING[i] in ("avocado", "rice")]
    if len(portioned) >= 3 or (len(f) >= 2 and np.median(scan["corr"][l, f]) > 0.5):
        return "over-portioning"
    return "theft or unrecorded loss"


# --- planning ----------------------------------------------------------------------------------------------------------------
class SystemPolicy:
    """The planner the service runs: prep and orders from the demand model's quantiles."""
    name = "system"

    def __init__(self, model, comp_ratio=None, raw_ratio=None, hazard=None, q_ing=0.95, intraday=True, backup=True, q_prep=0.9):
        self.m, self.hz, self.q_ing, self.intraday, self.backup = model, hazard, q_ing, intraday, backup
        self.q_prep = np.full(W.N_COMP, q_prep)
        self.comp_ratio = comp_ratio
        self.raw_ratio = raw_ratio

    def _day(self, obs, day):
        cache = obs.__dict__.setdefault("_forecasts", {})                                   # forecasts live as long as what they were made from
        if day not in cache:
            rain, ev, disc = obs.conditions(day)
            cache[day] = self.m.mean(day, rain, ev, disc).sum(2)                            # [L, I, S]
        return cache[day]

    def comp_demand(self, mu_is, slots, comps=None, factor=1.0, sigma2=None):
        """Mean and variance of each component's demand over some slots: [L, COMP] each."""
        mu = mu_is[:, :, slots] * factor
        M = mu.sum(2)                                                                      # [L, I]
        mean = M @ W.ITEM_COMP
        cell2 = (mu ** 2).sum(2) @ (W.ITEM_COMP ** 2)
        lin = M @ (W.ITEM_COMP ** 2)
        var = lin + self.m.a * cell2 + (self.m.sigma2 if sigma2 is None else sigma2) * mean ** 2
        if self.comp_ratio is not None:
            mean, var = mean * self.comp_ratio, var * self.comp_ratio ** 2
        return mean, var

    def prep(self, ch, d, window, obs):
        mu = self._day(obs, d)
        if window == 0:
            m_w, v_w = self.comp_demand(mu, slice(0, 20))
            m_d, v_d = self.comp_demand(mu, slice(0, 48))
            mean, var = np.where(W.WINDOW_COMP, m_w, m_d), np.where(W.WINDOW_COMP, v_w, v_d)
        else:
            f, s2 = np.ones(obs.L), None
            if self.intraday and obs.lunch_sales is not None:                             # what lunch said about today's shock
                sold = obs.lunch_sales.sum(2)                                              # [L, I, 20]
                exp_l = mu[:, :, :20]
                y, m_ = sold.sum((1, 2)), exp_l.sum((1, 2))
                k = 1 / self.m.sigma2
                f = (y + k) / (m_ + k)
                s2 = (1 / (y + k))[:, None]
            mean, var = self.comp_demand(mu, slice(20, 48), factor=f[:, None, None], sigma2=s2)
            mean, var = np.where(W.WINDOW_COMP, mean, 0), np.where(W.WINDOW_COMP, var, 1e-9)
        return quantile(mean, var, self.q_prep)

    def raw_need(self, obs, day):
        """Mean and variance of the raw each store will draw on a day: prep (to the plan's quantiles) plus items made to order."""
        mu = self._day(obs, day)
        mw, vw = self.comp_demand(mu, slice(0, 20))
        md, vd = self.comp_demand(mu, slice(20, 48))
        mall, vall = self.comp_demand(mu, slice(0, 48))
        prep = np.where(W.WINDOW_COMP, quantile(mw, vw, self.q_prep) + quantile(md, vd, self.q_prep), quantile(mall, vall, self.q_prep))
        M = mu.sum(2)
        direct = M @ W.ITEM_RAW
        q = W.ITEM_THEORETICAL_RAW                                                         # demand beyond the prep plan draws raw too (top-ups)
        var = M @ (q ** 2) + self.m.a * (mu ** 2).sum(2) @ (q ** 2) + self.m.sigma2 * (M @ q) ** 2
        mean = prep @ W.RAW_PER_COMP + direct
        r = self.raw_ratio if self.raw_ratio is not None else 1.0
        return mean * r, var * r ** 2

    def survival(self, obs, ages, horizon):
        """P(a lot of each age is still good after `horizon` more days) [L, ING, AGES], at today's cooler temperature."""
        if self.hz is None or horizon <= 0:
            return np.ones((obs.L, W.N_ING, W.AGES))
        out = np.ones((obs.L, W.N_ING, W.AGES))
        ll, ii, aa = np.meshgrid(np.arange(obs.L), np.arange(W.N_ING), ages, indexing="ij")
        for k in range(1, horizon + 1):
            out *= 1 - self.hz.p(ii.ravel(), (aa + k).ravel(), obs.temp[ll.ravel()]).reshape(ii.shape)
        return out

    def projected(self, obs, d, a):
        """Stock usable on the morning of day a: today's lots, aged, those past their date dropped, the expected use until
        then taken oldest first, discounted by the hazard model's survival, plus what is due before a."""
        ages = np.arange(W.AGES)
        lots = obs.lots * (ages[None, None, :] + (a - d) < W.SHELF[None, :, None])
        use = sum((self.raw_need(obs, t)[0] for t in range(d + 1, a)), np.zeros((obs.L, W.N_ING)))
        rem = use.copy()
        lots = lots.copy()
        for k in range(W.AGES - 1, -1, -1):
            take = np.minimum(lots[:, :, k], rem)
            lots[:, :, k] -= take
            rem -= take
        lots *= self.survival(obs, ages, a - d)
        return lots.sum(2) + W.pipeline_between(obs, d + 1, a - 1)

    def order(self, ch, d, obs):
        out = []
        for s in W.REGULAR:
            dd = W.order_due_days(d, s)
            if not dd:
                continue
            a, nxt = dd
            m = W.SUPPLIER_OF == W.REGULAR.index(s)
            needs = [self.raw_need(obs, t) for t in range(a, nxt)]
            mean = sum(n[0] for n in needs)
            sd = np.sqrt(sum(n[1] for n in needs))
            z = _z(self.q_ing)
            target = mean + z * sd
            shelf_cap = sum(self.raw_need(obs, t)[0] for t in range(a, a + int(min(W.SHELF.min(), 6))))
            target = np.where(W.PERISHABLE & (W.SHELF < 10), np.minimum(target, np.maximum(shelf_cap, mean)), target)
            on_hand = self.projected(obs, d, a)
            incoming = W.pipeline_between(obs, a, nxt - 1)
            q = np.where(m, W.round_cases(target - on_hand - incoming), 0)
            out.append({"supplier": s, "due": a, "qty": q, "cover_days": nxt - a, "need_mean": mean, "need_sd": sd, "target": target,
                        "usable_on_hand": on_hand, "incoming": incoming})
        if self.backup:
            b = self.backup_order(d, obs, out)
            if b is not None:
                out.append(b)
        return out

    def backup_order(self, d, obs, placed=()):
        """When the stock on hand and what will really arrive tomorrow (after the suppliers' notices) would leave a store
        short before its next delivery, buy the shortfall from the cash-and-carry for tomorrow morning."""
        t = d + 1
        stock = self.projected(obs, d, t)
        arriving = W.pipeline_between(obs, t, t)
        for o in placed:                                                                  # tonight's orders, with the suppliers' notices applied
            late = W.expected_delay(obs.ch, o, obs.delays)
            arriving += o["qty"] * ((o["due"] + late) == t)[:, None] if np.ndim(late) else o["qty"] * (o["due"] + late == t)
        nxt = np.full((obs.L, W.N_ING), t + 1)
        for k, s in enumerate(W.REGULAR):                                                 # the next morning anything else arrives
            m = W.SUPPLIER_OF == k
            for e in range(t + 1, t + 8):
                if e % 7 in W.SUPPLIERS[s][1]:
                    nxt[:, m] = e
                    break
        need_m, need_v = np.zeros((obs.L, W.N_ING)), np.zeros((obs.L, W.N_ING))
        for e in range(t, t + 7):
            nm, nv = self.raw_need(obs, e)
            on = e < nxt
            need_m += nm * on
            need_v += nv * on
        late = W.pipeline_between(obs, t + 1, int(nxt.max()))
        short = need_m + _z(self.q_ing) * np.sqrt(need_v) - stock - arriving
        big = short > np.maximum(0.15 * need_m, 0.5 * W.CASE)
        q = np.where(big & (late > 0) | big & (short > 0.5 * need_m), W.round_cases(short), 0)
        return {"supplier": "backup", "due": t, "qty": q, "cover_days": None, "need_mean": need_m, "need_sd": np.sqrt(need_v),
                "target": need_m + _z(self.q_ing) * np.sqrt(need_v), "usable_on_hand": stock, "incoming": arriving, "late": late} if q.any() else None


def _z(q):
    return float(norm.ppf(q))


def quantile(mean, var, q):
    """Quantile of a positive quantity with this mean and variance (gamma moment match)."""
    mean, var = np.maximum(mean, 1e-9), np.maximum(var, 1e-12)
    k = mean ** 2 / var
    return np.where(mean > 1e-6, gamma.ppf(np.broadcast_to(q, mean.shape), k, scale=var / mean), 0.0)


def config_hash(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


class WithPlans:
    """A policy that follows fixed prep plans for some (day, window) - a plan the planner made and a store follows - and
    defers to another policy for everything else."""

    def __init__(self, fallback, preps=None):
        self.fallback, self.preps = fallback, preps or {}
        self.name = getattr(fallback, "name", "")

    def prep(self, ch, d, window, obs):
        return self.preps[(d, window)] if (d, window) in self.preps else self.fallback.prep(ch, d, window, obs)

    def order(self, ch, d, obs):
        return self.fallback.order(ch, d, obs)


ORDER_LIMIT_USD = 250.0                        # an order line that moves more than this from the chain's usual par needs a store manager


def change_value(supplier, qty, par):
    return np.abs(qty - par) * W.COST * W.SUPPLIERS[supplier][2]


class Bounded:
    """The planner running unattended (inside a day the advance plays out): the system's order lines within the limit are
    placed; a line beyond it would need a store manager, so the store's usual par is placed instead and the line is logged."""

    def __init__(self, system, usual, limit=ORDER_LIMIT_USD):
        self.system, self.usual, self.limit = system, usual, limit
        self.name = "system (bounded automation)"

    def prep(self, ch, d, window, obs):
        return self.system.prep(ch, d, window, obs)

    def order(self, ch, d, obs):
        par = {o["supplier"]: o["qty"] for o in self.usual.order(ch, d, obs)}
        out = []
        for o in self.system.order(ch, d, obs):
            p = par.pop(o["supplier"], np.zeros_like(o["qty"]))
            ok = change_value(o["supplier"], o["qty"], p) <= self.limit
            out.append({"supplier": o["supplier"], "due": o["due"], "qty": np.where(ok, o["qty"], p), "proposed": o["qty"], "par": p, "auto": ok})
        for s, p in par.items():
            out.append({"supplier": s, "due": W.order_due_days(d, s)[0], "qty": p, "proposed": p, "par": p, "auto": np.ones_like(p, bool)})
        return out
