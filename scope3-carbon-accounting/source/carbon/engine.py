"""Models and calculations, all run on what the service stores (vendor records, invoice lines, shipments, bills,
disclosure text, the factor registry), never on the generator's truth.

    normalisation   currencies to USD at the month's rate, pounds to kg, miles to km, therms and m3 to kWh, MWh to kWh
    resolver        supplier entity resolution: candidates from character n-gram TF-IDF neighbours plus shared tax ids and
                    e-mail domains (blocking), then a logistic model on fuzzy and embedding-style similarities, tax id,
                    domain and country, and merges that never join two different tax ids. Baselines: exact name equality
                    after case and punctuation clean-up; fuzzy similarity alone
    classifier      invoice line -> spend category from description, GL account and vendor name (char n-gram TF-IDF into
                    logistic regression); abstains below a confidence threshold to a fallback heuristic and a review task.
                    Baseline: keyword rules, then the GL account
    emissions       spend x sector factor (by category and the supplier's region), supplier-specific factors where a
                    disclosure was accepted, tonne-km x mode factor for shipments, metered energy x grid or fuel factor;
                    energy and freight invoices are left to the bills and shipments so nothing is counted twice
    uncertainty     Monte Carlo: one draw per factor shared by every line that uses it, and one per supplier around its
                    sector mean for spend-based lines
    extraction      supplier disclosures (text) -> revenue, scope 1/2/3 upstream with units and scale, validated
    influence       emission-weighted Katz centrality on the supplier network from disclosures (who buys from whom)
    scenario        freight shifted between modes and suppliers decarbonising, recalculated from the stored lines
"""
import difflib
import functools
import hashlib
import json
import re
import unicodedata

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score

from . import world

CLASSIFIER_VERSION = "category-tfidf-lr-1"
RESOLVER_VERSION = "supplier-match-lr-1"
EXTRACTOR_VERSION = "disclosure-parser-1"
ABSTAIN = 0.55                       # below this the classifier hands the line to the fallback heuristic and a review task
MERGE, REVIEW_LO, REVIEW_HI = 0.5, 0.3, 0.7
DRAWS = 2000

# --- normalisation --------------------------------------------------------------------------------------------------------
TO_KG = {"kg": 1.0, "lb": 0.4536, "t": 1000.0}
TO_KM = {"km": 1.0, "mi": 1.609}
TO_KWH = {"kWh": 1.0, "MWh": 1000.0, "m3": 10.55, "therm": 29.31, "GJ": 277.8}
TO_L = {"L": 1.0, "gal": 3.785}


def currency(code):
    """-> ISO code or None. Aliases a clerk might type (RMB, US$, EURO) are mapped; anything else is refused."""
    code = (code or "").strip().upper()
    code = world.CURRENCY_ALIASES.get(code, code)
    return code if code in world.FX else None


def energy(fuel, quantity, unit):
    """A bill line -> (quantity in the factor's unit, that unit) or raises ValueError."""
    if fuel == "diesel":
        if unit not in TO_L:
            raise ValueError(f"diesel in {unit}")
        return quantity * TO_L[unit], "L"
    if unit not in TO_KWH:
        raise ValueError(f"{fuel} in {unit}")
    return quantity * TO_KWH[unit], "kWh"


# --- supplier names -------------------------------------------------------------------------------------------------------
LEGAL_TOKENS = set("inc incorporated llc corp corporation gmbh ag ltd limited plc co company pvt private ltda sa spa srl de cv kk "
                   "kabushiki kaisha jsc joint stock the".split())
NOISE_TOKENS = set("eur old use this one".split())
EXPAND = {"mfg": "manufacturing", "tech": "technologies", "logistic": "logistics", "comp": "components", "svcs": "services",
          "sys": "systems", "prods": "products", "trdg": "trading", "elec": "electronics", "pkg": "packaging", "chem": "chemicals",
          "mach": "machinery", "cnsltg": "consulting", "maint": "maintenance", "assoc": "associates", "intl": "international"}


@functools.lru_cache(maxsize=65536)
def norm_name(s):
    """Case, accents, punctuation, legal forms, abbreviations and clerks' notes removed: 'ALTAMIRA STEEL TRDG GMBH (old)' -> 'altamira steel trading'."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    toks = [EXPAND.get(t, t) for t in s.split()]
    return " ".join(t for t in toks if len(t) > 1 and t not in LEGAL_TOKENS and t not in NOISE_TOKENS)


def simple_name(s):
    """What a spreadsheet dedupe does: case, punctuation and spaces only (the string-equality baseline)."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split())


def norm_tax(t):
    return re.sub(r"[^A-Z0-9]", "", t.upper()) if t else None


def name_vectorizer():
    return TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)


def candidates(records, k=12, min_cos=0.25):
    """Blocking: each record's nearest neighbours by character n-gram TF-IDF cosine, plus every pair sharing a tax id or
    a company e-mail domain. Returns (pairs [(i, j)], name vectors). Brute force here (a thousand records); an ANN index past that."""
    names = [norm_name(r["name"]) or simple_name(r["name"]) for r in records]
    X = name_vectorizer().fit_transform(names)
    S = (X @ X.T).toarray()
    np.fill_diagonal(S, 0)
    pairs = set()
    for i in range(len(records)):
        for j in np.argsort(-S[i])[:k]:
            if S[i, j] >= min_cos:
                pairs.add((min(i, int(j)), max(i, int(j))))
    for key in ("tax_id", "email_domain"):
        by = {}
        for i, r in enumerate(records):
            v = norm_tax(r.get(key)) if key == "tax_id" else r.get(key)
            if v and v.lower() not in world.GENERIC_DOMAINS:
                by.setdefault(v, []).append(i)
        for ids in by.values():
            pairs.update((a, b) for x, a in enumerate(ids) for b in ids[x + 1:])
    return sorted(pairs), X, names


FEATURES = ["tfidf_cosine", "token_jaccard", "sequence_ratio", "first_token_equal", "tax_id", "email_domain", "same_country", "same_subsidiary"]


def pair_features(records, pairs, X, names):
    out = np.zeros((len(pairs), len(FEATURES)))
    if not pairs:
        return out
    a, b = np.array(pairs).T
    out[:, 0] = np.asarray(X[a].multiply(X[b]).sum(1)).ravel()
    for k, (i, j) in enumerate(pairs):
        ti, tj = set(names[i].split()), set(names[j].split())
        out[k, 1] = len(ti & tj) / max(1, len(ti | tj))
        out[k, 2] = difflib.SequenceMatcher(None, names[i], names[j]).ratio()
        out[k, 3] = float(bool(names[i]) and names[i].split()[:1] == names[j].split()[:1])
        ri, rj = records[i], records[j]
        xi, xj = norm_tax(ri.get("tax_id")), norm_tax(rj.get("tax_id"))
        out[k, 4] = 0.0 if not (xi and xj) else 1.0 if xi == xj else -1.0
        di, dj = ri.get("email_domain"), rj.get("email_domain")
        ok = di and dj and di not in world.GENERIC_DOMAINS and dj not in world.GENERIC_DOMAINS
        out[k, 5] = 0.0 if not ok else 1.0 if di == dj else -1.0
        out[k, 6] = float(ri.get("country") == rj.get("country"))
        out[k, 7] = float(ri.get("subsidiary") == rj.get("subsidiary"))
    return out


def train_resolver(records_sets):
    """records_sets: [(records with a 'supplier' truth label)] from earlier engagements (analyst-confirmed pairs).
    Returns (model, metrics on the training pairs, fuzzy-only threshold chosen on them)."""
    Xs, ys = [], []
    for recs in records_sets:
        pairs, X, names = candidates(recs)
        Xs.append(pair_features(recs, pairs, X, names))
        ys.append(np.array([recs[i]["supplier"] == recs[j]["supplier"] for i, j in pairs]))
    Xf, y = np.vstack(Xs), np.concatenate(ys)
    model = LogisticRegression(C=2.0, max_iter=2000).fit(Xf, y)
    fuzzy = Xf[:, 2]
    best = max(np.arange(0.5, 1.0, 0.02), key=lambda t: f1_score(y, fuzzy >= t))
    model.fuzzy_threshold_ = float(best)
    return model, {"training_pairs": int(len(y)), "matches": int(y.sum()), "weights": dict(zip(FEATURES, np.round(model.coef_[0], 2).tolist())),
                   "fuzzy_threshold": round(float(best), 2)}


class _UF:
    def __init__(self, n, taxes):
        self.p = list(range(n))
        self.tax = [{t} if t else set() for t in taxes]

    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, i, j):
        a, b = self.find(i), self.find(j)
        if a == b:
            return True
        if self.tax[a] and self.tax[b] and not (self.tax[a] & self.tax[b]):
            return False                        # never join two legal entities with different tax ids
        self.p[b] = a
        self.tax[a] |= self.tax[b]
        return True


def resolve(records, model):
    """-> {'cluster': [cluster index per record], 'pairs': [(i, j, prob, features)], 'review': [(i, j, prob)], 'blocked': n}."""
    pairs, X, names = candidates(records)
    F = pair_features(records, pairs, X, names)
    prob = model.predict_proba(F)[:, 1] if len(pairs) else np.array([])
    uf = _UF(len(records), [norm_tax(r.get("tax_id")) for r in records])
    order = np.argsort(-prob)
    refused = 0
    for k in order:
        if prob[k] < MERGE:
            break
        refused += not uf.union(*pairs[k])
    roots = [uf.find(i) for i in range(len(records))]
    ids = {r: n for n, r in enumerate(dict.fromkeys(roots))}
    review = [(pairs[k][0], pairs[k][1], float(prob[k])) for k in order if REVIEW_LO <= prob[k] < REVIEW_HI]
    return {"cluster": [ids[r] for r in roots], "pairs": [(i, j, float(p), f) for (i, j), p, f in zip(pairs, prob, F)], "review": review,
            "candidate_pairs": len(pairs), "refused_tax_conflicts": int(refused), "names": names}


def baseline_clusters(records, how="exact", threshold=0.9):
    """exact: identical after case/punctuation clean-up. fuzzy: sequence similarity of normalised names above a threshold."""
    if how == "exact":
        keys = {}
        return [keys.setdefault(simple_name(r["name"]), len(keys)) for r in records]
    pairs, X, names = candidates(records)
    uf = _UF(len(records), [None] * len(records))
    for i, j in pairs:
        if difflib.SequenceMatcher(None, names[i], names[j]).ratio() >= threshold:
            uf.union(i, j)
    roots = [uf.find(i) for i in range(len(records))]
    ids = {r: n for n, r in enumerate(dict.fromkeys(roots))}
    return [ids[r] for r in roots]


def pairwise_scores(cluster, truth):
    """Precision, recall and F1 over all record pairs placed in the same cluster vs the same true supplier."""
    def same_pairs(lbl):
        by = {}
        for i, c in enumerate(lbl):
            by.setdefault(c, []).append(i)
        return {(a, b) for ids in by.values() for x, a in enumerate(ids) for b in ids[x + 1:]}
    p, t = same_pairs(cluster), same_pairs(truth)
    tp = len(p & t)
    prec, rec = tp / max(1, len(p)), tp / max(1, len(t))
    return {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(2 * prec * rec / max(1e-9, prec + rec), 3),
            "clusters": len(set(cluster)), "true_suppliers": len(set(truth))}


# --- spend categories -----------------------------------------------------------------------------------------------------
KEYWORDS = [   # the rules a carbon team writes first; order matters, first hit wins
    ("freight", ["freight", "trucking", "surcharge", "courier", "customs", "haulage", "awb", "fcl", "ltl", "spedition", "frete"]),
    ("utilities", ["electricity", "natural gas", "power bill", "energy invoice", "diesel", "strom", "energia", "gas supply"]),
    ("business_travel", ["flight", "hotel", "taxi", "rail ticket", "car rental", "travel", "reisekosten", "passagem"]),
    ("steel_metals", ["steel", "coil", "sheet", "rebar", "round bar", "plate", "alumin", "copper", "tube", "stahl"]),
    ("plastics_resins", ["resin", "polymer", "granul", "pellet", "abs ", "pa66", "hdpe", "pvc", "polycarbonate", "kunststoff"]),
    ("chemicals", ["oil", "fluid", "coating", "solvent", "degreaser", "grease", "graxa"]),
    ("electronic_components", ["pcb", "mcu", "capacitor", "connector", "harness", "sensor", "relay", "leiterplatte"]),
    ("packaging", ["carton", "pallet", "film", "foam", "label", "strapping", "corrugated", "wellpappe", "caixas"]),
    ("machinery", ["cnc", "press", "conveyor", "robot", "compressor", "forklift", "machine", "lathe"]),
    ("it_software", ["software", "cloud", "laptop", "licen", "network", "it support"]),
    ("professional_services", ["consult", "audit", "legal", "engineering services", "recruit", "tax advisory", "beratung"]),
    ("facility_services", ["cleaning", "security", "waste", "hvac", "canteen", "pest", "reinigung", "manutencao"]),
]
GL_MAP = {"5100": "steel_metals", "5150": "electronic_components", "1600": "machinery", "6400": "it_software", "6500": "professional_services",
          "6200": "facility_services", "6600": "business_travel", "5300": "freight", "6100": "utilities"}     # 6900 sundry: no answer


_DIGITS = re.compile(r"\d+")


def mask(desc):
    return _DIGITS.sub("#", (desc or "").lower()).strip()


def rule_category(desc, gl):
    """The baseline (and the classifier's fallback): keyword rules, then the GL account. None when neither says anything."""
    d = " " + (desc or "").lower() + " "
    for cat, words in KEYWORDS:
        if any(w in d for w in words):
            return cat
    return GL_MAP.get(gl)


def class_text(desc, gl, vendor_name):
    return f"gl{gl} {norm_name(vendor_name)} | {mask(desc)}"


def train_classifier(texts, labels):
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=2, sublinear_tf=True)
    X = vec.fit_transform(texts)
    clf = LogisticRegression(C=8.0, max_iter=3000).fit(X, labels)
    return {"vectorizer": vec, "model": clf}


def classify(model, texts):
    """-> (category or None per text, confidence). Below ABSTAIN the answer is None (the caller falls back)."""
    if not len(texts):
        return [], np.array([])
    P = model["model"].predict_proba(model["vectorizer"].transform(texts))
    best = P.argmax(1)
    conf = P[np.arange(len(best)), best]
    cats = model["model"].classes_[best]
    return [str(c) if p >= ABSTAIN else None for c, p in zip(cats, conf)], conf


def map_lines(model, desc, gl, vendor_names, cache=None):
    """Every line -> (category or None, confidence, method: model / fallback / unmapped, input keys, {key: (category, conf)}).
    Distinct inputs are classified once; `cache` carries answers across calls (a big import arrives month by month)."""
    keys = [class_text(d, g, v) for d, g, v in zip(desc, gl, vendor_names)]
    look = cache if cache is not None else {}
    uniq = [k for k in dict.fromkeys(keys) if k not in look]
    cats, conf = classify(model, uniq)
    look.update({k: (c, float(p)) for k, c, p in zip(uniq, cats, conf)})
    out_c, out_p, out_m = [], np.zeros(len(keys)), []
    for n, (k, d, g) in enumerate(zip(keys, desc, gl)):
        c, p = look[k]
        out_p[n] = p
        if c is not None:
            out_c.append(c)
            out_m.append("model")
        else:
            fb = rule_category(d, g)
            out_c.append(fb)
            out_m.append("fallback" if fb else "unmapped")
    return out_c, out_p, out_m, keys, look


def category_scores(pred, truth, usd):
    pred, truth, usd = np.asarray(pred, dtype=object), np.asarray(truth, dtype=object), np.abs(np.asarray(usd, float))
    mapped = np.array([p is not None for p in pred])
    labels = [c for c in world.CATS if c in set(truth)]
    filled = np.where(mapped, pred, "unmapped")
    return {"accuracy": round(float((filled == truth).mean()), 3), "macro_f1": round(float(f1_score(truth.astype(str), filled.astype(str), labels=labels, average="macro", zero_division=0)), 3),
            "spend_weighted_accuracy": round(float(usd[filled == truth].sum() / usd.sum()), 3),
            "orphan_rate": round(float(1 - mapped.mean()), 4), "orphan_spend_share": round(float(usd[~mapped].sum() / usd.sum()), 4)}


# --- emissions ------------------------------------------------------------------------------------------------------------
def spend_factor_id(category, country):
    return f"SPEND:{category}:{world.region(country)}"


def _lookup(keys, table, default=""):
    """Map a large array of keys through a dict by its distinct values (vectorised)."""
    u, inv = np.unique(np.asarray(keys, dtype=str), return_inverse=True)
    return np.array([table.get(x, default) for x in u], dtype=object)[inv]


def calculate(acts, factors, supplier_factors):
    """acts: parallel arrays, one entry per activity line ("" where a field does not apply):
         kind ('ap' | 'freight' | 'utility'), category, country (the supplier's for invoices, the facility's for bills),
         supplier, amount_usd, tkm, mode, fuel, qty_norm
       factors: {factor_id: {'value', ...}} of one frozen version; supplier_factors: {"supplier|category": factor_id}, a
       disclosure's intensity applied to the lines in the category it covers (the supplier's main business with us).
       Returns (factor_id, method, scope, co2e_kg) arrays. Pure and deterministic: the same inputs give the same bytes."""
    kind = np.asarray(acts["kind"], dtype=str)
    cat = np.asarray(acts["category"], dtype=str)
    country = np.asarray(acts["country"], dtype=str)
    n = len(kind)
    ap, fr, ut = kind == "ap", kind == "freight", kind == "utility"
    covered = ap & np.isin(cat, list(world.COVERED))
    unmapped = ap & (cat == "")
    spend = ap & ~covered & ~unmapped
    reg = _lookup(country, {k: v[0] for k, v in world.COUNTRIES.items()})
    sup_f = _lookup(np.char.add(np.char.add(np.asarray(acts["supplier"], dtype=str), "|"), cat), supplier_factors)
    fid = np.full(n, "", dtype=object)
    fid[spend] = np.where(sup_f[spend] != "", sup_f[spend], "SPEND:" + cat[spend].astype(object) + ":" + reg[spend])
    fid[fr] = "FREIGHT:" + np.asarray(acts["mode"], dtype=object)[fr]
    fuel = np.asarray(acts["fuel"], dtype=object)
    fid[ut] = np.where(fuel[ut] == "electricity", "GRID:" + country[ut].astype(object), "FUEL:" + fuel[ut])
    method = np.full(n, "activity", dtype=object)
    method[unmapped], method[covered] = "unmapped", "covered"
    method[spend] = np.where(sup_f[spend] != "", "supplier-specific", "spend-based")
    scope = np.zeros(n, dtype=np.int16)
    scope[ap & ~unmapped] = _lookup(cat[ap & ~unmapped], {c: (3 if c == "freight" else v[1]) for c, v in world.CATEGORIES.items()}, 0).astype(np.int16)
    scope[fr] = 3
    scope[ut] = np.where(fuel[ut] == "electricity", 2, 1)
    qty = np.where(ap, np.asarray(acts["amount_usd"], float), np.where(fr, np.asarray(acts["tkm"], float), np.asarray(acts["qty_norm"], float)))
    value = _lookup(fid, {k: v["value"] for k, v in factors.items()}, 0.0).astype(float)
    if (missing := sorted({str(f) for f in np.unique(fid[(value == 0) & (fid != "")])})):
        raise KeyError(f"factors missing from this version: {missing[:5]}")
    kg = np.where(fid != "", qty * value, 0.0)
    return fid, method, scope, kg


def s3_category(category, kind):
    if kind == "freight":
        return 4
    if kind == "utility" or category is None:
        return None
    return world.CATEGORIES[category][2]


def result_hash(activity_id, fid, kg):
    """SHA-256 over every line in activity order: id, factor and CO2e to the micro-kilogram. Same version + same inputs -> same hash."""
    order = np.argsort(activity_id, kind="stable")
    h = hashlib.sha256()
    h.update(np.asarray(activity_id, np.int64)[order].tobytes())
    h.update("|".join(str(fid[i]) for i in order).encode())
    h.update(np.round(np.asarray(kg, float)[order], 6).tobytes())
    return h.hexdigest()


def monte_carlo(groups, factors, draws=DRAWS, seed=0, scenario=None):
    """groups: [{'factor_id', 'supplier', 'kg', 'buckets': [names it adds to]}] (lines summed per factor and supplier).
    One multiplier per factor (shared by every line using it) and, for spend-based factors, one per supplier around its
    sector mean (shared by that supplier's groups). `scenario`: a second kg per group evaluated on the same draws (paired). Returns per-bucket statistics."""
    rng = np.random.default_rng(seed)
    fids = sorted({g["factor_id"] for g in groups})
    fi = {f: n for n, f in enumerate(fids)}
    sig_f = np.array([np.log(factors[f]["gsd"]) for f in fids])
    FM = np.exp(rng.normal(-sig_f[:, None] ** 2 / 2, sig_f[:, None], (len(fids), draws)))
    sups = sorted({(g["supplier"], factors[g["factor_id"]]["dispersion"]) for g in groups if factors[g["factor_id"]]["dispersion"] > 0})
    si = {s: n + 1 for n, s in enumerate(sups)}                    # row 0: no supplier spread (activity data, supplier-specific factors)
    disp = np.array([0.0] + [d for _, d in sups])
    SMS = np.exp(rng.normal(-disp[:, None] ** 2 / 2, disp[:, None], (len(disp), draws)))
    SM = SMS[[si.get((g["supplier"], factors[g["factor_id"]]["dispersion"]), 0) for g in groups]]
    base = np.array([g["kg"] for g in groups])[:, None] * FM[[fi[g["factor_id"]] for g in groups]] * SM
    out = {}
    buckets = sorted({b for g in groups for b in g["buckets"]})
    for b in buckets:
        m = np.array([b in g["buckets"] for g in groups])
        out[b] = _stats(base[m].sum(0) / 1000, sum(g["kg"] for g, x in zip(groups, m) if x) / 1000)
        if scenario is not None:
            alt = (np.asarray(scenario)[m][:, None] * FM[[fi[g["factor_id"]] for g, x in zip(groups, m) if x]] * SM[m]).sum(0) / 1000
            out[b]["scenario"] = _stats(alt, float(np.asarray(scenario)[m].sum()) / 1000)
            out[b]["delta"] = _stats(alt - base[m].sum(0) / 1000, (float(np.asarray(scenario)[m].sum()) - sum(g["kg"] for g, x in zip(groups, m) if x)) / 1000)
    return out


def _stats(x, point):
    q = np.quantile(x, [0.025, 0.05, 0.5, 0.95, 0.975])
    return {"t": round(float(point), 1), "mean": round(float(x.mean()), 1), "p2_5": round(float(q[0]), 1), "p5": round(float(q[1]), 1),
            "p50": round(float(q[2]), 1), "p95": round(float(q[3]), 1), "p97_5": round(float(q[4]), 1)}


# --- supplier disclosures ---------------------------------------------------------------------------------------------------
SCALE = {"billion": 1e9, "bn": 1e9, "million": 1e6, "mn": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}
MASS = {"mtco2e": 1e6, "ktco2e": 1e3, "tco2e": 1.0}
CUR = "|".join(world.FX)
NUM = r"(\d[\d,]*\.?\d*)"


def _num(s):
    return float(s.replace(",", ""))


def _mass_on(line):
    m = re.search(NUM + r"\s*(mtco2e|ktco2e|tco2e)", line, re.I)
    if m:
        return _num(m[1]) * MASS[m[2].lower()], 1.0
    m = re.search(r"\|\s*" + NUM + r"\s*\|\s*(mtco2e|ktco2e|tco2e)", line, re.I)
    return (_num(m[1]) * MASS[m[2].lower()], 1.0) if m else (None, 0.0)


def extract(text):
    """A disclosure's text -> {'company', 'revenue', 'currency', 'revenue_usd', 'scope1_t', 'scope2_t', 'scope3_upstream_t',
    'assurance', 'principal_suppliers', 'confidence': {field: 0..1}}. Units and scale words are read, never assumed."""
    out = {"company": None, "revenue": None, "currency": None, "revenue_usd": None, "scope1_t": None, "scope2_t": None, "scope3_upstream_t": None,
           "assurance": None, "principal_suppliers": [], "confidence": {}}
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if lines:
        m = re.search(r"(?:company|unternehmen)[^:]*:\s*(.+)$", text, re.I | re.M)
        out["company"] = m[1].strip() if m else re.split(r"\s+-\s+|\s+—\s+", lines[0])[0].strip()
    for ln in lines:
        low = ln.lower()
        if re.search(r"revenue|umsatz", low) and out["revenue"] is None:
            cur = re.search(rf"\b({CUR})\b", ln)
            m = re.search(NUM + r"\s*(billion|bn|million|mn|thousand|m|k)?\b", ln.split(":", 1)[-1].split("|", 1)[-1], re.I)
            if m:
                scale = SCALE.get((m[2] or "").lower())
                if scale is None and re.search(r"\b(million|billion|thousand)\b", low):
                    scale = SCALE[re.search(r"\b(million|billion|thousand)\b", low)[1]]
                out["revenue"] = _num(m[1]) * (scale or 1.0)
                out["confidence"]["revenue"] = 1.0 if scale else 0.5
            if cur:
                out["currency"] = cur[1]
        elif re.search(r"scope[\s-]*1\b", low) and "scope 1 and" not in low:
            out["scope1_t"], out["confidence"]["scope1_t"] = _mass_on(ln)
        elif re.search(r"scope[\s-]*2\b", low):
            out["scope2_t"], out["confidence"]["scope2_t"] = _mass_on(ln)
        elif re.search(r"scope[\s-]*3", low) and re.search(r"cat\w*\.?\s*1\b|kategorie 1|upstream|purchased", low):
            out["scope3_upstream_t"], out["confidence"]["scope3_upstream_t"] = _mass_on(ln)
        elif re.search(r"assurance|verification", low):
            out["assurance"] = "reasonable" if "reasonable" in low else "limited" if "limited" in low else "none"
        elif low.startswith("principal material suppliers"):
            out["principal_suppliers"] = [x.strip() for x in ln.split(":", 1)[1].split(";") if x.strip()]
    if out["revenue"] is not None and out["currency"] in world.FX:
        out["revenue_usd"] = out["revenue"] * world.FX[out["currency"]]
    return out


def naive_extract(text):
    """The baseline: the first number on each keyword's line, taken as revenue in millions and emissions in tonnes."""
    out = {"revenue_usd": None, "scope1_t": None, "scope2_t": None, "scope3_upstream_t": None}
    cur = None
    for ln in text.splitlines():
        low = ln.lower()
        m = re.search(NUM, ln.split(":", 1)[-1])
        if not m:
            continue
        if ("revenue" in low or "umsatz" in low) and out["revenue_usd"] is None:
            c = re.search(rf"\b({CUR})\b", ln)
            cur = c[1] if c else "USD"
            out["revenue_usd"] = _num(m[1]) * 1e6 * world.FX[cur]
        elif re.search(r"scope[\s-]*1\b", low):
            out["scope1_t"] = _num(m[1])
        elif re.search(r"scope[\s-]*2\b", low):
            out["scope2_t"] = _num(m[1])
        elif re.search(r"scope[\s-]*3", low):
            out["scope3_upstream_t"] = _num(m[1])
    return out


INTENSITY_RANGE = (0.03, 5.0)       # kgCO2e per USD of revenue a manufacturer can plausibly have


def validate_disclosure(x):
    """-> (supplier-specific factor in kgCO2e/USD or None, reasons it was not accepted)."""
    why = [f"{f} not found" for f in ("revenue_usd", "scope1_t", "scope2_t") if x.get(f) is None]
    if x.get("scope3_upstream_t") is None:
        why.append("boundary incomplete: no scope 3 category 1 (upstream) figure, so a cradle-to-gate intensity cannot be formed")
    if why:
        return None, why
    v = (x["scope1_t"] + x["scope2_t"] + x["scope3_upstream_t"]) * 1000 / x["revenue_usd"]
    if not INTENSITY_RANGE[0] <= v <= INTENSITY_RANGE[1]:
        return None, [f"implausible intensity {v:.4g} kgCO2e/USD (expected {INTENSITY_RANGE[0]}-{INTENSITY_RANGE[1]}); check the units"]
    return v, []


def match_name(name, candidates_norm, X=None, vec=None, min_cos=0.55):
    """Best candidate index for a name by char n-gram cosine, or (None, score)."""
    if vec is None:
        vec = name_vectorizer().fit(candidates_norm)
        X = vec.transform(candidates_norm)
    q = vec.transform([norm_name(name)])
    s = (X @ q.T).toarray().ravel()
    j = int(s.argmax()) if len(s) else 0
    return (j if len(s) and s[j] >= min_cos else None), float(s[j]) if len(s) else 0.0


# --- the supplier network ---------------------------------------------------------------------------------------------------
DEFAULT_UPSTREAM_SHARE = 0.45       # share of a component maker's footprint embodied in its materials, when it lists its mills but not the split


def influence(emissions, edges, iters=30):
    """Emission-weighted Katz centrality: x = e + W^T x, where W[t, s] is the share of t's footprint bought from s.
    emissions: {supplier: tCO2e}; edges: {t: [s1, s2, ...]} in the order a disclosure lists them."""
    nodes = sorted(set(emissions) | set(edges) | {s for v in edges.values() for s in v}, key=str)
    ix = {n: i for i, n in enumerate(nodes)}
    e = np.array([emissions.get(n, 0.0) for n in nodes])
    rows, cols, vals = [], [], []
    for t, ups in edges.items():
        w = np.array([0.6, 0.4][:len(ups)] if len(ups) <= 2 else np.ones(len(ups)) / len(ups))
        w = w / w.sum() * DEFAULT_UPSTREAM_SHARE
        for s, x in zip(ups, w):
            rows.append(ix[t])
            cols.append(ix[s])
            vals.append(x)
    W = sparse.csr_matrix((vals, (rows, cols)), shape=(len(nodes), len(nodes)))
    x = e.copy()
    for _ in range(iters):
        x = e + W.T @ x
    return {n: float(x[ix[n]]) for n in nodes}


def covered_emissions(picked, emissions, upstream):
    """True emissions within reach of engaging `picked`: each picked supplier's own, plus the share of every other
    supplier's footprint that it sells them. upstream: {t: {s: share}} (the generator's truth in the evaluation)."""
    picked = set(picked)
    tot = sum(emissions.get(s, 0.0) for s in picked)
    for t, ups in upstream.items():
        if t not in picked:
            tot += emissions.get(t, 0.0) * sum(v for s, v in ups.items() if s in picked)
    return tot


# --- scenarios ---------------------------------------------------------------------------------------------------------------
OCEAN_KM_PER_DAY, PORT_DAYS, AIR_DAYS = 650.0, 7.0, 3.0


def scenario_kg(groups, factors, freight_shift=None, decarbonise=None, edges=None):
    """New kg per group under the scenario. groups carry: method, factor_id, supplier, kg, mode, lane (origin, destination),
    urgent, tonnes. freight_shift: {'from': 'air', 'to': 'ocean', 'share': 0..1, 'exclude_urgent': bool, 'intercontinental_only': bool}.
    decarbonise: {'suppliers': [...], 'reduction': 0..1}; their tier-1 customers' embodied share falls too (via edges).
    Returns (kg array, notes)."""
    new = np.array([g["kg"] for g in groups], float)
    notes = {}
    if freight_shift:
        to_v = factors[f"FREIGHT:{freight_shift['to']}"]["value"]
        moved_t, extra_days = 0.0, 0.0
        for n, g in enumerate(groups):
            if g.get("mode") != freight_shift["from"] or (freight_shift.get("exclude_urgent", True) and g.get("urgent")):
                continue
            ln = world.lane(*g["lane"])
            if freight_shift.get("intercontinental_only", True) and not ln["intercontinental"]:
                continue
            sh = freight_shift["share"]
            km_to = ln["sea_km"] if freight_shift["to"] == "ocean" else ln["road_km"]
            new[n] = g["kg"] * (1 - sh) + sh * g["tonnes"] * km_to * to_v
            moved_t += sh * g["tonnes"]
            extra_days += sh * g["tonnes"] * (ln["sea_km"] / OCEAN_KM_PER_DAY + PORT_DAYS - AIR_DAYS)
        notes["tonnes_shifted"] = round(moved_t, 1)
        notes["added_transit_days_per_tonne"] = round(extra_days / moved_t, 1) if moved_t else None
    if decarbonise:
        chosen, r = set(decarbonise["suppliers"]), decarbonise["reduction"]
        cut_upstream = {}
        for t, ups in (edges or {}).items():
            w = np.array([0.6, 0.4][:len(ups)] if len(ups) <= 2 else np.ones(len(ups)) / len(ups))
            w = w / w.sum() * DEFAULT_UPSTREAM_SHARE
            cut_upstream[t] = sum(x for s, x in zip(ups, w) if s in chosen) * r
        for n, g in enumerate(groups):
            if g.get("method") not in ("spend-based", "supplier-specific"):
                continue
            s = g.get("supplier")
            if s in chosen:
                new[n] *= 1 - r
            if s in cut_upstream:
                new[n] *= 1 - cut_upstream[s]
    return new, notes


def inputs_hash(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


# --- the activity normaliser --------------------------------------------------------------------------------------------------
def normalize_ap(lines, known_vendors, year):
    """AP lines (dict of parallel lists as an ERP extract delivers them) -> (kept indices, USD amounts, FX rates used,
    rejected [(index, code, reason)], duplicates dropped). A line is a duplicate when its (subsidiary, invoice, line) was seen."""
    keep, usd, rate, rejected, seen, dups = [], [], [], [], set(), 0
    for i, (sub, ven, inv, ln, per, amt, cur) in enumerate(zip(lines["subsidiary"], lines["vendor_ref"], lines["invoice"], lines["line"],
                                                                lines["period"], lines["amount"], lines["currency"])):
        key = (sub, inv, int(ln))
        if key in seen:
            dups += 1
            continue
        seen.add(key)
        c = currency(cur)
        if c is None:
            rejected.append((i, "unknown_currency", f"unknown currency '{cur}'"))
        elif ven not in known_vendors:
            rejected.append((i, "unknown_vendor", f"vendor {ven} is not in {sub}'s vendor master"))
        elif not str(per).startswith(str(year)):
            rejected.append((i, "outside_reporting_year", f"period {per} is outside the reporting year {year}"))
        else:
            r = world.fx(c, int(str(per)[5:7]))
            keep.append(i)
            usd.append(float(amt) * r)
            rate.append(r)
    return np.array(keep, dtype=np.int64), np.array(usd), np.array(rate), rejected, dups


def arrays_hash(*arrays):
    h = hashlib.sha256()
    for a in arrays:
        a = np.asarray(a)
        h.update(a.tobytes() if a.dtype.kind in "iufb" else "|".join(map(str, a)).encode())
    return h.hexdigest()[:16]


def s3_categories(kind, category):
    """GHG Protocol scope 3 category per line (0 when not scope 3): purchased goods 1, capital goods 2, transport 4, travel 6."""
    kind, category = np.asarray(kind, dtype=str), np.asarray(category, dtype=str)
    out = _lookup(category, {c: (v[2] or 0) for c, v in world.CATEGORIES.items()}, 0).astype(np.int16)
    out[kind == "freight"] = 4
    out[kind == "utility"] = 0
    return out


def mc_groups(fid, supplier, scope, s3c, cat, kg, factors):
    """Lines summed per (factor, supplier where the factor has a supplier spread, scope, scope-3 category, spend category):
    the inputs of `monte_carlo`. Buckets: total, scope N, s3:N, cat:<category>."""
    fid = np.asarray(fid, dtype=object)
    keep = (fid != "") & (np.asarray(kg) != 0)
    disp = _lookup(np.where(fid == "", "-", fid), {k: v["dispersion"] for k, v in factors.items()}, 0.0).astype(float)
    sup = np.where(disp > 0, np.asarray(supplier, dtype=object), "")
    cols = [fid[keep], sup[keep], np.asarray(scope)[keep], np.asarray(s3c)[keep], np.asarray(cat, dtype=object)[keep]]
    codes, uniq = [], []
    for col in cols:
        u, inv = np.unique(np.asarray(col).astype(str), return_inverse=True)
        codes.append(inv)
        uniq.append(u)
    key = codes[0].astype(np.int64)
    for cd, u in zip(codes[1:], uniq[1:]):
        key = key * len(u) + cd
    uk, ginv = np.unique(key, return_inverse=True)
    sums = np.bincount(ginv, weights=np.asarray(kg, float)[keep])
    first = np.zeros(len(uk), dtype=np.int64)
    first[ginv] = np.arange(len(ginv))
    out = []
    for g, i in enumerate(first):
        f, s, sc, s3, c = (uniq[k][codes[k][i]] for k in range(5))
        out.append({"factor_id": f, "supplier": s, "kg": float(sums[g]),
                    "buckets": ["total", f"scope{sc}"] + ([f"s3:{s3}"] if sc == "3" else []) + ([f"cat:{c}"] if c else [])})
    return out
