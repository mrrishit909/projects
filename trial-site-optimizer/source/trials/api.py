"""Public API (modular monolith). Blueprint services map to: protocol-parser (POST /v1/studies/parse), criteria-engine (the
review workflow and the DSL's validation), population-profile (the tokenised records and the funnel), patient-match
(POST /v1/match/evaluate, explanations), site-score (enrolment and dropout models), portfolio-optimizer (the MILP),
investigator-intelligence (profiles on every site score) and audit-service (the hash-chained log). No outside model or
service is called; see the README for what was not built.

    uvicorn trials.api:app          python -m core.jobs trials.api      # the worker
"""
import csv
import datetime
import functools
import hashlib
import io
import json
import pickle
import re
import secrets
import uuid
from typing import Literal

import numpy as np
from fastapi import Depends, Header, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import PlainTextResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from core import audit, db, jobs
from core.app import Ctx, Problem, create_app, run

from . import engine, world

READ = {"network:read", "jobs:read"}
ANALYST = READ | {"studies:parse", "match:run", "matches:read", "sites:score", "portfolios:propose", "exports:create"}
PERMISSIONS = {"viewer": READ, "feasibility_analyst": ANALYST,
               "study_director": ANALYST | {"network:load", "network:advance", "criteria:review", "portfolios:approve", "audit:read"}}
app = create_app("trial-site-optimizer", PERMISSIONS)
auth = app.state.auth
IdemKey = Header(None, alias="Idempotency-Key")
SPLIT_MONTH = -18          # the load job's backtest: history studies starting before this train, the rest test


def worker_ctx(job):
    return Ctx(job["tenant_id"], uuid.UUID(job["payload"]["actor_id"]), "worker", "system")


def network(c):
    n = c.execute("SELECT * FROM network").fetchone()
    if not n:
        raise Problem(409, "no_network", "load a network first: POST /v1/network:load")
    return n


def model_version(n):
    return f"net-{str(n['id'])[:8]}-1"


@functools.lru_cache(maxsize=16)
def _models(tenant_id, version):
    with db.tx(tenant_id) as c:
        return {r["name"]: pickle.loads(r["artifact"]) for r in c.execute("SELECT name, artifact FROM model_artifacts WHERE version = %s", [version])}


def models(n):
    return _models(str(n["tenant_id"]), model_version(n))


def study(c, study_id):
    s = c.execute("SELECT * FROM study WHERE id = %s", [study_id]).fetchone()
    if not s:
        raise Problem(404, "study_not_found")
    return s


def approved_criteria(c, study_id):
    rows = c.execute("SELECT ref, type, text, rules FROM criterion WHERE study_id = %s ORDER BY position", [study_id]).fetchall()
    return [{"ref": r["ref"], "type": r["type"], "text": r["text"], "rules": r["rules"]} for r in rows]


def sites_and_pis(c):
    sites = [{"id": r["id"], "region": r["region"], "kind": r["kind"], "lat": r["lat"], "lon": r["lon"], "competing_trials": r["competing_trials"],
              "activation_cost": float(r["activation_cost"]), "per_patient_cost": float(r["per_patient_cost"]), "capacity": r["capacity"],
              "investigators": [], "records": r["records"]} for r in c.execute("SELECT * FROM site ORDER BY id")]
    by = {s["id"]: s for s in sites}
    pis = []
    for r in c.execute("SELECT * FROM investigator ORDER BY id"):
        pis.append({"id": r["id"], "site": r["site_id"], "name": r["name"], "specialty": r["specialty"], "trials_by_indication": r["trials_by_indication"],
                    "publications_by_indication": r["publications_by_indication"], "open_gcp_finding": r["open_gcp_finding"]})
        by[r["site_id"]]["investigators"].append(r["id"])
    return sites, pis


def history(c):
    return [{"site": r["site_id"], "study_ref": r["study_ref"], "indication": r["indication"], "start_month": r["start_month"], "pool_estimate": r["pool_estimate"],
             "lead_investigator": r["lead_investigator"], "competing_trials": r["competing_trials"], "activation_months": r["activation_months"],
             "months_enrolling": r["months_enrolling"], "enrolled": r["enrolled"], "dropped": r["dropped"]}
            for r in c.execute("SELECT * FROM site_metric ORDER BY id")]


# --- loading the network ---------------------------------------------------------------------------------------------------
class LoadIn(BaseModel):
    seed: int = Field(7, ge=1, le=10 ** 6)


@app.post("/v1/network:load", status_code=202, tags=["network"], summary="(+) Load the synthetic research network: sites, investigators, five years of site history, and every site's EHR feed, tokenised at the door; fit and register the enrolment and dropout models with a backtest against their baselines")
def load_network(body: LoadIn, ctx: Ctx = Depends(auth("network:load")), idem: str | None = IdemKey):
    def work(c):
        if c.execute("SELECT 1 FROM network").fetchone():
            raise Problem(409, "network_exists", "this tenant already has a network; `make reset` for a fresh demo")
        return 202, jobs.enqueue(c, ctx, "network.load", body.model_dump())
    return run(ctx, idem, body, work)


@jobs.handler("network.load")
def load_job(c, job):
    t, seed = job["tenant_id"], job["payload"]["seed"]
    nid = uuid.uuid5(t, "network")
    net = world.network(seed)
    salt = secrets.token_hex(16)
    c.execute("INSERT INTO network (id, tenant_id, name, model_seed, snapshot_date, token_salt) VALUES (%s,%s,%s,%s,%s,%s)",
              [nid, t, "Halden Oncology Research Network", seed, world.INDEX, salt])
    db.load(c, "site", ["tenant_id", "id", "region", "kind", "lat", "lon", "records", "competing_trials", "activation_cost", "per_patient_cost", "capacity"],
            [(t, s["id"], s["region"], s["kind"], s["lat"], s["lon"], s["n_records"], s["competing_trials"], s["activation_cost"], s["per_patient_cost"], s["capacity"])
             for s in net["sites"]])
    db.load(c, "investigator", ["tenant_id", "id", "site_id", "name", "specialty", "trials_by_indication", "publications_by_indication", "open_gcp_finding"],
            [(t, p["id"], p["site"], p["name"], p["specialty"], Jsonb(p["trials_by_indication"]), Jsonb(p["publications_by_indication"]), p["open_gcp_finding"])
             for p in net["investigators"]])
    db.load(c, "site_metric", ["tenant_id", "site_id", "study_ref", "indication", "start_month", "pool_estimate", "lead_investigator", "competing_trials",
                               "activation_months", "months_enrolling", "enrolled", "dropped"],
            [(t, h["site"], h["study_ref"], h["indication"], h["start_month"], h["pool_estimate"], h["lead_investigator"], h["competing_trials"],
              h["activation_months"], h["months_enrolling"], h["enrolled"], h["dropped"]) for h in net["history"]])
    enrollees = [{"site": h["site"], "study_ref": h["study_ref"], "features": engine.enrollee_features(e), "dropped": e["dropped"]} for h in net["history"] for e in h["enrollees"]]
    db.load(c, "enrollee_history", ["tenant_id", "site_id", "study_ref", "features", "dropped"], [(t, e["site"], e["study_ref"], Jsonb(e["features"]), e["dropped"]) for e in enrollees])
    # the EHR feeds: every record is tokenised here; the raw record goes no further
    problems, rows, events = {}, [], 0
    for p in net["patients"]:
        tok, probs = engine.tokenise(p["record"], salt)
        for pr in probs:
            problems[pr] = problems.get(pr, 0) + 1
        events += len(tok["events"])
        rows.append((t, tok["token"], tok["site"], tok["sex"], tok["age_band"], tok["distance_band"], Jsonb(tok["events"]), engine.feature_hash(tok["events"])))
    db.load(c, "patient_token", ["tenant_id", "token", "site_id", "sex", "age_band", "distance_band", "timeline", "record_hash"], rows)
    feed = {"records_received": len(net["patients"]), "tokens": len(rows), "events": events, "events_refused": problems,
            "dropped_at_the_door": ["mrn", "birth_date (kept as a 5-year age band)", "event dates (kept as days before the snapshot)", "home distance (kept as a band)", "free-text note"]}
    c.execute("UPDATE network SET feed = %s", [Jsonb(feed)])
    # models: fitted on the whole history for production, with a backtest on the latest studies for the registry
    enr = engine.fit_enrolment(net["history"], net["sites"], net["investigators"])
    dm = engine.fit_dropout(enrollees)
    bt = engine.backtest(net["history"], enrollees, net["sites"], net["investigators"], SPLIT_MONTH)
    version = f"net-{str(nid)[:8]}-1"
    snapshot = f"{len(net['history'])} site-studies, {len(enrollees)} enrollees, seed {seed}, snapshot {world.INDEX}"
    for name, obj, metrics in (("site-enrolment", enr, {**bt["enrolment"], "split": bt["split"], "alpha": enr["alpha"], "weibull_k": enr["weibull_k"], "beta": dict(zip(enr["beta_names"], enr["beta"]))}),
                               ("dropout-risk", dm, {**bt["dropout"], "split": bt["split"], "features": engine.DROPOUT_FEATURES})):
        c.execute("INSERT INTO model_artifacts (tenant_id, name, version, data_snapshot, metrics, artifact, approved) VALUES (%s,%s,%s,%s,%s,%s,true)",
                  [t, name, version, snapshot, Jsonb(metrics), pickle.dumps(obj)])
    audit.record(c, worker_ctx(job), "network.loaded", "network", nid, {"sites": len(net["sites"]), "tokens": len(rows), "model_version": version})
    return {"network_id": nid, "sites": len(net["sites"]), "investigators": len(net["investigators"]), "academic_sites": sum(s["kind"] == "academic" for s in net["sites"]),
            "history_studies": len(net["history"]), "history_enrollees": len(enrollees), "feed": feed, "snapshot_date": world.INDEX,
            "models": {"version": version, "enrolment": bt["enrolment"], "dropout": bt["dropout"], "split": bt["split"]}}


@app.get("/v1/network/overview", tags=["network"], summary="(+) The command centre: sites on the map, records, the feed's refusals, the models in production, studies and their state")
def overview(ctx: Ctx = Depends(auth("network:read"))):
    with db.tx(ctx.tenant_id) as c:
        n = network(c)
        sites = c.execute("""SELECT s.id, s.region, s.kind, s.lat, s.lon, s.records, s.competing_trials, s.capacity,
                                    (SELECT count(*) FROM site_metric m WHERE m.site_id = s.id) AS past_studies,
                                    (SELECT avg(enrolled) FROM site_metric m WHERE m.site_id = s.id) AS mean_enrolled
                               FROM site s ORDER BY s.id""").fetchall()
        studies = c.execute("SELECT id, external_ref, name, indication, status, created_at FROM study ORDER BY created_at").fetchall()
        mods = c.execute("SELECT name, version, data_snapshot, metrics, approved FROM model_artifacts ORDER BY name").fetchall()
        pis = c.execute("SELECT count(*) AS n, count(*) FILTER (WHERE open_gcp_finding) AS finding FROM investigator").fetchone()
    return jsonable_encoder({"network": {"id": n["id"], "name": n["name"], "snapshot_date": n["snapshot_date"], "feed": n["feed"]},
                             "sites": [{**s, "mean_enrolled": round(float(s["mean_enrolled"] or 0), 2)} for s in sites],
                             "investigators": pis["n"], "investigators_with_open_finding": pis["finding"], "studies": studies, "models": mods})


@app.get("/v1/sites/{site_id}", tags=["sites"], summary="(+) One site: its history study by study, its investigators' profiles (investigator intelligence) and its latest score per study")
def site_detail(site_id: str, indication: Literal["NSCLC", "SCLC", "BREAST", "CRC", "MELANOMA"] = "NSCLC", ctx: Ctx = Depends(auth("network:read"))):
    with db.tx(ctx.tenant_id) as c:
        network(c)
        s = c.execute("SELECT * FROM site WHERE id = %s", [site_id]).fetchone()
        if not s:
            raise Problem(404, "site_not_found")
        hist = history(c)
        _, pis = sites_and_pis(c)
        scores = c.execute("SELECT st.external_ref, sc.* FROM site_score sc JOIN study st ON st.id = sc.study_id WHERE sc.site_id = %s", [site_id]).fetchall()
    return jsonable_encoder({**s, "history": [h for h in hist if h["site"] == site_id],
                             "investigators": [engine.investigator_profile(p, indication, hist) for p in pis if p["site"] == site_id], "scores": scores})


# --- protocol parser ----------------------------------------------------------------------------------------------------------
class ParseIn(BaseModel):
    external_ref: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")
    name: str | None = Field(None, max_length=200)
    text: str = Field(min_length=40, max_length=100_000, description="the protocol's eligibility section, numbered criteria under inclusion and exclusion headings")


def criterion_view(r):
    return {"id": r["id"], "ref": r["ref"], "type": r["type"], "text": r["text"], "proposed": r["proposed"], "status": r["status"],
            "confidence": r["confidence"], "reasons": r["reasons"], "review_action": r["review_action"], "rules": r["rules"]}


@app.post("/v1/studies/parse", status_code=201, tags=["studies"], summary="Parse a protocol's eligibility section into the criteria DSL with a deterministic grammar; every rule is validated; what the grammar cannot account for word by word goes to the review queue. Nothing runs on patients until a study director has reviewed every criterion")
def parse_study(body: ParseIn, ctx: Ctx = Depends(auth("studies:parse")), idem: str | None = IdemKey):
    def work(c):
        network(c)
        if c.execute("SELECT 1 FROM study WHERE external_ref = %s", [body.external_ref]).fetchone():
            raise Problem(409, "study_exists", f"{body.external_ref} was already parsed")
        parsed = engine.parse(body.text)
        if not parsed:
            raise Problem(422, "no_criteria_found", "expected numbered criteria under 'Inclusion criteria' and 'Exclusion criteria' headings")
        refs = [p["ref"] for p in parsed]
        if len(set(refs)) != len(refs):
            raise Problem(422, "duplicate_criterion_numbers", "each list must number its criteria once")
        diag = [r for p in parsed for r in p["rules"] if r["field"] == "diagnosis"]
        sid = uuid.uuid4()
        digest = hashlib.sha256(body.text.encode()).hexdigest()
        c.execute("""INSERT INTO study (id, tenant_id, external_ref, name, indication, protocol_text, text_sha256, parser_version, created_by)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                  [sid, ctx.tenant_id, body.external_ref, body.name or body.text.splitlines()[0][:200], diag[0]["code"] if diag else None, body.text, digest,
                   engine.PARSER_VERSION, ctx.actor_id])
        out = []
        for k, p in enumerate(parsed):
            cid = uuid.uuid4()
            c.execute("""INSERT INTO criterion (id, tenant_id, study_id, ref, position, type, text, proposed, status, confidence, reasons)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                      [cid, ctx.tenant_id, sid, p["ref"], k, p["type"], p["text"], Jsonb(p["rules"]), p["status"], p["confidence"], Jsonb(p["reasons"])])
            out.append({"id": cid, **p, "proposed": p["rules"]})
        c.execute("INSERT INTO model_runs (tenant_id, model_name, version, subject, inputs_hash, result) VALUES (%s,%s,%s,%s,%s,%s)",
                  [ctx.tenant_id, engine.PARSER_VERSION, engine.PARSER_VERSION, f"study:{sid}", digest[:16],
                   Jsonb({k: sum(p["status"] == k for p in parsed) for k in ("parsed", "review", "manual")})])
        audit.record(c, ctx, "study.parsed", "study", sid, {"ref": body.external_ref, "criteria": len(parsed), "review": sum(p["status"] == "review" for p in parsed)})
        counts = {k: sum(p["status"] == k for p in parsed) for k in ("parsed", "review", "manual")}
        return 201, {"study_id": sid, "external_ref": body.external_ref, "indication": diag[0]["code"] if diag else None, "status": "in_review",
                     "parser_version": engine.PARSER_VERSION, "text_sha256": digest, "counts": counts, "criteria": out,
                     "review_queue": [{"ref": p["ref"], "text": p["text"], "reasons": p["reasons"]} for p in parsed if p["status"] == "review"]}
    return run(ctx, idem, body, work)


class Decision(BaseModel):
    ref: str = Field(pattern=r"^[IE]\d{1,3}$")
    action: Literal["accept", "edit", "manual"]
    rules: list[dict] | None = Field(None, max_length=10, description="for edit: the rules in the DSL, validated like the parser's")
    note: str | None = Field(None, max_length=500)


class ReviewIn(BaseModel):
    decisions: list[Decision] = Field(default_factory=list, max_length=200)
    accept_remaining_parsed: bool = Field(False, description="accept every parsed or manual criterion not named in decisions")


@app.post("/v1/studies/{study_id}/review", tags=["studies"], summary="(+) A study director accepts, edits or marks as manual each criterion. Edits are validated like the parser's output; one invalid rule refuses the whole review. When every criterion is reviewed the criteria set is approved and frozen")
def review(study_id: uuid.UUID, body: ReviewIn, ctx: Ctx = Depends(auth("criteria:review")), idem: str | None = IdemKey):
    def work(c):
        s = study(c, study_id)
        if s["status"] == "approved":
            raise Problem(409, "criteria_frozen", "this study's criteria were approved; parse a new version to change them")
        crit = {r["ref"]: r for r in c.execute("SELECT * FROM criterion WHERE study_id = %s ORDER BY position FOR UPDATE", [study_id])}
        problems = {}
        for d in body.decisions:
            if d.ref not in crit:
                problems[d.ref] = ["no such criterion"]
            elif d.action == "accept" and crit[d.ref]["status"] == "review":
                problems[d.ref] = ["nothing to accept: the parser sent this one to review; edit it or mark it manual"]
            elif d.action == "edit":
                if not d.rules:
                    problems[d.ref] = ["an edit needs rules"]
                else:
                    p = [f"rule {k + 1}: {x}" for k, r in enumerate(d.rules) for x in engine.validate(r)]
                    if any(r.get("field") == "manual" for r in d.rules):
                        p.append("use action 'manual' for a criterion no record can answer")
                    if p:
                        problems[d.ref] = p
        if problems:
            raise Problem(422, "invalid_review", json.dumps(problems))
        decided = {d.ref: d for d in body.decisions}
        for ref, r in crit.items():
            d = decided.get(ref)
            if d is None and body.accept_remaining_parsed and r["status"] in ("parsed", "manual") and not r["review_action"]:
                d = Decision(ref=ref, action="manual" if r["status"] == "manual" else "accept")
            if d is None:
                continue
            rules = r["proposed"] if d.action == "accept" else d.rules if d.action == "edit" else [{"field": "manual", "topic": (r["proposed"] or [{}])[0].get("topic") or d.note or "checked at screening"}]
            action = {"accept": "accepted", "edit": "edited", "manual": "manual"}[d.action]
            c.execute("UPDATE criterion SET review_action = %s, rules = %s, reviewed_by = %s, reviewed_at = now() WHERE id = %s",
                      [action, Jsonb(rules), ctx.actor_id, r["id"]])
            audit.record(c, ctx, f"criterion.{action}", "criterion", r["id"], {"study": str(study_id), "ref": ref, "note": d.note})
        rows = c.execute("SELECT * FROM criterion WHERE study_id = %s ORDER BY position", [study_id]).fetchall()
        open_ = [r["ref"] for r in rows if not r["review_action"]]
        if not open_:
            c.execute("UPDATE study SET status = 'approved', approved_by = %s, approved_at = now() WHERE id = %s", [ctx.actor_id, study_id])
            audit.record(c, ctx, "criteria.approved", "study", study_id, {"criteria": len(rows)})
        proposed = [r for r in rows if r["status"] != "review" and r["review_action"]]
        accepted = sum(r["review_action"] in ("accepted", "manual") and r["status"] != "review" for r in rows)
        stats = {"criteria": len(rows), "accepted_unchanged": sum(r["review_action"] == "accepted" for r in rows),
                 "edited": sum(r["review_action"] == "edited" for r in rows), "manual": sum(r["review_action"] == "manual" for r in rows),
                 "proposed_by_parser": len(proposed), "proposals_accepted": accepted,
                 "acceptance_rate": round(accepted / len(proposed), 4) if proposed else None,
                 "auto_translated": round(sum(r["status"] != "review" for r in rows) / len(rows), 4)}
        return 200, {"study_id": study_id, "status": "approved" if not open_ else "in_review", "open": open_, "stats": stats,
                     "criteria": [criterion_view(r) for r in rows]}
    return run(ctx, idem, body, work)


@app.get("/v1/studies/{study_id}", tags=["studies"], summary="(+) A study: the protocol's criteria as parsed, as reviewed, and their state")
def study_detail(study_id: uuid.UUID, ctx: Ctx = Depends(auth("network:read"))):
    with db.tx(ctx.tenant_id) as c:
        s = study(c, study_id)
        rows = c.execute("SELECT * FROM criterion WHERE study_id = %s ORDER BY position", [study_id]).fetchall()
    return jsonable_encoder({**{k: v for k, v in s.items() if k != "protocol_text"}, "criteria": [criterion_view(r) for r in rows]})


# --- patient match ---------------------------------------------------------------------------------------------------------------
class MatchIn(BaseModel):
    study_id: uuid.UUID


def criteria_hash(crit):
    return engine.feature_hash([[c["ref"], c["type"], c["rules"]] for c in crit])


@app.post("/v1/match/evaluate", status_code=202, tags=["match"], summary="202 + job: run the approved criteria over every tokenised record with the temporal rules engine: eligible, potentially eligible (the record cannot answer a criterion today) or ineligible, criterion by criterion")
def match(body: MatchIn, ctx: Ctx = Depends(auth("match:run")), idem: str | None = IdemKey):
    def work(c):
        network(c)
        s = study(c, body.study_id)
        if s["status"] != "approved":
            raise Problem(409, "criteria_not_approved", "a study director must review every criterion before it runs on patients")
        return 202, jobs.enqueue(c, ctx, "match.evaluate", body.model_dump(mode="json"))
    return run(ctx, idem, body, work)


@jobs.handler("match.evaluate")
def match_job(c, job):
    sid = job["payload"]["study_id"]
    s = study(c, sid)
    crit = approved_criteria(c, sid)
    ch = criteria_hash(crit)
    c.execute("DELETE FROM eligibility_event WHERE study_id = %s", [sid])
    c.execute("DELETE FROM population_bucket WHERE study_id = %s", [sid])
    toks = c.execute("SELECT token, site_id, age_band, distance_band, timeline, record_hash FROM patient_token ORDER BY token").fetchall()
    tokens = [{"token": r["token"], "site": r["site_id"], "age_band": r["age_band"], "distance_band": r["distance_band"], "events": r["timeline"]} for r in toks]
    ixs = [engine.index_timeline(t) for t in tokens]
    res = [engine.evaluate(crit, ix) for ix in ixs]
    strata = [engine.on_treatment(ix) for ix in ixs]
    rates = engine.pass_rates(res, crit, strata)
    weights = [engine.expected_eligible(r, rates, g) for r, g in zip(res, strata)]
    rows, buckets = [], {}
    for r, t, w, tk in zip(res, toks, weights, tokens):
        rows.append((uuid.uuid4(), job["tenant_id"], sid, t["token"], t["site_id"], r["status"], Jsonb(r["values"]), r["failed"], r["unknown"], round(w, 5),
                     engine.ENGINE_VERSION, ch, t["record_hash"]))
        b = buckets.setdefault((t["site_id"], t["age_band"], r["status"]), [0, 0.0])
        b[0] += 1
        b[1] += w
    db.load(c, "eligibility_event", ["id", "tenant_id", "study_id", "token", "site_id", "status", "criterion_values", "failed", "unknown", "weight",
                                     "engine_version", "criteria_hash", "record_hash"], rows)
    db.load(c, "population_bucket", ["tenant_id", "study_id", "site_id", "age_band", "status", "patients", "expected_eligible"],
            [(job["tenant_id"], sid, k[0], k[1], k[2], v[0], round(v[1], 4)) for k, v in buckets.items()])
    summary = {"records": len(res), "eligible": sum(r["status"] == "eligible" for r in res), "potential": sum(r["status"] == "potential" for r in res),
               "ineligible": sum(r["status"] == "ineligible" for r in res), "expected_eligible": round(sum(weights), 1)}
    c.execute("INSERT INTO model_runs (tenant_id, model_name, version, subject, inputs_hash, result) VALUES (%s,%s,%s,%s,%s,%s)",
              [job["tenant_id"], engine.ENGINE_VERSION, engine.ENGINE_VERSION, f"study:{sid}", engine.feature_hash([ch, [t["record_hash"] for t in toks]]), Jsonb(summary)])
    steps = engine.funnel(res, crit)
    c.execute("UPDATE study SET metadata = metadata || %s WHERE id = %s", [Jsonb({"funnel": steps, "match_summary": summary, "criteria_hash": ch}), sid])
    audit.record(c, worker_ctx(job), "match.evaluated", "study", sid, {**summary, "criteria_hash": ch})
    return {"study_id": sid, "external_ref": s["external_ref"], "engine_version": engine.ENGINE_VERSION, "criteria_hash": ch, **summary,
            "pass_rates_for_unknowns": {f"{k[0]}{' (on treatment)' if k[1] else ''}": round(v, 3) for k, v in sorted(rates.items()) if v < 0.995}}


@app.get("/v1/studies/{study_id}/funnel", tags=["match"], summary="Attrition criterion by criterion in protocol order, eligible and potentially eligible patients and the expected eligible pool by site, and what the unknowns are waiting for")
def funnel(study_id: uuid.UUID, ctx: Ctx = Depends(auth("network:read"))):
    with db.tx(ctx.tenant_id) as c:
        s = study(c, study_id)
        crit = approved_criteria(c, study_id)
        if "funnel" not in s["metadata"]:
            raise Problem(409, "not_matched", "run POST /v1/match/evaluate first")
        by_site = c.execute("""SELECT s.id AS site, s.region, s.kind, s.lat, s.lon, s.records,
                                      coalesce(sum(b.patients) FILTER (WHERE b.status = 'eligible'), 0) AS eligible,
                                      coalesce(sum(b.patients) FILTER (WHERE b.status = 'potential'), 0) AS potential,
                                      coalesce(sum(b.expected_eligible), 0) AS expected_eligible
                                 FROM site s LEFT JOIN population_bucket b ON b.site_id = s.id AND b.study_id = %s
                                GROUP BY s.tenant_id, s.id ORDER BY expected_eligible DESC""", [study_id]).fetchall()
        waiting = c.execute("""SELECT u AS ref, count(*) AS n FROM eligibility_event, unnest(unknown) u
                                WHERE study_id = %s AND status = 'potential' GROUP BY u ORDER BY n DESC""", [study_id]).fetchall()
    text = {x["ref"]: x["text"] for x in crit}
    m = s["metadata"]["match_summary"]
    return jsonable_encoder({"study_id": study_id, "external_ref": s["external_ref"], "engine_version": engine.ENGINE_VERSION, "steps": s["metadata"]["funnel"],
                             "totals": {k: m[k] for k in ("eligible", "potential", "ineligible")},
                             "expected_eligible": round(sum(float(x["expected_eligible"]) for x in by_site), 1),
                             "by_site": [{**x, "expected_eligible": round(float(x["expected_eligible"]), 2)} for x in by_site],
                             "potential_waiting_on": [{**w, "text": text.get(w["ref"])} for w in waiting]})


@app.get("/v1/studies/{study_id}/matches", tags=["match"], summary="(+) Matches by status, failing or open criterion and site: identifiers are match ids and pseudonymous tokens only")
def matches(study_id: uuid.UUID, status: Literal["eligible", "potential", "ineligible"] | None = None, failed: str | None = None,
            only: bool = Query(False, description="with failed: the patient fails that criterion and nothing else"),
            unknown: str | None = None, site: str | None = None, limit: int = Query(20, ge=1, le=200), ctx: Ctx = Depends(auth("matches:read"))):
    with db.tx(ctx.tenant_id) as c:
        study(c, study_id)
        rows = c.execute("""SELECT id AS match_id, left(token, 10) AS token, site_id, status, failed, unknown, weight FROM eligibility_event
                             WHERE study_id = %s AND (%s::text IS NULL OR status = %s) AND (%s::text IS NULL OR %s = ANY(failed))
                               AND (NOT %s OR cardinality(failed) = 1) AND (%s::text IS NULL OR %s = ANY(unknown)) AND (%s::text IS NULL OR site_id = %s)
                             ORDER BY token LIMIT %s""", [study_id, status, status, failed, failed, only and failed is not None, unknown, unknown, site, site, limit]).fetchall()
    return jsonable_encoder({"items": rows})


@app.get("/v1/matches/{match_id}/explanation", tags=["match"], summary="Why a patient is eligible or not, criterion by criterion: the rule, the value the record gave, the evidence with its day relative to the snapshot and the window it had to fall in. Re-derived from the stored timeline and the approved criteria, and checked against the stored decision")
def explanation(match_id: uuid.UUID, ctx: Ctx = Depends(auth("matches:read"))):
    with db.tx(ctx.tenant_id) as c:
        e = c.execute("SELECT * FROM eligibility_event WHERE id = %s", [match_id]).fetchone()
        if not e:
            raise Problem(404, "match_not_found")
        t = c.execute("SELECT * FROM patient_token WHERE token = %s", [e["token"]]).fetchone()
        crit = approved_criteria(c, e["study_id"])
        s = study(c, e["study_id"])
        audit.record(c, ctx, "match.explained", "eligibility_event", match_id, {"study": str(e["study_id"])})
    tok = {"token": t["token"], "site": t["site_id"], "age_band": t["age_band"], "distance_band": t["distance_band"], "events": t["timeline"]}
    out = engine.evaluate(crit, engine.index_timeline(tok), explain=True)
    lineage_ok = engine.feature_hash(t["timeline"]) == e["record_hash"] == t["record_hash"] and criteria_hash(crit) == e["criteria_hash"]
    keep = ("medication", "lab", "ecog", "biomarker", "condition", "diagnosis")
    return jsonable_encoder({"match_id": match_id, "study": s["external_ref"], "token": t["token"][:10], "site": t["site_id"], "age_band": t["age_band"],
                             "sex": t["sex"], "distance_band": t["distance_band"], "status": e["status"], "reproduces_stored_decision": out["status"] == e["status"] and out["values"] == e["criterion_values"],
                             "lineage_verified": lineage_ok, "engine_version": e["engine_version"], "record_hash": e["record_hash"], "criteria_hash": e["criteria_hash"],
                             "failed": out["failed"], "unknown": out["unknown"], "trace": out["trace"],
                             "timeline": [x for x in t["timeline"] if x["type"] in keep], "snapshot_date": world.INDEX,
                             "note": "days are relative to the data snapshot (day 0); the record holds no dates"})


PHI_PATTERNS = {"calendar date": r"\b(19|20)\d\d-\d\d-\d\d\b", "patient token or long hex": r"\b[0-9a-f]{10,}\b", "MRN-like number": r"\b\d{7,}\b"}


@app.get("/v1/studies/{study_id}/export", tags=["match"], summary="(+) The analytics export: patients by site, age band and status, with cells under 11 suppressed; no tokens, dates or identifiers. The response says what the outgoing payload was scanned for")
def export(study_id: uuid.UUID, format: Literal["json", "csv"] = "json", ctx: Ctx = Depends(auth("exports:create"))):
    with db.tx(ctx.tenant_id) as c:
        s = study(c, study_id)
        rows = c.execute("""SELECT site_id AS site, age_band, status, patients, round(expected_eligible::numeric, 1) AS expected_eligible
                              FROM population_bucket WHERE study_id = %s ORDER BY site_id, age_band, status""", [study_id]).fetchall()
        if not rows:
            raise Problem(409, "not_matched", "run POST /v1/match/evaluate first")
        out, suppressed = [], 0
        for r in rows:
            small = r["patients"] < engine.SMALL_CELL
            suppressed += small
            out.append({"site": r["site"], "age_band": r["age_band"], "status": r["status"], "patients": f"<{engine.SMALL_CELL}" if small else r["patients"],
                        "expected_eligible": None if small else float(r["expected_eligible"])})
        audit.record(c, ctx, "export.created", "study", study_id, {"rows": len(out), "suppressed_cells": suppressed, "format": format})
    body = json.dumps(out)
    scan = {name: len(re.findall(p, body)) for name, p in PHI_PATTERNS.items()}
    if any(scan.values()):
        raise Problem(500, "export_blocked", f"identifier-like content found: {scan}")
    if format == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["site", "age_band", "status", "patients", "expected_eligible"])
        w.writeheader()
        w.writerows(out)
        return PlainTextResponse(buf.getvalue(), media_type="text/csv")
    return jsonable_encoder({"study": s["external_ref"], "grain": "site x age band x status", "small_cell_rule": f"counts under {engine.SMALL_CELL} suppressed",
                             "rows": out, "suppressed_cells": suppressed, "scan": {**scan, "fields": ["site", "age_band", "status", "patients", "expected_eligible"]}})


# --- site score ---------------------------------------------------------------------------------------------------------------------
class ScoreIn(BaseModel):
    study_id: uuid.UUID
    horizon_months: int = Field(12, ge=6, le=24)


@app.post("/v1/sites/score", status_code=202, tags=["sites"], summary="202 + job: score every site for a study: expected eligible pool, activation (Weibull survival), enrolment with an 80% interval (Poisson-gamma), dropout risk, expected evaluable patients, the lead investigator's profile and the naive baseline")
def score(body: ScoreIn, ctx: Ctx = Depends(auth("sites:score")), idem: str | None = IdemKey):
    def work(c):
        network(c)
        study(c, body.study_id)
        if not c.execute("SELECT 1 FROM eligibility_event WHERE study_id = %s LIMIT 1", [body.study_id]).fetchone():
            raise Problem(409, "not_matched", "run POST /v1/match/evaluate first")
        return 202, jobs.enqueue(c, ctx, "sites.score", body.model_dump(mode="json"))
    return run(ctx, idem, body, work)


def study_rng(study_id, salt=""):
    return np.random.default_rng(int(hashlib.sha256(f"{study_id}{salt}".encode()).hexdigest()[:12], 16))


def scored_inputs(c, sid):
    pools = {r["site_id"]: float(r["w"]) for r in c.execute("SELECT site_id, sum(weight) AS w FROM eligibility_event WHERE study_id = %s GROUP BY site_id", [sid])}
    feats = {}
    for r in c.execute("""SELECT e.site_id, e.weight, t.token, t.site_id AS site, t.age_band, t.distance_band, t.timeline FROM eligibility_event e
                           JOIN patient_token t ON t.token = e.token WHERE e.study_id = %s AND e.weight > 0""", [sid]):
        tok = {"token": r["token"], "site": r["site"], "age_band": r["age_band"], "distance_band": r["distance_band"], "events": r["timeline"]}
        feats.setdefault(r["site_id"], []).append((float(r["weight"]), engine.candidate_features(tok, engine.index_timeline(tok))))
    return pools, feats


@jobs.handler("sites.score")
def score_job(c, job):
    p = job["payload"]
    sid = p["study_id"]
    n = network(c)
    s = study(c, sid)
    m = models(n)
    sites, pis = sites_and_pis(c)
    hist = history(c)
    pools, feats = scored_inputs(c, sid)
    rows, _, _ = engine.score_sites(m["site-enrolment"], m["dropout-risk"], sites, pis, hist, s["indication"], pools, feats, p["horizon_months"], study_rng(sid))
    c.execute("DELETE FROM site_score WHERE study_id = %s", [sid])
    version = model_version(n)
    out, runs = [], []
    for r in rows:
        inputs = {"site": r["site"], "pool": r["expected_eligible"], "pi": r["investigator"]["id"], "horizon": p["horizon_months"], "version": version}
        h = engine.feature_hash(inputs)
        detail = {k: r[k] for k in ("activation_median_months", "p_open_by_month_3", "p_never_opens", "rate_per_eligible_month", "site_frailty", "activation_cost",
                                    "per_patient_cost", "capacity", "investigator", "region", "kind", "lat", "lon")}
        detail["horizon_months"] = p["horizon_months"]
        c.execute("""INSERT INTO site_score (tenant_id, study_id, site_id, expected_eligible, expected_enrolled, p10, p90, dropout_risk, expected_evaluable,
                                             naive_expected, excluded, detail, model_version, inputs_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                  [job["tenant_id"], sid, r["site"], r["expected_eligible"], r["mean"], r["p10"], r["p90"], r["dropout_risk"], r["evaluable"], r["naive_expected"],
                   r["excluded"], Jsonb(detail), version, h])
        runs.append((job["tenant_id"], engine.ENROLMENT_VERSION, version, f"site:{r['site']}:study:{sid}", h, Jsonb({"mean": r["mean"], "p10": r["p10"], "p90": r["p90"], "dropout": r["dropout_risk"]})))
        out.append({**r, "inputs_hash": h})
    db.load(c, "model_runs", ["tenant_id", "model_name", "version", "subject", "inputs_hash", "result"], runs)
    audit.record(c, worker_ctx(job), "sites.scored", "study", sid, {"sites": len(rows), "model_version": version})
    out.sort(key=lambda r: -r["evaluable"])
    metrics = c.execute("SELECT metrics FROM model_artifacts WHERE name = 'site-enrolment' AND version = %s", [version]).fetchone()["metrics"]
    return {"study_id": sid, "horizon_months": p["horizon_months"], "model_version": version, "models": [engine.ENROLMENT_VERSION, engine.DROPOUT_VERSION],
            "sites": len(out), "expected_enrolled_all_sites": round(sum(r["mean"] for r in out), 1), "naive_all_sites": round(sum(r["naive_expected"] for r in out), 1),
            "excluded": [{"site": r["site"], "why": r["excluded"]} for r in out if r["excluded"]], "backtest": metrics,
            "ranked": out[:25], "map": [{"site": r["site"], "lat": r["lat"], "lon": r["lon"], "kind": r["kind"], "evaluable": r["evaluable"], "expected_eligible": r["expected_eligible"]} for r in out]}


# --- portfolio ------------------------------------------------------------------------------------------------------------------------
class OptimizeIn(BaseModel):
    study_id: uuid.UUID
    n_sites: int = Field(20, ge=1, le=200)
    budget_usd: float = Field(gt=0, le=1e9)
    target_evaluable: int | None = Field(None, ge=1, le=100_000)
    max_per_region: int | None = Field(None, ge=1, le=200)
    min_academic: int = Field(0, ge=0, le=200)


@app.post("/v1/portfolios/optimize", status_code=202, tags=["portfolios"], summary="202 + job: choose the sites that maximise expected evaluable enrolment under the budget (activation plus per-patient fees at expected enrolment), region and academic rules and the investigator policy, by MILP; the same predictions picked greedily and the top sites by historical enrolment are the baselines. The plan is a proposal until a second person approves it")
def optimize(body: OptimizeIn, ctx: Ctx = Depends(auth("portfolios:propose")), idem: str | None = IdemKey):
    def work(c):
        network(c)
        study(c, body.study_id)
        if not c.execute("SELECT 1 FROM site_score WHERE study_id = %s LIMIT 1", [body.study_id]).fetchone():
            raise Problem(409, "not_scored", "run POST /v1/sites/score first")
        return 202, jobs.enqueue(c, ctx, "portfolio.optimize", body.model_dump(mode="json"))
    return run(ctx, idem, body, work)


def score_rows(c, sid):
    return [{"site": r["site_id"], "expected_eligible": r["expected_eligible"], "mean": r["expected_enrolled"], "p10": r["p10"], "p90": r["p90"],
             "dropout_risk": r["dropout_risk"], "evaluable": r["expected_evaluable"], "naive_expected": r["naive_expected"], "excluded": r["excluded"], **r["detail"]}
            for r in c.execute("SELECT * FROM site_score WHERE study_id = %s ORDER BY site_id", [sid])]


def predictive_draws(m, rows, sites_by, sid, feats):
    draws, drop = {}, {}
    for r in rows:
        _, d = engine.predict_site(m, sites_by[r["site"]], r["investigator"]["trials_in_indication"], r["expected_eligible"], r["horizon_months"], study_rng(sid, r["site"]),
                                   pool_weights=[w for w, _ in feats.get(r["site"], [])] or None)
        draws[r["site"]], drop[r["site"]] = d, r["dropout_risk"]
    return draws, drop


@jobs.handler("portfolio.optimize")
def optimize_job(c, job):
    p = job["payload"]
    sid = p["study_id"]
    n = network(c)
    m = models(n)
    rows = score_rows(c, sid)
    sites, _ = sites_and_pis(c)
    sites_by = {s["id"]: s for s in sites}
    cands = engine.candidates(rows)
    plan = engine.optimise(cands, p["n_sites"], p["budget_usd"], p["max_per_region"], p["min_academic"])
    if plan["status"] == "infeasible":                 # nothing to propose; the job says why instead of retrying
        return {"status": "infeasible", "study_id": sid, "reason": "no set of sites satisfies the budget, size, region and academic constraints together",
                "constraints": {k: v for k, v in p.items() if k != "actor_id"}}
    draws, drop = predictive_draws(m["site-enrolment"], rows, sites_by, sid, scored_inputs(c, sid)[1])
    rng = study_rng(sid, "portfolio")
    alts = {"milp": plan["sites"], "top_by_history": engine.greedy(cands, lambda c_: c_["naive"], p["n_sites"], p["budget_usd"]),
            "greedy_value_per_dollar": engine.greedy_ratio(cands, p["n_sites"], p["budget_usd"])}
    compared = {}
    for name, chosen in alts.items():
        compared[name] = {"sites": chosen, "count": len(chosen), **engine.totals(cands, chosen),
                          "predicted": engine.portfolio_interval(draws, drop, chosen, rng, p["target_evaluable"]),
                          "historical_mean_enrolled": round(sum(next(c_["naive"] for c_ in cands if c_["id"] == s) for s in chosen), 1)}
    by = {r["site"]: r for r in rows}
    chosen = [{"site": s, "region": by[s]["region"], "kind": by[s]["kind"], "lat": by[s]["lat"], "lon": by[s]["lon"], "expected_eligible": by[s]["expected_eligible"],
               "expected_enrolled": by[s]["mean"], "p10": by[s]["p10"], "p90": by[s]["p90"], "dropout_risk": by[s]["dropout_risk"], "evaluable": by[s]["evaluable"],
               "cost": round(engine.cost(next(c_ for c_ in cands if c_["id"] == s))), "investigator": by[s]["investigator"]["name"],
               "activation_median_months": by[s]["activation_median_months"]} for s in sorted(plan["sites"], key=lambda s: -by[s]["evaluable"])]
    result = {"solver": {"engine": "OR-Tools SCIP", "status": plan["status"], "solve_ms": plan["solve_ms"], "candidates": plan["candidates"],
                         "eligible_candidates": plan["eligible_candidates"]},
              "constraints": {"n_sites": p["n_sites"], "budget_usd": p["budget_usd"], "max_per_region": p["max_per_region"], "min_academic": p["min_academic"],
                              "policy": "no site whose lead investigator has an open GCP inspection finding", "excluded_by_policy": [r["site"] for r in rows if r["excluded"]]},
              "budget_used": round(plan["expected_cost"] / p["budget_usd"], 4), "target_evaluable": p["target_evaluable"], "chosen": chosen, "compared": compared,
              "map": [{"site": r["site"], "lat": r["lat"], "lon": r["lon"], "kind": r["kind"], "evaluable": r["evaluable"]} for r in rows],
              "objective": "maximise expected evaluable patients (expected enrolment x (1 - dropout risk)) in the horizon"}
    pid = uuid.uuid4()
    c.execute("INSERT INTO portfolio_plan (id, tenant_id, study_id, request, sites, result, proposed_by) VALUES (%s,%s,%s,%s,%s,%s,%s)",
              [pid, job["tenant_id"], sid, Jsonb({k: v for k, v in p.items() if k != "actor_id"}), plan["sites"], Jsonb(jsonable_encoder(result)), uuid.UUID(p["actor_id"])])
    audit.record(c, worker_ctx(job), "portfolio.proposed", "portfolio_plan", pid, {"sites": len(plan["sites"]), "expected_evaluable": plan["expected_evaluable"],
                                                                                  "expected_cost": plan["expected_cost"]})
    return {"plan_id": pid, "status": "proposed", "study_id": sid, **result}


class ApproveIn(BaseModel):
    decision: Literal["approved", "rejected"] = "approved"
    note: str | None = Field(None, max_length=500)


@app.post("/v1/portfolios/{plan_id}/approve", tags=["portfolios"], summary="(+) A study director approves or rejects a proposed portfolio; the person who proposed it cannot")
def approve(plan_id: uuid.UUID, body: ApproveIn, ctx: Ctx = Depends(auth("portfolios:approve")), idem: str | None = IdemKey):
    def work(c):
        pl = c.execute("SELECT * FROM portfolio_plan WHERE id = %s FOR UPDATE", [plan_id]).fetchone()
        if not pl:
            raise Problem(404, "plan_not_found")
        if pl["status"] != "proposed":
            raise Problem(409, "already_decided", f"this plan is {pl['status']}")
        if pl["proposed_by"] == ctx.actor_id:
            raise Problem(403, "proposer_cannot_approve", "a site portfolio needs a second person")
        c.execute("UPDATE portfolio_plan SET status = %s, decided_by = %s, decided_at = now() WHERE id = %s", [body.decision, ctx.actor_id, plan_id])
        audit.record(c, ctx, f"portfolio.{body.decision}", "portfolio_plan", plan_id, {"sites": len(pl["sites"]), "note": body.note})
        return 200, {"plan_id": plan_id, "status": body.decision, "sites": pl["sites"] if body.decision == "approved" else [],
                     "expected_evaluable": pl["result"]["compared"]["milp"]["expected_evaluable"], "expected_cost": pl["result"]["compared"]["milp"]["expected_cost"]}
    return run(ctx, idem, body, work)


@app.get("/v1/portfolios/{plan_id}", tags=["portfolios"], summary="(+) A plan with its comparison, constraints and decision")
def plan_detail(plan_id: uuid.UUID, ctx: Ctx = Depends(auth("network:read"))):
    with db.tx(ctx.tenant_id) as c:
        pl = c.execute("SELECT * FROM portfolio_plan WHERE id = %s", [plan_id]).fetchone()
        if not pl:
            raise Problem(404, "plan_not_found")
    return jsonable_encoder(pl)


# --- the simulator runs the study --------------------------------------------------------------------------------------------------
class AdvanceIn(BaseModel):
    study_id: uuid.UUID


@app.post("/v1/network:advance", status_code=202, tags=["network"], summary="(+) The simulator runs the study for the horizon at the approved plan's sites (and, as simulation truth only, at the baseline's sites with the same draws); the service compares what happened with what it predicted")
def advance(body: AdvanceIn, ctx: Ctx = Depends(auth("network:advance")), idem: str | None = IdemKey):
    def work(c):
        network(c)
        s = study(c, body.study_id)
        if s["external_ref"] not in world.CATALOGUE:
            raise Problem(422, "not_a_simulated_protocol", "the simulator can only run protocols it wrote: " + ", ".join(world.CATALOGUE))
        if not c.execute("SELECT 1 FROM portfolio_plan WHERE study_id = %s AND status = 'approved'", [body.study_id]).fetchone():
            raise Problem(409, "no_approved_plan", "a study director must approve a site portfolio first")
        return 202, jobs.enqueue(c, ctx, "network.advance", body.model_dump(mode="json"))
    return run(ctx, idem, body, work)


@jobs.handler("network.advance")
def advance_job(c, job):
    sid = job["payload"]["study_id"]
    n = network(c)
    s = study(c, sid)
    pl = c.execute("SELECT * FROM portfolio_plan WHERE study_id = %s AND status = 'approved' ORDER BY decided_at DESC LIMIT 1", [sid]).fetchone()
    rows = {r["site"]: r for r in score_rows(c, sid)}
    horizon = next(iter(rows.values()))["horizon_months"]
    # --- simulation side: the generator's own protocol truth and its patients ---
    net = world.network(n["model_seed"])
    truth = world.catalogue_protocol(s["external_ref"])
    pools = world.truth_pools(net, truth["criteria"])
    base = pl["result"]["compared"]["top_by_history"]["sites"]
    ran = world.run_study(net, s["external_ref"], truth["indication"], truth["criteria"], sorted(set(pl["sites"]) | set(base)), months=horizon, pools=pools)
    # --- service side: what it predicted against what happened ---
    target = pl["result"]["target_evaluable"]

    def outcome(sites):
        monthly = np.sum([np.array(ran[x]["monthly"]) for x in sites], axis=0) if sites else np.zeros(horizon)
        ev = sum(ran[x]["enrolled"] - ran[x]["dropped"] for x in sites)
        cum = np.cumsum(monthly)
        drop_share = sum(ran[x]["dropped"] for x in sites) / max(1, sum(ran[x]["enrolled"] for x in sites))
        reach = next((k + 1 for k, v in enumerate(cum * (1 - drop_share)) if target and v >= target), None)
        return {"sites": len(sites), "enrolled": int(sum(ran[x]["enrolled"] for x in sites)), "dropped": int(sum(ran[x]["dropped"] for x in sites)),
                "evaluable": int(ev), "cumulative_enrolled": [int(v) for v in cum], "month_target_reached": reach,
                "never_opened": [x for x in sites if ran[x]["activation_months"] is None],
                "actual_cost": round(sum(rows[x]["activation_cost"] + rows[x]["per_patient_cost"] * ran[x]["enrolled"] for x in sites))}
    plan_out = outcome(pl["sites"])
    per_site = [{"site": x, "predicted": rows[x]["mean"], "p10": rows[x]["p10"], "p90": rows[x]["p90"], "enrolled": ran[x]["enrolled"], "dropped": ran[x]["dropped"],
                 "inside_interval": rows[x]["p10"] <= ran[x]["enrolled"] <= rows[x]["p90"], "activation_months": ran[x]["activation_months"],
                 "predicted_activation_months": rows[x]["activation_median_months"]} for x in sorted(pl["sites"], key=lambda x: -rows[x]["mean"])]
    pred = pl["result"]["compared"]["milp"]["predicted"]
    result = {"study_id": sid, "plan_id": pl["id"], "horizon_months": horizon, "target_evaluable": target, "plan": plan_out, "per_site": per_site,
              "predicted": pred, "predicted_expected_evaluable": pl["result"]["compared"]["milp"]["expected_evaluable"],
              "sites_inside_interval": sum(x["inside_interval"] for x in per_site),
              "simulation_truth": {"baseline_top_by_history": outcome(base),
                                   "truly_eligible_at_plan_sites": sum(pools[0][x] for x in pl["sites"]),
                                   "expected_eligible_at_plan_sites": round(sum(rows[x]["expected_eligible"] for x in pl["sites"]), 1),
                                   "true_monthly_rate_at_plan_sites": round(sum(ran[x]["true_rate"] for x in pl["sites"]), 2),
                                   "note": "what the generator did with its own protocol truth and patients; the analysis never reads this. The baseline ran with the same draws per site"}}
    rid = uuid.uuid4()
    c.execute("INSERT INTO study_run (id, tenant_id, study_id, plan_id, result) VALUES (%s,%s,%s,%s,%s)", [rid, job["tenant_id"], sid, pl["id"], Jsonb(jsonable_encoder(result))])
    c.execute("UPDATE network SET told = told || %s::jsonb", [json.dumps([{"ran": s["external_ref"], "sites": pl["sites"], "months": horizon,
                                                                          "at": datetime.datetime.now(datetime.UTC).isoformat()}])])
    audit.record(c, worker_ctx(job), "study.enrolment_simulated", "study", sid, {"plan": str(pl["id"]), "evaluable": plan_out["evaluable"], "months": horizon})
    return {"run_id": rid, **result}
