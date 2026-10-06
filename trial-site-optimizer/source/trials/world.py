"""A synthetic oncology research network: sites with their investigators and enrolment history, each site's patients as an
EHR feed would send them (identifiers, birth dates, dated diagnoses, staging, biomarkers, labs, regimens by line, ECOG,
comorbidities, a free-text note), protocols whose eligibility sections are written from templates with a known structured
truth, and the enrolment a study would really get at each site.

The generator knows the truth the service never sees: each patient's lab values and ECOG *today* (the record only has past
measurements), biomarkers nobody tested, the regimen given at another hospital that never reached the record, each site's
true enrolment rate and contracting speed, each enrolled patient's chance of dropping out. Tests and the evaluation score
the service against it.

Every random draw is keyed: a site's patients by (seed, site), a study's enrolment at a site by (seed, study, site), so the
same site enrols the same patients in any portfolio that includes it: comparing portfolios is a paired comparison.
"""
import datetime
import math

import numpy as np

INDEX = datetime.date(2026, 9, 1)                   # the data snapshot; screening is evaluated as of this day
REGIONS = {"Northeast": (41.5, -74.0, 2.2), "Southeast": (33.5, -83.5, 2.6), "Midwest": (41.8, -88.5, 2.8),
           "South Central": (31.5, -96.5, 2.8), "Mountain": (39.8, -106.5, 2.6), "Pacific": (37.5, -121.0, 2.4)}
INDICATIONS = ["NSCLC", "SCLC", "BREAST", "CRC", "MELANOMA"]
MIX = np.array([0.30, 0.06, 0.28, 0.24, 0.12])     # network-wide share of each indication among oncology patients
STAGES = ["I", "IIA", "IIB", "IIIA", "IIIB", "IIIC", "IV"]
STAGE_P = {"NSCLC": [.10, .05, .06, .10, .10, .05, .54], "SCLC": [.03, .03, .04, .10, .12, .08, .60],
           "BREAST": [.20, .14, .12, .10, .08, .06, .30], "CRC": [.12, .10, .10, .12, .08, .08, .40], "MELANOMA": [.20, .12, .10, .10, .08, .06, .34]}
AGE = {"NSCLC": (67, 9), "SCLC": (66, 8), "BREAST": (59, 12), "CRC": (64, 11), "MELANOMA": (63, 13)}
DRUG_CLASS = {   # reference pharmacology (RxNorm/ATC-like): the service maps a recorded drug to its classes with this table
    "pembrolizumab": "anti-PD-1", "nivolumab": "anti-PD-1", "cemiplimab": "anti-PD-1", "atezolizumab": "anti-PD-L1",
    "durvalumab": "anti-PD-L1", "ipilimumab": "anti-CTLA-4", "carboplatin": "platinum", "cisplatin": "platinum",
    "oxaliplatin": "platinum", "pemetrexed": "antifolate", "paclitaxel": "taxane", "docetaxel": "taxane",
    "osimertinib": "EGFR-TKI", "alectinib": "ALK-TKI", "sotorasib": "KRAS-G12C-inhibitor", "ramucirumab": "anti-VEGFR2",
    "bevacizumab": "anti-VEGF", "trastuzumab": "anti-HER2", "pertuzumab": "anti-HER2", "letrozole": "aromatase-inhibitor",
    "palbociclib": "CDK4/6-inhibitor", "capecitabine": "fluoropyrimidine", "fluorouracil": "fluoropyrimidine",
    "irinotecan": "topoisomerase-inhibitor", "topotecan": "topoisomerase-inhibitor", "etoposide": "topoisomerase-inhibitor",
    "gemcitabine": "antimetabolite", "dabrafenib": "BRAF-inhibitor", "trametinib": "MEK-inhibitor"}
CHEMO = {"platinum", "antifolate", "taxane", "fluoropyrimidine", "topoisomerase-inhibitor", "antimetabolite"}
CHECKPOINT = {"anti-PD-1", "anti-PD-L1", "anti-CTLA-4"}
LABS = {   # canonical unit, and how a site that reports per microlitre or g/L writes it (factor to canonical)
    "ANC": ("10^9/L", "cells/uL", 1e-3), "PLT": ("10^9/L", "cells/uL", 1e-3), "HGB": ("g/dL", "g/L", 0.1),
    "CRCL": ("mL/min", None, 1), "AST": ("xULN", None, 1), "ALT": ("xULN", None, 1), "TBIL": ("xULN", None, 1)}
CONDITIONS = ["brain_metastases_active", "brain_metastases_treated", "interstitial_lung_disease", "autoimmune_disease",
              "hiv", "hepatitis_active", "second_malignancy"]
SURNAMES = ["Okafor", "Lindqvist", "Moreau", "Tanaka", "Haddad", "Novak", "Castillo", "Mensah", "Kowalski", "Iyer", "Brennan",
            "Sato", "Delacroix", "Abara", "Fischer", "Ruiz", "Petrov", "Nakamura", "Osei", "Varga", "Quinn", "Halvorsen",
            "Adeyemi", "Marchetti", "Chowdhury", "Silva", "Bauer", "Kaur", "Lemaire", "Odhiambo"]
SPECIALTY = {"NSCLC": "thoracic", "SCLC": "thoracic", "BREAST": "breast", "CRC": "GI", "MELANOMA": "melanoma"}

BASE_RATE = 0.120              # enrolments per truly eligible record per month at an average site with an average investigator
HORIZON = 12                   # months of enrolment in every study (history and new)
TYPE_RATE = {"academic": 1.15, "community": 1.0}
TYPE_ACTIVATION = {"academic": 1.55, "community": 1.0}
WEIBULL_K = 1.6


# --- the network --------------------------------------------------------------------------------------------------------
def network(seed, n_sites=120, records=True):
    """Sites, investigators and five years of site history. `records=False` skips the patients (big networks for timing)."""
    rng = np.random.default_rng([seed, 1])
    sites, investigators = [], []
    names = list(REGIONS)
    for i in range(n_sites):
        region = names[int(rng.choice(len(names), p=[.2, .18, .2, .16, .1, .16]))]
        lat0, lon0, spread = REGIONS[region]
        kind = "academic" if rng.random() < 0.3 else "community"
        mix = rng.dirichlet(MIX * 14)
        n_rec = int(np.clip(rng.lognormal(math.log(330 if kind == "academic" else 240), 0.45), 60, 1400))
        site = {"index": i, "id": f"S-{i + 1:03d}", "region": region, "kind": kind,
                "lat": round(float(lat0 + rng.normal(0, spread * 0.55)), 3), "lon": round(float(lon0 + rng.normal(0, spread)), 3),
                "mix": mix, "n_records": n_rec, "competing_trials": int(rng.integers(0, 7)),
                "lab_units": "per_uL" if rng.random() < 0.3 else "canonical",
                "activation_cost": round(float(rng.uniform(55, 80) if kind == "academic" else rng.uniform(28, 48)), 1) * 1000,
                "per_patient_cost": round(float(rng.uniform(13, 18) if kind == "academic" else rng.uniform(9, 13.5)), 1) * 1000,
                "capacity": int(rng.integers(14, 36) if kind == "academic" else rng.integers(8, 24)),
                # latent: what the generator knows and the service has to infer from history
                "quality": float(rng.gamma(2.5, 1 / 2.5)), "retention": float(rng.normal(0, 0.45)),
                "contracting": float(rng.lognormal(0, 0.3) * (3.2 if rng.random() < 0.08 else 1.0))}
        pis = []
        for k in range(int(rng.integers(1, 4))):
            spec = SPECIALTY[INDICATIONS[int(np.argmax(rng.multinomial(1, mix)))]] if k else "medical oncology"
            trials = {ind: int(rng.poisson(2.2 * mix[j] * 5 * (1.6 if kind == "academic" else 1))) for j, ind in enumerate(INDICATIONS)}
            pis.append({"id": f"PI-{len(investigators) + len(pis) + 1:04d}", "site": site["id"],
                        "name": f"Dr. {chr(65 + int(rng.integers(0, 26)))}. {SURNAMES[int(rng.integers(0, len(SURNAMES)))]}",
                        "specialty": spec, "trials_by_indication": trials,
                        "publications_by_indication": {ind: int(rng.poisson(t * (2.5 if kind == "academic" else 0.4))) for ind, t in trials.items()},
                        "open_gcp_finding": bool(rng.random() < 0.05)})
        investigators += pis
        site["investigators"] = [p["id"] for p in pis]
        sites.append(site)
    pi_by_id = {p["id"]: p for p in investigators}
    history = []
    for s in sites:
        hrng = np.random.default_rng([seed, 2, s["index"]])
        for j in range(int(hrng.integers(2, 9))):
            ind = INDICATIONS[int(np.argmax(hrng.multinomial(1, s["mix"])))]
            pool = max(1, int(round(s["n_records"] * s["mix"][INDICATIONS.index(ind)] * hrng.uniform(0.04, 0.22))))
            lead = lead_investigator(s, ind, pi_by_id)
            ref = f"H{seed % 1000:03d}-{s['index']:03d}-{j}"
            out = run_site(seed, ref, s, pi_by_id[lead], ind, pool, hrng)
            history.append({"site": s["id"], "study_ref": ref, "indication": ind, "start_month": -60 + int(hrng.integers(0, 46)),
                            "pool": pool, "pool_estimate": max(1, int(round(pool * hrng.lognormal(0, 0.25)))), "lead_investigator": lead, "competing_trials": s["competing_trials"], **out})
    net = {"seed": seed, "sites": sites, "investigators": investigators, "history": history}
    if records:
        net["patients"] = [p for s in sites for p in site_patients(seed, s)]
    return net


def lead_investigator(site, indication, pi_by_id):
    """The investigator with most trials in the indication (ties: first listed) leads the study at the site."""
    return max(site["investigators"], key=lambda p: (pi_by_id[p]["trials_by_indication"][indication], -int(p[3:])))


def investigator_multiplier(pi, indication):
    return 1 + 0.30 * math.log1p(pi["trials_by_indication"][indication])


def true_rate(site, pi, indication, pool):
    """Enrolments a month once active: proportional to the truly eligible patients, scaled by the site and investigator."""
    return BASE_RATE * pool * site["quality"] * TYPE_RATE[site["kind"]] * math.exp(-0.10 * site["competing_trials"]) * investigator_multiplier(pi, indication)


def activation_scale(site):
    return 2.3 * TYPE_ACTIVATION[site["kind"]] * site["contracting"]


def dropout_prob(f, site):
    z = -2.1 + 0.45 * (f["ecog"] >= 1) + 0.7 * (f["ecog"] >= 2) + 0.4 * (f["age"] >= 75) + 0.35 * (f["distance_km"] > 30) \
        + 0.55 * (f["distance_km"] > 80) + 0.18 * f["prior_lines"] + 0.25 * f["comorbidities"] + site["retention"]
    return 1 / (1 + math.exp(-z))


def run_site(seed, study_ref, site, pi, indication, pool, rng=None, enrollees_from=None, months=HORIZON):
    """One study at one site: activation, monthly enrolments, enrollees with features and whether they drop out.
    Keyed by (seed, study, site) so the same site in two portfolios enrols the same way."""
    r = np.random.default_rng([seed, 3, hash_str(study_ref) % (2 ** 31), site["index"]])
    act = float(activation_scale(site) * r.weibull(WEIBULL_K))
    lam = true_rate(site, pi, indication, pool)
    monthly, total = [], 0
    for m in range(months):
        exposure = float(np.clip(m + 1 - act, 0, 1))
        n = min(int(r.poisson(lam * exposure)) if exposure > 0 else 0, site["capacity"] - total)      # a site stops at its slot cap
        monthly.append(n)
        total += n
    enrolled = int(sum(monthly))
    enrollees = []
    for k in range(enrolled):
        if enrollees_from:
            p = enrollees_from[int(r.integers(0, len(enrollees_from)))]
            f = {"age": p["age"], "ecog": p["ecog"], "distance_km": p["distance_km"], "prior_lines": p["prior_lines"], "comorbidities": p["comorbidities"]}
        else:
            f = {"age": int(np.clip(r.normal(*AGE[indication]), 25, 90)), "ecog": int(r.choice(3, p=[.42, .46, .12])),
                 "distance_km": float(r.lognormal(math.log(18 if site["kind"] == "community" else 32), 0.8)),
                 "prior_lines": int(r.choice(4, p=[.4, .35, .18, .07])), "comorbidities": int(r.poisson(0.5))}
        f["dropped"] = bool(r.random() < dropout_prob(f, site))
        enrollees.append(f)
    return {"activation_months": round(act, 2) if act < months else None, "months_enrolling": round(max(0.0, months - act), 2),
            "enrolled": enrolled, "monthly": monthly, "dropped": sum(e["dropped"] for e in enrollees), "enrollees": enrollees,
            "true_rate": lam}


def hash_str(s):
    h = 2166136261
    for ch in s.encode():
        h = (h ^ ch) * 16777619 % 2 ** 32
    return h


# --- patients -----------------------------------------------------------------------------------------------------------
def _date(day):
    return (INDEX + datetime.timedelta(days=int(day))).isoformat()


def site_patients(seed, site):
    rng = np.random.default_rng([seed, 4, site["index"]])
    return [patient(rng, seed, site, k) for k in range(site["n_records"])]


def _regimens(rng, ind, bm, n_lines):
    first = {"NSCLC": (["osimertinib"] if bm.get("EGFR") else ["alectinib"] if bm.get("ALK") else
                       (["pembrolizumab"] if rng.random() < .6 else ["carboplatin", "pemetrexed", "pembrolizumab"]) if bm.get("PD-L1_TPS", 0) >= 50 else
                       (["carboplatin", "pemetrexed", "pembrolizumab"] if rng.random() < .7 else ["carboplatin", "paclitaxel"])),
             "SCLC": ["carboplatin", "etoposide", "atezolizumab"],
             "BREAST": ["trastuzumab", "pertuzumab", "docetaxel"] if bm.get("HER2") else ["letrozole", "palbociclib"] if bm.get("ER") else ["paclitaxel"],
             "CRC": ["pembrolizumab"] if bm.get("MSI-H") else ["fluorouracil", "oxaliplatin", "bevacizumab"],
             "MELANOMA": ["dabrafenib", "trametinib"] if bm.get("BRAF") and rng.random() < .5 else ["nivolumab", "ipilimumab"]}[ind]
    later = {"NSCLC": [["docetaxel", "ramucirumab"], ["docetaxel"], ["gemcitabine"], ["carboplatin", "pemetrexed"]],
             "SCLC": [["topotecan"], ["paclitaxel"]], "BREAST": [["capecitabine"], ["paclitaxel"], ["gemcitabine"]],
             "CRC": [["irinotecan", "fluorouracil"], ["capecitabine"]], "MELANOMA": [["pembrolizumab"], ["paclitaxel", "carboplatin"]]}[ind]
    out = [first]
    if ind == "NSCLC" and bm.get("KRAS_G12C"):
        later = [["sotorasib"]] + later
    if ind == "NSCLC" and (bm.get("EGFR") or bm.get("ALK")):
        later = [["carboplatin", "pemetrexed"], ["docetaxel"]]
    for k in range(1, n_lines):
        out.append(later[min(k - 1, len(later) - 1)])
    return out


def patient(rng, seed, site, k):
    """One patient: the latent truth, and the record the site's EHR feed sends."""
    ind = INDICATIONS[int(np.argmax(rng.multinomial(1, site["mix"])))]
    age = float(np.clip(rng.normal(*AGE[ind]), 24, 92))
    sex = "F" if ind == "BREAST" and rng.random() < .99 or ind != "BREAST" and rng.random() < .5 else "M"
    stage = STAGES[int(rng.choice(len(STAGES), p=STAGE_P[ind]))]
    advanced = stage in ("IIIB", "IIIC", "IV")
    dx_day = -int(rng.uniform(15, 1600))
    bm = {}
    if ind == "NSCLC":
        u = rng.random()
        bm["PD-L1_TPS"] = 0 if u < .32 else int(rng.integers(1, 50)) if u < .66 else int(rng.integers(50, 101))
        bm["EGFR"] = rng.random() < .15
        bm["ALK"] = not bm["EGFR"] and rng.random() < .045
        bm["KRAS_G12C"] = not bm["EGFR"] and not bm["ALK"] and rng.random() < .13
    elif ind == "BREAST":
        bm["HER2"], bm["ER"] = rng.random() < .2, rng.random() < .7
    elif ind == "CRC":
        bm["MSI-H"], bm["KRAS"] = rng.random() < .05, rng.random() < .4
    elif ind == "MELANOMA":
        bm["BRAF"] = rng.random() < .45
    # lines of systemic therapy for advanced disease, laid forward from the start of advanced disease
    lines = []
    if advanced:
        start = dx_day + int(rng.uniform(10, 60))
        n = min(4, int(rng.poisson(0.35 + 0.9 * (-dx_day) / 365)))
        regs = _regimens(rng, ind, {k_: v for k_, v in bm.items()}, max(n, 1))
        t = start
        for li in range(n):
            if t > -3:
                break
            dur = int(rng.uniform(50, 330))
            end = t + dur
            lines.append({"line": li + 1, "drugs": regs[li], "start": t, "end": None if end >= 0 else end})
            t = end + int(rng.uniform(7, 45))
    on_treatment = bool(lines) and lines[-1]["end"] is None
    # labs today (truth) and their history
    chemo_now = on_treatment and any(DRUG_CLASS[d] in CHEMO for d in lines[-1]["drugs"])
    today = {"ANC": float(rng.lognormal(math.log(2.3 if chemo_now else 3.6), 0.45)), "PLT": float(max(15, rng.normal(205 if chemo_now else 245, 70))),
             "HGB": float(np.clip(rng.normal(10.9 if chemo_now else 12.4, 1.5), 6, 17)),
             "CRCL": float(np.clip(rng.normal(118 - 0.85 * age, 20), 12, 160)), "AST": float(rng.lognormal(math.log(0.65), 0.55)),
             "ALT": float(rng.lognormal(math.log(0.6), 0.6)), "TBIL": float(rng.lognormal(math.log(0.55), 0.45))}
    last_visit = -int(rng.uniform(0, 21)) if on_treatment else -int(rng.uniform(0, 200))
    visits = [last_visit - 21 * j - int(rng.integers(0, 5)) for j in range(3)] if on_treatment else [last_visit, last_visit - int(rng.uniform(40, 160))]
    labs = []
    for name, v0 in today.items():
        for d in visits:
            walk = 0.16 if name in ("ANC", "PLT") else 0.07 if name in ("HGB", "CRCL") else 0.2
            val = v0 * math.exp(walk * math.sqrt(-d / 30) * rng.normal() + 0.03 * rng.normal())
            labs.append({"name": name, "day": d, "value": val})
    ecog_now = int(rng.choice(4, p=[.3, .42, .2, .08] if advanced else [.55, .35, .08, .02]))
    ecog_day = -int(rng.uniform(0, 30)) if on_treatment else last_visit
    ecog_rec = max(0, ecog_now - (1 if rng.random() < .18 else 0))           # people get worse: an older score can be better than today
    conds = {}
    p_brain = {"NSCLC": .22, "SCLC": .35, "BREAST": .08, "MELANOMA": .2, "CRC": .02}[ind] if advanced else 0
    if rng.random() < p_brain:
        conds["brain_metastases_active" if rng.random() < .55 else "brain_metastases_treated"] = -int(rng.uniform(0, 400))
    for name, p, span in (("interstitial_lung_disease", .03, 3000), ("autoimmune_disease", .06, 2200), ("hiv", .01, 5000),
                          ("hepatitis_active", .02, 3000), ("second_malignancy", .045, 3600)):
        if rng.random() < p:
            conds[name] = -int(rng.uniform(0, span))
    distance = float(rng.lognormal(math.log(18 if site["kind"] == "community" else 32), 0.8))
    hidden_line = None                     # a regimen given at another hospital that never reached this record
    if len(lines) >= 2 and rng.random() < .05:
        hidden_line = int(rng.integers(0, len(lines)))
    # --- the record, as the site's feed sends it -------------------------------------------------------------------------
    mrn = f"{site['id'][2:]}{k:05d}{int(rng.integers(100, 1000))}"             # unique within the network, like a real MRN
    birth = INDEX - datetime.timedelta(days=int(age * 365.25))
    events = [{"type": "diagnosis", "code": ind, "stage": stage, "date": _date(dx_day)}]
    if stage != STAGES[0] and rng.random() < .5:
        events.append({"type": "diagnosis", "code": ind, "stage": STAGES[max(0, STAGES.index(stage) - 2)], "date": _date(dx_day - int(rng.uniform(30, 400)))})
    test_p = {"PD-L1_TPS": .85, "EGFR": .82, "ALK": .78, "KRAS_G12C": .55, "HER2": .95, "ER": .97, "MSI-H": .8, "KRAS": .7, "BRAF": .9}
    for name, val in bm.items():
        if advanced or rng.random() < .5:
            if rng.random() < test_p[name]:
                events.append({"type": "biomarker", "name": name, "value": val if isinstance(val, int) and not isinstance(val, bool) else ("positive" if val else "negative"),
                               "date": _date(dx_day + int(rng.uniform(0, 30)))})
    for ln in lines:
        if ln["line"] - 1 == hidden_line:
            continue
        for d in ln["drugs"]:
            events.append({"type": "medication", "drug": d, "line": ln["line"], "start": _date(ln["start"]), "end": _date(ln["end"]) if ln["end"] is not None else None})
    unit = site["lab_units"]
    for lb in labs:
        canon, alt_unit, factor = LABS[lb["name"]]
        if unit == "per_uL" and alt_unit:
            events.append({"type": "lab", "name": lb["name"], "value": round(lb["value"] / factor, 0 if alt_unit == "cells/uL" else 0), "unit": alt_unit, "date": _date(lb["day"])})
        else:
            events.append({"type": "lab", "name": lb["name"], "value": round(lb["value"], 2), "unit": canon, "date": _date(lb["day"])})
    events.append({"type": "ecog", "value": ecog_rec, "date": _date(ecog_day)})
    for name, d in conds.items():
        events.append({"type": "condition", "name": name, "date": _date(d)})
    if rng.random() < 0.012:              # what real feeds contain: a blinded study drug no dictionary can classify ...
        events.append({"type": "medication", "drug": "blinded study drug", "line": 0, "start": _date(dx_day + 30), "end": _date(dx_day + 120)})
    if rng.random() < 0.006:              # ... and a lab in a unit the service will not guess at
        events.append({"type": "lab", "name": "HGB", "value": 7.1, "unit": "mmol/L", "date": _date(last_visit)})
    order = np.argsort([e.get("date") or e.get("start") for e in events], kind="stable")
    record = {"mrn": mrn, "birth_date": birth.isoformat(), "sex": sex, "site": site["id"],
              "home_distance_km": round(distance, 1),
              "note": f"Seen in clinic {_date(last_visit)}, MRN {mrn}, born {birth.isoformat()}. {ind} stage {stage}.",
              "events": [events[i] for i in order]}
    truth = {"age": age, "indication": ind, "stage": stage, "biomarkers": bm, "labs_today": today, "ecog_today": ecog_now,
             "lines": lines, "conditions": conds, "hidden_line": hidden_line}
    return {"site": site["id"], "record": record, "truth": truth, "features": {
        "age": int(age), "ecog": ecog_now, "distance_km": distance, "prior_lines": len(lines), "comorbidities": sum(c not in ("brain_metastases_treated",) for c in conds)}}


# --- the truth of a rule ------------------------------------------------------------------------------------------------
def truth_rule(rule, t):
    """Whether a patient truly meets one DSL rule today (labs and ECOG as of today, every regimen including unrecorded ones,
    biomarkers whether or not anyone tested them). The service never calls this."""
    f = rule["field"]
    if f == "age":
        return _cmp(t["age"], rule["op"], rule["value"])
    if f == "diagnosis":
        return t["indication"] == rule["code"] and (not rule.get("stages") or t["stage"] in rule["stages"])
    if f == "biomarker":
        v = t["biomarkers"].get(rule["name"])
        if v is None:
            return False
        if "op" in rule:
            return _cmp(v, rule["op"], rule["value"])
        return bool(v) == (rule["value"] == "positive")
    if f == "lab":
        return _cmp(t["labs_today"][rule["name"]], rule["op"], rule["value"])
    if f == "ecog":
        return _cmp(t["ecog_today"], rule["op"], rule["value"])
    if f == "therapy":
        w = rule.get("within_days")
        for ln in t["lines"]:
            if any(DRUG_CLASS[d] in rule["classes"] or "any_systemic" in rule["classes"] or ("chemotherapy" in rule["classes"] and DRUG_CLASS[d] in CHEMO) for d in ln["drugs"]):
                if w is None or ln["end"] is None or ln["end"] >= -w:
                    return True
        return False
    if f == "prior_lines":
        return _cmp(len(t["lines"]), rule["op"], rule["value"])
    if f == "condition":
        d = t["conditions"].get(rule["name"])
        return d is not None and (rule.get("within_days") is None or d >= -rule["within_days"])
    raise ValueError(f)


def _cmp(a, op, b):
    return {">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b, "==": a == b}[op]


def truly_eligible(criteria, t):
    """Eligible on every computable criterion (manual ones are checked by the site at screening and are not in the truth)."""
    for c in criteria:
        rules = [r for r in c["rules"] if r["field"] != "manual"]
        if not rules:
            continue
        hit = [truth_rule(r, t) for r in rules]
        if c["type"] == "inclusion" and not all(hit) or c["type"] == "exclusion" and any(hit):
            return False
    return True


# --- protocols ------------------------------------------------------------------------------------------------------------
# Each family has phrasings (most common first); a phrasing marked hard is one a strict grammar should not claim to understand.
def _lab_words(name, op, value, unit_style):
    words = {"ANC": ["absolute neutrophil count (ANC)", "ANC", "neutrophils"], "PLT": ["platelet count", "platelets"],
             "HGB": ["hemoglobin", "haemoglobin", "Hb"], "CRCL": ["creatinine clearance", "calculated creatinine clearance (Cockcroft-Gault)", "CrCl"],
             "AST": ["AST"], "ALT": ["ALT"], "TBIL": ["total bilirubin", "bilirubin"]}[name]
    sym = {">=": ["≥", ">=", "at least", "no less than"], "<=": ["≤", "<=", "no more than", "not exceeding"]}[op]
    if name in ("ANC", "PLT"):
        val = f"{value:g} × 10^9/L" if unit_style == 0 else f"{value * 1000:,.0f}/µL" if unit_style == 1 else f"{value * 1000:,.0f}/mm³"
    elif name == "HGB":
        val = f"{value:g} g/dL" if unit_style != 1 else f"{value * 10:g} g/L"
    elif name == "CRCL":
        val = f"{value:g} mL/min"
    else:
        val = f"{value:g} × ULN" if unit_style != 1 else f"{value:g} times the upper limit of normal"
    return words, sym, val


def _window(rng, days, hard=False):
    if hard:
        return {182: "within the last half year", 14: "in the fortnight before screening", 28: "since the start of the screening period"}.get(days, "recently")
    weeks, months = days // 7, round(days / 30.4)
    if days % 365 == 0:
        opts = [f"within the past {days // 365} years", f"in the last {days // 365} years", f"within {days // 365} years before screening"]
    elif months and days == round(months * 30.4) and days >= 60:      # months are 30.4 days, the convention the parser uses
        opts = [f"within {months} months before screening", f"in the past {months} months", f"within {months} months prior to enrollment", f"within {days} days prior to screening"]
    else:
        opts = [f"within {days} days prior to screening", f"within {days} days before enrollment", f"in the {days} days before first dose"]
        if days % 7 == 0 and days <= 56:
            opts.append(f"within {weeks} week{'s' if weeks > 1 else ''} of screening")
    return opts[int(rng.integers(0, len(opts)))]


TEMPLATES = {   # protocol archetype: indication, stage set, inclusion family list, exclusion family list
    "nsclc_post_platinum": ("NSCLC", ["IIIB", "IIIC", "IV"], ["age", "diagnosis", "platinum_prior", "lines_max2", "pdl1_1", "ecog01", "labs_marrow", "crcl", "liver", "measurable", "consent"],
                            ["egfr_alk", "io_window", "systemic_28", "brain_active", "ild", "autoimmune", "hiv", "hepatitis", "second_malignancy", "pregnancy", "life_expectancy"]),
    "nsclc_io_first_line": ("NSCLC", ["IIIB", "IIIC", "IV"], ["age", "diagnosis", "pdl1_50", "ecog01", "naive", "labs_marrow", "crcl", "liver", "measurable", "consent"],
                            ["egfr_alk", "io_window", "brain_active", "ild", "autoimmune", "hiv", "hepatitis", "second_malignancy", "life_expectancy"]),
    "nsclc_second_line": ("NSCLC", ["IIIB", "IIIC", "IV"], ["age", "diagnosis", "platinum_prior", "lines_max2", "ecog01", "anc", "plt", "hgb", "crcl", "consent"],
                          ["egfr_alk", "docetaxel_prior", "systemic_28", "brain_active", "ild", "second_malignancy", "pregnancy"]),
    "nsclc_kras": ("NSCLC", ["IV"], ["age", "diagnosis", "kras", "lines_min1", "ecog01", "labs_marrow", "liver", "consent"],
                   ["kras_inhibitor_prior", "systemic_21", "brain_active", "hepatitis", "life_expectancy"]),
    "sclc_extensive": ("SCLC", ["IV"], ["age", "diagnosis", "naive", "ecog01", "labs_marrow", "crcl", "consent"],
                       ["io_ever", "autoimmune", "ild", "hiv", "pregnancy"]),
    "breast_her2": ("BREAST", ["IV"], ["age", "diagnosis", "her2", "lines_max2", "ecog01", "anc", "plt", "liver", "consent"],
                    ["brain_active", "second_malignancy", "systemic_21", "pregnancy", "life_expectancy"]),
    "crc_msi": ("CRC", ["IV"], ["age", "diagnosis", "msi", "ecog01", "labs_marrow", "liver", "consent"],
                ["io_ever", "autoimmune", "hiv", "hepatitis", "life_expectancy"]),
    "melanoma_io_refractory": ("MELANOMA", ["IIIC", "IV"], ["age", "diagnosis", "io_prior", "ecog01", "anc", "plt", "hgb", "consent"],
                               ["brain_active", "autoimmune", "ild", "systemic_28", "pregnancy"]),
}
CANCER_NAMES = {"NSCLC": ["non-small cell lung cancer (NSCLC)", "NSCLC", "non-small-cell lung carcinoma"],
                "SCLC": ["small cell lung cancer (SCLC)", "extensive-stage small cell lung cancer"],
                "BREAST": ["breast cancer", "adenocarcinoma of the breast"], "CRC": ["colorectal cancer (CRC)", "adenocarcinoma of the colon or rectum"],
                "MELANOMA": ["cutaneous melanoma", "melanoma"]}


def _family(rng, fam, ind, stages, hard_p):
    """-> (text, rules). rules == [{'field': 'manual', ...}] for criteria no record can answer."""
    hard = rng.random() < hard_p
    pick = lambda xs: xs[int(rng.integers(0, len(xs)))]          # noqa: E731
    if fam == "age":
        if hard:
            return "Adults who have reached the age of majority in their jurisdiction.", [{"field": "age", "op": ">=", "value": 18}]
        return pick(["Age ≥ 18 years at the time of signing informed consent.", "Male or female patients aged 18 years or older.",
                     "At least 18 years of age.", "Adults ≥ 18 years old."]), [{"field": "age", "op": ">=", "value": 18}]
    if fam == "diagnosis":
        name = pick(CANCER_NAMES[ind])
        if hard:
            return f"Histologically confirmed advanced {name}.", [{"field": "diagnosis", "code": ind, "stages": stages}]
        st = {("IIIB", "IIIC", "IV"): pick(["stage IIIB, IIIC or IV", "locally advanced (stage IIIB/IIIC) or metastatic (stage IV)", "stage IIIB-IV"]),
              ("IV",): pick(["stage IV", "metastatic (stage IV)"]), ("IIIC", "IV"): pick(["stage IIIC or IV", "unresectable stage IIIC or stage IV"])}[tuple(stages)]
        return pick([f"Histologically or cytologically confirmed {st} {name} not amenable to curative therapy.",
                     f"Documented diagnosis of {st} {name}."]), [{"field": "diagnosis", "code": ind, "stages": stages}]
    if fam == "pdl1_50":
        return pick(["PD-L1 tumor proportion score (TPS) ≥ 50% by an approved assay.", "PD-L1 expression on at least 50% of tumor cells (TPS ≥ 50%).",
                     "High PD-L1 expression (TPS of 50% or greater)."]), [{"field": "biomarker", "name": "PD-L1_TPS", "op": ">=", "value": 50}]
    if fam == "pdl1_1":
        return pick(["PD-L1 tumor proportion score (TPS) ≥ 1%.", "PD-L1 expression on at least 1% of tumor cells.", "PD-L1-positive tumor (TPS ≥ 1%) by a validated assay."]), \
            [{"field": "biomarker", "name": "PD-L1_TPS", "op": ">=", "value": 1}]
    if fam == "kras":
        return pick(["Documented KRAS G12C mutation in tumor tissue or blood.", "Tumor harbouring a KRAS G12C mutation."]), [{"field": "biomarker", "name": "KRAS_G12C", "value": "positive"}]
    if fam == "her2":
        return pick(["HER2-positive disease (IHC 3+ or ISH amplified).", "Documented HER2-positive status."]), [{"field": "biomarker", "name": "HER2", "value": "positive"}]
    if fam == "msi":
        return pick(["Microsatellite instability-high (MSI-H) tumor.", "Documented MSI-H status."]), [{"field": "biomarker", "name": "MSI-H", "value": "positive"}]
    if fam == "ecog01":
        v = 1
        if hard:
            return "Performance status 0-1 on the ECOG scale, assessed by the investigator unless documented by the referring physician.", [{"field": "ecog", "op": "<=", "value": v}]
        days = int(pick([28, 14, None, None]) or 0) or None
        w = f" {_window(rng, days)}" if days else ""
        return pick([f"ECOG performance status of 0 or 1{w}.", f"Eastern Cooperative Oncology Group (ECOG) performance status ≤ 1{w}.",
                     f"ECOG PS 0-1{w}."]), [{"field": "ecog", "op": "<=", "value": v, **({"within_days": days} if days else {})}]
    if fam in ("anc", "plt", "hgb", "crcl"):
        name, op, value = {"anc": ("ANC", ">=", 1.5), "plt": ("PLT", ">=", 100), "hgb": ("HGB", ">=", 9), "crcl": ("CRCL", ">=", 50)}[fam]
        days = int(pick([14, 14, 7, 28]))
        words, sym, val = _lab_words(name, op, value, int(rng.integers(0, 3)))
        if hard and fam == "anc":
            return f"ANC must not fall below 1.5 × 10^9/L {_window(rng, days)}.", [{"field": "lab", "name": name, "op": op, "value": value, "unit": LABS[name][0], "within_days": days}]
        return f"{_cap(pick(words))} {pick(sym)} {val} {_window(rng, days)}.", [{"field": "lab", "name": name, "op": op, "value": value, "unit": LABS[name][0], "within_days": days}]
    if fam == "labs_marrow":
        days = int(pick([14, 14, 7, 28]))
        style = int(rng.integers(0, 3))
        parts, rules = [], []
        for name, value in (("ANC", 1.5), ("PLT", 100), ("HGB", 9)):
            words, sym, val = _lab_words(name, ">=", value, style)
            parts.append(f"{pick(words)} {pick(sym)} {val}")
            rules.append({"field": "lab", "name": name, "op": ">=", "value": value, "unit": LABS[name][0], "within_days": days})
        return f"Adequate bone marrow function {_window(rng, days)}: {parts[0]}, {parts[1]} and {parts[2]}.", rules
    if fam == "liver":
        days = int(pick([14, 14, 28]))
        if hard:
            return (f"AST and ALT ≤ 2.5 × ULN (≤ 5 × ULN if liver metastases are present) {_window(rng, days)}.",
                    [{"field": "lab", "name": n, "op": "<=", "value": 2.5, "unit": "xULN", "within_days": days} for n in ("AST", "ALT")])
        _, sym, val = _lab_words("AST", "<=", 2.5, int(rng.integers(0, 3)))
        _, sym2, val2 = _lab_words("TBIL", "<=", 1.5, 0)
        return (f"Adequate liver function {_window(rng, days)}: AST and ALT {pick(sym)} {val}, and total bilirubin {pick(sym2)} {val2}.",
                [{"field": "lab", "name": n, "op": "<=", "value": v, "unit": "xULN", "within_days": days} for n, v in (("AST", 2.5), ("ALT", 2.5), ("TBIL", 1.5))])
    if fam == "naive":
        return pick(["No prior systemic therapy for advanced or metastatic disease.", "Treatment-naive for advanced disease.",
                     "Has not received prior systemic treatment for metastatic disease."]), [{"field": "prior_lines", "op": "<=", "value": 0}]
    if fam == "lines_max2":
        if hard:
            return "Fewer than three prior regimens, counting maintenance as part of the preceding line.", [{"field": "prior_lines", "op": "<=", "value": 2}]
        text = pick(["No more than 2 prior lines of systemic therapy for advanced disease.", "At most two prior lines of systemic therapy.", "1 or 2 prior lines of systemic therapy."])
        return text, ([{"field": "prior_lines", "op": ">=", "value": 1}] if text.startswith("1 or") else []) + [{"field": "prior_lines", "op": "<=", "value": 2}]
    if fam == "lines_min1":
        return pick(["At least one prior line of systemic therapy for advanced disease.", "Received ≥ 1 prior line of systemic therapy."]), [{"field": "prior_lines", "op": ">=", "value": 1}]
    if fam == "platinum_prior":
        return pick(["Disease progression on or after at least one prior platinum-based chemotherapy regimen.", "Prior treatment with a platinum-containing regimen."]), \
            [{"field": "therapy", "classes": ["platinum"]}]
    if fam == "io_prior":
        return pick(["Prior treatment with an anti-PD-1 or anti-PD-L1 antibody.", "Received at least one prior anti-PD-1 or anti-PD-L1 therapy."]), \
            [{"field": "therapy", "classes": ["anti-PD-1", "anti-PD-L1"]}]
    if fam == "measurable":
        return pick(["At least one measurable lesion per RECIST v1.1.", "Measurable disease per RECIST 1.1."]), [{"field": "manual", "topic": "measurable disease (RECIST)"}]
    if fam == "consent":
        return pick(["Able to understand and willing to sign a written informed consent document.", "Signed informed consent prior to any study procedure."]), \
            [{"field": "manual", "topic": "informed consent"}]
    if fam == "life_expectancy":
        return pick(["Life expectancy of less than 3 months.", "Expected survival under 12 weeks in the opinion of the investigator."]), [{"field": "manual", "topic": "life expectancy"}]
    if fam == "pregnancy":
        return pick(["Pregnant or breastfeeding.", "Women who are pregnant or nursing."]), [{"field": "manual", "topic": "pregnancy"}]
    if fam == "egfr_alk":
        return pick(["Known EGFR sensitizing mutation or ALK rearrangement.", "Tumors with a documented EGFR mutation or ALK fusion."]), \
            [{"field": "biomarker", "name": "EGFR", "value": "positive"}, {"field": "biomarker", "name": "ALK", "value": "positive"}]
    if fam == "io_window":
        days = int(pick([182, 182, 91]))
        if hard and days == 182:
            return f"Prior PD-1 or PD-L1 blockade {_window(rng, days, hard=True)}.", [{"field": "therapy", "classes": ["anti-PD-1", "anti-PD-L1"], "within_days": days}]
        return pick([f"Prior treatment with an anti-PD-1, anti-PD-L1 or anti-CTLA-4 antibody {_window(rng, days)}.",
                     f"Received any immune checkpoint inhibitor {_window(rng, days)}."]), [{"field": "therapy", "classes": ["anti-CTLA-4", "anti-PD-1", "anti-PD-L1"], "within_days": days}]
    if fam == "io_ever":
        return pick(["Any prior treatment with an immune checkpoint inhibitor.", "Prior anti-PD-1, anti-PD-L1 or anti-CTLA-4 therapy."]), \
            [{"field": "therapy", "classes": ["anti-CTLA-4", "anti-PD-1", "anti-PD-L1"]}]
    if fam in ("systemic_28", "systemic_21"):
        days = 28 if fam == "systemic_28" else 21
        return pick([f"Systemic anticancer therapy {_window(rng, days)}.", f"Any chemotherapy, targeted therapy or immunotherapy {_window(rng, days)}."]), \
            [{"field": "therapy", "classes": ["any_systemic"], "within_days": days}]
    if fam == "docetaxel_prior":
        return pick(["Prior treatment with a taxane (paclitaxel or docetaxel).", "Previously received a taxane."]) if not hard else "Prior taxane, unless given as part of adjuvant treatment.", \
            [{"field": "therapy", "classes": ["taxane"]}]
    if fam == "kras_inhibitor_prior":
        return "Prior treatment with a KRAS G12C inhibitor.", [{"field": "therapy", "classes": ["KRAS-G12C-inhibitor"]}]
    if fam == "brain_active":
        return pick(["Active or untreated central nervous system (CNS) metastases.", "Symptomatic or untreated brain metastases."]), \
            [{"field": "condition", "name": "brain_metastases_active"}]
    if fam == "ild":
        return pick(["History of interstitial lung disease or non-infectious pneumonitis.", "Known interstitial lung disease."]), [{"field": "condition", "name": "interstitial_lung_disease"}]
    if fam == "autoimmune":
        days = 730
        return pick([f"Active autoimmune disease that required systemic treatment {_window(rng, days)}.", f"Autoimmune disease requiring systemic therapy {_window(rng, days)}."]), \
            [{"field": "condition", "name": "autoimmune_disease", "within_days": days}]
    if fam == "hiv":
        return pick(["Known history of HIV infection.", "Known human immunodeficiency virus (HIV) infection."]), [{"field": "condition", "name": "hiv"}]
    if fam == "hepatitis":
        return pick(["Active hepatitis B or hepatitis C infection.", "Known active HBV or HCV infection."]), [{"field": "condition", "name": "hepatitis_active"}]
    if fam == "second_malignancy":
        days = 1095
        return pick([f"Additional malignancy that required active treatment {_window(rng, days)}.", f"Another malignancy diagnosed {_window(rng, days)}."]), \
            [{"field": "condition", "name": "second_malignancy", "within_days": days}]
    raise ValueError(fam)


def _unseen(rng, fam, ind, stages):
    """Phrasings written separately from the ones above and never shown to the parser while it was written: the evaluation's
    test of how the grammar does on wording it was not built against. Same structured truth as the family's."""
    pick = lambda xs: xs[int(rng.integers(0, len(xs)))]          # noqa: E731
    _, truth = _family(np.random.default_rng(0), fam, ind, stages, 0.0)
    lab = lambda n, op, v, w: {"field": "lab", "name": n, "op": op, "value": v, "unit": LABS[n][0], "within_days": w}   # noqa: E731
    name = pick(CANCER_NAMES[ind])
    st = {("IIIB", "IIIC", "IV"): "stage IIIB to IV", ("IV",): "stage IV", ("IIIC", "IV"): "stage IIIC/IV"}[tuple(stages)]
    text = {
        "age": ["Participants must be 18 years or older on the day of consent.", "Aged eighteen years or above."],
        "diagnosis": [f"Confirmed {name}, {st}, with no curative option available.", f"{_cap(name)} ({st}) confirmed by pathology."],
        "pdl1_50": ["Tumor PD-L1 TPS of at least 50 percent.", "PD-L1 high (≥50% tumor cells staining)."],
        "pdl1_1": ["Any PD-L1 expression (TPS 1% or higher).", "PD-L1 TPS greater than or equal to 1 percent."],
        "kras": ["KRAS p.G12C-mutant tumor.", "Presence of a KRAS G12C alteration."],
        "her2": ["HER2-amplified or HER2 3+ by IHC.", "Tumor that is HER2 positive per ASCO/CAP guidelines."],
        "msi": ["Tumor is MSI-high or mismatch-repair deficient.", "MSI-H by PCR or NGS."],
        "ecog01": ["ECOG score no greater than 1.", "Performance status (ECOG) 0 to 1."],
        "anc": ["Neutrophil count of 1.5 x 10^9/L or more within 14 days of starting treatment."],
        "plt": ["Platelet count not below 100 × 10^9/L within 14 days prior to screening."],
        "hgb": ["Hemoglobin of 9 g/dL or higher (transfusion permitted) within 14 days prior to screening."],
        "crcl": ["Estimated GFR or creatinine clearance ≥ 50 mL/min within 14 days prior to screening."],
        "labs_marrow": ["Bone marrow reserve, measured within 14 days: neutrophils ≥ 1.5 × 10^9/L; platelets ≥ 100 × 10^9/L; hemoglobin ≥ 9 g/dL."],
        "liver": ["AST, ALT ≤ 2.5 × ULN and bilirubin ≤ 1.5 × ULN within 14 days prior to screening."],
        "naive": ["No systemic anticancer treatment received in the advanced setting.", "First-line candidates only (no previous systemic therapy)."],
        "lines_max2": ["Up to two previous lines of systemic treatment.", "A maximum of 2 prior systemic regimens."],
        "lines_min1": ["Progressed after one or more prior systemic therapies."],
        "platinum_prior": ["Previously treated with platinum doublet chemotherapy."],
        "io_prior": ["Progression on prior PD-1/PD-L1 inhibitor therapy."],
        "measurable": ["Measurable target lesion by RECIST."], "consent": ["Provision of signed consent."],
        "life_expectancy": ["Predicted survival < 3 months."], "pregnancy": ["Lactating or pregnant women."],
        "egfr_alk": ["Actionable EGFR or ALK alteration."],
        "io_window": ["Checkpoint inhibitor exposure in the 6 months before screening.", "Anti-PD-(L)1 therapy within 182 days before screening."],
        "io_ever": ["Previous exposure to checkpoint blockade."], "systemic_28": ["Anticancer drugs within 28 days of screening."],
        "systemic_21": ["Anticancer drugs within 21 days of screening."], "docetaxel_prior": ["Previous taxane-based treatment."],
        "kras_inhibitor_prior": ["Prior sotorasib or adagrasib."], "brain_active": ["Untreated brain metastases or leptomeningeal disease."],
        "ild": ["Pneumonitis requiring steroids, or ILD."], "autoimmune": ["Autoimmune disorder treated systemically within the past 2 years."],
        "hiv": ["HIV positive."], "hepatitis": ["Uncontrolled hepatitis B or C."],
        "second_malignancy": ["Prior cancer within 3 years, other than treated skin cancer."],
    }[fam]
    t = pick(text)
    if fam in ("anc", "plt", "hgb", "crcl", "labs_marrow", "liver"):          # the unseen lab wordings all say 14 days
        truth = [{**r, "within_days": 14} for r in truth]
    if fam == "io_window":
        truth = [{"field": "therapy", "classes": ["anti-CTLA-4", "anti-PD-1", "anti-PD-L1"] if t.startswith("Checkpoint") else ["anti-PD-1", "anti-PD-L1"], "within_days": 182}]
    if fam == "lines_max2":
        truth = [{"field": "prior_lines", "op": "<=", "value": 2}]
    if fam == "ecog01":
        truth = [{"field": "ecog", "op": "<=", "value": 1}]
    return t, truth


def _cap(s):
    return s[0].upper() + s[1:]


def protocol(seed, template, ref=None, hard_p=0.08, style="seen"):
    """An eligibility section in the style of an oncology protocol, and its structured truth criterion by criterion.
    style="unseen" writes every criterion in the wording the parser was never developed against."""
    rng = np.random.default_rng([seed, 5, hash_str(template) % (2 ** 31)])
    ind, stages, inc, exc = TEMPLATES[template]
    criteria, lines = [], []
    for kind, fams, head in (("inclusion", inc, "5.1 Inclusion criteria"), ("exclusion", exc, "5.2 Exclusion criteria")):
        lines.append(head)
        lines.append(f"Patients must meet all of the following criteria to be eligible:" if kind == "inclusion" else "Patients meeting any of the following criteria are not eligible:")
        for k, fam in enumerate(fams, 1):
            text, rules = _family(rng, fam, ind, stages, hard_p) if style == "seen" else _unseen(rng, fam, ind, stages)
            ref_ = f"{'I' if kind == 'inclusion' else 'E'}{k}"
            criteria.append({"ref": ref_, "type": kind, "text": text, "rules": rules, "family": fam})
            lines.append(f"{k}. {text}")
        lines.append("")
    title = {"NSCLC": "Non-Small Cell Lung Cancer", "SCLC": "Small Cell Lung Cancer", "BREAST": "Breast Cancer", "CRC": "Colorectal Cancer", "MELANOMA": "Melanoma"}[ind]
    ref = ref or f"ONC-{template.split('_')[0].upper()}-{seed % 1000:03d}"
    head = f"{ref}: A Phase 3, Randomized, Open-Label Study in {title}\n\n5. STUDY POPULATION\n\n"
    return {"ref": ref, "template": template, "indication": ind, "text": head + "\n".join(lines).strip() + "\n", "criteria": criteria}


# The generator's catalogue: protocols it wrote, by reference, so the simulator can run a study the service parsed.
CATALOGUE = {"ONC-LUNG-301": (1, "nsclc_post_platinum")}


def catalogue_protocol(ref):
    seed, template = CATALOGUE[ref]
    return protocol(seed, template, ref=ref)


# --- running a study ------------------------------------------------------------------------------------------------------
def truth_pools(net, criteria):
    """Truly eligible patients per site for a study (the generator's count, with every latent fact)."""
    out = {s["id"]: 0 for s in net["sites"]}
    elig = {s["id"]: [] for s in net["sites"]}
    for p in net["patients"]:
        if truly_eligible(criteria, p["truth"]):
            out[p["site"]] += 1
            elig[p["site"]].append(p["features"])
    return out, elig


def run_study(net, study_ref, indication, criteria, site_ids, months=HORIZON, pools=None):
    """Enrol a study at the given sites. Same (seed, study, site) -> same draws, whatever else is in the portfolio."""
    pools, elig = pools or truth_pools(net, criteria)
    by_id = {s["id"]: s for s in net["sites"]}
    pi_by_id = {p["id"]: p for p in net["investigators"]}
    out = {}
    for sid in site_ids:
        s = by_id[sid]
        pi = pi_by_id[lead_investigator(s, indication, pi_by_id)]
        out[sid] = run_site(net["seed"], study_ref, s, pi, indication, pools[sid], enrollees_from=elig[sid] or None, months=months)
        out[sid]["pool"] = pools[sid]
    return out
