"""Everything the service computes, from what it stores (tokenised records, protocol text, site history), never from the
generator's truth.

    tokenise         an EHR record -> a token: hashed identifier, age band, distance band, events as days before the snapshot;
                     names, birth dates, dates and free text never get past this function
    parse            protocol text -> typed criteria DSL, by a deterministic grammar; a criterion it cannot account for word
                     by word goes to the review queue instead of being guessed. Baseline: a keyword spotter
    validate         deterministic checks on any rule (parsed or edited by a reviewer): known field, operator, unit, range, window
    evaluate         the temporal rules engine: each criterion true / false / unknown on a patient's timeline, with the evidence.
                     Baseline: the same rules without time (latest value ever, any therapy ever)
    enrolment model  Poisson rate per eligible patient-month (covariates + a gamma site frailty from its own history) times
                     the months a Weibull activation model expects the site to be open; predictive draws give intervals.
                     Baseline: the site's historical average per study
    dropout model    logistic regression on the enrollee's features and the site's past retention. Baseline: the base rate
    portfolio        a MILP (OR-Tools SCIP) choosing sites to maximise expected evaluable enrolment under a budget, region and
                     policy constraints. Baseline: top sites by historical enrolment, filled to the budget
"""
import hashlib
import json
import math
import re
import time

import numpy as np
from ortools.linear_solver import pywraplp
from scipy import optimize, special, stats
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

from . import world

PARSER_VERSION = "criteria-grammar-1"
ENGINE_VERSION = "temporal-rules-1"
ENROLMENT_VERSION = "poisson-gamma-weibull-1"
DROPOUT_VERSION = "dropout-logit-1"
ECOG_STALE_DAYS = 90                   # an ECOG older than this is not evidence of today's performance status
SMALL_CELL = 11                        # analytics exports suppress counts below this
DRAWS = 2000


def feature_hash(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True, default=str).encode()).hexdigest()[:16]


# --- de-identification at the door ------------------------------------------------------------------------------------------
def age_band(age):
    return "90+" if age >= 90 else f"{int(age) // 5 * 5}-{int(age) // 5 * 5 + 4}"


def distance_band(km):
    return "<10 km" if km < 10 else "10-30 km" if km < 30 else "30-80 km" if km < 80 else ">80 km"


def _days(date_s, index):
    import datetime
    return (datetime.date.fromisoformat(date_s) - index).days


def tokenise(record, salt, index=world.INDEX):
    """-> (token dict, problems). The token keeps a keyed hash of the MRN, an age band, sex, a distance band and every event
    as days relative to the snapshot. Labs are converted to canonical units. A problem drops the event, not the patient."""
    problems = []
    birth = __import__("datetime").date.fromisoformat(record["birth_date"])
    age = (index - birth).days / 365.25
    events = []
    for e in record["events"]:
        t = e.get("type")
        try:
            if t == "diagnosis":
                events.append({"type": t, "code": e["code"], "stage": e["stage"], "day": _days(e["date"], index)})
            elif t == "biomarker":
                events.append({"type": t, "name": e["name"], "value": e["value"], "day": _days(e["date"], index)})
            elif t == "medication":
                cls = world.DRUG_CLASS.get(e["drug"].lower())
                if not cls:
                    problems.append(f"unknown drug {e['drug']!r}")
                    continue
                events.append({"type": t, "drug": e["drug"].lower(), "class": cls, "line": int(e["line"]), "start": _days(e["start"], index),
                               "end": _days(e["end"], index) if e.get("end") else None})
            elif t == "lab":
                canon, alt, factor = world.LABS[e["name"]]
                if e["unit"] == canon:
                    v = float(e["value"])
                elif alt and e["unit"] == alt:
                    v = float(e["value"]) * factor
                else:
                    problems.append(f"{e['name']}: unit {e['unit']!r} not convertible to {canon}")
                    continue
                events.append({"type": t, "name": e["name"], "value": round(v, 3), "day": _days(e["date"], index)})
            elif t == "ecog":
                events.append({"type": t, "value": int(e["value"]), "day": _days(e["date"], index)})
            elif t == "condition":
                events.append({"type": t, "name": e["name"], "day": _days(e["date"], index)})
            else:
                problems.append(f"unknown event type {t!r}")
        except (KeyError, ValueError, TypeError) as x:
            problems.append(f"{t}: malformed ({type(x).__name__}: {x})")
    if any(ev.get("day", 0) > 0 or (ev.get("start") or 0) > 0 for ev in events):
        problems.append("events after the snapshot were dropped")
        events = [ev for ev in events if ev.get("day", 0) <= 0 and (ev.get("start") or 0) <= 0]
    token = hashlib.sha256(f"{salt}:{record['mrn']}".encode()).hexdigest()[:20]
    return {"token": token, "site": record["site"], "sex": record["sex"], "age_band": age_band(age),
            "distance_band": distance_band(float(record.get("home_distance_km") or 0)), "events": events}, problems


# --- the criteria DSL ---------------------------------------------------------------------------------------------------------
FIELDS = {
    "age": {"ops": {">=", "<=", ">", "<"}, "range": (12, 100)},
    "diagnosis": {}, "biomarker": {}, "lab": {}, "ecog": {"ops": {"<=", "<", ">=", "=="}, "range": (0, 4)},
    "therapy": {}, "prior_lines": {"ops": {"<=", ">=", "==", "<", ">"}, "range": (0, 10)}, "condition": {}, "manual": {}}
LAB_RANGE = {"ANC": (0.3, 5), "PLT": (20, 400), "HGB": (5, 15), "CRCL": (10, 150), "AST": (1, 10), "ALT": (1, 10), "TBIL": (1, 5)}
BIOMARKERS = {"PD-L1_TPS": "numeric", "EGFR": "categorical", "ALK": "categorical", "KRAS_G12C": "categorical", "HER2": "categorical",
              "ER": "categorical", "MSI-H": "categorical", "KRAS": "categorical", "BRAF": "categorical"}
THERAPY_CLASSES = set(world.DRUG_CLASS.values()) | {"any_systemic", "chemotherapy"}


def validate(rule):
    """Deterministic checks on one rule -> list of problems (empty when valid). Used on the parser's output and on every
    reviewer edit, so a unit slip (ANC >= 1500 x 10^9/L) cannot reach a patient."""
    p = []
    f = rule.get("field")
    if f not in FIELDS:
        return [f"unknown field {f!r}"]
    spec = FIELDS[f]
    if "ops" in spec and rule.get("op") not in spec["ops"]:
        p.append(f"{f}: operator must be one of {sorted(spec['ops'])}")
    if "range" in spec and not (isinstance(rule.get("value"), (int, float)) and spec["range"][0] <= rule["value"] <= spec["range"][1]):
        p.append(f"{f}: value must be a number in {spec['range']}")
    if f == "diagnosis":
        if rule.get("code") not in world.INDICATIONS:
            p.append(f"diagnosis: unknown code {rule.get('code')!r}")
        if not set(rule.get("stages") or []) <= set(world.STAGES):
            p.append("diagnosis: unknown stage")
    if f == "biomarker":
        kind = BIOMARKERS.get(rule.get("name"))
        if not kind:
            p.append(f"biomarker: unknown name {rule.get('name')!r}")
        elif kind == "numeric" and not (rule.get("op") in {">=", "<=", ">", "<"} and isinstance(rule.get("value"), (int, float)) and 0 <= rule["value"] <= 100):
            p.append("biomarker: PD-L1 TPS needs an operator and a percentage")
        elif kind == "categorical" and rule.get("value") not in ("positive", "negative"):
            p.append("biomarker: value must be positive or negative")
    if f == "lab":
        n = rule.get("name")
        if n not in LAB_RANGE:
            p.append(f"lab: unknown test {n!r}")
        else:
            if rule.get("unit") != world.LABS[n][0]:
                p.append(f"lab: {n} must be in {world.LABS[n][0]}")
            lo, hi = LAB_RANGE[n]
            if not (isinstance(rule.get("value"), (int, float)) and lo <= rule["value"] <= hi):
                p.append(f"lab: {n} threshold {rule.get('value')} outside the plausible range {lo}-{hi} {world.LABS[n][0]} (a unit slip?)")
            if rule.get("op") not in {">=", "<=", ">", "<"}:
                p.append("lab: operator must be >=, <=, > or <")
            if not rule.get("within_days"):
                p.append("lab: a lab criterion needs a time window")
    if f == "therapy" and (not rule.get("classes") or not set(rule["classes"]) <= THERAPY_CLASSES):
        p.append(f"therapy: classes must be from {sorted(THERAPY_CLASSES)}")
    if f == "condition" and rule.get("name") not in world.CONDITIONS:
        p.append(f"condition: unknown name {rule.get('name')!r}")
    w = rule.get("within_days")
    if w is not None and not (isinstance(w, int) and 1 <= w <= 3650):
        p.append("within_days must be a whole number of days from 1 to 3650")
    if f == "manual" and not rule.get("topic"):
        p.append("manual: needs a topic")
    return p


def _numeric(v):
    if isinstance(v, float):
        v = round(v, 4)
        return int(v) if v.is_integer() else v
    return v


def canonical(rules):
    """Rules in a comparable form (sorted keys and lists, floats rounded) for exact-match scoring."""
    out = []
    for r in rules:
        r = {k: (sorted(v) if isinstance(v, list) else _numeric(v)) for k, v in r.items() if v is not None}
        if r.get("field") == "manual":
            r = {"field": "manual"}
        out.append(json.dumps(r, sort_keys=True))
    return sorted(out)


# --- the parser ----------------------------------------------------------------------------------------------------------------
NUMWORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
CANCERS = [("non-small cell lung cancer", "NSCLC"), ("non-small-cell lung carcinoma", "NSCLC"), ("nsclc", "NSCLC"),
           ("small cell lung cancer", "SCLC"), ("sclc", "SCLC"), ("adenocarcinoma of the breast", "BREAST"), ("breast cancer", "BREAST"),
           ("adenocarcinoma of the colon or rectum", "CRC"), ("colorectal cancer", "CRC"), ("crc", "CRC"), ("cutaneous melanoma", "MELANOMA"), ("melanoma", "MELANOMA")]
LAB_WORDS = [("absolute neutrophil count", "ANC"), ("neutrophils", "ANC"), ("anc", "ANC"), ("platelet count", "PLT"), ("platelets", "PLT"),
             ("hemoglobin", "HGB"), ("hb", "HGB"), ("calculated creatinine clearance", "CRCL"), ("creatinine clearance", "CRCL"), ("crcl", "CRCL"),
             ("ast and alt", "AST+ALT"), ("total bilirubin", "TBIL"), ("bilirubin", "TBIL"), ("ast", "AST"), ("alt", "ALT")]
CMP = r"(>=|<=|at least|no less than|no more than|not exceeding)"
CMP_OP = {">=": ">=", "<=": "<=", "at least": ">=", "no less than": ">=", "no more than": "<=", "not exceeding": "<="}
NUM = r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
UNIT = r"(x 10\^9/l|/ul|/mm3|g/dl|g/l|ml/min|x uln|times the upper limit of normal)"
WINDOW = (r"(?:within|in) (?:the )?(?:past |last )?(\d+) (days?|weeks?|months?|years?)"
          r"(?: (?:prior to|before|of) (?:screening|enrollment|first dose|randomization))?|in the (\d+) (days?) before first dose")
THERAPY_WORDS = [("immune checkpoint inhibitor", ["anti-CTLA-4", "anti-PD-1", "anti-PD-L1"]), ("anti-pd-l1", ["anti-PD-L1"]), ("anti-pd-1", ["anti-PD-1"]),
                 ("anti-ctla-4", ["anti-CTLA-4"]), ("platinum-based chemotherapy", ["platinum"]), ("platinum-containing", ["platinum"]),
                 ("kras g12c inhibitor", ["KRAS-G12C-inhibitor"]), ("taxane", ["taxane"]), ("systemic anticancer therapy", ["any_systemic"]),
                 ("chemotherapy, targeted therapy or immunotherapy", ["any_systemic"])]
CONDITION_WORDS = [(r"(?:active|untreated|symptomatic)[\w\s()]*?(?:central nervous system|brain|cns)[\w\s()]*?metastases|brain metastases", "brain_metastases_active"),
                   (r"interstitial lung disease|pneumonitis", "interstitial_lung_disease"), (r"autoimmune disease", "autoimmune_disease"),
                   (r"hiv|human immunodeficiency virus", "hiv"), (r"hepatitis b or hepatitis c|hbv or hcv", "hepatitis_active"),
                   (r"(?:additional|another) malignancy", "second_malignancy")]
MANUAL_WORDS = [("informed consent", "informed consent"), ("life expectancy", "life expectancy"), ("expected survival", "life expectancy"),
                ("recist", "measurable disease (RECIST)"), ("pregnant", "pregnancy")]
FILLER = set("""a an the of to for or and in on by at as with any all is are be been has have had not no must that which this who
patients patient male female adults adult aged age years year old time signing written document understand able willing sign signed
prior previously received receive receiving treatment treated therapy therapies documented diagnosis confirmed histologically
cytologically amenable curative known history tumor tumors tissue blood harboring expression cells cell score proportion tps approved
validated assay determined by status positive high or greater ihc ish amplified 3+ disease mutation sensitizing rearrangement fusion
eastern cooperative oncology group ecog performance ps adequate bone marrow function liver required requiring systemic infection
active additional another malignancy diagnosed lines line advanced metastatic locally stage regimen antibody agent procedure study
progression after one documented least lung non-infectious central nervous system cns brain metastases untreated symptomatic nursing
breastfeeding women less than months weeks days expectancy opinion investigator under survival measurable lesion per v1.1 1.1
on unresectable extensive-stage informed consent""".split())


def _norm(t):
    t = t.lower().replace("≥", " >= ").replace("≤", " <= ").replace("×", " x ").replace("µ", "u").replace("³", "3")
    t = t.replace("–", "-").replace("—", "-").replace("haemoglobin", "hemoglobin").replace("harbouring", "harboring")
    t = re.sub(r"\s+", " ", t).strip().rstrip(".")
    return t


def _num(s):
    return float(s.replace(",", ""))


def _window(t):
    """-> (days or None, span or None). Months are 30.4 days, years 365."""
    m = re.search(WINDOW, t)
    if not m:
        return None, None
    n, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    n = int(n)
    days = n if unit.startswith("day") else 7 * n if unit.startswith("week") else round(30.4 * n) if unit.startswith("month") else 365 * n
    return days, m.span()


def _lab_value(name, value, unit):
    """-> value in the canonical unit, or None when the unit does not fit the test."""
    if name in ("ANC", "PLT"):
        return {"x 10^9/l": value, "/ul": value / 1000, "/mm3": value / 1000}.get(unit)
    if name == "HGB":
        return {"g/dl": value, "g/l": value / 10}.get(unit)
    if name == "CRCL":
        return value if unit == "ml/min" else None
    return value if unit in ("x uln", "times the upper limit of normal") else None


def parse_criterion(text, kind):
    """One criterion -> {'rules', 'status': parsed|manual|review, 'confidence', 'reasons'}. Deterministic and strict: every
    word must be explained by a recognised clause or be protocol boilerplate, otherwise the criterion goes to review."""
    t = _norm(text)
    spans, rules, reasons = [], [], []

    def take(span):
        spans.append(span)

    days, wspan = _window(t)
    if wspan:
        take(wspan)
    # labs: one or more "<test> <comparator> <number> <unit>" clauses sharing the window
    for m in re.finditer(r"(" + "|".join(re.escape(w) for w, _ in LAB_WORDS) + r")(?: \([\w\s-]+\))? " + CMP + " " + NUM + " ?" + UNIT, t):
        names = {"AST+ALT": ["AST", "ALT"]}.get(dict(LAB_WORDS)[m.group(1)], [dict(LAB_WORDS)[m.group(1)]])
        for n in names:
            v = _lab_value(n, _num(m.group(3)), m.group(4))
            if v is None:
                reasons.append(f"{n}: unit '{m.group(4)}' does not fit the test")
                continue
            rules.append({"field": "lab", "name": n, "op": CMP_OP[m.group(2)], "value": round(v, 4), "unit": world.LABS[n][0], "within_days": days})
        take(m.span())
    if not rules:
        for pat, fn in _CLAUSES:
            for m in re.finditer(pat, t):
                out = fn(m, t, kind, days)
                if out is not None:          # [] is a clause that only qualifies another (a stage list, "metastatic")
                    rules += out
                    take(m.span())
        # a recognised therapy or condition takes the window; the others must not have one left over
        for r in rules:
            if r["field"] in ("therapy", "condition", "ecog") and days is not None:
                r["within_days"] = days
    if not rules:
        for word, topic in MANUAL_WORDS:
            if word in t:
                return {"rules": [{"field": "manual", "topic": topic}], "status": "manual", "confidence": 1.0, "reasons": [f"no record can answer '{topic}': checked by the site at screening"]}
        return {"rules": [], "status": "review", "confidence": 0.0, "reasons": reasons + ["no recognised clause"]}
    rules = [json.loads(r) for r in dict.fromkeys(json.dumps(r, sort_keys=True) for r in rules)]      # one fact named twice is one rule
    # strictness: what is left must be boilerplate
    keep = list(t)
    for a, b in spans:
        keep[a:b] = " " * (b - a)
    rest = [w for w in re.findall(r"[a-z0-9.+\-/^]+", "".join(keep).replace(",", " ").replace(":", " ").replace("(", " ").replace(")", " ")) if w not in FILLER]
    if rest:
        reasons.append("unexplained words: " + " ".join(rest[:8]))
    if any(r["field"] == "diagnosis" and not r.get("stages") for r in rules) and "advanced" in t:
        reasons.append("'advanced' without a stage: which stages are meant?")
    if any(r["field"] in ("ecog", "therapy", "condition") for r in rules) and days is None and _window_words(t):
        reasons.append("a time window is mentioned but not understood")
    problems = [p for r in rules for p in validate(r)]
    reasons += problems
    if reasons:
        return {"rules": rules, "status": "review", "confidence": round(max(0.0, 0.5 - 0.1 * len(reasons)), 2), "reasons": reasons}
    return {"rules": rules, "status": "parsed", "confidence": 1.0, "reasons": []}


def _window_words(t):
    return bool(re.search(r"\b(within|since|recently|half|fortnight|past|last)\b", t))


def _age(m, t, kind, days):
    op = ">=" if (m.group(1) or "") in (">=", "at least") or "or older" in t or (m.group(1) or "").startswith(">=") else None
    return [{"field": "age", "op": op or ">=", "value": int(m.group(2))}] if op or "aged" in t else None


STAGE_RE = r"stage ((?:(?:iv|i{1,3})[abc]?)(?:(?:, | or |/|-| and )(?:stage )?(?:iv|i{1,3})[abc]?)*)\b"


def _stages(t):
    found = set()
    for g in re.finditer(STAGE_RE, t):
        parts = re.findall(r"(iv|i{1,3})([abc]?)|(-)", g.group(1))
        seq, dash = [], False
        for r, l, d in parts:
            if d:
                dash = True
                continue
            label = (r.upper() + l.upper())
            if dash and seq:
                lo, hi = world.STAGES.index(seq[-1]), world.STAGES.index(label if label in world.STAGES else "IV")
                seq += world.STAGES[lo + 1:hi + 1]
                dash = False
            else:
                seq.append(label)
        found |= {s for s in seq if s in world.STAGES}
    if not found:
        if "locally advanced" in t and "metastatic" in t:
            found = {"IIIB", "IIIC", "IV"}
        elif "metastatic" in t:
            found = {"IV"}
    return sorted(found, key=world.STAGES.index)


def _diagnosis(m, t, kind, days):
    code = dict(CANCERS)[m.group(0)]
    if code == "SCLC" and re.search(r"non-small", t):
        return None
    stages = _stages(t)
    return [{"field": "diagnosis", "code": code, **({"stages": stages} if stages else {})}]


def _pdl1(m, t, kind, days):
    op = {">=": ">=", "at least": ">=", "of": ">="}.get(m.group(1).strip()) if m.group(1) else None
    if "or greater" in t:
        op = ">="
    return [{"field": "biomarker", "name": "PD-L1_TPS", "op": op or ">=", "value": int(m.group(2))}] if op or "or greater" in t else None


def _categorical(name):
    return lambda m, t, kind, days: [{"field": "biomarker", "name": name, "value": "positive"}]


def _ecog(m, t, kind, days):
    hi = m.group(2) or m.group(3) or m.group(5)
    return [{"field": "ecog", "op": "<=", "value": int(hi)}]


def _lines(m, t, kind, days):
    g = m.group(0)
    if re.search(r"no prior systemic|treatment-naive|has not received prior systemic", g):
        return [{"field": "prior_lines", "op": "<=", "value": 0}]
    n = re.search(r"(\d+|one|two|three)", g)
    v = int(n.group(1)) if n.group(1).isdigit() else NUMWORDS[n.group(1)]
    if g.startswith("1 or 2"):
        return [{"field": "prior_lines", "op": ">=", "value": 1}, {"field": "prior_lines", "op": "<=", "value": 2}]
    if re.match(r"(no more than|at most)", g):
        return [{"field": "prior_lines", "op": "<=", "value": v}]
    return [{"field": "prior_lines", "op": ">=", "value": v}]


def _therapy(m, t, kind, days):
    classes = set()
    for w, cls in THERAPY_WORDS:
        if w in m.group(0):
            classes |= set(cls)
    return [{"field": "therapy", "classes": sorted(classes)}] if classes else None


def _condition(name):
    return lambda m, t, kind, days: [{"field": "condition", "name": name}]


_CLAUSES = [
    (r"(?:age|aged|adults)? ?(>=|at least)? ?(\d+) years(?: of age| old| or older)?", _age),
    ("|".join(re.escape(w) for w, _ in CANCERS), lambda m, t, k, d: _diagnosis(m, t, k, d)),
    (STAGE_RE + r"|locally advanced|metastatic|not amenable to curative therapy", lambda m, t, k, d: []),
    (r"pd-l1 (?:tumor proportion score \(tps\)|expression on|expression)?[\w\s(]*?(>=|at least|of)? ?(\d+)%(?: of tumor cells)?(?: or greater)?(?: \(tps >= \d+%\))?", _pdl1),
    (r"pd-l1-positive tumor \(tps >= (\d+)%\)", lambda m, t, k, d: [{"field": "biomarker", "name": "PD-L1_TPS", "op": ">=", "value": int(m.group(1))}]),
    (r"kras g12c mutation", _categorical("KRAS_G12C")), (r"her2-positive", _categorical("HER2")),
    (r"microsatellite instability-high \(msi-h\)|msi-h status", _categorical("MSI-H")),
    (r"egfr (?:sensitizing )?mutation", _categorical("EGFR")), (r"alk (?:rearrangement|fusion)", _categorical("ALK")),
    (r"(?:ecog|eastern cooperative oncology group \(ecog\)) (?:performance status|ps)(?: of)? (?:(0) or (1)|<= (\d)|(0)-(\d))", _ecog),
    (r"no prior systemic therapy for advanced or metastatic disease|treatment-naive for advanced disease|has not received prior systemic treatment for metastatic disease"
     r"|(?:no more than|at most) (?:\d+|two|three) prior lines? of systemic therapy(?: for advanced disease)?|1 or 2 prior lines of systemic therapy"
     r"|(?:at least one|>= 1) prior lines? of systemic therapy(?: for advanced disease)?|received >= 1 prior line of systemic therapy", _lines),
    (r"(?:anti-pd-1|anti-pd-l1|anti-ctla-4)(?:, | or )?(?:anti-pd-l1|anti-ctla-4)?(?:,? or anti-ctla-4)?(?: antibody| therapy)?|immune checkpoint inhibitor"
     r"|platinum-based chemotherapy(?: regimen)?|platinum-containing regimen|kras g12c inhibitor|a taxane(?: \(paclitaxel or docetaxel\))?"
     r"|systemic anticancer therapy|chemotherapy, targeted therapy or immunotherapy", _therapy),
] + [(pat, _condition(name)) for pat, name in CONDITION_WORDS]


def split_protocol(text):
    """Protocol text -> [(ref, type, criterion text)] from the numbered lists under the inclusion and exclusion headings."""
    out, kind = [], None
    for line in text.splitlines():
        s = line.strip()
        low = s.lower()
        if re.match(r"^[\d.]*\s*inclusion criteria", low):
            kind = "inclusion"
            continue
        if re.match(r"^[\d.]*\s*exclusion criteria", low):
            kind = "exclusion"
            continue
        m = re.match(r"^(\d+)[.)]\s+(.*)", s)
        if kind and m:
            out.append((f"{'I' if kind == 'inclusion' else 'E'}{m.group(1)}", kind, m.group(2)))
        elif kind and out and s and not low.startswith("patients"):
            ref, k, txt = out[-1]
            out[-1] = (ref, k, txt + " " + s)                 # a wrapped line continues the criterion above
    return out


def parse(text):
    return [{"ref": ref, "type": kind, "text": txt, **parse_criterion(txt, kind)} for ref, kind, txt in split_protocol(text)]


def parse_keywords(text):
    """Baseline: a keyword spotter. The first known keyword names the field, the first number is the threshold, >= is assumed;
    no units, no windows, no lists."""
    out = []
    for ref, kind, txt in split_protocol(text):
        t = _norm(txt)
        num = re.search(r"\d+(?:\.\d+)?", t)
        v = float(num.group(0)) if num else None
        rule = None
        for w, name in LAB_WORDS:
            if re.search(r"\b" + re.escape(w) + r"\b", t):
                rule = {"field": "lab", "name": name.split("+")[0], "op": ">=", "value": v, "unit": world.LABS[name.split("+")[0]][0]}
                break
        if rule is None:
            for w, topic in MANUAL_WORDS:
                if w in t:
                    rule = {"field": "manual", "topic": topic}
        if rule is None:
            for w, code in CANCERS:
                if w in t:
                    rule = {"field": "diagnosis", "code": code}
                    break
        if rule is None and "ecog" in t:
            rule = {"field": "ecog", "op": "<=", "value": v}
        if rule is None and "pd-l1" in t:
            rule = {"field": "biomarker", "name": "PD-L1_TPS", "op": ">=", "value": v}
        if rule is None and re.search(r"\byears\b", t):
            rule = {"field": "age", "op": ">=", "value": v}
        if rule is None:
            for w, cls in THERAPY_WORDS:
                if w in t:
                    rule = {"field": "therapy", "classes": cls}
                    break
        if rule is None:
            for pat, name in CONDITION_WORDS:
                if re.search(pat, t):
                    rule = {"field": "condition", "name": name}
                    break
        out.append({"ref": ref, "type": kind, "text": txt, "rules": [rule] if rule else [], "status": "parsed" if rule else "review"})
    return out


def score_parse(parsed, truth):
    """Exact-criterion accuracy against the generator's structured truth."""
    by = {c["ref"]: c for c in truth}
    n = len(truth)
    exact = sum(canonical(p["rules"]) == canonical(by[p["ref"]]["rules"]) and p["status"] != "review" for p in parsed if p["ref"] in by)
    wrong = sum(canonical(p["rules"]) != canonical(by[p["ref"]]["rules"]) and p["status"] != "review" for p in parsed if p["ref"] in by)
    review = sum(p["status"] == "review" for p in parsed)
    return {"criteria": n, "exact": exact, "exact_rate": round(exact / n, 4), "review": review, "confidently_wrong": wrong,
            "wrong_refs": [p["ref"] for p in parsed if p["ref"] in by and p["status"] != "review" and canonical(p["rules"]) != canonical(by[p["ref"]]["rules"])]}


# --- the temporal rules engine ----------------------------------------------------------------------------------------------------
def index_timeline(tok):
    ix = {"labs": {}, "ecog": [], "biomarkers": {}, "meds": [], "conditions": {}, "diagnosis": None}
    for e in tok["events"]:
        t = e["type"]
        if t == "lab":
            ix["labs"].setdefault(e["name"], []).append(e)
        elif t == "ecog":
            ix["ecog"].append(e)
        elif t == "biomarker":
            if e["name"] not in ix["biomarkers"] or e["day"] >= ix["biomarkers"][e["name"]]["day"]:
                ix["biomarkers"][e["name"]] = e
        elif t == "medication":
            ix["meds"].append(e)
        elif t == "condition":
            if e["name"] not in ix["conditions"] or e["day"] > ix["conditions"][e["name"]]:
                ix["conditions"][e["name"]] = e["day"]
        elif t == "diagnosis":
            if ix["diagnosis"] is None or e["day"] >= ix["diagnosis"]["day"]:
                ix["diagnosis"] = e
    for v in ix["labs"].values():
        v.sort(key=lambda e: -e["day"])
    ix["ecog"].sort(key=lambda e: -e["day"])
    ix["age_band"], ix["lines"] = tok["age_band"], sorted({m["line"] for m in ix["meds"]})
    return ix


def _cmpv(a, op, b):
    return world._cmp(a, op, b)


def _class_match(m, classes):
    return m["class"] in classes or "any_systemic" in classes or ("chemotherapy" in classes and m["class"] in world.CHEMO)


def eval_rule(rule, ix, temporal=True):
    """-> (True | False | None, evidence). None means the record cannot answer (not measured in the window, never tested)."""
    f = rule["field"]
    if f == "age":
        lo, hi = (90, 120) if ix["age_band"] == "90+" else map(int, ix["age_band"].split("-"))
        yes, no = (lo >= rule["value"], hi < rule["value"]) if rule["op"] in (">=", ">") else (hi <= rule["value"], lo > rule["value"])
        return (True if yes else False if no else None), {"age_band": ix["age_band"]}
    if f == "diagnosis":
        d = ix["diagnosis"]
        if not d:
            return False, {"diagnosis": None}
        ok = d["code"] == rule["code"] and (not rule.get("stages") or d["stage"] in rule["stages"])
        return ok, {"code": d["code"], "stage": d["stage"], "day": d["day"]}
    if f == "biomarker":
        b = ix["biomarkers"].get(rule["name"])
        if not b:
            return None, {"why": f"{rule['name']} never tested"}
        ok = _cmpv(b["value"], rule["op"], rule["value"]) if "op" in rule else b["value"] == rule["value"]
        return ok, {"value": b["value"], "day": b["day"]}
    if f == "lab":
        series = ix["labs"].get(rule["name"], [])
        w = rule["within_days"]
        inside = [e for e in series if e["day"] >= -w] if temporal else series
        if not inside:
            last = series[0] if series else None
            return None, {"why": f"no {rule['name']} in the last {w} days" + (f" (last on day {last['day']})" if last else " (never measured)")}
        e = inside[0]
        return _cmpv(e["value"], rule["op"], rule["value"]), {"value": e["value"], "unit": rule["unit"], "day": e["day"], "window_days": w if temporal else None}
    if f == "ecog":
        w = rule.get("within_days") or ECOG_STALE_DAYS
        inside = [e for e in ix["ecog"] if e["day"] >= -w] if temporal else ix["ecog"]
        if not inside:
            return None, {"why": f"no ECOG in the last {w} days" + (f" (last on day {ix['ecog'][0]['day']})" if ix["ecog"] else "")}
        return _cmpv(inside[0]["value"], rule["op"], rule["value"]), {"value": inside[0]["value"], "day": inside[0]["day"], "window_days": w if temporal else None}
    if f == "therapy":
        w = rule.get("within_days")
        hits = [m for m in ix["meds"] if _class_match(m, rule["classes"]) and (not temporal or w is None or m["end"] is None or m["end"] >= -w)]
        ev = [{"drug": m["drug"], "class": m["class"], "line": m["line"], "start": m["start"], "end": m["end"]} for m in hits]
        return bool(hits), {"regimens": ev[:4], "window_days": w if temporal else None}
    if f == "prior_lines":
        return _cmpv(len(ix["lines"]), rule["op"], rule["value"]), {"lines": len(ix["lines"])}
    if f == "condition":
        d = ix["conditions"].get(rule["name"])
        w = rule.get("within_days")
        ok = d is not None and (not temporal or w is None or d >= -w)
        return ok, {"day": d, "window_days": w if temporal else None}
    raise ValueError(f)


def evaluate(criteria, ix, temporal=True, explain=False):
    """-> {'status': eligible | potential | ineligible, 'values': {ref: 1/0/None}, 'failed': [...], 'unknown': [...]} where 1 means
    the criterion is satisfied (an exclusion that does not apply). Manual criteria are left to the site."""
    values, failed, unknown, trace = {}, [], [], []
    for c in criteria:
        rules = [r for r in c["rules"] if r["field"] != "manual"]
        if not rules:
            continue
        res = [eval_rule(r, ix, temporal) for r in rules]
        vals = [v for v, _ in res]
        if c["type"] == "inclusion":
            v = 0 if False in vals else 1 if all(x is True for x in vals) else None
        else:
            v = 0 if True in vals else 1 if all(x is False for x in vals) else None
        values[c["ref"]] = v
        (failed if v == 0 else unknown if v is None else []).append(c["ref"])
        if explain:
            trace.append({"ref": c["ref"], "type": c["type"], "text": c["text"], "satisfied": v,
                          "rules": [{"rule": r, "value": x, "evidence": e} for r, (x, e) in zip(rules, res)]})
    status = "ineligible" if failed else "potential" if unknown else "eligible"
    out = {"status": status, "values": values, "failed": failed, "unknown": unknown}
    if explain:
        out["trace"] = trace
    return out


def pass_rates(results, criteria, strata=None):
    """P(criterion satisfied | the record can answer it), among patients with the study's diagnosis, by stratum (on treatment
    or not: labs are measured far more often during treatment, and treatment moves them, so missing is not missing at random)."""
    strata = strata or [0] * len(results)
    diag = next((c["ref"] for c in criteria if any(r["field"] == "diagnosis" for r in c["rules"])), None)
    refs = set(results[0]["values"]) if results else set()
    acc = {}
    for r, g in zip(results, strata):
        if diag and r["values"].get(diag) != 1:
            continue
        for ref in refs:
            v = r["values"].get(ref)
            if v is not None:
                a = acc.setdefault((ref, g), [0, 0])
                a[0] += v
                a[1] += 1
    return {k: (a + 1) / (n + 2) for k, (a, n) in acc.items()}


def expected_eligible(r, rates, stratum=0):
    """1 for an eligible patient, 0 for an ineligible one, and for a potential one the chance its unknowns pass."""
    if r["status"] == "eligible":
        return 1.0
    if r["status"] == "ineligible":
        return 0.0
    return float(np.prod([rates.get((u, stratum), 0.5) for u in r["unknown"]]))


def on_treatment(ix):
    return any(m["end"] is None or m["end"] >= -35 for m in ix["meds"])


def funnel(results, criteria):
    """Sequential attrition in protocol order: patients still in after each criterion (unknowns stay in)."""
    alive = list(range(len(results)))
    steps = [{"ref": "records", "text": "Tokenised records", "remaining": len(alive)}]
    for c in criteria:
        if not any(c["ref"] in r["values"] for r in results[:1]):
            continue
        alive = [i for i in alive if results[i]["values"][c["ref"]] != 0]
        unknown = sum(results[i]["values"][c["ref"]] is None for i in alive)
        steps.append({"ref": c["ref"], "type": c["type"], "text": c["text"], "remaining": len(alive), "unknown_here": unknown})
    return steps


# --- enrolment: rate (Poisson-gamma) x open months (Weibull activation) --------------------------------------------------------------
def _x(kind, competing, pi_trials):
    return np.array([1.0, kind == "academic", competing, math.log1p(pi_trials)], float)


def fit_enrolment(history, sites, investigators):
    """history rows: site, indication, pool_estimate, months_enrolling, enrolled, activation_months (None = never opened),
    lead_investigator. Returns the fitted model (plain dicts and arrays, JSON-safe)."""
    site_by = {s["id"]: s for s in sites}
    pi_by = {p["id"]: p for p in investigators}
    rows = [h for h in history if h["months_enrolling"] > 0]
    X = np.array([_x(site_by[h["site"]]["kind"], h["competing_trials"], pi_by[h["lead_investigator"]]["trials_by_indication"][h["indication"]]) for h in rows])
    off = np.log(np.array([h["pool_estimate"] * h["months_enrolling"] for h in rows], float))
    y = np.array([h["enrolled"] for h in rows], float)

    capped = np.array([h["enrolled"] >= site_by[h["site"]]["capacity"] for h in rows])

    def nll(p):             # negative binomial (gamma site frailty, shape a); a study that filled the site's slots is right-censored
        b, a = p[:4], math.exp(p[4])
        mu = np.exp(X @ b + off)
        q = a / (a + mu)
        return -float(np.sum(stats.nbinom.logpmf(y[~capped], a, q[~capped])) + np.sum(stats.nbinom.logsf(y[capped] - 1, a, q[capped])))
    start = np.array([math.log(max(y.sum(), 1) / np.exp(off).sum()), 0, 0, 0, 0.5])
    fit = optimize.minimize(nll, start, method="BFGS")
    beta, alpha = fit.x[:4], float(math.exp(fit.x[4]))
    cov = _covariance(nll, fit.x)[:4, :4]          # parameter uncertainty, shared by every site in a prediction
    mu = np.exp(X @ beta + off)
    y_post = y.copy()
    for i in np.nonzero(capped)[0]:        # a capped study tells the site's posterior what it would have enrolled, given at least the cap
        ks = np.arange(int(y[i]), int(y[i]) + 400)
        w = stats.nbinom.pmf(ks, alpha, alpha / (alpha + mu[i]))
        y_post[i] = float((ks * w).sum() / max(w.sum(), 1e-300))
    groups = {}
    for h, yy, m in zip(rows, y_post, mu):
        g = groups.setdefault(h["site"], [0.0, 0.0])
        g[0] += yy
        g[1] += m
    # activation: Weibull with a scale by site type, then each site's own contracting history shrinks its scale
    T = np.array([max(0.05, h["activation_months"]) if h["activation_months"] is not None else world.HORIZON for h in history], float)
    E = np.array([h["activation_months"] is not None for h in history], float)
    Z = np.array([[1.0, site_by[h["site"]]["kind"] == "academic"] for h in history])

    def wnll(p):
        k, g = math.exp(p[0]), p[1:]
        lam = np.exp(Z @ g)
        z = (T / lam) ** k
        return -float(np.sum(E * (math.log(k) - np.log(lam) + (k - 1) * (np.log(T) - np.log(lam))) - z))
    p = optimize.minimize(wnll, np.array([0.3, 1.0, 0.3]), method="Nelder-Mead", options={"maxiter": 4000, "xatol": 1e-6, "fatol": 1e-8}).x
    k, gamma = math.exp(p[0]), p[1:]
    by_site = {}
    for h, t, e, z in zip(history, T, E, Z):
        by_site.setdefault(h["site"], []).append((t, e, float(np.exp(z @ gamma))))
    offsets = {}
    for sid, obs in by_site.items():
        def snll(u, obs=obs):
            s = 0.0
            for t, e, lam in obs:
                lam = lam * math.exp(u)
                s -= e * (math.log(k) - math.log(lam) + (k - 1) * (math.log(t) - math.log(lam))) - (t / lam) ** k
            return s + u * u / (2 * 0.5 ** 2)               # prior: a site's contracting speed varies about 50% around its type
        offsets[sid] = round(float(optimize.minimize_scalar(snll, bounds=(-2, 2.5), method="bounded").x), 4)
    beta_draws = np.random.default_rng(42).multivariate_normal(beta, cov, DRAWS)
    return {"version": ENROLMENT_VERSION, "beta": [round(float(b), 5) for b in beta], "beta_se": [round(float(x), 5) for x in np.sqrt(np.diag(cov))],
            "beta_draws": beta_draws, "beta_names": ["intercept", "academic", "competing_trials", "log1p_pi_trials_in_indication"],
            "alpha": round(alpha, 4), "frailty": {s: [round(alpha + Y, 4), round(alpha + M, 4)] for s, (Y, M) in groups.items()},
            "weibull_k": round(k, 4), "weibull_gamma": [round(float(g), 5) for g in gamma], "activation_offset": offsets,
            "history_mean": {s: round(float(np.mean(v)) if (v := [h["enrolled"] for h in history if h["site"] == s]) else float(np.mean([h["enrolled"] for h in history])), 3) for s in site_by},
            "studies": len(history)}


def _covariance(f, x, h=1e-3):
    """Inverse of the negative log-likelihood's Hessian by central differences (the parameters' approximate covariance)."""
    n = len(x)
    H = np.zeros((n, n))
    for i in range(n):
        for j in range(i, n):
            e_i, e_j = np.eye(n)[i] * h, np.eye(n)[j] * h
            H[i, j] = H[j, i] = (f(x + e_i + e_j) - f(x + e_i - e_j) - f(x - e_i + e_j) + f(x - e_i - e_j)) / (4 * h * h)
    try:
        cov = np.linalg.inv(H)
        return cov if np.all(np.diag(cov) > 0) else np.diag(np.full(n, 1e-6))
    except np.linalg.LinAlgError:
        return np.diag(np.full(n, 1e-6))


def predict_site(model, site, pi_trials, pool, horizon=world.HORIZON, rng=None, draws=DRAWS, pool_weights=None):
    """Predictive draws of enrolment at one site for a study with `pool` expected eligible records. With `pool_weights`
    (1 for an eligible patient, the pass chance for a potential one) the pool itself is drawn. The rate coefficients are
    drawn from their fitted uncertainty with draws shared across sites, so a portfolio's total carries it. -> summary + draws."""
    rng = rng if rng is not None else np.random.default_rng(0)
    a, b = model["frailty"].get(site["id"], [model["alpha"], model["alpha"]])
    x = _x(site["kind"], site["competing_trials"], pi_trials)
    rate = math.exp(float(x @ np.array(model["beta"])))
    bd = model.get("beta_draws")
    rates = np.exp(bd[:draws] @ x) if bd is not None and len(bd) >= draws else np.full(draws, rate)
    if pool_weights is not None and len(pool_weights):
        w = np.asarray(pool_weights, float)
        pools = (rng.random((draws, len(w))) < w).sum(1).astype(float)
    else:
        pools = np.full(draws, max(pool, 0.0))
    scale = math.exp(model["weibull_gamma"][0] + model["weibull_gamma"][1] * (site["kind"] == "academic") + model["activation_offset"].get(site["id"], 0.0))
    act = scale * rng.weibull(model["weibull_k"], draws)
    open_months = np.clip(horizon - act, 0, horizon)
    theta = rng.gamma(a, 1 / b, draws)
    n = np.minimum(rng.poisson(theta * rates * pools * open_months), site["capacity"])
    return {"mean": round(float(n.mean()), 3), "p10": int(np.quantile(n, 0.1)), "p90": int(np.quantile(n, 0.9)),
            "activation_median_months": round(float(np.median(act)), 2), "p_open_by_month_3": round(float((act < 3).mean()), 3),
            "p_never_opens": round(float((act >= horizon).mean()), 3), "rate_per_eligible_month": round(rate * a / b, 4),
            "site_frailty": round(a / b, 3)}, n


# --- dropout ----------------------------------------------------------------------------------------------------------------------------
DROPOUT_FEATURES = ["ecog>=1", "ecog>=2", "age>=75", "distance 30-80 km", "distance >80 km", "prior_lines", "comorbidities", "site_past_dropout"]


def dropout_x(f, site_rate):
    band = f["distance_band"]
    return [f["ecog"] >= 1, f["ecog"] >= 2, f["age_band"] >= "75" and f["age_band"] != "90+" or f["age_band"] == "90+", band == "30-80 km",
            band == ">80 km", min(f["prior_lines"], 4), min(f["comorbidities"], 3), site_rate]


def enrollee_features(e):
    """Generator enrollee -> what the service stores about an enrolled patient (banded)."""
    return {"age_band": age_band(e["age"]), "ecog": int(e["ecog"]), "distance_band": distance_band(e["distance_km"]),
            "prior_lines": int(e["prior_lines"]), "comorbidities": int(e["comorbidities"])}


def site_dropout_rates(rows, exclude_study=None, a=10.0):
    """Each site's past dropout, shrunk toward the network rate (a pseudo-enrollees), optionally leaving one study out."""
    base = np.mean([r["dropped"] for r in rows]) if rows else 0.15
    acc = {}
    for r in rows:
        if r["study_ref"] == exclude_study:
            continue
        s = acc.setdefault(r["site"], [0, 0])
        s[0] += r["dropped"]
        s[1] += 1
    return {k: (d + a * base) / (n + a) for k, (d, n) in acc.items()}, float(base)


def fit_dropout(rows):
    """rows: enrollees of past studies {site, study_ref, features, dropped}. Site rates are leave-own-study-out."""
    base = float(np.mean([r["dropped"] for r in rows]))
    site_tot, study_tot = {}, {}
    for r in rows:
        a = site_tot.setdefault(r["site"], [0, 0])
        b = study_tot.setdefault((r["site"], r["study_ref"]), [0, 0])
        a[0] += r["dropped"]
        a[1] += 1
        b[0] += r["dropped"]
        b[1] += 1
    X, y = [], []
    for r in rows:
        (d, n), (d1, n1) = site_tot[r["site"]], study_tot[(r["site"], r["study_ref"])]
        X.append(dropout_x(r["features"], (d - d1 + 10 * base) / (n - n1 + 10)))
        y.append(r["dropped"])
    m = LogisticRegression(C=1.0, max_iter=500).fit(np.array(X, float), np.array(y))
    rates, base = site_dropout_rates(rows)
    return {"model": m, "site_rates": rates, "base_rate": base}


def dropout_risk(dm, features, site_id):
    x = dropout_x(features, dm["site_rates"].get(site_id, dm["base_rate"]))
    return float(dm["model"].predict_proba(np.array([x], float))[0, 1])


def score_dropout(dm, rows):
    p = np.array([dropout_risk(dm, r["features"], r["site"]) for r in rows])
    y = np.array([r["dropped"] for r in rows])
    base = np.full(len(y), dm["base_rate"])
    return {"auc": round(float(roc_auc_score(y, p)), 3) if 0 < y.sum() < len(y) else None, "brier": round(float(brier_score_loss(y, p)), 4),
            "base_rate_brier": round(float(brier_score_loss(y, base)), 4), "observed_rate": round(float(y.mean()), 3),
            "mean_predicted": round(float(p.mean()), 3), "enrollees": int(len(y))}


# --- investigator intelligence ------------------------------------------------------------------------------------------------------
def investigator_profile(pi, indication, history):
    led = [h for h in history if h["lead_investigator"] == pi["id"]]
    led_ind = [h for h in led if h["indication"] == indication]
    return {"id": pi["id"], "name": pi["name"], "specialty": pi["specialty"], "trials_total": sum(pi["trials_by_indication"].values()),
            "trials_in_indication": pi["trials_by_indication"][indication], "publications_in_indication": pi["publications_by_indication"][indication],
            "led_studies": len(led), "led_in_indication": len(led_ind),
            "mean_enrolled_when_leading": round(float(np.mean([h["enrolled"] for h in led])), 1) if led else None,
            "open_gcp_finding": pi["open_gcp_finding"]}


# --- portfolio ------------------------------------------------------------------------------------------------------------------------
def optimise(cands, n_sites=20, budget=None, max_per_region=None, min_academic=0, time_limit_s=110):
    """cands: [{id, region, kind, evaluable, enrolled, activation_cost, per_patient_cost, excluded}] -> plan.
    Maximise expected evaluable enrolment with exactly n_sites sites; cost = activation + per-patient fee x expected enrolment."""
    t0 = time.perf_counter()
    solver = pywraplp.Solver.CreateSolver("SCIP")
    solver.SetTimeLimit(int(time_limit_s * 1000))
    x = {c["id"]: solver.BoolVar(c["id"]) for c in cands if not c.get("excluded")}
    ok = [c for c in cands if c["id"] in x]
    solver.Add(sum(x.values()) == min(n_sites, len(ok)))
    if budget:
        solver.Add(sum(cost(c) * x[c["id"]] for c in ok) <= budget)
    if max_per_region:
        for reg in {c["region"] for c in ok}:
            solver.Add(sum(x[c["id"]] for c in ok if c["region"] == reg) <= max_per_region)
    if min_academic:
        solver.Add(sum(x[c["id"]] for c in ok if c["kind"] == "academic") >= min_academic)
    solver.Maximize(sum(c["evaluable"] * x[c["id"]] for c in ok))
    status = solver.Solve()
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return {"status": "infeasible", "sites": [], "solve_ms": round(1000 * (time.perf_counter() - t0), 1)}
    chosen = [c["id"] for c in ok if x[c["id"]].solution_value() > 0.5]
    return {"status": "optimal" if status == pywraplp.Solver.OPTIMAL else "feasible", "sites": chosen,
            "solve_ms": round(1000 * (time.perf_counter() - t0), 1), "candidates": len(cands), "eligible_candidates": len(ok),
            **totals(cands, chosen)}


def cost(c):
    return c["activation_cost"] + c["per_patient_cost"] * c["enrolled"]


def totals(cands, chosen):
    by = {c["id"]: c for c in cands}
    return {"expected_evaluable": round(sum(by[s]["evaluable"] for s in chosen), 1), "expected_enrolled": round(sum(by[s]["enrolled"] for s in chosen), 1),
            "expected_cost": round(sum(cost(by[s]) for s in chosen)), "regions": {r: sum(by[s]["region"] == r for s in chosen) for r in sorted({by[s]["region"] for s in chosen})},
            "academic": sum(by[s]["kind"] == "academic" for s in chosen)}


def greedy(cands, key, n_sites=20, budget=None, cost_of=cost):
    """Take sites in order of `key` (highest first), skipping any that would break the budget, until n_sites."""
    chosen, spent = [], 0.0
    for c in sorted((c for c in cands if not c.get("excluded")), key=lambda c: -key(c)):
        if len(chosen) == n_sites:
            break
        if budget and spent + cost_of(c) > budget:
            continue
        chosen.append(c["id"])
        spent += cost_of(c)
    return chosen


def greedy_ratio(cands, n_sites=20, budget=None):
    """Baseline with the same predictions: sites by expected evaluable enrolment per dollar, filled to the budget."""
    return greedy(cands, lambda c: c["evaluable"] / cost(c), n_sites, budget)


# --- one study end to end (shared by the API's jobs and the evaluation) ------------------------------------------------------------
def candidate_features(tok, ix):
    """What the dropout model knows about a matched patient (banded, from the token)."""
    return {"age_band": tok["age_band"], "ecog": ix["ecog"][0]["value"] if ix["ecog"] else 1, "distance_band": tok["distance_band"],
            "prior_lines": len(ix["lines"]), "comorbidities": sum(n != "brain_metastases_treated" for n in ix["conditions"])}


def study_pools(results, tokens, ixs, rates):
    """Expected eligible patients per site (eligible = 1, potential = chance its unknowns pass) and the matched patients'
    dropout features with their weights."""
    pools, feats = {}, {}
    for r, tok, ix in zip(results, tokens, ixs):
        w = expected_eligible(r, rates, on_treatment(ix))
        pools[tok["site"]] = pools.get(tok["site"], 0.0) + w
        if w > 0:
            feats.setdefault(tok["site"], []).append((w, candidate_features(tok, ix)))
    return pools, feats


def score_sites(model, dm, sites, investigators, history, indication, pools, feats, horizon=world.HORIZON, rng=None):
    """Every site for one study: eligible pool, activation, enrolment with an 80% interval, dropout, evaluable patients,
    the lead investigator's profile, cost, and the naive baseline. -> (rows, predictive draws by site, dropout by site)."""
    rng = rng if rng is not None else np.random.default_rng(0)
    pis = {p["id"]: p for p in investigators}
    rows, draws, drop = [], {}, {}
    for s in sites:
        lead = pis[world.lead_investigator(s, indication, pis)]
        pool = pools.get(s["id"], 0.0)
        fs = feats.get(s["id"], [])
        pr, d = predict_site(model, s, lead["trials_by_indication"][indication], pool, horizon, rng, pool_weights=[w for w, _ in fs] or None)
        dr = sum(w * dropout_risk(dm, f, s["id"]) for w, f in fs) / sum(w for w, _ in fs) if fs else dm["site_rates"].get(s["id"], dm["base_rate"])
        draws[s["id"]], drop[s["id"]] = d, dr
        excluded = "lead investigator has an open GCP inspection finding" if lead["open_gcp_finding"] else None
        rows.append({"site": s["id"], "region": s["region"], "kind": s["kind"], "lat": s["lat"], "lon": s["lon"], "expected_eligible": round(pool, 2),
                     **pr, "dropout_risk": round(dr, 3), "evaluable": round(pr["mean"] * (1 - dr), 3), "naive_expected": model["history_mean"].get(s["id"], 0.0),
                     "activation_cost": s["activation_cost"], "per_patient_cost": s["per_patient_cost"], "capacity": s["capacity"],
                     "investigator": investigator_profile(lead, indication, history), "excluded": excluded})
    return rows, draws, drop


def candidates(rows):
    return [{"id": r["site"], "region": r["region"], "kind": r["kind"], "enrolled": r["mean"], "evaluable": r["evaluable"],
             "activation_cost": r["activation_cost"], "per_patient_cost": r["per_patient_cost"], "excluded": bool(r["excluded"]),
             "naive": r["naive_expected"]} for r in rows]


def portfolio_interval(draws, dropout, chosen, rng, target=None):
    """Predicted total evaluable enrolment of a portfolio: mean, 80% interval and P(>= target)."""
    if not chosen:
        return {"mean": 0.0, "p10": 0, "p90": 0, "p_reach_target": 0.0 if target else None}
    tot = sum(rng.binomial(draws[s].astype(int), 1 - dropout[s]) for s in chosen)
    return {"mean": round(float(tot.mean()), 1), "p10": int(np.quantile(tot, 0.1)), "p90": int(np.quantile(tot, 0.9)),
            "p_reach_target": round(float((tot >= target).mean()), 3) if target else None}


def backtest(history, enrollees, sites, investigators, split_month=-18):
    """Train on the studies that started before `split_month`, score on the later ones (as the service sees them: the pool
    estimate recorded at feasibility). -> metrics for the model registry."""
    site_by = {s["id"]: s for s in sites}
    pis = {p["id"]: p for p in investigators}
    train = [h for h in history if h["start_month"] < split_month]
    test = [h for h in history if h["start_month"] >= split_month]
    m = fit_enrolment(train, sites, investigators)
    rng = np.random.default_rng(0)
    net_mean = float(np.mean([h["enrolled"] for h in train]))
    pred, naive, actual, inside = [], [], [], []
    for h in test:
        pr, _ = predict_site(m, site_by[h["site"]], pis[h["lead_investigator"]]["trials_by_indication"][h["indication"]], h["pool_estimate"], rng=rng, draws=500)
        prior = [x["enrolled"] for x in train if x["site"] == h["site"]]
        pred.append(pr["mean"])
        naive.append(float(np.mean(prior)) if prior else net_mean)
        actual.append(h["enrolled"])
        inside.append(pr["p10"] <= h["enrolled"] <= pr["p90"])
    pred, naive, actual = map(np.array, (pred, naive, actual))
    test_refs = {h["study_ref"] for h in test}
    dm = fit_dropout([e for e in enrollees if e["study_ref"] not in test_refs])
    d = score_dropout(dm, [e for e in enrollees if e["study_ref"] in test_refs])
    return {"enrolment": {"train_studies": len(train), "test_studies": len(test), "mae": round(float(np.abs(pred - actual).mean()), 2),
                          "naive_mae": round(float(np.abs(naive - actual).mean()), 2), "interval_coverage_80": round(float(np.mean(inside)), 3),
                          "predicted_total": round(float(pred.sum()), 1), "actual_total": int(actual.sum())},
            "dropout": d, "split": f"studies starting before month {split_month} train, the rest test"}
