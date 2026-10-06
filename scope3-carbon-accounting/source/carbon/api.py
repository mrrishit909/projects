"""Public API (modular monolith). Blueprint services map to: connector-hub (the ERP extract, the forwarders' shipments,
utility bills and supplier disclosures arrive through POST /v1/activities/import), activity-normalizer (currencies,
units, double postings, validation with reasons), factor-registry (versions the database freezes), supplier-resolution,
emissions-engine, uncertainty-service (Monte Carlo), document-extractor (supplier disclosures), scenario-service and
reporting. Not built: Kafka, Neo4j, pgvector, a columnar store, SSO; see the README.

    uvicorn carbon.api:app          python -m core.jobs carbon.api      # the worker
"""
import collections
import datetime
import functools
import hashlib
import json
import pickle
import time
import uuid
from typing import Literal

import numpy as np
from fastapi import Depends, Header, Query
from fastapi.encoders import jsonable_encoder
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from core import audit, db, jobs
from core.app import Ctx, Problem, create_app, run

from . import engine, world

READ = {"carbon:read", "jobs:read"}
ANALYST = READ | {"activities:import", "suppliers:resolve", "documents:extract", "factors:propose", "calculations:run", "scenarios:run",
                  "decisions:propose", "reports:export"}
PERMISSIONS = {"viewer": READ, "analyst": ANALYST, "lead": ANALYST | {"company:load", "decisions:approve", "audit:read"}}
app = create_app("scope3-carbon-accounting", PERMISSIONS)
auth = app.state.auth
IdemKey = Header(None, alias="Idempotency-Key")
RESOLVER_TRAINING_SEEDS, RESOLVER_CHECK_SEED = (900, 901), 902     # earlier engagements' analyst-confirmed vendor pairs
POLICY = {"min_lineage_coverage": 1.0, "max_orphan_rate": 0.01}     # what an inventory must meet before it can be proposed for publication
TOP_ENGAGE = 20


def worker_ctx(job):
    return Ctx(job["tenant_id"], uuid.UUID(job["payload"]["actor_id"]), "worker", "system")


def group(c):
    g = c.execute("SELECT * FROM organization WHERE kind = 'group'").fetchone()
    if not g:
        raise Problem(409, "no_company", "load the company first: POST /v1/company:load")
    return g


def model_version(t):
    return f"{str(t)[:8]}-1"


@functools.lru_cache(maxsize=16)
def _models(tenant_id, version):
    with db.tx(tenant_id) as c:
        return {r["name"]: pickle.loads(r["artifact"]) for r in c.execute("SELECT name, artifact FROM model_artifacts WHERE version = %s", [version])}


def models(t):
    return _models(str(t), model_version(t))


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


# --- the company ------------------------------------------------------------------------------------------------------------
class LoadIn(BaseModel):
    seed: int = Field(7, ge=1, le=10 ** 6)


@app.post("/v1/company:load", status_code=202, tags=["company"], summary="(+) Load the synthetic multinational: group and subsidiaries, facilities, the factor registry (two frozen versions), last year's analyst-labelled invoice lines; train and register the category classifier and the supplier matcher and report them against their baselines")
def load_company(body: LoadIn, ctx: Ctx = Depends(auth("company:load")), idem: str | None = IdemKey):
    def work(c):
        if c.execute("SELECT 1 FROM organization").fetchone():
            raise Problem(409, "company_exists", "this tenant already has a company; `make reset` for a fresh demo")
        return 202, jobs.enqueue(c, ctx, "company.load", body.model_dump())
    return run(ctx, idem, body, work)


def factor_rows(t, version, factors):
    return [(t, version, fid, f["kind"], f["category"], f["geography"], f["year"], f["unit"], f["value"], f["gsd"], f["dispersion"], f["source"],
             f.get("supplier_id"), f.get("evidence_id")) for fid, f in sorted(factors.items())]


FACTOR_COLS = ["tenant_id", "version", "id", "kind", "category", "geography", "year", "unit", "value", "gsd", "dispersion", "source", "supplier_id", "evidence_id"]


def version_hash(c, version):
    rows = c.execute("SELECT id, value, gsd, dispersion, unit FROM emission_factor WHERE version = %s ORDER BY id", [version]).fetchall()
    return sha(json.dumps([[r["id"], r["value"], r["gsd"], r["dispersion"], r["unit"]] for r in rows]))


def freeze(c, version):
    c.execute("UPDATE factor_version SET status = 'frozen', content_hash = %s, frozen_at = now() WHERE id = %s", [version_hash(c, version), version])


@jobs.handler("company.load")
def load_job(c, job):
    t, seed = job["tenant_id"], job["payload"]["seed"]
    w = world.company(seed)
    db.load(c, "organization", ["tenant_id", "id", "parent_id", "external_ref", "name", "kind", "country", "currency", "model_seed", "reporting_year", "current_factor_version"],
            [(t, "MDG", None, "MDG", "Meridale Group", "group", None, "USD", seed, world.YEAR, "EF-2025.1")]
            + [(t, code, "MDG", code, name, "subsidiary", country, cur, None, None, None) for code, name, country, cur, _s, _l in world.SUBSIDIARIES])
    db.load(c, "facility", ["tenant_id", "id", "organization_id", "kind", "country", "attributes"],
            [(t, f["id"], f["subsidiary"], f["kind"], f["country"], Jsonb({})) for f in w["facilities"]])
    for v, note in (("EF-2024.2", "last year's catalogue, used for the published 2024 inventory"), ("EF-2025.1", "this year's catalogue")):
        c.execute("INSERT INTO factor_version (tenant_id, id, notes, created_by) VALUES (%s,%s,%s,%s)", [t, v, note, uuid.UUID(job["payload"]["actor_id"])])
        db.load(c, "emission_factor", FACTOR_COLS, factor_rows(t, v, world.catalogue(v)))
        freeze(c, v)
    # the category classifier, from last year's analyst-labelled lines (80% to train, 20% to score it against the rules)
    lab = world.labelled_sample(seed)
    names = {r["vendor_ref"]: r["name"] for r in w["records"]}
    texts = [engine.class_text(d, g, names[v]) for d, g, v in zip(lab["description"], lab["gl_code"], lab["vendor_ref"])]
    test = np.random.default_rng(seed).random(len(texts)) < 0.2
    clf = engine.train_classifier([x for x, k in zip(texts, test) if not k], [x for x, k in zip(lab["label"], test) if not k])
    tl = [i for i in range(len(texts)) if test[i]]
    cats, _c, _m, _k, _l = engine.map_lines(clf, [lab["description"][i] for i in tl], [lab["gl_code"][i] for i in tl], [names[lab["vendor_ref"][i]] for i in tl])
    labels, usd = [lab["label"][i] for i in tl], [lab["true_usd"][i] for i in tl]
    cls_metrics = {**engine.category_scores(cats, labels, usd), "baseline": engine.category_scores([engine.rule_category(lab["description"][i], lab["gl_code"][i]) for i in tl], labels, usd),
                   "train_lines": int((~test).sum()), "test_lines": int(test.sum()), "abstain_below": engine.ABSTAIN}
    # the supplier matcher, from earlier engagements' confirmed pairs, checked on a third
    resolver, r_metrics = engine.train_resolver([world.company(s)["records"] for s in RESOLVER_TRAINING_SEEDS])
    chk = world.company(RESOLVER_CHECK_SEED)["records"]
    truth = [r["supplier"] for r in chk]
    r_metrics.update(check=engine.pairwise_scores(engine.resolve(chk, resolver)["cluster"], truth),
                     check_exact_baseline=engine.pairwise_scores(engine.baseline_clusters(chk), truth),
                     check_fuzzy_baseline=engine.pairwise_scores(engine.baseline_clusters(chk, "fuzzy", resolver.fuzzy_threshold_), truth))
    version = model_version(t)
    for name, obj, metrics, snap in (("category-classifier", clf, cls_metrics, f"{len(texts)} analyst-labelled {world.YEAR - 1} invoice lines, seed {seed}"),
                                     ("supplier-matcher", resolver, r_metrics, f"confirmed vendor pairs from engagements {RESOLVER_TRAINING_SEEDS}")):
        c.execute("INSERT INTO model_artifacts (tenant_id, name, version, data_snapshot, metrics, artifact, approved) VALUES (%s,%s,%s,%s,%s,%s,true)",
                  [t, name, version, snap, Jsonb(metrics), pickle.dumps(obj)])
    audit.record(c, worker_ctx(job), "company.loaded", "organization", "MDG", {"seed": seed, "model_version": version, "factor_versions": ["EF-2024.2", "EF-2025.1"]})
    return {"company": "Meridale Group", "subsidiaries": len(world.SUBSIDIARIES), "facilities": len(w["facilities"]), "reporting_year": world.YEAR,
            "factor_versions": {v: len(world.catalogue(v)) for v in ("EF-2024.2", "EF-2025.1")},
            "models": {"version": version, "category_classifier": cls_metrics, "supplier_matcher": r_metrics}}


@app.get("/v1/overview", tags=["company"], summary="(+) The command centre: company, data loaded, factor versions, models, calculations, open review tasks and decisions")
def overview(ctx: Ctx = Depends(auth("carbon:read"))):
    with db.tx(ctx.tenant_id) as c:
        g = group(c)
        subs = c.execute("SELECT id, name, country, currency FROM organization WHERE kind = 'subsidiary' ORDER BY id").fetchall()
        acts = c.execute("SELECT kind, count(*) AS n, sum(amount_usd) AS usd FROM activity GROUP BY kind ORDER BY kind").fetchall()
        sup = c.execute("SELECT count(*) AS records, count(DISTINCT supplier_id) AS suppliers FROM supplier_alias").fetchone()
        versions = c.execute("""SELECT v.id, v.status, v.based_on, v.notes, v.content_hash, v.frozen_at, count(f.id) AS factors,
                                       count(f.id) FILTER (WHERE f.kind = 'supplier') AS supplier_specific
                                  FROM factor_version v LEFT JOIN emission_factor f ON f.version = v.id GROUP BY v.tenant_id, v.id ORDER BY v.id""").fetchall()
        calcs = c.execute("SELECT id, factor_version, status, lines, totals->'scope' AS scope, created_at FROM calculation ORDER BY created_at DESC LIMIT 10").fetchall()
        tasks = c.execute("SELECT kind, count(*) AS n, sum(weight) AS weight FROM review_task WHERE status = 'open' GROUP BY kind ORDER BY kind").fetchall()
        decisions = c.execute("SELECT id, kind, subject, status, created_at, decided_at FROM decision_record ORDER BY created_at DESC LIMIT 10").fetchall()
        mods = c.execute("SELECT name, version, data_snapshot, metrics FROM model_artifacts ORDER BY name").fetchall()
    return jsonable_encoder({"company": g["name"], "reporting_year": g["reporting_year"], "current_factor_version": g["current_factor_version"], "subsidiaries": subs,
                             "activities": acts, "vendor_records": sup["records"], "suppliers": sup["suppliers"], "factor_versions": versions,
                             "calculations": calcs, "open_review_tasks": tasks, "decisions": decisions, "models": mods})


# --- connector-hub and activity-normalizer -----------------------------------------------------------------------------------
class Connector(BaseModel):
    name: Literal["erp-extract"] = "erp-extract"
    transactions: int = Field(2_000_000, ge=1200, le=5_000_000, description="AP invoice lines to pull from the six ERPs")


class ApRow(BaseModel):
    subsidiary: str = Field(pattern=r"^MDG-[A-Z]{2}$")
    vendor_ref: str = Field(min_length=3, max_length=40)
    invoice: str = Field(min_length=1, max_length=40)
    line: int = Field(ge=1, le=999)
    period: datetime.date
    description: str = Field(max_length=200)
    gl_code: str = Field(pattern=r"^\d{4}$")
    amount: float
    currency: str = Field(min_length=1, max_length=8)


class ImportIn(BaseModel):
    connector: Connector | None = None
    rows: list[ApRow] | None = Field(None, max_length=500)


AP_COLS = ["tenant_id", "batch_id", "kind", "source_ref", "subsidiary", "facility_id", "vendor_ref", "period", "description", "gl_code", "amount", "currency", "fx_rate",
           "amount_usd", "quantity", "unit", "qty_norm", "unit_norm", "distance_km", "tkm", "mode", "fuel", "origin", "destination", "urgent", "category", "category_conf",
           "mapping_method", "input_hash"]


@app.post("/v1/activities/import", status_code=202, tags=["activities"], summary="Import activity data. `connector`: 202 + job that pulls the ERP vendor masters and AP ledgers, the forwarders' shipments, utility bills and supplier disclosures, normalises currencies and units, drops double postings, refuses bad lines with reasons and maps every invoice line to a spend category. `rows`: up to 500 invoice lines keyed in directly, validated one by one (201)")
def import_activities(body: ImportIn, ctx: Ctx = Depends(auth("activities:import")), idem: str | None = IdemKey):
    if bool(body.connector) == bool(body.rows):
        raise Problem(422, "one_source", "send either `connector` or `rows`")

    def work(c):
        g = group(c)
        if body.connector:
            return 202, jobs.enqueue(c, ctx, "activities.import", {"transactions": body.connector.transactions}, max_attempts=2)
        return 201, import_rows(c, ctx, g, body.rows)
    return run(ctx, idem, body, work)


def import_rows(c, ctx, g, rows):
    subs = {r["id"] for r in c.execute("SELECT id FROM organization WHERE kind = 'subsidiary'")}
    vendors = {r["vendor_ref"]: r["name"] for r in c.execute("SELECT vendor_ref, name FROM supplier_alias")}
    m = models(ctx.tenant_id)["category-classifier"]
    bid = uuid.uuid4()
    accepted, refused, keep = [], [], []
    for n, r in enumerate(rows):
        cur = engine.currency(r.currency)
        ref = f"{r.subsidiary}:{r.invoice}:{r.line}"
        why = ("unknown subsidiary" if r.subsidiary not in subs else f"unknown currency '{r.currency}'" if cur is None
               else f"vendor {r.vendor_ref} is not in the vendor master" if r.vendor_ref not in vendors
               else f"period {r.period} is outside the reporting year {g['reporting_year']}" if r.period.year != g["reporting_year"]
               else "amount is zero" if r.amount == 0 else "already imported" if c.execute("SELECT 1 FROM activity WHERE kind = 'ap' AND source_ref = %s", [ref]).fetchone()
               else "duplicate in this upload" if ref in {k[0] for k in keep} else None)
        if why:
            refused.append({"row": n, "invoice": r.invoice, "why": why})
        else:
            keep.append((ref, r, cur))
    c.execute("INSERT INTO import_batch (tenant_id, id, connector, stats, rejected, created_by) VALUES (%s,%s,'api',%s,%s,%s)",
              [ctx.tenant_id, bid, Jsonb({"rows": len(rows), "accepted": len(keep)}), Jsonb(refused), ctx.actor_id])
    if keep:
        cats, conf, meth, keys, _ = engine.map_lines(m, [r.description for _, r, _ in keep], [r.gl_code for _, r, _ in keep], [vendors[r.vendor_ref] for _, r, _ in keep])
        out = []
        for (ref, r, cur), cat, cf, mt, k in zip(keep, cats, conf, meth, keys):
            rate = world.fx(cur, r.period.month)
            h = sha(k)[:16]
            out.append((ctx.tenant_id, bid, "ap", ref, r.subsidiary, None, r.vendor_ref, r.period, r.description, r.gl_code, r.amount, cur, rate, r.amount * rate,
                        None, None, None, None, None, None, None, None, None, None, None, cat, float(cf), mt, h))
            accepted.append({"source_ref": ref, "amount_usd": round(r.amount * rate, 2), "currency": cur, "fx_rate": round(rate, 6), "category": cat, "confidence": round(float(cf), 3),
                             "method": mt, "vendor": vendors[r.vendor_ref]})
            c.execute("INSERT INTO model_runs (tenant_id, model_name, version, subject, inputs_hash, result) VALUES (%s,%s,%s,%s,%s,%s)",
                      [ctx.tenant_id, engine.CLASSIFIER_VERSION, model_version(ctx.tenant_id), f"line:{ref}", h, Jsonb({"category": cat, "confidence": round(float(cf), 3)})])
        db.load(c, "activity", AP_COLS, out)
    audit.record(c, ctx, "activities.imported", "import_batch", bid, {"connector": "api", "accepted": len(keep), "refused": len(refused)})
    return {"batch_id": bid, "accepted": accepted, "refused": refused}


@jobs.handler("activities.import")
def import_job(c, job):
    t0 = time.time()
    p, t = job["payload"], job["tenant_id"]
    g = group(c)
    seed, year = g["model_seed"], g["reporting_year"]
    w = world.company(seed)
    bid = uuid.uuid4()
    c.execute("INSERT INTO import_batch (tenant_id, id, connector, stats, created_by) VALUES (%s,%s,'erp-extract','{}',%s)", [t, bid, uuid.UUID(p["actor_id"])])
    # vendor masters
    have = {r["vendor_ref"] for r in c.execute("SELECT vendor_ref FROM supplier_alias")}
    new = [r for r in w["records"] if r["vendor_ref"] not in have]
    db.load(c, "supplier_alias", ["tenant_id", "vendor_ref", "subsidiary", "name", "country", "tax_id", "email_domain"],
            [(t, r["vendor_ref"], r["subsidiary"], r["name"], r["country"], r["tax_id"], r["email_domain"]) for r in new])
    names = {r["vendor_ref"]: r["name"] for r in c.execute("SELECT vendor_ref, name FROM supplier_alias")}
    clf = models(t)["category-classifier"]
    c.execute("CREATE TEMP TABLE _act (LIKE activity INCLUDING DEFAULTS) ON COMMIT DROP")
    cache, uses, spend_by_key = {}, collections.Counter(), collections.Counter()
    stats = collections.Counter()
    reasons, rejected_examples, injected = collections.Counter(), [], collections.Counter()
    truth_hits = {"model": [0.0, 0.0], "rules": [0.0, 0.0]}
    fx_used, rule_cache = {}, {}
    with c.cursor().copy(f"COPY _act ({', '.join(AP_COLS)}) FROM STDIN") as cp:
        for month, n in enumerate(world.month_lines(p["transactions"]), 1):
            L = world.ledger_month(seed, month, n)
            injected.update(L.pop("_injected"))
            keep, usd, rate, rejected, dups = engine.normalize_ap(L, names, year)
            stats["ap_read"] += len(L["amount"])
            stats["ap_duplicates"] += dups
            for i, code, why in rejected:
                reasons[code] += 1
                if len(rejected_examples) < 8:
                    rejected_examples.append({"source_ref": f"{L['subsidiary'][i]}:{L['invoice'][i]}:{L['line'][i]}", "why": why})
            stats["currency_aliases"] += sum(L["currency"][i] in world.CURRENCY_ALIASES for i in keep)
            desc = [L["description"][i] for i in keep]
            gl = [L["gl_code"][i] for i in keep]
            ven = [L["vendor_ref"][i] for i in keep]
            cats, conf, meth, keys, _ = engine.map_lines(clf, desc, gl, [names[v] for v in ven], cache)
            hashes = {}
            for j, i in enumerate(keep):
                k = keys[j]
                h = hashes.get(k) or hashes.setdefault(k, sha(k)[:16])
                uses[k] += 1
                spend_by_key[k] += abs(usd[j])
                cur = engine.currency(L["currency"][i])
                fx_used[(cur, month)] = rate[j]
                cp.write_row((t, bid, "ap", f"{L['subsidiary'][i]}:{L['invoice'][i]}:{L['line'][i]}", L["subsidiary"][i], None, ven[j], L["period"][i], desc[j], gl[j],
                              float(L["amount"][i]), cur, float(rate[j]), float(usd[j]), None, None, None, None, None, None, None, None, None, None, None,
                              cats[j], float(conf[j]), meth[j], h))
                stats[f"method_{meth[j]}"] += 1
                stats[f"spend_{meth[j]}"] += abs(float(usd[j]))
            # generator truth, for the simulation_truth block only (the mapping never sees it)
            tc = [L["true_category"][i] for i in keep]
            a = np.abs(usd)
            truth_hits["model"][0] += float(a[np.array([x == y for x, y in zip(cats, tc)])].sum())
            truth_hits["model"][1] += float(a.sum())
            rules = [rule_cache[k] if (k := (engine.mask(d), gg)) in rule_cache else rule_cache.setdefault(k, engine.rule_category(d, gg)) for d, gg in zip(desc, gl)]
            truth_hits["rules"][0] += float(a[np.array([x == y for x, y in zip(rules, tc)])].sum())
            truth_hits["rules"][1] += float(a.sum())
            stats["rules_unmapped"] += sum(r is None for r in rules)
            stats["spend_rules_unmapped"] += float(a[np.array([r is None for r in rules])].sum())
            stats["ap_accepted"] += len(keep)
            stats["ap_rejected"] += len(rejected)
        # forwarders' shipment records
        for s in world.shipments(seed, year=year):
            kg = s["weight"] * engine.TO_KG[s["weight_unit"]]
            km = s["distance"] * engine.TO_KM[s["distance_unit"]]
            stats["unit_conversions"] += (s["weight_unit"] != "kg") + (s["distance_unit"] != "km")
            cp.write_row((t, bid, "freight", s["shipment"], s["subsidiary"], s["facility_id"], s["carrier_ref"], f"{year}-{s['month']:02d}-15", None, None, None, None, None, None,
                          s["weight"], s["weight_unit"], kg / 1000, "t", km, kg / 1000 * km, s["mode"], None, s["origin"], s["destination"], s["urgent"], None, None, None, None))
            stats["freight_read"] += 1
        # utility bills
        for b in world.utility_bills(seed, year=year):
            q, u = engine.energy(b["fuel"], b["quantity"], b["unit"])
            stats["unit_conversions"] += b["unit"] not in ("kWh", "L")
            cp.write_row((t, bid, "utility", b["bill"], b["subsidiary"], b["facility_id"], None, f"{year}-{b['month']:02d}-01", None, None, None, None, None, None,
                          b["quantity"], b["unit"], q, u, None, None, None, b["fuel"], None, None, None, None, None, None, None))
            stats["bills_read"] += 1
    staged = c.execute("SELECT kind, count(*) AS n FROM _act GROUP BY kind").fetchall()
    ins = c.execute(f"INSERT INTO activity ({', '.join(AP_COLS)}) SELECT {', '.join(AP_COLS)} FROM _act ON CONFLICT (tenant_id, kind, source_ref) DO NOTHING RETURNING kind")
    landed = collections.Counter(r["kind"] for r in ins.fetchall())
    c.execute("DROP TABLE _act")
    staged = {r["kind"]: r["n"] for r in staged}
    # every distinct classifier input is logged once with its count; the ones it abstained on become review tasks
    runs, tasks = [], []
    for k, n in uses.items():
        cat, conf = cache[k]
        h = sha(k)[:16]
        runs.append((t, engine.CLASSIFIER_VERSION, model_version(t), f"text:{h}", h, Jsonb({"category": cat, "confidence": round(conf, 3), "lines": n})))
        if cat is None:
            gl, rest = k.split(" ", 1)
            vendor, desc = rest.split(" | ", 1)
            fb = engine.rule_category(desc, gl[2:])
            tasks.append((t, uuid.uuid4(), "category", h, Jsonb({"vendor": vendor, "description": desc, "gl_code": gl[2:], "fallback": fb, "confidence": round(conf, 3),
                                                                  "lines": n, "spend_usd": round(spend_by_key[k], 2)}), spend_by_key[k]))
    db.load(c, "model_runs", ["tenant_id", "model_name", "version", "subject", "inputs_hash", "result"], runs)
    db.load(c, "review_task", ["tenant_id", "id", "kind", "subject", "detail", "weight"], tasks)
    # supplier disclosures as received
    docs = world.disclosures(seed, year=year - 1)
    have_docs = {r["sha256"] for r in c.execute("SELECT sha256 FROM assurance_evidence WHERE kind = 'disclosure'")}
    fresh = [d for d in docs if sha(d["text"]) not in have_docs]
    db.load(c, "assurance_evidence", ["tenant_id", "id", "kind", "subject", "content", "sha256"],
            [(t, uuid.uuid4(), "disclosure", f"disclosure {n + 1} of {len(docs)}", d["text"], sha(d["text"])) for n, d in enumerate(fresh)])
    ap_kept = stats["ap_accepted"]
    sp_all = sum(stats[f"spend_{m}"] for m in ("model", "fallback", "unmapped")) or 1
    out = {"batch_id": bid, "seconds": round(time.time() - t0, 1), "vendor_records": len(names), "new_vendor_records": len(new),
           "ap": {"read": stats["ap_read"], "rejected": stats["ap_rejected"], "duplicates_dropped": stats["ap_duplicates"] + staged.get("ap", 0) - landed["ap"],
                  "stored": landed["ap"], "rejected_by_reason": dict(reasons), "rejected_examples": rejected_examples, "currency_aliases_normalised": stats["currency_aliases"],
                  "spend_usd": round(sp_all), "currencies": sorted({k[0] for k in fx_used})},
           "freight": {"read": stats["freight_read"], "stored": landed["freight"]},
           "utility": {"read": stats["bills_read"], "stored": landed["utility"], "duplicates_dropped": stats["bills_read"] - landed["utility"]},
           "unit_conversions": stats["unit_conversions"], "disclosures_received": len(fresh),
           "mapping": {"distinct_inputs_classified": len(uses), "by_method": {m: stats[f"method_{m}"] for m in ("model", "fallback", "unmapped")},
                       "spend_by_method": {m: round(stats[f"spend_{m}"]) for m in ("model", "fallback", "unmapped")},
                       "orphan_rate": round(stats["method_unmapped"] / max(1, ap_kept), 4), "orphan_spend_share": round(stats["spend_unmapped"] / sp_all, 4),
                       "rules_baseline_orphan_rate": round(stats["rules_unmapped"] / max(1, ap_kept), 4), "rules_baseline_orphan_spend_share": round(stats["spend_rules_unmapped"] / sp_all, 4),
                       "review_tasks": len(tasks), "model": engine.CLASSIFIER_VERSION, "version": model_version(t)},
           "simulation_truth": {"told": {"transactions": p["transactions"], **dict(injected)},
                                "spend_mapped_to_the_true_category": {"classifier": round(truth_hits["model"][0] / max(1, truth_hits["model"][1]), 4),
                                                                       "rules_baseline": round(truth_hits["rules"][0] / max(1, truth_hits["rules"][1]), 4)},
                                "note": "what the generator was told and knows; the analysis never reads this"}}
    out["lines_per_second"] = round((stats["ap_read"] + stats["freight_read"] + stats["bills_read"]) / max(1e-9, out["seconds"]))
    c.execute("UPDATE import_batch SET stats = %s, rejected = %s WHERE id = %s", [Jsonb(jsonable_encoder({k: v for k, v in out.items() if k != "simulation_truth"})), Jsonb(rejected_examples), bid])
    audit.record(c, worker_ctx(job), "activities.imported", "import_batch", bid, {"connector": "erp-extract", "ap_lines": landed["ap"], "shipments": landed["freight"], "bills": landed["utility"]})
    return out


# --- supplier-resolution ------------------------------------------------------------------------------------------------------
class ResolveIn(BaseModel):
    scope: Literal["all"] = "all"


def _display_name(names_subs):
    """The most representative name: no clerk's note, not truncated, not shouting, the fullest form."""
    def score(x):
        clean = not any(n in x[0].lower() for n in ("(old)", "use this one", "*", "(eur)"))
        return (clean, x[1] != "MDG-IN", not x[0].isupper(), x[0] != x[0].lower(), len(engine.norm_name(x[0])), x[0])
    return max(names_subs, key=score)[0]


@app.post("/v1/suppliers/resolve", status_code=202, tags=["suppliers"], summary="202 + job: resolve the vendor records of every ERP into suppliers. Blocking by character n-gram neighbours and shared tax ids or domains, a logistic matcher on fuzzy and embedding-style similarity, tax id, domain and country, merges that never join two tax ids; uncertain pairs become review tasks")
def resolve_suppliers(body: ResolveIn, ctx: Ctx = Depends(auth("suppliers:resolve")), idem: str | None = IdemKey):
    def work(c):
        group(c)
        if not c.execute("SELECT 1 FROM supplier_alias LIMIT 1").fetchone():
            raise Problem(409, "no_vendor_records", "import the vendor masters first: POST /v1/activities/import")
        return 202, jobs.enqueue(c, ctx, "suppliers.resolve", body.model_dump())
    return run(ctx, idem, body, work)


@jobs.handler("suppliers.resolve")
def resolve_job(c, job):
    t = job["tenant_id"]
    g = group(c)
    recs = c.execute("SELECT vendor_ref, subsidiary, name, country, tax_id, email_domain FROM supplier_alias ORDER BY vendor_ref").fetchall()
    matcher = models(t)["supplier-matcher"]
    res = engine.resolve(recs, matcher)
    cl = res["cluster"]
    members = collections.defaultdict(list)
    for i, k in enumerate(cl):
        members[k].append(i)
    spend = {r["vendor_ref"]: (r["usd"], r["category"]) for r in c.execute(
        """SELECT DISTINCT ON (vendor_ref) vendor_ref, category, sum(amount_usd) OVER (PARTITION BY vendor_ref) AS usd
             FROM (SELECT vendor_ref, category, sum(amount_usd) AS amount_usd FROM activity WHERE kind = 'ap' GROUP BY vendor_ref, category) x
            ORDER BY vendor_ref, amount_usd DESC""")}
    best = {}                        # each record's strongest link inside its cluster
    for i, j, prob, f in res["pairs"]:
        if cl[i] == cl[j]:
            for a, b in ((i, j), (j, i)):
                if prob > best.get(a, (0,))[0]:
                    best[a] = (prob, b, f)
    weights = dict(zip(engine.FEATURES, matcher.coef_[0].round(2).tolist()))
    sup_rows, alias_upd, runs = [], [], []
    sid = {}
    for k, idx in members.items():
        refs = sorted(recs[i]["vendor_ref"] for i in idx)
        s_id = uuid.uuid5(t, "supplier:" + refs[0])
        sid[k] = s_id
        cat_spend = collections.Counter()
        for i in idx:
            u, cat = spend.get(recs[i]["vendor_ref"], (0, None))
            if cat:
                cat_spend[cat] += u or 0
        taxes = [engine.norm_tax(recs[i]["tax_id"]) for i in idx if recs[i]["tax_id"]]
        countries = collections.Counter(recs[i]["country"] for i in idx)
        sup_rows.append((t, s_id, _display_name([(recs[i]["name"], recs[i]["subsidiary"]) for i in idx]), countries.most_common(1)[0][0],
                         taxes[0] if taxes else None, cat_spend.most_common(1)[0][0] if cat_spend else None, len(idx), engine.RESOLVER_VERSION))
        for i in idx:
            pb = best.get(i)
            ev = {"linked_to": recs[pb[1]]["vendor_ref"], "linked_name": recs[pb[1]]["name"], "features": dict(zip(engine.FEATURES, np.round(pb[2], 3).tolist())),
                  "weights": weights} if pb else {"singleton": True}
            alias_upd.append((recs[i]["vendor_ref"], s_id, pb[0] if pb else None, Jsonb(ev)))
            h = engine.inputs_hash([recs[i]["vendor_ref"], recs[i]["name"], recs[i]["country"], recs[i]["tax_id"], recs[i]["email_domain"]])
            runs.append((t, engine.RESOLVER_VERSION, model_version(t), f"vendor:{recs[i]['vendor_ref']}", h, Jsonb({"supplier_id": str(s_id), "link_prob": round(pb[0], 3) if pb else None})))
    c.execute("UPDATE supplier_alias SET supplier_id = NULL, match_prob = NULL")
    c.execute("CREATE TEMP TABLE _sup (LIKE supplier INCLUDING DEFAULTS) ON COMMIT DROP")
    db.copy(c, "_sup", ["tenant_id", "id", "name", "country", "tax_id", "main_category", "records", "resolver_version"], sup_rows)
    c.execute("""INSERT INTO supplier (tenant_id, id, name, country, tax_id, main_category, records, resolver_version)
                 SELECT tenant_id, id, name, country, tax_id, main_category, records, resolver_version FROM _sup
                 ON CONFLICT (tenant_id, id) DO UPDATE SET name = EXCLUDED.name, country = EXCLUDED.country, tax_id = EXCLUDED.tax_id,
                   main_category = EXCLUDED.main_category, records = EXCLUDED.records, resolver_version = EXCLUDED.resolver_version""")
    c.execute("DROP TABLE _sup")
    c.execute("CREATE TEMP TABLE _al (vendor_ref text, supplier_id uuid, match_prob float8, evidence jsonb) ON COMMIT DROP")
    db.copy(c, "_al", ["vendor_ref", "supplier_id", "match_prob", "evidence"], alias_upd)
    c.execute("UPDATE supplier_alias a SET supplier_id = x.supplier_id, match_prob = x.match_prob, evidence = x.evidence FROM _al x WHERE a.vendor_ref = x.vendor_ref")
    c.execute("DROP TABLE _al")
    db.load(c, "model_runs", ["tenant_id", "model_name", "version", "subject", "inputs_hash", "result"], runs)
    c.execute("DELETE FROM review_task WHERE kind = 'supplier_match' AND status = 'open'")
    db.load(c, "review_task", ["tenant_id", "id", "kind", "subject", "detail", "weight"],
            [(t, uuid.uuid4(), "supplier_match", f"{recs[i]['vendor_ref']}~{recs[j]['vendor_ref']}",
              Jsonb({"a": recs[i]["name"], "b": recs[j]["name"], "a_ref": recs[i]["vendor_ref"], "b_ref": recs[j]["vendor_ref"], "prob": round(p, 3), "merged": cl[i] == cl[j]}),
              (spend.get(recs[i]["vendor_ref"], (0,))[0] or 0) + (spend.get(recs[j]["vendor_ref"], (0,))[0] or 0)) for i, j, p in res["review"]])
    # what to show: the biggest merged suppliers, and the closest names that were kept apart
    usd = lambda idx: sum(spend.get(recs[i]["vendor_ref"], (0,))[0] or 0 for i in idx)       # noqa: E731
    merged = sorted([idx for idx in members.values() if len(idx) >= 2], key=lambda idx: -usd(idx))
    examples = [{"supplier_id": sid[cl[idx[0]]], "name": _display_name([(recs[i]["name"], recs[i]["subsidiary"]) for i in idx]), "spend_usd": round(usd(idx)),
                 "records": [{"vendor_ref": recs[i]["vendor_ref"], "subsidiary": recs[i]["subsidiary"], "name": recs[i]["name"], "country": recs[i]["country"],
                              "tax_id": recs[i]["tax_id"], "link_prob": round(best[i][0], 3) if i in best else None} for i in idx]}
                for idx in [m for m in merged if len(m) >= 3][:3]]
    apart = sorted([(f[0], i, j, p, f) for i, j, p, f in res["pairs"] if cl[i] != cl[j] and p < engine.REVIEW_LO], key=lambda x: -x[0])[:3]
    near = [{"a": {k: recs[i][k] for k in ("vendor_ref", "name", "country", "tax_id", "email_domain")}, "b": {k: recs[j][k] for k in ("vendor_ref", "name", "country", "tax_id", "email_domain")},
             "prob": round(p, 3), "features": dict(zip(engine.FEATURES, np.round(f, 3).tolist()))} for _, i, j, p, f in apart]
    w = world.company(g["model_seed"])
    truth = {r["vendor_ref"]: r["supplier"] for r in w["records"]}
    tl = [truth[r["vendor_ref"]] for r in recs]
    out = {"vendor_records": len(recs), "suppliers": len(members), "merged_suppliers": len(merged), "records_in_merged": sum(len(m) for m in merged),
           "candidate_pairs": res["candidate_pairs"], "all_pairs": len(recs) * (len(recs) - 1) // 2, "review_pairs": len(res["review"]),
           "merges_refused_for_conflicting_tax_ids": res["refused_tax_conflicts"], "examples": examples, "kept_apart": near, "model": engine.RESOLVER_VERSION,
           "version": model_version(t), "weights": weights,
           "simulation_truth": {"true_suppliers": len(set(tl)), "resolver": engine.pairwise_scores(cl, tl),
                                "exact_name_baseline": engine.pairwise_scores(engine.baseline_clusters(recs), tl),
                                "fuzzy_name_baseline": engine.pairwise_scores(engine.baseline_clusters(recs, "fuzzy", matcher.fuzzy_threshold_), tl),
                                "note": "scored against the generator's true supplier behind each vendor record; the resolver never reads this"}}
    audit.record(c, worker_ctx(job), "suppliers.resolved", "supplier", "all", {"records": len(recs), "suppliers": len(members), "review": len(res["review"])})
    return out


# --- document-extractor ------------------------------------------------------------------------------------------------------
class ExtractIn(BaseModel):
    status: Literal["received"] = "received"


@app.post("/v1/documents/extract", status_code=202, tags=["documents"], summary="(+) 202 + job: read every received supplier disclosure (revenue, scope 1, 2 and 3 upstream with their units and scale), validate it, match it and its principal suppliers to resolved suppliers. Accepted ones can become supplier-specific factors; the rest go to review with the reason")
def extract_documents(body: ExtractIn, ctx: Ctx = Depends(auth("documents:extract")), idem: str | None = IdemKey):
    def work(c):
        group(c)
        if not c.execute("SELECT 1 FROM supplier LIMIT 1").fetchone():
            raise Problem(409, "suppliers_not_resolved", "resolve suppliers first: disclosures are matched to resolved suppliers")
        return 202, jobs.enqueue(c, ctx, "documents.extract", body.model_dump())
    return run(ctx, idem, body, work)


def supplier_index(c):
    rows = c.execute("SELECT a.supplier_id, a.name FROM supplier_alias a WHERE a.supplier_id IS NOT NULL ORDER BY a.vendor_ref").fetchall()
    names = [engine.norm_name(r["name"]) for r in rows]
    vec = engine.name_vectorizer().fit(names)
    return rows, names, vec, vec.transform(names)


@jobs.handler("documents.extract")
def extract_job(c, job):
    t = job["tenant_id"]
    g = group(c)
    docs = c.execute("SELECT id, subject, content FROM assurance_evidence WHERE kind = 'disclosure' AND status = 'received' ORDER BY subject").fetchall()
    rows, names, vec, X = supplier_index(c)
    sup = {r["id"]: r for r in c.execute("SELECT id, name, main_category, country FROM supplier")}
    spend = {r["sid"]: r["usd"] for r in c.execute("""WITH v AS (SELECT vendor_ref, category, sum(amount_usd) AS usd FROM activity WHERE kind = 'ap' GROUP BY 1, 2)
                                                        SELECT sa.supplier_id AS sid, sum(v.usd) AS usd FROM v JOIN supplier_alias sa ON sa.vendor_ref = v.vendor_ref
                                                          JOIN supplier s ON s.id = sa.supplier_id WHERE v.category = s.main_category GROUP BY 1""")}
    cat_f = {r["id"]: r["value"] for r in c.execute("SELECT id, value FROM emission_factor WHERE version = %s AND kind = 'spend'", [g["current_factor_version"]])}
    accepted, review, runs, tasks = [], [], [], []
    for d in docs:
        x = engine.extract(d["content"])
        value, why = engine.validate_disclosure(x)
        j, score = engine.match_name(x["company"] or "", names, X, vec)
        s_id = rows[j]["supplier_id"] if j is not None else None
        if s_id is None:
            why = why + [f"company '{x['company']}' matches no resolved supplier (best similarity {score:.2f})"]
        ups = []
        for pn in x["principal_suppliers"]:
            k, _ = engine.match_name(pn, names, X, vec)
            if k is not None and rows[k]["supplier_id"] != s_id:
                ups.append(str(rows[k]["supplier_id"]))
        status = "accepted" if value is not None and s_id else "review"
        ext = {**x, "intensity_kg_per_usd": value, "match_score": round(score, 3), "principal_supplier_ids": ups, "reasons": why, "extractor": engine.EXTRACTOR_VERSION}
        c.execute("UPDATE assurance_evidence SET extracted = %s, status = %s, supplier_id = %s WHERE id = %s", [Jsonb(jsonable_encoder(ext)), status, s_id, d["id"]])
        runs.append((t, engine.EXTRACTOR_VERSION, model_version(t), f"evidence:{d['id']}", sha(d["content"])[:16], Jsonb({"status": status, "intensity": value})))
        item = {"evidence_id": d["id"], "supplier_id": s_id, "supplier": sup[s_id]["name"] if s_id else x["company"], "intensity_kg_per_usd": round(value, 4) if value else None,
                "revenue_usd": round(x["revenue_usd"]) if x["revenue_usd"] else None, "scope1_t": x["scope1_t"], "scope2_t": x["scope2_t"], "scope3_upstream_t": x["scope3_upstream_t"],
                "assurance": x["assurance"], "principal_suppliers": len(ups), "reasons": why}
        if s_id:
            s = sup[s_id]
            sector = cat_f.get(engine.spend_factor_id(s["main_category"], s["country"])) if s["main_category"] in world.CATEGORIES and s["main_category"] not in world.COVERED else None
            item.update(category=s["main_category"], sector_factor=sector, spend_covered_usd=round(spend.get(s_id) or 0))
        (accepted if status == "accepted" else review).append(item)
        if status == "review":
            tasks.append((t, uuid.uuid4(), "disclosure", str(d["id"]), Jsonb(jsonable_encoder(item)), float(item.get("spend_covered_usd") or 0)))
    db.load(c, "model_runs", ["tenant_id", "model_name", "version", "subject", "inputs_hash", "result"], runs)
    db.load(c, "review_task", ["tenant_id", "id", "kind", "subject", "detail", "weight"], tasks)
    example = next((d for d in docs if any(a["evidence_id"] == d["id"] for a in accepted)), None)
    w = world.company(g["model_seed"])
    truth = {sha(x["text"]): x for x in world.disclosures(g["model_seed"], year=g["reporting_year"] - 1)}
    ok_fields = tot_fields = 0
    for d in docs:
        tr, ex = truth.get(sha(d["content"])), engine.extract(d["content"])
        if tr:
            for f, tv in (("revenue_usd", tr["truth"]["revenue_usd"] * (1000 if tr["truth"]["unit_slip"] else 1)), ("scope1_t", tr["truth"]["scope1_t"]),
                          ("scope2_t", tr["truth"]["scope2_t"]), ("scope3_upstream_t", tr["truth"]["scope3_upstream_t"])):
                if tv is not None:
                    tot_fields += 1
                    ok_fields += ex[f] is not None and abs(ex[f] / tv - 1) < 0.01
    by_sid = {}
    for r in c.execute("SELECT vendor_ref, supplier_id FROM supplier_alias"):
        by_sid.setdefault(r["supplier_id"], []).append(r["vendor_ref"])
    rec_sup = {r["vendor_ref"]: r["supplier"] for r in w["records"]}
    matched_right = sum(1 for a in accepted + review if a["supplier_id"] and truth.get(sha(next(d["content"] for d in docs if d["id"] == a["evidence_id"])), {}).get("supplier")
                        in {rec_sup[v] for v in by_sid.get(a["supplier_id"], [])})
    out = {"documents": len(docs), "accepted": accepted, "review": review, "edges": sum(a["principal_suppliers"] for a in accepted + review),
           "example": {"text": example["content"], "extracted": next(a for a in accepted if a["evidence_id"] == example["id"])} if example else None,
           "model": engine.EXTRACTOR_VERSION,
           "simulation_truth": {"fields_read_within_1pct": f"{ok_fields} of {tot_fields}", "documents_matched_to_the_right_supplier": f"{matched_right} of {len(docs)}",
                                "note": "checked against the figures the generator wrote into each document (the unit slip is its, not the extractor's); the extractor never reads this"}}
    audit.record(c, worker_ctx(job), "documents.extracted", "assurance_evidence", "disclosures", {"documents": len(docs), "accepted": len(accepted), "review": len(review)})
    return out


# --- factor-registry ---------------------------------------------------------------------------------------------------------
class VersionIn(BaseModel):
    id: str = Field(pattern=r"^EF-\d{4}\.\d+(-[A-Z0-9]{1,8})?$")
    based_on: str = Field(pattern=r"^EF-\d{4}\.\d+(-[A-Z0-9]{1,8})?$")
    include: Literal["accepted_disclosures"] = "accepted_disclosures"
    notes: str = Field("", max_length=300)


@app.post("/v1/factor-versions", status_code=201, tags=["factors"], summary="(+) Propose a new factor version: a frozen version plus supplier-specific factors from accepted disclosures. It stays a draft, unusable by calculations, until a lead who did not propose it approves; approval freezes it for good")
def propose_version(body: VersionIn, ctx: Ctx = Depends(auth("factors:propose")), idem: str | None = IdemKey):
    def work(c):
        group(c)
        base = c.execute("SELECT * FROM factor_version WHERE id = %s", [body.based_on]).fetchone()
        if not base:
            raise Problem(404, "version_not_found", body.based_on)
        if base["status"] != "frozen":
            raise Problem(409, "base_not_frozen", "a version can only build on a frozen one")
        if c.execute("SELECT 1 FROM factor_version WHERE id = %s", [body.id]).fetchone():
            raise Problem(409, "version_exists", body.id)
        docs = c.execute("""SELECT e.id, e.supplier_id, e.extracted, s.name, s.main_category, s.country FROM assurance_evidence e JOIN supplier s ON s.id = e.supplier_id
                             WHERE e.kind = 'disclosure' AND e.status = 'accepted' ORDER BY s.name""").fetchall()
        docs = [d for d in docs if d["main_category"] in world.CATEGORIES and d["main_category"] not in world.COVERED]
        if not docs:
            raise Problem(409, "nothing_to_add", "no accepted disclosures: POST /v1/documents/extract first")
        c.execute("INSERT INTO factor_version (tenant_id, id, based_on, notes, created_by) VALUES (%s,%s,%s,%s,%s)",
                  [ctx.tenant_id, body.id, body.based_on, body.notes or f"{body.based_on} plus {len(docs)} supplier-specific factors", ctx.actor_id])
        c.execute("""INSERT INTO emission_factor (tenant_id, version, id, kind, category, geography, year, unit, value, gsd, dispersion, source, supplier_id, evidence_id)
                     SELECT tenant_id, %s, id, kind, category, geography, year, unit, value, gsd, dispersion, source, supplier_id, evidence_id
                       FROM emission_factor WHERE version = %s""", [body.id, body.based_on])
        sector = {r["id"]: r["value"] for r in c.execute("SELECT id, value FROM emission_factor WHERE version = %s AND kind = 'spend'", [body.based_on])}
        added = []
        for d in docs:
            v = d["extracted"]["intensity_kg_per_usd"]
            sf = sector[engine.spend_factor_id(d["main_category"], d["country"])]
            c.execute("""INSERT INTO emission_factor (tenant_id, version, id, kind, category, geography, year, unit, value, gsd, dispersion, source, supplier_id, evidence_id)
                         VALUES (%s,%s,%s,'supplier',%s,%s,%s,'kgCO2e/USD',%s,1.1,0,%s,%s,%s) ON CONFLICT DO NOTHING""",
                      [ctx.tenant_id, body.id, f"SUP:{d['supplier_id']}", d["main_category"], d["country"], world.YEAR - 1, v,
                       f"supplier disclosure FY{world.YEAR - 1} ({d['extracted'].get('assurance') or 'no'} assurance)", d["supplier_id"], d["id"]])
            added.append({"factor_id": f"SUP:{d['supplier_id']}", "supplier": d["name"], "category": d["main_category"], "value": round(v, 4), "replaces_sector_factor": sf,
                          "ratio": round(v / sf, 2)})
        did = uuid.uuid4()
        rationale = {"version": body.id, "based_on": body.based_on, "added": added}
        c.execute("INSERT INTO decision_record (tenant_id, id, kind, subject, rationale, proposed_by) VALUES (%s,%s,'adopt_factor_version',%s,%s,%s)",
                  [ctx.tenant_id, did, body.id, Jsonb(rationale), ctx.actor_id])
        audit.record(c, ctx, "factor_version.proposed", "factor_version", body.id, {"based_on": body.based_on, "supplier_factors": len(added), "decision": str(did)})
        return 201, {"decision_id": did, "status": "proposed", "version": body.id, "version_status": "draft", "based_on": body.based_on, "added": added}
    return run(ctx, idem, body, work)


@app.get("/v1/factor-versions", tags=["factors"], summary="(+) Factor versions: status, content hash, and their factors (with `id`)")
def versions(id: str | None = None, kind: str | None = None, ctx: Ctx = Depends(auth("carbon:read"))):
    with db.tx(ctx.tenant_id) as c:
        vs = c.execute("SELECT * FROM factor_version ORDER BY id").fetchall()
        fs = c.execute("SELECT * FROM emission_factor WHERE version = %s AND (%s::text IS NULL OR kind = %s) ORDER BY id", [id, kind, kind]).fetchall() if id else None
    return jsonable_encoder({"versions": vs, "factors": fs})


# --- decisions ------------------------------------------------------------------------------------------------------------------
@app.post("/v1/decisions/{decision_id}/approve", tags=["decisions"], summary="(+) A lead approves or rejects a proposal; never the person who proposed it. Approving a factor version freezes it and makes it current; approving an inventory publishes it")
def approve(decision_id: uuid.UUID, decision: Literal["approved", "rejected"] = "approved", ctx: Ctx = Depends(auth("decisions:approve")), idem: str | None = IdemKey):
    def work(c):
        d = c.execute("SELECT * FROM decision_record WHERE id = %s FOR UPDATE", [decision_id]).fetchone()
        if not d:
            raise Problem(404, "decision_not_found")
        if d["status"] != "proposed":
            raise Problem(409, "already_decided", f"this decision is {d['status']}")
        if d["proposed_by"] == ctx.actor_id:
            raise Problem(403, "proposer_cannot_approve", "a second person must approve")
        c.execute("UPDATE decision_record SET status = %s, decided_by = %s, decided_at = now() WHERE id = %s", [decision, ctx.actor_id, decision_id])
        out = {"decision_id": decision_id, "kind": d["kind"], "subject": d["subject"], "status": decision}
        if decision == "approved" and d["kind"] == "adopt_factor_version":
            freeze(c, d["subject"])
            c.execute("UPDATE organization SET current_factor_version = %s WHERE kind = 'group'", [d["subject"]])
            out["version"] = c.execute("SELECT id, status, content_hash, frozen_at FROM factor_version WHERE id = %s", [d["subject"]]).fetchone()
        elif decision == "approved":
            c.execute("UPDATE calculation SET status = 'published', published_at = now() WHERE id = %s", [d["subject"]])
            out["published"] = True
        elif d["kind"] == "adopt_factor_version":
            c.execute("DELETE FROM emission_factor WHERE version = %s", [d["subject"]])
            c.execute("DELETE FROM factor_version WHERE id = %s", [d["subject"]])
        audit.record(c, ctx, f"{d['kind']}.{decision}", d["kind"], d["subject"], {"decision": str(decision_id)})
        return 200, out
    return run(ctx, idem, {"decision": decision}, work)


@app.get("/v1/decisions", tags=["decisions"], summary="(+) Proposals and decisions")
def decisions(ctx: Ctx = Depends(auth("carbon:read"))):
    with db.tx(ctx.tenant_id) as c:
        return jsonable_encoder({"items": c.execute("SELECT id, kind, subject, status, proposed_by, decided_by, created_at, decided_at FROM decision_record ORDER BY created_at DESC").fetchall()})


@app.get("/v1/review-tasks", tags=["decisions"], summary="(+) The operations inbox: lines the classifier abstained on, uncertain supplier matches, disclosures it could not accept; largest spend first")
def review_tasks(kind: Literal["category", "supplier_match", "disclosure"] | None = None, limit: int = Query(20, ge=1, le=200), ctx: Ctx = Depends(auth("carbon:read"))):
    with db.tx(ctx.tenant_id) as c:
        rows = c.execute("""SELECT id, kind, subject, detail, weight, status, created_at FROM review_task WHERE status = 'open' AND (%s::text IS NULL OR kind = %s)
                             ORDER BY weight DESC LIMIT %s""", [kind, kind, limit]).fetchall()
        counts = c.execute("SELECT kind, count(*) AS n, sum(weight) AS weight FROM review_task WHERE status = 'open' GROUP BY kind").fetchall()
    return jsonable_encoder({"counts": counts, "items": rows})


# --- emissions-engine and uncertainty-service ---------------------------------------------------------------------------------
class CalcIn(BaseModel):
    factor_version: str | None = Field(None, description="a frozen version; default: the company's current one")


@app.post("/v1/calculations", status_code=202, tags=["calculations"], summary="(+) 202 + job: calculate Scope 1, 2 and 3 for every activity line with one frozen factor version, store a lineage row per line, propagate uncertainty by Monte Carlo, and hash the result so it can be reproduced bit for bit")
def calculate(body: CalcIn, ctx: Ctx = Depends(auth("calculations:run")), idem: str | None = IdemKey):
    def work(c):
        g = group(c)
        v = body.factor_version or g["current_factor_version"]
        fv = c.execute("SELECT status FROM factor_version WHERE id = %s", [v]).fetchone()
        if not fv:
            raise Problem(404, "version_not_found", v)
        if fv["status"] != "frozen":
            raise Problem(409, "version_not_frozen", f"{v} is a draft; a calculation only runs on a frozen version, so it can be reproduced")
        if not c.execute("SELECT 1 FROM activity LIMIT 1").fetchone():
            raise Problem(409, "no_activities", "import activity data first")
        return 202, jobs.enqueue(c, ctx, "calculations.run", {"factor_version": v}, max_attempts=2)
    return run(ctx, idem, body, work)


LINES_SQL = """CREATE TEMP TABLE _x ON COMMIT DROP AS
  WITH x AS (SELECT a.id, a.kind, coalesce(a.category, '') AS cat, coalesce(CASE WHEN a.kind = 'ap' THEN sa.country ELSE f.country END, '') AS country,
                    coalesce(sa.supplier_id::text, a.vendor_ref, '') AS sup, coalesce(a.mode, '') AS mode, coalesce(a.fuel, '') AS fuel, a.subsidiary,
                    coalesce(CASE a.kind WHEN 'ap' THEN a.amount_usd WHEN 'freight' THEN a.tkm ELSE a.qty_norm END, 0) AS q, coalesce(a.amount_usd, 0) AS usd
               FROM activity a LEFT JOIN supplier_alias sa ON a.kind = 'ap' AND sa.vendor_ref = a.vendor_ref
               LEFT JOIN facility f ON a.kind = 'utility' AND f.id = a.facility_id)
  SELECT *, dense_rank() OVER (ORDER BY kind, cat, country, sup, mode, fuel, subsidiary) - 1 AS k FROM x"""
COMBO_FIELDS = ["kind", "category", "country", "supplier", "mode", "fuel", "subsidiary"]


def fetch_activities(c):
    """Every activity line as numbers (id, combination index, quantity, USD), plus the few thousand distinct combinations of
    kind, category, country, supplier, mode, fuel and subsidiary that decide its factor. Two million lines never become
    two million Python strings."""
    c.execute(LINES_SQL)
    combos = c.execute("SELECT DISTINCT k, kind, cat, country, sup, mode, fuel, subsidiary FROM _x ORDER BY k").fetchall()
    C = {f: np.array([r[col] for r in combos], dtype=object) for f, col in zip(COMBO_FIELDS, ["kind", "cat", "country", "sup", "mode", "fuel", "subsidiary"])}
    parts = []
    with c.cursor(name="lines", row_factory=tuple_row) as cur:
        cur.execute("SELECT id, k, q, usd FROM _x ORDER BY id")
        while rows := cur.fetchmany(250_000):
            parts.append(np.array(rows, dtype=float))
    c.execute("DROP TABLE _x")
    L = np.concatenate(parts) if parts else np.zeros((0, 4))
    return C, {"id": L[:, 0].astype(np.int64), "k": L[:, 1].astype(np.int64), "q": L[:, 2], "usd": L[:, 3]}


def load_factors(c, version):
    rows = c.execute("SELECT * FROM emission_factor WHERE version = %s", [version]).fetchall()
    factors = {r["id"]: r for r in rows}
    sup = {f"{r['supplier_id']}|{r['category']}": r["id"] for r in rows if r["kind"] == "supplier"}
    return factors, sup


def calc_lines(C, L, factors, sup):
    """The engine on each combination (unit quantity), then every line = its quantity x its combination's factor."""
    n = len(C["kind"])
    cfid, cmethod, cscope, cval = engine.calculate({**C, "amount_usd": np.ones(n), "tkm": np.ones(n), "qty_norm": np.ones(n)}, factors, sup)
    kg = L["q"] * cval[L["k"]]
    return {"fid": cfid, "method": cmethod, "scope": cscope}, kg


def compute(c, version):
    C, L = fetch_activities(c)
    factors, sup = load_factors(c, version)
    K, kg = calc_lines(C, L, factors, sup)
    return C, L, factors, K, kg


def line_hash(L, K, kg):
    return engine.result_hash(L["id"], K["fid"][L["k"]], kg)


def summarise(c, C, L, factors, K, kg):
    """Totals by scope, GHG category, spend category, method, subsidiary and supplier, the orphans, and the Monte Carlo bands,
    all from per-combination sums."""
    n = len(C["kind"])
    ckg = np.bincount(L["k"], weights=kg, minlength=n)
    cusd = np.bincount(L["k"], weights=np.abs(L["usd"]), minlength=n)
    cnt = np.bincount(L["k"], minlength=n)
    ap = C["kind"] == "ap"
    s3c = engine.s3_categories(C["kind"], C["category"])
    method, scope = K["method"], K["scope"]
    t = lambda m: round(float(ckg[m].sum()) / 1000, 1)        # noqa: E731
    groups = engine.mc_groups(K["fid"], C["supplier"], scope, s3c, np.where(ap, C["category"], ""), ckg, factors)
    mc = engine.monte_carlo(groups, factors)
    by_method = {m: {"lines": int(cnt[method == m].sum()), "t": t(method == m), "spend_usd": round(float(cusd[(method == m) & ap].sum()))}
                 for m in ("spend-based", "supplier-specific", "activity", "covered", "unmapped")}
    keyed = ap & np.isin(method, ["spend-based", "supplier-specific"])
    sup_t = collections.Counter()
    for s, v in zip(C["supplier"][keyed], ckg[keyed]):
        sup_t[s] += v / 1000
    top = sup_t.most_common(12)
    names = supplier_names(c, [k for k, _ in top])
    un = method == "unmapped"
    return {"scope": {str(s): t(scope == s) for s in (1, 2, 3)}, "total_t": t(scope > 0),
            "scope3_categories": {str(k): t(s3c == k) for k in (1, 2, 4, 6)},
            "spend_categories": {k: t(ap & (C["category"] == k)) for k in world.CATS if k not in world.COVERED},
            "freight_by_mode": {m: t(C["mode"] == m) for m in world.MODES},
            "by_method": by_method, "by_subsidiary": {s: t(C["subsidiary"] == s) for s in world.SUB_CODES},
            "top_suppliers": [{"key": k, "name": names.get(k, k), "t": round(v, 1)} for k, v in top],
            "orphans": {"lines": int(cnt[un].sum()), "rate": round(float(cnt[un].sum() / max(1, cnt[ap].sum())), 4),
                        "spend_share": round(float(cusd[un].sum() / max(1e-9, cusd[ap].sum())), 4)},
            "uncertainty": {**mc, "draws": engine.DRAWS, "how": "one draw per factor shared by every line that uses it, and one per supplier around its sector mean for spend-based lines"}}


def supplier_names(c, keys):
    ids = [k for k in keys if len(k) == 36]
    out = {str(r["id"]): r["name"] for r in c.execute("SELECT id, name FROM supplier WHERE id = ANY(%s::uuid[])", [ids])} if ids else {}
    out.update({r["vendor_ref"]: r["name"] for r in c.execute("SELECT vendor_ref, name FROM supplier_alias WHERE vendor_ref = ANY(%s)", [[k for k in keys if len(k) != 36]])})
    return out


def coverage(c, calc_id, version):
    """Lines carrying a CO2e figure whose every link exists (source record, import batch, mapping and model call for invoices,
    factor in the frozen version) and whose figure re-derives from them."""
    r = c.execute("""SELECT count(*) AS carrying,
                            count(*) FILTER (WHERE a.source_ref IS NOT NULL AND b.id IS NOT NULL AND f.id IS NOT NULL
                                               AND (a.kind <> 'ap' OR (a.category IS NOT NULL AND a.input_hash IS NOT NULL))
                                               AND abs(l.co2e_kg - CASE a.kind WHEN 'ap' THEN a.amount_usd WHEN 'freight' THEN a.tkm ELSE a.qty_norm END * f.value)
                                                   <= 1e-6 * greatest(1, abs(l.co2e_kg))) AS complete
                       FROM calculation_lineage l JOIN activity a ON a.id = l.activity_id JOIN import_batch b ON b.id = a.batch_id
                       LEFT JOIN emission_factor f ON f.version = %s AND f.id = l.factor_id
                      WHERE l.calculation_id = %s AND l.method IN ('spend-based', 'supplier-specific', 'activity')""", [version, calc_id]).fetchone()
    return r["complete"] / max(1, r["carrying"]), r


def inputs_hash(C, L):
    return engine.arrays_hash(L["id"], L["q"], L["usd"], *[C[f][L["k"]] for f in ("kind", "category", "country", "supplier", "mode", "fuel")])


def _tsv(v):
    return "\\N" if v is None or v == "" else str(v)


@jobs.handler("calculations.run")
def calc_job(c, job):
    t0 = time.time()
    t, v = job["tenant_id"], job["payload"]["factor_version"]
    C, L, factors, K, kg = compute(c, v)
    t1 = time.time()
    totals = summarise(c, C, L, factors, K, kg)
    cid = uuid.uuid4()
    rhash, ihash = line_hash(L, K, kg), inputs_hash(C, L)
    multi = {r["k"] for r in c.execute("SELECT supplier_id::text AS k FROM supplier_alias WHERE supplier_id IS NOT NULL GROUP BY 1 HAVING count(*) >= 2")}
    okc = np.array([m == "spend-based" and s in multi for m, s in zip(K["method"], C["supplier"])])
    cand = np.nonzero(okc[L["k"]])[0]
    totals["trace_example"] = int(L["id"][cand[np.argmax(kg[cand])]]) if len(cand) else int(L["id"][np.argmax(kg)])
    t2 = time.time()
    c.execute("""INSERT INTO calculation (tenant_id, id, factor_version, lines, totals, result_hash, inputs_hash, lineage_coverage, model_versions, created_by)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,0,%s,%s)""",
              [t, cid, v, len(kg), Jsonb(jsonable_encoder(totals)), rhash, ihash,
               Jsonb({"classifier": engine.CLASSIFIER_VERSION, "resolver": engine.RESOLVER_VERSION, "extractor": engine.EXTRACTOR_VERSION, "models": model_version(t)}),
               uuid.UUID(job["payload"]["actor_id"])])
    ap = C["kind"] == "ap"
    lcat = np.where(ap, C["category"], np.where(C["kind"] == "freight", C["mode"], C["fuel"]))
    prefix = f"{t}\t{cid}\t"
    combo = [f"{_tsv(s if a else None)}\t{sc}\t{_tsv(ct)}\t{m}\t{_tsv(f)}" for s, a, sc, ct, m, f in zip(C["supplier"], ap, K["scope"], lcat, K["method"], K["fid"])]
    c.execute("CREATE TEMP TABLE _lin (LIKE calculation_lineage) ON COMMIT DROP")
    cols = ["tenant_id", "calculation_id", "activity_id", "supplier_key", "scope", "category", "method", "factor_id", "co2e_kg"]
    ids, ks, kgs = L["id"].tolist(), L["k"].tolist(), kg.tolist()
    with c.cursor().copy(f"COPY _lin ({', '.join(cols)}) FROM STDIN") as cp:
        for s in range(0, len(ids), 100_000):
            cp.write("".join(f"{prefix}{i}\t{combo[k]}\t{x!r}\n" for i, k, x in zip(ids[s:s + 100_000], ks[s:s + 100_000], kgs[s:s + 100_000])))
    c.execute(f"INSERT INTO calculation_lineage ({', '.join(cols)}) SELECT {', '.join(cols)} FROM _lin")
    c.execute("DROP TABLE _lin")
    t3 = time.time()
    cov, counts = coverage(c, cid, v)
    c.execute("UPDATE calculation SET lineage_coverage = %s WHERE id = %s", [cov, cid])
    audit.record(c, worker_ctx(job), "calculation.run", "calculation", cid, {"factor_version": v, "lines": len(kg), "total_t": totals["total_t"], "result_hash": rhash})
    return {"calculation_id": cid, "factor_version": v, "lines": len(kg), "result_hash": rhash, "inputs_hash": ihash, "lineage_coverage": cov,
            "lines_carrying_co2e": counts["carrying"], "lines_with_complete_lineage": counts["complete"], "combinations": len(C["kind"]), **totals,
            "seconds": {"read_and_calculate": round(t1 - t0, 1), "uncertainty_and_totals": round(t2 - t1, 1), "store_lineage": round(t3 - t2, 1),
                        "check_lineage": round(time.time() - t3, 1), "total": round(time.time() - t0, 1)}}


class ReproduceIn(BaseModel):
    compare_with: str | None = Field(None, description="also recalculate (without storing) under this frozen version and show the bridge")


@app.post("/v1/calculations/{calc_id}:reproduce", status_code=202, tags=["calculations"], summary="(+) 202 + job: recalculate from the stored activities with the calculation's frozen factor version and compare hashes line for line; optionally show what another version would give")
def reproduce(calc_id: uuid.UUID, body: ReproduceIn, ctx: Ctx = Depends(auth("calculations:run")), idem: str | None = IdemKey):
    def work(c):
        if not c.execute("SELECT 1 FROM calculation WHERE id = %s", [calc_id]).fetchone():
            raise Problem(404, "calculation_not_found")
        if body.compare_with and not c.execute("SELECT 1 FROM factor_version WHERE id = %s AND status = 'frozen'", [body.compare_with]).fetchone():
            raise Problem(409, "version_not_frozen", f"{body.compare_with} is unknown or a draft")
        return 202, jobs.enqueue(c, ctx, "calculations.reproduce", {"calculation_id": str(calc_id), "compare_with": body.compare_with}, max_attempts=2)
    return run(ctx, idem, body, work)


@jobs.handler("calculations.reproduce")
def reproduce_job(c, job):
    t0 = time.time()
    p, t = job["payload"], job["tenant_id"]
    calc = c.execute("SELECT * FROM calculation WHERE id = %s", [p["calculation_id"]]).fetchone()
    v = calc["factor_version"]
    stored_v = c.execute("SELECT content_hash FROM factor_version WHERE id = %s", [v]).fetchone()["content_hash"]
    C, L, factors, K, kg = compute(c, v)
    again, ihash = line_hash(L, K, kg), inputs_hash(C, L)
    parts = []
    fids = []
    with c.cursor(name="stored", row_factory=tuple_row) as cur:
        cur.execute("SELECT activity_id, co2e_kg, coalesce(factor_id, '') FROM calculation_lineage WHERE calculation_id = %s ORDER BY activity_id", [calc["id"]])
        while rows := cur.fetchmany(250_000):
            parts.append(np.array([r[:2] for r in rows], dtype=float))
            fids.extend(r[2] for r in rows)
    S = np.concatenate(parts) if parts else np.zeros((0, 2))
    stored_lines = engine.result_hash(S[:, 0].astype(np.int64), np.array(fids, dtype=object), S[:, 1])
    out = {"calculation_id": calc["id"], "factor_version": v, "version_hash_at_freeze": stored_v, "version_hash_now": version_hash(c, v),
           "result_hash_stored": calc["result_hash"], "result_hash_recalculated": again, "result_hash_of_stored_lines": stored_lines,
           "inputs_unchanged": ihash == calc["inputs_hash"], "lines": len(kg)}
    out["identical"] = out["version_hash_at_freeze"] == out["version_hash_now"] and again == calc["result_hash"] == stored_lines
    if p.get("compare_with"):
        f2, sup2 = load_factors(c, p["compare_with"])
        K2, kg2 = calc_lines(C, L, f2, sup2)
        n = len(C["kind"])
        c1, c2 = np.bincount(L["k"], weights=kg, minlength=n), np.bincount(L["k"], weights=kg2, minlength=n)
        ap = C["kind"] == "ap"
        row = lambda name, sel: {"category": name, "this_t": round(float(c1[sel].sum()) / 1000, 1), "other_t": round(float(c2[sel].sum()) / 1000, 1)}     # noqa: E731
        bridge = [row(k, ap & (C["category"] == k)) for k in world.CATS if k not in world.COVERED]
        bridge += [row("scope 1 (energy)", K["scope"] == 1), row("scope 2 (energy)", K["scope"] == 2), row("freight (shipments)", C["kind"] == "freight")]
        out["compare_with"] = {"version": p["compare_with"], "total_t": round(float(kg2.sum()) / 1000, 1), "this_total_t": round(float(kg.sum()) / 1000, 1),
                               "lines_changed": int((np.abs(kg2 - kg) > 1e-9).sum()), "bridge": bridge,
                               "methods": {m: int(np.bincount(L["k"], minlength=n)[K2["method"] == m].sum()) for m in ("spend-based", "supplier-specific")}}
    out["seconds"] = round(time.time() - t0, 1)
    eid = uuid.uuid4()
    body = json.dumps(jsonable_encoder(out), sort_keys=True)
    c.execute("INSERT INTO assurance_evidence (tenant_id, id, kind, subject, content, sha256, status) VALUES (%s,%s,'reproduction',%s,%s,%s,%s)",
              [t, eid, str(calc["id"]), body, sha(body), "identical" if out["identical"] else "different"])
    audit.record(c, worker_ctx(job), "calculation.reproduced", "calculation", calc["id"], {"identical": out["identical"], "evidence": str(eid)})
    return {**out, "evidence_id": eid}


def calc_or_latest(c, calc_id):
    calc = c.execute("SELECT * FROM calculation WHERE id = %s", [calc_id]).fetchone() if calc_id else \
        c.execute("SELECT * FROM calculation ORDER BY created_at DESC LIMIT 1").fetchone()
    if not calc:
        raise Problem(404, "calculation_not_found", "run POST /v1/calculations first" if not calc_id else "")
    return calc


@app.get("/v1/inventory/scope3", tags=["calculations"], summary="The Scope 3 inventory of a calculation (default: the latest): GHG categories with 95% Monte Carlo intervals, spend categories, methods, the suppliers that matter, orphans and lineage coverage, beside Scope 1 and 2")
def inventory(calculation_id: uuid.UUID | None = None, ctx: Ctx = Depends(auth("carbon:read"))):
    with db.tx(ctx.tenant_id) as c:
        g = group(c)
        calc = calc_or_latest(c, calculation_id)
    T = calc["totals"]
    u = T["uncertainty"]
    band = lambda k: {kk: u[k][kk] for kk in ("t", "p2_5", "p97_5")} if k in u else None      # noqa: E731
    return jsonable_encoder({"company": g["name"], "year": g["reporting_year"], "calculation_id": calc["id"], "factor_version": calc["factor_version"], "status": calc["status"],
                             "result_hash": calc["result_hash"], "lineage_coverage": calc["lineage_coverage"], "lines": calc["lines"],
                             "scope3_t": band("scope3"), "scope1_t": band("scope1"), "scope2_t": band("scope2"), "total_t": band("total"),
                             "ghg_categories": [{"category": k, "name": {"1": "Purchased goods and services", "2": "Capital goods", "4": "Upstream transportation", "6": "Business travel"}[k],
                                                 **(band(f"s3:{k}") or {"t": 0})} for k in ("1", "2", "4", "6")],
                             "spend_categories": [{"category": k, "name": world.CATEGORIES[k][0], **(band(f"cat:{k}") or {"t": v})} for k, v in sorted(T["spend_categories"].items(), key=lambda x: -x[1])],
                             "freight_by_mode": T["freight_by_mode"], "by_method": T["by_method"], "by_subsidiary": T["by_subsidiary"], "top_suppliers": T["top_suppliers"],
                             "orphans": T["orphans"], "trace_example": T["trace_example"], "uncertainty_method": u["how"], "draws": u["draws"]})


@app.get("/v1/calculations/{calc_id}/lineage", tags=["calculations"], summary="Lineage. With `activity_id`: one CO2e figure traced to its invoice line (or shipment or bill), the import, the normalisation, the category mapping and the model call, the resolved supplier with the evidence that joined its records, and the factor in its frozen version, with the arithmetic re-done. Without: coverage across the calculation")
def lineage(calc_id: uuid.UUID, activity_id: int | None = None, ctx: Ctx = Depends(auth("carbon:read"))):
    with db.tx(ctx.tenant_id) as c:
        calc = c.execute("SELECT id, factor_version, status, result_hash, lineage_coverage, lines, totals->'by_method' AS by_method FROM calculation WHERE id = %s", [calc_id]).fetchone()
        if not calc:
            raise Problem(404, "calculation_not_found")
        if activity_id is None:
            return jsonable_encoder({**calc, "how": "every line carrying a CO2e figure has its source record, import batch, mapping and model call, and a factor of the frozen version; and its figure re-derives from them"})
        ln = c.execute("SELECT * FROM calculation_lineage WHERE calculation_id = %s AND activity_id = %s", [calc_id, activity_id]).fetchone()
        if not ln:
            raise Problem(404, "line_not_found")
        a = c.execute("SELECT * FROM activity WHERE id = %s", [activity_id]).fetchone()
        batch = c.execute("SELECT id, connector, created_at FROM import_batch WHERE id = %s", [a["batch_id"]]).fetchone()
        f = c.execute("SELECT * FROM emission_factor WHERE version = %s AND id = %s", [calc["factor_version"], ln["factor_id"]]).fetchone() if ln["factor_id"] else None
        fv = c.execute("SELECT id, status, content_hash, frozen_at, based_on FROM factor_version WHERE id = %s", [calc["factor_version"]]).fetchone()
        run_ = c.execute("SELECT model_name, version, inputs_hash, result, created_at FROM model_runs WHERE inputs_hash = %s ORDER BY id LIMIT 1", [a["input_hash"]]).fetchone() if a["input_hash"] else None
        rec = sup = others = doc = None
        if a["vendor_ref"]:
            rec = c.execute("SELECT vendor_ref, subsidiary, name, country, tax_id, email_domain, supplier_id, match_prob, evidence FROM supplier_alias WHERE vendor_ref = %s", [a["vendor_ref"]]).fetchone()
            if rec and rec["supplier_id"]:
                sup = c.execute("SELECT id, name, country, tax_id, main_category, records FROM supplier WHERE id = %s", [rec["supplier_id"]]).fetchone()
                others = c.execute("SELECT vendor_ref, subsidiary, name, match_prob FROM supplier_alias WHERE supplier_id = %s AND vendor_ref <> %s ORDER BY vendor_ref", [rec["supplier_id"], a["vendor_ref"]]).fetchall()
        if f and f["evidence_id"]:
            doc = c.execute("SELECT id, subject, sha256, extracted, created_at FROM assurance_evidence WHERE id = %s", [f["evidence_id"]]).fetchone()
    qty, unit = ((a["amount_usd"], "USD") if a["kind"] == "ap" else (a["tkm"], "tonne-km") if a["kind"] == "freight" else (a["qty_norm"], a["unit_norm"]))
    redo = qty * f["value"] if f else 0.0
    return jsonable_encoder({
        "calculation": {"id": calc["id"], "factor_version": calc["factor_version"], "status": calc["status"], "result_hash": calc["result_hash"]},
        "result": {"co2e_kg": ln["co2e_kg"], "scope": ln["scope"], "method": ln["method"], "category": ln["category"]},
        "arithmetic": {"quantity": qty, "unit": unit, "factor": f["value"] if f else None, "factor_unit": f["unit"] if f else None, "recomputed_kg": redo,
                       "matches": abs(redo - ln["co2e_kg"]) <= 1e-6 * max(1, abs(ln["co2e_kg"]))},
        "source": {"kind": a["kind"], "record": a["source_ref"], "subsidiary": a["subsidiary"], "period": a["period"], "description": a["description"], "gl_code": a["gl_code"],
                   "amount": a["amount"], "currency": a["currency"], "quantity": a["quantity"], "unit": a["unit"], "mode": a["mode"], "origin": a["origin"], "destination": a["destination"],
                   "import_batch": batch},
        "normalisation": {"fx_rate": a["fx_rate"], "amount_usd": a["amount_usd"], "qty_norm": a["qty_norm"], "unit_norm": a["unit_norm"], "distance_km": a["distance_km"], "tkm": a["tkm"]},
        "mapping": {"category": a["category"], "confidence": a["category_conf"], "method": a["mapping_method"], "input_hash": a["input_hash"], "model_call": run_},
        "vendor_record": rec, "supplier": sup, "other_records_of_this_supplier": others,
        "factor": f, "factor_version": fv, "disclosure": doc})


# --- supplier engagement ------------------------------------------------------------------------------------------------------
def engagement_data(c, calc):
    direct = {r["k"]: r["t"] for r in c.execute("""SELECT supplier_key AS k, sum(co2e_kg) / 1000 AS t FROM calculation_lineage
                                                     WHERE calculation_id = %s AND method IN ('spend-based', 'supplier-specific') GROUP BY 1""", [calc["id"]])}
    spend = {r["k"]: r for r in c.execute("""SELECT coalesce(sa.supplier_id::text, a.vendor_ref) AS k, sum(a.amount_usd) AS usd, count(DISTINCT a.subsidiary) AS subs
                                               FROM activity a LEFT JOIN supplier_alias sa ON sa.vendor_ref = a.vendor_ref WHERE a.kind = 'ap' GROUP BY 1""")}
    edges, docs = {}, {}
    for r in c.execute("SELECT supplier_id, status, extracted FROM assurance_evidence WHERE kind = 'disclosure' AND supplier_id IS NOT NULL"):
        docs[str(r["supplier_id"])] = r["status"]
        ups = [u for u in (r["extracted"] or {}).get("principal_supplier_ids", []) if u in direct]
        if ups:
            edges[str(r["supplier_id"])] = ups
    infl = engine.influence(direct, edges)
    return direct, spend, edges, docs, infl


def ranking(direct, spend, infl, by):
    keys = [k for k in spend if k in direct or k in infl]
    score = {"spend": lambda k: spend[k]["usd"] or 0, "emissions": lambda k: direct.get(k, 0), "influence": lambda k: infl.get(k, 0)}[by]
    return sorted(keys, key=lambda k: -score(k))


@app.get("/v1/suppliers/engagement", tags=["suppliers"], summary="(+) Which suppliers to engage first: each supplier's estimated emissions, plus what flows through it on the supplier network read from disclosures (emission-weighted Katz centrality), against ranking by spend")
def engagement(calculation_id: uuid.UUID | None = None, top: int = Query(TOP_ENGAGE, ge=1, le=100), ctx: Ctx = Depends(auth("carbon:read"))):
    with db.tx(ctx.tenant_id) as c:
        g = group(c)
        calc = calc_or_latest(c, calculation_id)
        direct, spend, edges, docs, infl = engagement_data(c, calc)
        order = {by: ranking(direct, spend, infl, by) for by in ("spend", "emissions", "influence")}
        pick = order["influence"][:top]
        names = supplier_names(c, list({k for v in order.values() for k in v[:top]}))
        customers = collections.defaultdict(list)
        for tt, ups in edges.items():
            for u in ups:
                customers[u].append(tt)
        cat1 = sum(direct.values())
        reach = {by: engine.covered_emissions(order[by][:top], direct, {tt: dict(zip(ups, _shares(ups))) for tt, ups in edges.items()}) for by in order}
        rows = [{"rank": n + 1, "key": k, "name": names.get(k, k), "direct_t": round(direct.get(k, 0), 1), "influence_t": round(infl.get(k, 0), 1),
                 "via": [names.get(x) or supplier_names(c, [x]).get(x, x) for x in customers.get(k, [])][:4], "spend_usd": round(spend[k]["usd"] or 0),
                 "subsidiaries": spend[k]["subs"], "rank_by_spend": order["spend"].index(k) + 1, "disclosure": docs.get(k)} for n, k in enumerate(pick)]
        truth = engagement_truth(g, c, order, top)
    return jsonable_encoder({"calculation_id": calc["id"], "top": top, "suppliers_ranked": len(order["influence"]), "network_edges": sum(len(v) for v in edges.values()),
                             "disclosing_suppliers": len(docs), "items": rows,
                             "estimated_reach_share": {by: round(reach[by] / max(1e-9, cat1), 3) for by in reach},
                             "overlap_with_spend_ranking": len(set(pick) & set(order["spend"][:top])),
                             "how": "influence = own estimated emissions + the share of each disclosing customer's footprint it supplies (listed principal suppliers, 60/40 of a default 45% embodied share)",
                             "simulation_truth": truth})


def _shares(ups):
    w = np.array([0.6, 0.4][:len(ups)] if len(ups) <= 2 else np.ones(len(ups)) / len(ups))
    return (w / w.sum() * engine.DEFAULT_UPSTREAM_SHARE).tolist()


def engagement_truth(g, c, order, top):
    """The generator's true emissions within reach of each ranking's top suppliers (the ranking never reads this)."""
    w = world.company(g["model_seed"])
    rec = {r["vendor_ref"]: r["supplier"] for r in w["records"]}
    key_to_true = {}
    for r in c.execute("SELECT vendor_ref, supplier_id FROM supplier_alias"):
        key_to_true.setdefault(str(r["supplier_id"]) if r["supplier_id"] else r["vendor_ref"], collections.Counter())[rec[r["vendor_ref"]]] += 1
        key_to_true.setdefault(r["vendor_ref"], collections.Counter())[rec[r["vendor_ref"]]] += 1
    true_e = {s["idx"]: s["spend_usd"] * sum(share * world.true_intensity(w, s, cat) for cat, share in s["mix"].items() if cat not in world.COVERED) / 1000 for s in w["suppliers"]}
    up = {s["idx"]: s["upstream"] for s in w["suppliers"] if s["upstream"]}
    tot = sum(true_e.values())
    out = {}
    for by, keys in order.items():
        picked = {key_to_true[k].most_common(1)[0][0] for k in keys[:top] if k in key_to_true}
        out[by] = round(engine.covered_emissions(picked, true_e, up) / tot, 3)
    return {"true_reach_share": out, "note": "share of the generator's true supplier emissions (own plus what each sells to our other suppliers) within reach of each ranking's top suppliers; the ranking never reads this"}


# --- scenario-service ----------------------------------------------------------------------------------------------------------
class FreightShift(BaseModel):
    from_mode: Literal["air", "road"] = "air"
    to_mode: Literal["ocean", "rail"] = "ocean"
    share: float = Field(ge=0, le=1)
    exclude_urgent: bool = True


class Decarbonise(BaseModel):
    top_n: int | None = Field(None, ge=1, le=200, description="the top suppliers of the engagement ranking")
    supplier_ids: list[str] | None = Field(None, max_length=200)
    reduction: float = Field(gt=0, le=0.9, description="cut in each supplier's carbon intensity")


class ScenarioIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    calculation_id: uuid.UUID | None = None
    freight_shift: FreightShift | None = None
    supplier_decarbonisation: Decarbonise | None = None


@app.post("/v1/scenarios", status_code=202, tags=["scenarios"], summary="202 + job: recalculate the inventory from every stored line under changed assumptions (freight moved between modes, suppliers decarbonising), with the same Monte Carlo draws for before and after so the change has its own interval; timed")
def scenario(body: ScenarioIn, ctx: Ctx = Depends(auth("scenarios:run")), idem: str | None = IdemKey):
    if not body.freight_shift and not body.supplier_decarbonisation:
        raise Problem(422, "nothing_to_change", "give freight_shift and/or supplier_decarbonisation")
    if body.supplier_decarbonisation and bool(body.supplier_decarbonisation.top_n) == bool(body.supplier_decarbonisation.supplier_ids):
        raise Problem(422, "pick_suppliers", "give either top_n or supplier_ids")

    def work(c):
        calc = calc_or_latest(c, body.calculation_id)
        return 202, jobs.enqueue(c, ctx, "scenarios.run", {**body.model_dump(mode="json"), "calculation_id": str(calc["id"])})
    return run(ctx, idem, body, work)


SCENARIO_SQL = """SELECT l.method, coalesce(l.factor_id, '') AS factor_id, coalesce(l.supplier_key, '') AS supplier, l.scope, coalesce(l.category, '') AS category, a.kind,
                         coalesce(a.mode, '') AS mode, coalesce(a.origin, '') AS origin, coalesce(a.destination, '') AS destination, coalesce(a.urgent, false) AS urgent,
                         sum(l.co2e_kg) AS kg, sum(a.qty_norm) FILTER (WHERE a.kind = 'freight') AS tonnes, count(*) AS n
                    FROM calculation_lineage l JOIN activity a ON a.id = l.activity_id
                   WHERE l.calculation_id = %s AND l.co2e_kg <> 0 GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10"""


@jobs.handler("scenarios.run")
def scenario_job(c, job):
    p, t = job["payload"], job["tenant_id"]
    t0 = time.time()
    calc = c.execute("SELECT * FROM calculation WHERE id = %s", [p["calculation_id"]]).fetchone()
    rows = c.execute(SCENARIO_SQL, [calc["id"]]).fetchall()
    t1 = time.time()
    factors, _ = load_factors(c, calc["factor_version"])
    groups = []
    for r in rows:
        s3 = 4 if r["kind"] == "freight" else (world.CATEGORIES[r["category"]][2] or 0) if r["kind"] == "ap" else 0
        groups.append({"method": r["method"], "factor_id": r["factor_id"], "supplier": r["supplier"] if factors[r["factor_id"]]["dispersion"] > 0 else "",
                       "supplier_key": r["supplier"], "kg": r["kg"], "mode": r["mode"] or None, "lane": (r["origin"], r["destination"]), "urgent": r["urgent"],
                       "tonnes": r["tonnes"] or 0.0, "lines": r["n"],
                       "buckets": ["total", f"scope{r['scope']}"] + ([f"s3:{s3}"] if r["scope"] == 3 else []) + ([f"cat:{r['category']}"] if r["kind"] == "ap" else [])})
    chosen, names, edges = [], {}, {}
    d = p.get("supplier_decarbonisation")
    if d:
        direct, spend, edges, docs, infl = engagement_data(c, calc)
        chosen = ranking(direct, spend, infl, "influence")[:d["top_n"]] if d.get("top_n") else d["supplier_ids"]
        names = supplier_names(c, chosen)
    eng = [{**g, "supplier": g["supplier_key"]} for g in groups]
    fs = p.get("freight_shift")
    new, notes = engine.scenario_kg(eng, factors, {"from": fs["from_mode"], "to": fs["to_mode"], "share": fs["share"], "exclude_urgent": fs["exclude_urgent"]} if fs else None,
                                    {"suppliers": chosen, "reduction": d["reduction"]} if d else None, edges)
    t2 = time.time()
    mc = engine.monte_carlo(groups, factors, scenario=new)
    t3 = time.time()
    keys = ["total", "scope3", "s3:1", "s3:2", "s3:4", "s3:6"]
    result = {"scenario_id": None, "calculation_id": calc["id"], "factor_version": calc["factor_version"], "name": p["name"],
              "results": {k: {"before": {kk: mc[k][kk] for kk in ("t", "p2_5", "p97_5")}, "after": {kk: mc[k]["scenario"][kk] for kk in ("t", "p2_5", "p97_5")},
                              "change": {kk: mc[k]["delta"][kk] for kk in ("t", "p2_5", "p97_5")}} for k in keys if k in mc},
              "freight": notes if fs else None,
              "suppliers": [{"key": k, "name": names.get(k, k)} for k in chosen][:30] if d else None,
              "levers": {"freight_shift": fs, "supplier_decarbonisation": d},
              "recalculation": {"activity_lines": int(sum(g["lines"] for g in groups)), "groups": len(groups), "seconds_scan": round(t1 - t0, 2),
                                "seconds_recalculate": round(t2 - t1, 2), "seconds_monte_carlo": round(t3 - t2, 2), "seconds_total": round(t3 - t0, 2)},
              "how": "the stored lines are re-aggregated and recalculated under the levers; before and after use the same Monte Carlo draws, so the change carries its own interval"}
    sid = uuid.uuid4()
    result["scenario_id"] = sid
    c.execute("INSERT INTO scenario (tenant_id, id, calculation_id, name, request, result, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s)",
              [t, sid, calc["id"], p["name"], Jsonb(p), Jsonb(jsonable_encoder(result)), uuid.UUID(p["actor_id"])])
    audit.record(c, worker_ctx(job), "scenario.run", "scenario", sid, {"calculation": str(calc["id"]), "change_t": result["results"]["total"]["change"]["t"]})
    return result


# --- publication and reporting -------------------------------------------------------------------------------------------------
class PublishIn(BaseModel):
    note: str = Field("", max_length=300)


@app.post("/v1/calculations/{calc_id}/publish", status_code=201, tags=["reporting"], summary="(+) Propose publishing an inventory. Policy checks first (complete lineage, orphan rate under 1%, a reproduction that matched); then a lead who did not propose it must approve")
def propose_publish(calc_id: uuid.UUID, body: PublishIn, ctx: Ctx = Depends(auth("decisions:propose")), idem: str | None = IdemKey):
    def work(c):
        calc = c.execute("SELECT * FROM calculation WHERE id = %s", [calc_id]).fetchone()
        if not calc:
            raise Problem(404, "calculation_not_found")
        if calc["status"] == "published":
            raise Problem(409, "already_published")
        rep = c.execute("SELECT id FROM assurance_evidence WHERE kind = 'reproduction' AND subject = %s AND status = 'identical' ORDER BY created_at DESC LIMIT 1", [str(calc_id)]).fetchone()
        checks = {"lineage_coverage": {"value": calc["lineage_coverage"], "required": POLICY["min_lineage_coverage"], "ok": calc["lineage_coverage"] >= POLICY["min_lineage_coverage"]},
                  "orphan_rate": {"value": calc["totals"]["orphans"]["rate"], "required": f"< {POLICY['max_orphan_rate']}", "ok": calc["totals"]["orphans"]["rate"] < POLICY["max_orphan_rate"]},
                  "reproduced": {"value": str(rep["id"]) if rep else None, "required": "a reproduction with identical hashes", "ok": bool(rep)}}
        if not all(x["ok"] for x in checks.values()):
            raise Problem(422, "policy_failed", "; ".join(f"{k}: {v['value']} (required {v['required']})" for k, v in checks.items() if not v["ok"]))
        did = uuid.uuid4()
        rationale = {"calculation": str(calc_id), "factor_version": calc["factor_version"], "total_t": calc["totals"]["total_t"], "checks": checks, "note": body.note}
        c.execute("INSERT INTO decision_record (tenant_id, id, kind, subject, rationale, proposed_by) VALUES (%s,%s,'publish_inventory',%s,%s,%s)",
                  [ctx.tenant_id, did, str(calc_id), Jsonb(rationale), ctx.actor_id])
        audit.record(c, ctx, "publish_inventory.proposed", "calculation", calc_id, {"decision": str(did)})
        return 201, {"decision_id": did, "status": "proposed", "checks": checks}
    return run(ctx, idem, body, work)


class ExportIn(BaseModel):
    calculation_id: uuid.UUID
    format: Literal["json", "csv"] = "json"


@app.post("/v1/reports/export", status_code=201, tags=["reporting"], summary="Export a published inventory: the executive report as JSON plus a machine-readable CSV by category and method, hashed and kept as assurance evidence")
def export(body: ExportIn, ctx: Ctx = Depends(auth("reports:export")), idem: str | None = IdemKey):
    def work(c):
        g = group(c)
        calc = c.execute("SELECT * FROM calculation WHERE id = %s", [body.calculation_id]).fetchone()
        if not calc:
            raise Problem(404, "calculation_not_found")
        if calc["status"] != "published":
            raise Problem(409, "not_published", "only a published inventory can be exported; propose it with POST /v1/calculations/{id}/publish")
        T, u = calc["totals"], calc["totals"]["uncertainty"]
        fv = c.execute("SELECT id, content_hash, frozen_at FROM factor_version WHERE id = %s", [calc["factor_version"]]).fetchone()
        dec = c.execute("SELECT id, proposed_by, decided_by, decided_at FROM decision_record WHERE kind = 'publish_inventory' AND subject = %s AND status = 'approved'", [str(calc["id"])]).fetchone()
        rep = c.execute("SELECT id, created_at FROM assurance_evidence WHERE kind = 'reproduction' AND subject = %s AND status = 'identical' ORDER BY created_at DESC LIMIT 1", [str(calc["id"])]).fetchone()
        band = lambda k: [u[k]["t"], u[k]["p2_5"], u[k]["p97_5"]] if k in u else None      # noqa: E731
        report = {"company": g["name"], "reporting_year": g["reporting_year"], "calculation_id": calc["id"], "published_at": calc["published_at"],
                  "factor_version": fv, "result_hash": calc["result_hash"], "unit": "tCO2e [point, 2.5%, 97.5%]",
                  "scope1": band("scope1"), "scope2_location_based": band("scope2"), "scope3": band("scope3"), "total": band("total"),
                  "scope3_categories": {k: band(f"s3:{k}") for k in ("1", "2", "4", "6")},
                  "methods": {k: v for k, v in T["by_method"].items()}, "lineage_coverage": calc["lineage_coverage"], "orphans": T["orphans"],
                  "approval": dec, "reproduction_evidence": rep,
                  "not_included": "market-based scope 2, scope 3 categories 3, 5, 7 and 8-15; see the README"}
        lines = ["scope,ghg_category,category,tco2e,p2_5,p97_5"]
        for k, v in sorted(T["spend_categories"].items()):
            b = u.get(f"cat:{k}", {"t": v, "p2_5": "", "p97_5": ""})
            lines.append(f"3,{world.CATEGORIES[k][2]},{k},{b['t']},{b['p2_5']},{b['p97_5']}")
        for m, v in T["freight_by_mode"].items():
            lines.append(f"3,4,freight_{m},{v},,")
        for s in ("1", "2"):
            lines.append(f"{s},,energy,{u[f'scope{s}']['t']},{u[f'scope{s}']['p2_5']},{u[f'scope{s}']['p97_5']}")
        csv = "\n".join(lines) + "\n"
        body_json = json.dumps(jsonable_encoder(report), sort_keys=True)
        digest = sha(body_json + csv)
        eid = uuid.uuid4()
        c.execute("INSERT INTO assurance_evidence (tenant_id, id, kind, subject, content, sha256, status) VALUES (%s,%s,'export',%s,%s,%s,'issued')",
                  [ctx.tenant_id, eid, str(calc["id"]), body_json + "\n" + csv, digest])
        audit.record(c, ctx, "report.exported", "calculation", calc["id"], {"sha256": digest, "evidence": str(eid), "format": body.format})
        return 201, {"evidence_id": eid, "sha256": digest, "report": report, "csv": csv, "format": body.format}
    return run(ctx, idem, body, work)


@app.get("/v1/suppliers/{supplier_id}", tags=["suppliers"], summary="(+) A resolved supplier: its vendor records across the ERPs with the evidence that joined them, spend by subsidiary and category, and its disclosure")
def supplier_detail(supplier_id: uuid.UUID, ctx: Ctx = Depends(auth("carbon:read"))):
    with db.tx(ctx.tenant_id) as c:
        s = c.execute("SELECT * FROM supplier WHERE id = %s", [supplier_id]).fetchone()
        if not s:
            raise Problem(404, "supplier_not_found")
        recs = c.execute("SELECT vendor_ref, subsidiary, name, country, tax_id, email_domain, match_prob, evidence FROM supplier_alias WHERE supplier_id = %s ORDER BY vendor_ref", [supplier_id]).fetchall()
        sp = c.execute("""SELECT a.subsidiary, a.category, count(*) AS lines, sum(a.amount_usd) AS usd FROM activity a JOIN supplier_alias sa ON sa.vendor_ref = a.vendor_ref
                           WHERE a.kind = 'ap' AND sa.supplier_id = %s GROUP BY 1, 2 ORDER BY usd DESC""", [supplier_id]).fetchall()
        doc = c.execute("SELECT id, subject, status, extracted FROM assurance_evidence WHERE kind = 'disclosure' AND supplier_id = %s", [supplier_id]).fetchone()
    return jsonable_encoder({**s, "records": recs, "spend": sp, "disclosure": doc})
