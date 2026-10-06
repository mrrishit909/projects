"""Models and analysis, all fitted on what the service stores (sensor summaries, test maps, engineers' labels), never on the
generator's internals.

    map_features     rotation-invariant description of a wafer's fail map (radial profile, sorted sectors, the largest
                     connected cluster and how elongated it is); invariance replaces rotation/flip augmentation
    classifier       gradient-boosted trees on those features, abstaining below a confidence threshold; baseline: nearest
                     centroid on the radial profile
    baselines        each chamber's normal operating point per sensor (median and spread over the training weeks)
    yield model      gradient-boosted regression on every step's sensor deviations from its chamber's baseline; baseline:
                     the product's trailing mean over the last 20 lots
    bocpd            Bayesian online change-point detection (Adams & MacKay) on a chamber's primary sensor; baseline: a
                     Shewhart 3-sigma rule on single points
    root_cause       rank every chamber by commonality with the affected wafers (log-odds within the step, Fisher's test),
                     change-point evidence on its sensor, and how often the pattern came from that step in the history
"""
import hashlib
import json
import math

import numpy as np
from scipy import ndimage
from scipy.stats import fisher_exact
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import f1_score
from sklearn.neighbors import NearestCentroid

from . import world

GRID = 2 * 13 + 1
R_EDGES = np.array([0, .2, .35, .5, .6, .7, .78, .85, .9, .95, 1.01])
ABSTAIN = 0.6
CLASSIFIER_VERSION = "wafer-pattern-hgb-1"
YIELD_VERSION = "yield-hgb-1"
EXCURSION_PATTERNS = ("edge-ring", "center", "donut", "random-high")


# --- wafer maps ------------------------------------------------------------------------------------------------------
def map_features(bins):
    fail = np.asarray(bins) != world.BINS["pass"]
    r, th = world.DIE_R, world.DIE_TH
    radial = [fail[(r >= a) & (r < b)].mean() for a, b in zip(R_EDGES[:-1], R_EDGES[1:])]
    sectors = np.sort([fail[(th >= a) & (th < a + np.pi / 4)].mean() for a in np.linspace(-np.pi, np.pi, 8, endpoint=False)])
    grid = np.zeros((GRID, GRID), bool)
    grid[world.DIE_Y + 13, world.DIE_X + 13] = fail
    lab, n = ndimage.label(grid)
    sizes = np.bincount(lab.ravel())[1:] if n else np.array([0])
    big = int(sizes.max()) if n else 0
    elong = 0.0
    if big >= 4:
        ys, xs = np.nonzero(lab == (np.argmax(sizes) + 1))
        ev = np.linalg.eigvalsh(np.cov(np.vstack([xs, ys])) + 1e-6 * np.eye(2))
        elong = float(np.sqrt(ev[1] / ev[0]))
    return np.array([fail.mean(), *radial, *sectors, sectors[-1] - sectors[0], big / world.N_DIES, min(elong, 20.0), n / 50])


def novelty_threshold(X, y):
    """The fail rate above which a wafer the model calls 'none' is sent for review: the 99.5th percentile of normal wafers."""
    return float(np.quantile(np.asarray(X)[np.asarray(y) == "none", 0], 0.995))


def train_classifier(X, y, test_mask):
    """Fit on training wafers, score on the test wafers against a nearest-centroid baseline. Returns (model, metrics)."""
    X, y = np.asarray(X), np.asarray(y)
    tr, te = ~test_mask, test_mask
    clf = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.08, class_weight="balanced", random_state=0).fit(X[tr], y[tr])
    base = NearestCentroid().fit(X[tr][:, 1:11], y[tr])
    clf.novelty_ = novelty_threshold(X[tr], y[tr])
    pred, conf = _predict(clf, X[te])
    keep = pred != "review"
    labels = [p for p in world.PATTERNS if p in set(y[te])]       # score only patterns that occur in the test weeks
    return clf, {
        "macro_f1": round(float(f1_score(y[te], np.where(keep, pred, "none"), labels=labels, average="macro", zero_division=0)), 3),
        "macro_f1_answered": round(float(f1_score(y[te][keep], pred[keep], labels=labels, average="macro", zero_division=0)), 3),
        "abstained": round(float(1 - keep.mean()), 3),
        "baseline_macro_f1": round(float(f1_score(y[te], base.predict(X[te][:, 1:11]), labels=labels, average="macro", zero_division=0)), 3),
        "per_pattern_recall": {p: round(float((pred[te_p] == p).mean()), 3) for p in labels if (te_p := y[te] == p).sum()},
        "sent_for_review": {p: round(float((pred[te_p] == "review").mean()), 3) for p in labels if (te_p := y[te] == p).sum()},
        "unseen_in_training": sorted(set(y[te]) - set(y[tr])),
        "test_wafers": int(te.sum()), "train_wafers": int(tr.sum()),
        "excursion_wafers_in_test": int(np.isin(y[te], EXCURSION_PATTERNS).sum()),
    }


def _predict(clf, X):
    X = np.atleast_2d(X)
    proba = clf.predict_proba(X)
    best = proba.argmax(1)
    conf = proba[np.arange(len(best)), best]
    label = np.where(conf >= ABSTAIN, clf.classes_[best], "review")
    novel = (label == "none") & (X[:, 0] > getattr(clf, "novelty_", 1.0))     # 'none' but failing like nothing normal
    return np.where(novel, "review", label), np.where(novel, 0.0, conf)


def classify(clf, X):
    pred, conf = _predict(clf, X)
    return [str(p) for p in pred], [round(float(c), 3) for c in conf]


# --- chambers and yield ----------------------------------------------------------------------------------------------
def chamber_baselines(rows):
    """rows: [(chamber, product, {sensor: value})] from the qualification week -> {chamber: {product: {sensor: [median, robust sd]}}}.
    Per product, because each product's recipe runs the chamber at its own setpoints."""
    acc = {}
    for ch, product, sens in rows:
        for k, v in sens.items():
            acc.setdefault(ch, {}).setdefault(product, {}).setdefault(k, []).append(v)
    out = {}
    for ch, by_product in acc.items():
        out[ch] = {}
        for product, d in by_product.items():
            out[ch][product] = {}
            for k, vs in d.items():
                a = np.asarray(vs)
                med = float(np.median(a))
                out[ch][product][k] = [med, float(1.4826 * np.median(np.abs(a - med))) or 1e-6]
    return out


FEATURE_NAMES = [f"{s}.{k}" for s in world.STEPS for k in world.SENSORS[s]] + ["product_P2"]


def yield_features(steps, baselines, product):
    """Each step's sensors as deviations from the qualified baseline of the chamber that ran it, in the sensor's own units
    (physics acts on units, not on a chamber's noise level). Order fixed by FEATURE_NAMES."""
    by = {st["step"]: st for st in steps}
    out = []
    for s in world.STEPS:
        st = by[s]
        for k in world.SENSORS[s]:
            out.append(st["sensors"][k] - baselines[st["chamber"]][product][k][0])
    return np.array(out + [1.0 if product == "P2" else 0.0])


def feature_hash(x):
    return hashlib.sha256(json.dumps([round(float(v), 4) for v in x]).encode()).hexdigest()[:16]


def train_yield(X, y, lot_index, product, test_mask, excursion):
    """Gradient-boosted regression vs the product's trailing mean over the 20 lots before each wafer's lot."""
    X, y = np.asarray(X), np.asarray(y)
    reg = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.06, random_state=0).fit(X[~test_mask], y[~test_mask])
    pred = reg.predict(X[test_mask])
    lot_mean = {}
    for li, pr, yy in zip(lot_index, product, y):
        lot_mean.setdefault((pr, li), []).append(yy)
    order = {pr: sorted(li for p2, li in lot_mean if p2 == pr) for pr in set(product)}

    def trailing(li, pr):
        prev = [l for l in order[pr] if l < li][-20:]
        return float(np.mean([np.mean(lot_mean[(pr, l)]) for l in prev])) if prev else float(np.mean(y[~test_mask]))
    base = np.array([trailing(li, pr) for li, pr, t in zip(lot_index, product, test_mask) if t])
    yt, ex = y[test_mask], np.asarray(excursion)[test_mask]
    mae = lambda a: round(float(np.mean(np.abs(a - yt))) * 100, 2)            # noqa: E731  percentage points
    sub = lambda a: round(float(np.mean(np.abs(a[ex] - yt[ex]))) * 100, 2) if ex.any() else None   # noqa: E731
    return reg, {"mae_pp": mae(pred), "baseline_mae_pp": mae(base), "mae_pp_excursion_wafers": sub(pred),
                 "baseline_mae_pp_excursion_wafers": sub(base), "excursion_wafers": int(ex.sum()), "test_wafers": int(test_mask.sum())}


# --- drift ------------------------------------------------------------------------------------------------------------
def bocpd(z, hazard=1 / 300, mu0=0.0, var0=4.0, rmax=120):
    """Bayesian online change-point detection for a Gaussian with unit variance and unknown mean.
    Returns (P(run length <= 5) at each point, posterior mean of the current run)."""
    z = np.asarray(z, float)
    R = np.array([1.0])
    mus, vs = np.array([mu0]), np.array([var0])
    cp, mean = np.zeros(len(z)), np.zeros(len(z))
    for t, x in enumerate(z):
        pred = np.exp(-0.5 * (x - mus) ** 2 / (vs + 1)) / np.sqrt(2 * np.pi * (vs + 1))
        growth = R * pred * (1 - hazard)
        change = (R * pred * hazard).sum()
        R = np.append(change, growth)
        R /= R.sum()
        new_v = 1 / (1 / vs + 1)
        new_mu = new_v * (mus / vs + x)
        mus, vs = np.append(mu0, new_mu), np.append(var0, new_v)
        if len(R) > rmax:
            R, mus, vs = R[:rmax], mus[:rmax], vs[:rmax]
            R /= R.sum()
        cp[t] = R[:6].sum()
        mean[t] = float((R * mus).sum())
    return cp, mean


def drift_alarms(z, rule="bocpd", min_shift=2.0):
    """Indices where an alarm would first fire after being quiet for 30 points."""
    z = np.asarray(z, float)
    if rule == "shewhart":
        hit = np.abs(z) > 3
    else:
        cp, mean = bocpd(z)
        run = np.convolve(z, np.ones(5) / 5, mode="full")[:len(z)]           # the last five points
        hit = (cp > 0.5) & (np.abs(run) > min_shift) | (np.abs(mean) > min_shift) & (np.abs(run) > min_shift)
    out, last = [], -10 ** 9
    for i in np.nonzero(hit)[0]:
        if i - last > 30:
            out.append(int(i))
        last = i
    return out


# --- root cause -------------------------------------------------------------------------------------------------------
def step_priors(labelled):
    """labelled: [(pattern, {step: |z| of that step's primary sensor})] -> P(step | pattern), Laplace-smoothed."""
    counts = {p: {s: 1.0 for s in world.STEPS} for p in EXCURSION_PATTERNS}
    for pattern, zs in labelled:
        if pattern in counts:
            counts[pattern][max(zs, key=zs.get)] += 1
    return {p: {s: round(v / sum(c.values()), 4) for s, v in c.items()} for p, c in counts.items()}


def root_cause(wafers, pattern, priors=None, drifting=(), use=("commonality", "drift", "prior")):
    """wafers: [{'affected': bool, 'route': {step: chamber}}]; drifting: chambers with a change-point alarm in the window.
    Returns every chamber ranked, with its evidence and a confidence (softmax of the scores)."""
    aff = np.array([w["affected"] for w in wafers])
    rows = []
    for ch, tool, step in world.CHAMBERS:
        through = np.array([w["route"][step] == ch for w in wafers])
        a, b = int((aff & through).sum()), int((~aff & through).sum())
        c, d = int((aff & ~through).sum()), int((~aff & ~through).sum())
        lor = math.log((a + .5) * (d + .5) / ((b + .5) * (c + .5)))
        p = fisher_exact([[a, b], [c, d]], alternative="greater")[1] if a else 1.0
        z = min(8.0, -math.log10(max(p, 1e-300)))
        score = 0.0
        if "commonality" in use:
            score += z * (lor > 0) + 0.3 * max(lor, 0)
        if "drift" in use and ch in drifting:
            score += 3.0
        if "prior" in use and priors and pattern in priors:
            score += 2.0 * math.log(priors[pattern][step] * len(world.STEPS))
        rows.append({"chamber": ch, "tool": tool, "step": step, "score": round(score, 3),
                     "evidence": {"affected_through": a, "wafers_through": a + b, "affected_rate": round(a / max(1, a + b), 3),
                                  "affected_rate_elsewhere_in_step": round(c / max(1, c + d), 3), "log_odds": round(lor, 2),
                                  "fisher_p": float(f"{p:.3g}"), "sensor_change_point": ch in drifting,
                                  "pattern_step_prior": priors[pattern][step] if priors and pattern in priors else None}})
    rows.sort(key=lambda r: -r["score"])
    s = np.array([r["score"] for r in rows])
    w = np.exp(s - s.max())
    for r, v in zip(rows, w / w.sum()):
        r["confidence"] = round(float(v), 3)
    return rows


# --- fitting from stored records --------------------------------------------------------------------------------------
def records(lots, labelled=True):
    """Generator lots -> the records the service stores (sensors, test map, and an engineer's label for history wafers)."""
    out = []
    for lot in lots:
        for w in lot["wafers"]:
            out.append({"lot_index": lot["index"], "lot": lot["lot"], "product": lot["product"], "slot": w["slot"], "steps": w["steps"],
                        "bins": w["bins"], "yield": w["yield"], "label": w["truth_pattern"] if labelled else None})
    return out


def primary_z(rec, baselines):
    out = {}
    for st in rec["steps"]:
        k = world.PRIMARY[st["step"]]
        med, sd = baselines[st["chamber"]][rec["product"]][k]
        out[st["step"]] = abs((st["sensors"][k] - med) / sd)
    return out


def fit(recs, test_from_lot):
    """Everything the service needs, trained on lots before `test_from_lot` and scored on the rest."""
    lot_idx = np.array([r["lot_index"] for r in recs])
    test = lot_idx >= test_from_lot
    baselines = chamber_baselines((st["chamber"], r["product"], st["sensors"]) for r in recs if r["lot_index"] < world.QUALIFICATION_LOTS for st in r["steps"])
    Xm = np.array([map_features(r["bins"]) for r in recs])
    y = np.array([r["label"] for r in recs])
    clf, cls_metrics = train_classifier(Xm, y, test)
    Xy = np.array([yield_features(r["steps"], baselines, r["product"]) for r in recs])
    reg, y_metrics = train_yield(Xy, [r["yield"] for r in recs], lot_idx, [r["product"] for r in recs], test, np.isin(y, EXCURSION_PATTERNS))
    priors = step_priors((r["label"], primary_z(r, baselines)) for r, t in zip(recs, test) if not t and r["label"] in EXCURSION_PATTERNS)
    return {"classifier": clf, "yield": reg, "baselines": baselines, "priors": priors,
            "metrics": {"classifier": cls_metrics, "yield": y_metrics, "train_lots": int(test_from_lot), "test_lots": int(lot_idx.max() - test_from_lot + 1)}}
