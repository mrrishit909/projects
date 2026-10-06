"""Public API (modular monolith). Blueprint services map to: billing-connectors and resource-inventory (account connection
and the sync that stores the inventory, hourly utilisation and CUR-style billing lines), utilization-engine (histories,
drill-downs, cost explanation), workload-forecast and rightsizer (recommendations with their SLO evidence and change risk),
commitment-optimizer (the savings-plan and reservation portfolio), iac-pr-bot (Terraform diffs as a pull request, never
applied) and savings-verifier (realised savings by counterfactual re-pricing). The simulator endpoints stand in for the
clouds themselves. Not built: real cloud SDK connectors, Kafka, ClickHouse; see the README.

    uvicorn finops.api:app          python -m core.jobs finops.api      # the worker
"""
import collections
import datetime
import difflib
import functools
import json
import pickle
import re
import uuid
from typing import Literal

import numpy as np
from fastapi import Depends, Header, Query
from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from core import audit, db, jobs
from core.app import Ctx, Problem, create_app, run

from . import engine, world

READ = {"estate:read", "jobs:read"}
ENGINEER = READ | {"recommendations:run", "simulations:run", "commitments:propose", "changes:propose", "changes:approve"}
PERMISSIONS = {"viewer": READ, "engineer": ENGINEER,
               "finops_lead": ENGINEER | {"accounts:connect", "simulator:control", "commitments:approve", "audit:read"}}
app = create_app("cloud-finops-optimizer", PERMISSIONS)
auth = app.state.auth
IdemKey = Header(None, alias="Idempotency-Key")
PRE_DAYS = 14                     # the verifier's window before a change
MIN_POST_DAYS = 7                 # ... and the least it needs after
SERVICE = {"vm": "compute", "pool": "kubernetes", "db": "database", "volume": "storage"}


def at(day):
    return datetime.datetime.combine(world.day_date(day), datetime.time(), datetime.UTC)


def day_of(d):
    return (d - world.START).days


def worker_ctx(job):
    return Ctx(job["tenant_id"], uuid.UUID(job["payload"]["actor_id"]), "worker", "system")


def estate(c):
    e = c.execute("SELECT * FROM estates").fetchone()
    if not e:
        raise Problem(409, "no_estate", "start the simulated cloud first: POST /v1/simulator:start")
    return e


def policy(c):
    row = c.execute("SELECT rules FROM policy").fetchone()
    return {**engine.POLICY, **(row["rules"] if row else {})}


@functools.lru_cache(maxsize=3)
def _sim(seed, d0, d1, told):
    t = json.loads(told)
    return world.run(seed, d0, d1, t["changes"], t["commitments"])


def sim_for(est, d0, d1, told=None):
    return _sim(est["model_seed"], d0, d1, json.dumps(told if told is not None else est["told"], sort_keys=True))


def rdict(row, cfg=None):
    """A stored resource as the engine reads it (optionally with another configuration)."""
    a = row["attributes"]
    out = {"id": str(row["id"]), "kind": row["kind"], "cloud": a["provider"], "size": a.get("size_index"), "min_nodes": a.get("min_nodes"),
           "max_nodes": a.get("max_nodes"), "gb": a.get("gb"), "env": a["tags"]["env"], "account": str(row["cloud_account_id"])}
    return {**out, **(cfg or {})}


def attributes(r, size, mins):
    a = {"provider": r["cloud"], "region": world.CLOUDS[r["cloud"]]["region"], "tf_address": r["tf_address"],
         "tags": {"env": r["env"], "team": r["team"], **({"schedule": "office-hours"} if r.get("schedule") == "office" else {})}}
    if r["kind"] in ("vm", "db"):
        a.update(type=world.type_name(r["cloud"], r["kind"], size), size_index=int(size), vcpu=world.VCPU[size], memory_gb=world.VCPU[size] * world.GB_PER_VCPU)
    elif r["kind"] == "pool":
        a.update(node_type=world.type_name(r["cloud"], "pool", world.NODE_SIZE), node_vcpu=world.VCPU[world.NODE_SIZE], min_nodes=int(mins),
                 max_nodes=r["max_nodes"], autoscaler_target=world.SCALE_TARGET)
    else:
        a.update(gb=r["gb"], volume_type={"aws": "gp3", "azure": "Premium_LRS", "gcp": "pd-balanced"}[r["cloud"]])
    return a


# --- the simulated clouds -------------------------------------------------------------------------------------------------
class StartIn(BaseModel):
    seed: int = Field(7, ge=1, le=10 ** 6)


@app.post("/v1/simulator:start", status_code=201, tags=["simulator"], summary="(+) Start the synthetic multi-cloud this tenant's connectors will read: six accounts on AWS, Azure and GCP with eight weeks of history. Returns the accounts a cloud console would list; nothing is stored about them until they are connected")
def start(body: StartIn, ctx: Ctx = Depends(auth("simulator:control")), idem: str | None = IdemKey):
    def work(c):
        if c.execute("SELECT 1 FROM estates").fetchone():
            raise Problem(409, "estate_exists", "this tenant already has an estate; `make reset` for a fresh demo")
        eid = uuid.uuid5(ctx.tenant_id, "estate")
        c.execute("INSERT INTO estates (id, tenant_id, name, model_seed, clock_day) VALUES (%s,%s,%s,%s,%s)", [eid, ctx.tenant_id, "Acme multi-cloud", body.seed, world.HISTORY_DAYS])
        c.execute("INSERT INTO policy (tenant_id, rules) VALUES (%s,%s) ON CONFLICT (tenant_id) DO NOTHING", [ctx.tenant_id, Jsonb(engine.POLICY)])
        audit.record(c, ctx, "simulator.started", "estate", eid, {"seed": body.seed})
        accounts = [{"provider": cl, "external_ref": ref, "name": name, "environment": env,
                     "credential_ref_example": {"aws": f"arn:aws:iam::{ref}:role/finops-readonly", "azure": f"azure-mi://{ref}/finops-reader",
                                                "gcp": f"gcp-sa://finops-reader@{ref}.iam.gserviceaccount.com"}[cl]} for _k, cl, ref, name, env, _ in world.ACCOUNTS]
        return 201, {"estate_id": eid, "clock": at(world.HISTORY_DAYS), "history_from": at(0), "accounts": accounts}
    return run(ctx, idem, body, work)


# --- billing connectors and inventory ---------------------------------------------------------------------------------------
REF_PATTERN = {"aws": r"^\d{12}$", "azure": r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", "gcp": r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$"}
CRED_PATTERN = {"aws": r"^arn:aws:iam::(\d{12}):role/[\w+=,.@-]{1,64}$", "azure": r"^azure-mi://([0-9a-f-]{36})/[\w-]{1,64}$",
                "gcp": r"^gcp-sa://[a-z][a-z0-9-]{4,29}@([a-z][a-z0-9-]{4,28}[a-z0-9])\.iam\.gserviceaccount\.com$"}
SECRET_LIKE = re.compile(r"(AKIA|ASIA)[0-9A-Z]{16}|-----BEGIN|\"private_key\"|[A-Za-z0-9/+=]{40}")


class ConnectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")             # a key, a secret or a token in the body is a validation error
    provider: Literal["aws", "azure", "gcp"]
    external_ref: str = Field(min_length=6, max_length=64, description="AWS account id, Azure subscription id or GCP project id")
    name: str = Field(min_length=1, max_length=80)
    credential_ref: str = Field(min_length=8, max_length=200, description="a role to assume or an identity to use; never a key")


@app.post("/v1/accounts/connect", status_code=202, tags=["accounts"], summary="Connect a cloud account with a read-only role or identity reference (never a key). Validated, then a job backfills eight weeks of inventory, hourly utilisation and billing lines")
def connect(body: ConnectIn, ctx: Ctx = Depends(auth("accounts:connect")), idem: str | None = IdemKey):
    def work(c):
        est = estate(c)
        if SECRET_LIKE.search(body.credential_ref):
            raise Problem(422, "secret_not_accepted", "send a role or identity reference; keys and secrets are never accepted or stored")
        if not re.match(REF_PATTERN[body.provider], body.external_ref):
            raise Problem(422, "bad_external_ref", f"not a valid {body.provider} account reference")
        m = re.match(CRED_PATTERN[body.provider], body.credential_ref)
        if not m:
            raise Problem(422, "bad_credential_ref", {"aws": "expected arn:aws:iam::<account>:role/<name>", "azure": "expected azure-mi://<subscription>/<identity>",
                                                      "gcp": "expected gcp-sa://<name>@<project>.iam.gserviceaccount.com"}[body.provider])
        if body.provider in ("aws", "azure") and m[1] != body.external_ref:
            raise Problem(422, "credential_account_mismatch", "the role belongs to a different account")
        acct = next((a for a in world.ACCOUNTS if a[2] == body.external_ref and a[1] == body.provider), None)
        if not acct:
            raise Problem(422, "account_not_reachable", "the role could not be assumed in that account")
        if c.execute("SELECT 1 FROM cloud_account WHERE external_ref = %s", [body.external_ref]).fetchone():
            raise Problem(409, "already_connected")
        aid = uuid.uuid5(ctx.tenant_id, f"account:{body.external_ref}")
        c.execute("""INSERT INTO cloud_account (id, tenant_id, provider, external_ref, name, credential_ref, metadata) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                  [aid, ctx.tenant_id, body.provider, body.external_ref, body.name, body.credential_ref,
                   Jsonb({"simulator_key": acct[0], "environment": acct[4], "region": world.CLOUDS[body.provider]["region"], "iac_repo": f"github.com/acme/infra-{acct[0]}"})])
        audit.record(c, ctx, "account.connect_requested", "cloud_account", aid, {"provider": body.provider, "external_ref": body.external_ref})
        return 202, jobs.enqueue(c, ctx, "accounts.sync", {"account_id": str(aid), "from_day": 0, "to_day": est["clock_day"]})
    return run(ctx, idem, body, work)


def sync(c, est, accounts, d0, d1):
    """The connectors' pull for days d0..d1-1: an inventory snapshot at the end, hourly utilisation and the billing lines."""
    t, seed = est["tenant_id"], est["model_seed"]
    sim = sim_for(est, d0, d1)
    by_ref = {a["external_ref"]: a for a in accounts}
    now = datetime.datetime.now(datetime.UTC)
    inv, metrics, lines, counts = [], [], [], collections.Counter()
    for r in world.estate(seed):
        a = by_ref.get(world.ACCOUNT[r["account"]][2])
        i = r["idx"]
        if not a or not sim["alive"][i].any():
            continue
        rid = uuid.uuid5(t, r["external_id"])
        alive = np.nonzero(sim["alive"][i])[0]
        last = alive[-1]
        status = "running" if sim["alive"][i][-1] else "deleted" if r["kind"] == "volume" else "terminated"
        attrs = attributes(r, int(sim["size"][i, last]), int(sim["min_nodes"][i, last]))
        inv.append((rid, t, a["id"], r["external_id"], r["kind"], r["name"], status, Jsonb(attrs), world.day_date(r["launched_day"]), at(d1), now))
        counts[status] += 1
        for k in alive:
            day = world.day_date(d0 + k)
            metrics.append((t, rid, day, *[[round(float(x), 4) for x in sim[key][i, k]] for key in ("cpu_util", "mem_util", "units", "io")]))
            size = int(sim["size"][i, k])
            if r["kind"] == "volume":
                usage, utype, unit = float(r["gb"]), f"VolumeUsage.{attrs['volume_type']}", world.price(r["cloud"], "volume", gb=1) * 24
            else:
                usage = float(sim["units"][i, k].sum())
                typ = world.type_name(r["cloud"], r["kind"], world.NODE_SIZE if r["kind"] == "pool" else size)
                utype = {"vm": "BoxUsage", "pool": "NodeUsage", "db": "InstanceUsage"}[r["kind"]] + ":" + typ
                unit = world.price(r["cloud"], r["kind"], world.NODE_SIZE if r["kind"] == "pool" else size)
            lines.append((t, a["id"], rid, None, day, "usage", SERVICE[r["kind"]], utype, engine.pool_key(r["cloud"], r["kind"], size),
                          usage, unit, float(sim["od"][i, k].sum()), float(sim["eff"][i, k].sum())))
    if len(accounts) and sim["commit_lines"]:
        payer = {}
        for a in sorted(accounts, key=lambda a: a["name"]):
            payer.setdefault(a["provider"], a["id"])
        told = {cm["id"]: cm for cm in est["told"]["commitments"]}
        for cl in sim["commit_lines"]:
            cm = told[cl["id"]]
            if cl["cloud"] not in payer:
                continue
            pool = f"compute:{cl['cloud']}" if cl["kind"] == "compute_sp" else f"db:{cl['cloud']}:{cm['type']}"
            for k in range(d1 - d0):
                fee = float(cl["unused_fee"][k].sum())
                if fee > 0:
                    lines.append((t, payer[cl["cloud"]], None, uuid.UUID(cl["id"]), world.day_date(d0 + k), "commitment_unused", "commitment",
                                  "SavingsPlanUnused" if cl["kind"] == "compute_sp" else "ReservationUnused", pool, 0.0, 0.0, 0.0, fee))
    db.many(c, """INSERT INTO resource (id, tenant_id, cloud_account_id, external_id, kind, name, status, attributes, launched_on, observed_at, synced_at)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (tenant_id, external_id) DO UPDATE
                  SET status = EXCLUDED.status, attributes = EXCLUDED.attributes, observed_at = EXCLUDED.observed_at, synced_at = EXCLUDED.synced_at""", inv)
    db.load(c, "resource_metric", ["tenant_id", "resource_id", "day", "cpu_util", "mem_util", "units", "io"], metrics)
    db.load(c, "cost_line", ["tenant_id", "cloud_account_id", "resource_id", "commitment_id", "day", "line_type", "service", "usage_type", "pricing_pool",
                             "usage_amount", "unit_price", "on_demand_cost", "effective_cost"], lines)
    c.execute("UPDATE cloud_account SET status = 'connected', synced_through_day = %s, last_sync_at = %s WHERE id = ANY(%s)", [d1, now, [a["id"] for a in accounts]])
    return {"resources": len(inv), "by_status": dict(counts), "metric_days": len(metrics), "cost_lines": len(lines),
            "spend": round(sum(x[-1] for x in lines), 2)}


@jobs.handler("accounts.sync")
def sync_job(c, job):
    p = job["payload"]
    est = estate(c)
    a = c.execute("SELECT * FROM cloud_account WHERE id = %s", [p["account_id"]]).fetchone()
    t0 = datetime.datetime.now(datetime.UTC)
    out = sync(c, est, [a], p["from_day"], p["to_day"])
    out["seconds"] = round((datetime.datetime.now(datetime.UTC) - t0).total_seconds(), 2)
    audit.record(c, worker_ctx(job), "account.synced", "cloud_account", a["id"], {k: v for k, v in out.items() if k != "by_status"})
    return {"account": a["name"], "provider": a["provider"], "external_ref": a["external_ref"], "days": [str(world.day_date(p["from_day"])), str(world.day_date(p["to_day"] - 1))], **out}


@app.get("/v1/accounts", tags=["accounts"], summary="(+) Connected accounts: resources, spend, how fresh the inventory is (policy: under 15 minutes)")
def accounts(ctx: Ctx = Depends(auth("estate:read"))):
    with db.tx(ctx.tenant_id) as c:
        est = estate(c)
        pol = policy(c)
        rows = c.execute("""SELECT a.id, a.provider, a.external_ref, a.name, a.status, a.metadata, a.synced_through_day, a.last_sync_at,
                                   (SELECT count(*) FROM resource r WHERE r.cloud_account_id = a.id AND r.status = 'running') AS running
                              FROM cloud_account a ORDER BY a.provider, a.name""").fetchall()
        spend = {r["cloud_account_id"]: r["s"] for r in c.execute("SELECT cloud_account_id, sum(effective_cost) AS s FROM cost_line WHERE day >= %s GROUP BY 1",
                                                                       [world.day_date(est["clock_day"] - 30)])}
    now = datetime.datetime.now(datetime.UTC)
    out = []
    for r in rows:
        age = (now - r["last_sync_at"]).total_seconds() / 60 if r["last_sync_at"] else None
        out.append({**r, "spend_30d": round(spend.get(r["id"], 0), 2), "inventory_age_minutes": round(age, 1) if age is not None else None,
                    "fresh": age is not None and age <= pol["freshness_minutes"]})
    return jsonable_encoder({"clock": at(est["clock_day"]), "freshness_policy_minutes": pol["freshness_minutes"], "items": out})


# --- reading the estate ------------------------------------------------------------------------------------------------------
@app.get("/v1/estate/overview", tags=["estate"], summary="(+) The command centre: daily spend by cloud and service, accounts and inventory freshness, open recommendations, commitments, verified savings and the models")
def overview(ctx: Ctx = Depends(auth("estate:read"))):
    with db.tx(ctx.tenant_id) as c:
        est = estate(c)
        clock = est["clock_day"]
        daily = c.execute("""SELECT l.day, a.provider, l.service, sum(l.effective_cost) AS cost, sum(l.on_demand_cost) AS od
                               FROM cost_line l JOIN cloud_account a ON a.id = l.cloud_account_id GROUP BY 1, 2, 3 ORDER BY 1""").fetchall()
        inv = c.execute("SELECT kind, status, count(*) AS n FROM resource GROUP BY 1, 2").fetchall()
        recs = c.execute("SELECT status, count(*) AS n, sum(monthly_savings) AS s FROM recommendation WHERE status <> 'superseded' GROUP BY 1").fetchall()
        commits = c.execute("SELECT provider, instrument, instance_type, amount, hourly_fee, status, start_day FROM commitment WHERE status IN ('approved', 'active') ORDER BY provider").fetchall()
        verified = c.execute("SELECT change_request_id, estimate, baselines, window_from, window_to FROM savings_measurement WHERE resource_id IS NULL ORDER BY created_at DESC LIMIT 1").fetchone()
        models = c.execute("SELECT name, version, data_snapshot, metrics, approved FROM model_artifact ORDER BY created_at DESC, name LIMIT 6").fetchall()
        n_acc = c.execute("SELECT count(*) AS n FROM cloud_account WHERE status = 'connected'").fetchone()["n"]
    by_day = collections.defaultdict(lambda: collections.Counter())
    for r in daily:
        by_day[str(r["day"])][r["provider"]] += r["cost"]
    last30 = [r for r in daily if day_of(r["day"]) >= clock - 30]
    svc = collections.Counter()
    for r in last30:
        svc[r["service"]] += r["cost"]
    return jsonable_encoder({"clock": at(clock), "accounts_connected": n_acc,
                             "daily": [{"day": d, **{k: round(v, 2) for k, v in by.items()}} for d, by in sorted(by_day.items())],
                             "spend_30d": round(sum(r["cost"] for r in last30), 2), "on_demand_30d": round(sum(r["od"] for r in last30), 2),
                             "by_service_30d": {k: round(v, 2) for k, v in svc.most_common()},
                             "inventory": inv, "recommendations": {r["status"]: {"count": r["n"], "monthly_savings": round(r["s"] or 0, 2)} for r in recs},
                             "commitments": commits, "latest_verified": verified, "models": models})


@app.get("/v1/resources", tags=["estate"], summary="(+) The inventory, most expensive first (last seven days of effective cost)")
def resources(kind: Literal["vm", "pool", "db", "volume", "all"] = "all", status: Literal["running", "all"] = "running", limit: int = Query(50, ge=1, le=500),
              ctx: Ctx = Depends(auth("estate:read"))):
    with db.tx(ctx.tenant_id) as c:
        est = estate(c)
        rows = c.execute("""SELECT r.id, r.kind, r.name, r.status, r.attributes, r.external_id, a.name AS account, a.provider,
                                   coalesce(sum(l.effective_cost), 0) AS cost_7d
                              FROM resource r JOIN cloud_account a ON a.id = r.cloud_account_id
                              LEFT JOIN cost_line l ON l.resource_id = r.id AND l.day >= %s
                             WHERE (%s = 'all' OR r.kind = %s) AND (%s = 'all' OR r.status = %s)
                             GROUP BY r.tenant_id, r.id, a.name, a.provider ORDER BY cost_7d DESC LIMIT %s""",
                         [world.day_date(est["clock_day"] - 7), kind, kind, status, status, limit]).fetchall()
    return jsonable_encoder({"items": [{**r, "cost_7d": round(r["cost_7d"], 2)} for r in rows]})


@app.get("/v1/resources/{resource_id}", tags=["estate"], summary="(+) One resource: inventory, hourly utilisation, the forecast band for the next week at its current size, its recommendations and its daily cost")
def resource_detail(resource_id: uuid.UUID, days: int = Query(21, ge=7, le=56), ctx: Ctx = Depends(auth("estate:read"))):
    with db.tx(ctx.tenant_id) as c:
        est = estate(c)
        row = c.execute("SELECT r.*, a.name AS account FROM resource r JOIN cloud_account a ON a.id = r.cloud_account_id WHERE r.id = %s", [resource_id]).fetchone()
        if not row:
            raise Problem(404, "resource_not_found")
        h = histories(c, 0, est["clock_day"], [resource_id]).get(resource_id)
        recs = c.execute("SELECT id, action, from_config, to_config, monthly_savings, confidence, risk, status, reason, evidence, created_at FROM recommendation WHERE resource_id = %s AND status <> 'superseded' ORDER BY created_at DESC", [resource_id]).fetchall()
        cost = c.execute("SELECT day, sum(effective_cost) AS cost, sum(on_demand_cost) AS od FROM cost_line WHERE resource_id = %s GROUP BY day ORDER BY day", [resource_id]).fetchall()
    out = {"resource": row, "recommendations": recs, "daily_cost": cost[-days:], "hourly": None}
    if h:
        n = min(days * 24, len(h["units"]))
        cap = row["attributes"].get("vcpu") or row["attributes"].get("node_vcpu") or 0
        y = h["cpu_util"] * cap * (h["units"] if row["kind"] == "pool" else 1)
        hourly = {"t0": at((h["t0"] + len(h["units"]) - n) // 24), "cpu_util": h["cpu_util"][-n:], "mem_util": h["mem_util"][-n:],
                  "units": h["units"][-n:], "io": h["io"][-n:], "cpu_demand_vcpu": y[-n:]}
        if row["kind"] != "volume" and row["status"] == "running" and len(y) >= 7 * 24:
            p, lo, hi, b = engine.forecast_band(y, h["t0"], 7 * 24, np.random.default_rng(0))
            hourly["forecast"] = {"point": p, "p10": lo, "p90": hi, "growth_per_week": round(float(np.exp(b) - 1), 4), "model": engine.FORECAST_VERSION}
        out["hourly"] = {k: (np.round(v, 4).tolist() if isinstance(v, np.ndarray) else v) for k, v in hourly.items()}
        if "forecast" in hourly:
            out["hourly"]["forecast"] = {k: (np.round(v, 3).tolist() if isinstance(v, np.ndarray) else v) for k, v in hourly["forecast"].items()}
    return jsonable_encoder(out)


def histories(c, d_from, d_to, ids=None):
    """Hourly arrays per resource over [d_from, d_to): {resource_id: {cpu_util, mem_util, units, io, t0}}."""
    q = "SELECT resource_id, day, cpu_util, mem_util, units, io FROM resource_metric WHERE day >= %s AND day < %s"
    args = [world.day_date(d_from), world.day_date(d_to)]
    if ids is not None:
        q += " AND resource_id = ANY(%s)"
        args.append(list(ids))
    acc = {}
    for r in c.execute(q + " ORDER BY resource_id, day", args):
        a = acc.setdefault(r["resource_id"], {"first": r["day"], "cpu_util": [], "mem_util": [], "units": [], "io": []})
        for k in ("cpu_util", "mem_util", "units", "io"):
            a[k].append(r[k])
    return {rid: {**{k: np.asarray(a[k], float).ravel() for k in ("cpu_util", "mem_util", "units", "io")}, "t0": day_of(a["first"]) * 24} for rid, a in acc.items()}


@app.get("/v1/costs/explain", tags=["costs"], summary="Why spend changed: a period against an earlier one of the same length, split into usage, configuration (resizes), rate (commitments), new and removed resources, with the biggest movers and totals by service, account or resource")
def costs_explain(end: datetime.date | None = None, days: int = Query(7, ge=1, le=28), compare_end: datetime.date | None = Query(None, description="end of the earlier period (default: where the later one starts)"),
                  group_by: Literal["service", "account", "resource"] = "service", ctx: Ctx = Depends(auth("estate:read"))):
    with db.tx(ctx.tenant_id) as c:
        est = estate(c)
        end = end or world.day_date(est["clock_day"])
        b0 = end - datetime.timedelta(days=days)
        a1 = compare_end or b0
        a0 = a1 - datetime.timedelta(days=days)
        if a0 < world.START or day_of(end) > est["clock_day"] or a1 > b0:
            raise Problem(422, "outside_history", f"two periods, the earlier first, between {world.START} and {world.day_date(est['clock_day'])}")
        rows = c.execute("""SELECT coalesce(l.resource_id::text, 'commitment:' || l.commitment_id::text) AS k, l.day >= %s AS b, l.service, a.name AS account,
                                   coalesce(r.name || ' (' || coalesce(r.attributes->>'type', r.attributes->>'node_type', (r.attributes->>'gb') || ' GB') || ')', l.usage_type) AS label,
                                   sum(CASE WHEN l.line_type = 'usage' THEN l.usage_amount ELSE 1 END) AS u, sum(l.on_demand_cost) AS od, sum(l.effective_cost) AS cost
                              FROM cost_line l JOIN cloud_account a ON a.id = l.cloud_account_id LEFT JOIN resource r ON r.id = l.resource_id
                             WHERE (l.day >= %s AND l.day < %s) OR (l.day >= %s AND l.day < %s) GROUP BY 1, 2, 3, 4, 5""", [b0, a0, a1, b0, end]).fetchall()
    per = {False: {}, True: {}}
    group = {False: collections.Counter(), True: collections.Counter()}
    for r in rows:
        per[r["b"]][r["k"]] = (r["u"], r["od"], r["cost"], r["label"])
        group[r["b"]][r[group_by] if group_by != "resource" else r["label"]] += r["cost"]
    drivers = engine.explain(per[False], per[True])
    total_a, total_b = sum(group[False].values()), sum(group[True].values())
    groups = sorted(set(group[False]) | set(group[True]), key=lambda g: -group[True][g])
    return jsonable_encoder({"period": [b0, end], "compared_with": [a0, a1], "total": round(total_b, 2), "previous": round(total_a, 2), "change": round(total_b - total_a, 2),
                             "drivers": drivers, "groups": [{"group": g, "previous": round(group[False][g], 2), "total": round(group[True][g], 2),
                                                            "change": round(group[True][g] - group[False][g], 2)} for g in groups[:12]],
                             "how": "usage: more or fewer units at the old effective rate; configuration: a different list price per unit (a resize); rate: a different discount on the same list price (commitments)"})


# --- rightsizing --------------------------------------------------------------------------------------------------------------
class RunIn(BaseModel):
    note: str | None = Field(None, max_length=200)


@app.post("/v1/recommendations/run", status_code=202, tags=["recommendations"], summary="Run the forecast, the SLO-constrained rightsizer and change-risk scoring over every running resource; returns recommendations with their evidence, and what the average-utilisation rule would have done instead")
def recommendations_run(body: RunIn, ctx: Ctx = Depends(auth("recommendations:run")), idem: str | None = IdemKey):
    def work(c):
        estate(c)
        if not c.execute("SELECT 1 FROM cloud_account WHERE status = 'connected'").fetchone():
            raise Problem(409, "no_accounts", "connect an account first")
        return 202, jobs.enqueue(c, ctx, "recommendations.run", body.model_dump())
    return run(ctx, idem, body, work)


def train_risk_model(rows, H, clock, rng):
    """Backtest on the estate's own history: features as of four weeks ago for every one- and two-step resize, labelled by
    whether that size would have broken the SLO in the four weeks since (from observed utilisation)."""
    cut = (clock - 28) * 24
    X, y, who = [], [], []
    for row in rows:
        h = H.get(row["id"])
        if row["kind"] not in ("vm", "db") or not h or h["t0"] > cut - 14 * 24 or h["t0"] + len(h["units"]) < clock * 24:
            continue
        r = rdict(row)
        k = cut - h["t0"]
        past = {key: h[key][:k] for key in ("cpu_util", "mem_util", "units", "io")}
        after = {key: h[key][k:] for key in ("cpu_util", "mem_util", "units", "io")}
        for s, feats in engine.candidate_features(r, past, h["t0"], rng):
            X.append([feats[f] for f in engine.RISK_FEATURES])
            y.append(engine.breached(r, {"set": {"size": r["size"] - s}}, engine.observed(r, after)))
            who.append(row["id"])
    if len(set(y)) < 2:
        return None, {"n": len(y), "note": "not enough outcomes to train"}
    ids = sorted(set(who), key=str)
    half = {i for i in ids[::2]}
    tr = np.array([w in half for w in who])
    m_half = engine.train_risk(np.array(X)[tr], np.array(y)[tr])
    metrics = {"training_rows": len(y), "positives": int(sum(y)), "holdout": engine.score_risk(m_half, np.array(X)[~tr], np.array(y)[~tr]),
               "how": "fitted on half the resources, scored on the other half; the production model is refitted on all"}
    return engine.train_risk(X, y), metrics


def describe(row, r, action, s):
    a = row["attributes"]
    if "size" in s:
        return f"{a.get('type')} -> {world.type_name(r['cloud'], row['kind'], s['size'])}"
    if "min_nodes" in s:
        return f"min nodes {a.get('min_nodes')} -> {s['min_nodes']}"
    return action


@jobs.handler("recommendations.run")
def recommend_job(c, job):
    est = estate(c)
    pol = policy(c)
    clock = est["clock_day"]
    now = datetime.datetime.now(datetime.UTC)
    accts = {a["id"]: a for a in c.execute("SELECT * FROM cloud_account WHERE status = 'connected'")}
    stale = {i: (now - a["last_sync_at"]).total_seconds() / 60 for i, a in accts.items() if (now - a["last_sync_at"]).total_seconds() > pol["freshness_minutes"] * 60}
    rows = c.execute("SELECT * FROM resource WHERE status = 'running' AND cloud_account_id = ANY(%s) ORDER BY external_id", [list(accts)]).fetchall()
    H = histories(c, 0, clock)
    rng = np.random.default_rng([est["model_seed"], clock])
    risk_model, risk_metrics = train_risk_model(rows, H, clock, rng)
    tag = str(est["tenant_id"])[:8]
    versions = {"forecast": engine.FORECAST_VERSION, "rightsizer": engine.RIGHTSIZER_VERSION, "risk": f"{engine.RISK_VERSION}+{tag}.d{clock}"}
    snapshot = f"hourly utilisation of {len(H)} resources, {world.day_date(0)} to {world.day_date(clock - 1)}"
    for name, version, metrics, art in (("change-risk", versions["risk"], risk_metrics, pickle.dumps(risk_model) if risk_model else None),
                                        ("rightsizer", engine.RIGHTSIZER_VERSION, {"policy": pol}, None), ("workload-forecast", engine.FORECAST_VERSION, {"method": "hour-of-week profile x weekly log-linear trend, day-block bootstrap"}, None)):
        c.execute("""INSERT INTO model_artifact (tenant_id, name, version, data_snapshot, metrics, artifact, approved) VALUES (%s,%s,%s,%s,%s,%s,true)
                     ON CONFLICT (tenant_id, name, version) DO UPDATE SET metrics = EXCLUDED.metrics, artifact = EXCLUDED.artifact, data_snapshot = EXCLUDED.data_snapshot""",
                  [est["tenant_id"], name, version, snapshot, Jsonb(metrics), art])
    run_id = uuid.uuid4()
    c.execute("UPDATE recommendation SET status = 'superseded' WHERE status IN ('open', 'review')")
    recs, naive_recs, model_runs = [], [], []
    for row in rows:
        h = H.get(row["id"])
        if not h:
            continue
        r = rdict(row)
        rec = engine.rightsize(r, h, h["t0"], rng, pol)
        nv = engine.naive(r, h, pol)
        if nv:
            naive_recs.append((row, nv, rec))
        if not rec:
            continue
        feats = rec.pop("_features", None)
        risk = engine.risk_score(risk_model, feats) if feats else None
        status, reason = ("review", rec.get("reason")) if rec["action"] == "review" else ("open", None)
        if status == "open" and risk is not None and risk > pol["risk_review_above"]:
            status, reason = "review", f"change risk {risk:.2f} is above the policy's {pol['risk_review_above']}"
        if status == "open" and row["cloud_account_id"] in stale:
            status, reason = "review", f"inventory is {stale[row['cloud_account_id']]:.0f} minutes old (policy: {pol['freshness_minutes']})"
        a = row["attributes"]
        frm = {"size": a.get("size_index"), "type": a.get("type")} if row["kind"] in ("vm", "db") else {"min_nodes": a.get("min_nodes")} if row["kind"] == "pool" else {"gb": a.get("gb")}
        rid = uuid.uuid4()
        inputs = engine.feature_hash({"resource": str(row["id"]), "hours": len(h["units"]), "cpu": h["cpu_util"][-168:].round(3).tolist(), "units": h["units"][-168:].tolist()})
        evidence = {**rec.get("evidence", {}), **({"risk_features": {k: round(v, 4) for k, v in feats.items()}} if feats else {})}
        recs.append((rid, est["tenant_id"], run_id, row["id"], rec["action"], Jsonb(frm), Jsonb(rec.get("set", {})), rec.get("monthly_savings", 0.0), rec.get("confidence"),
                     risk, status, reason, Jsonb({**evidence, "to": rec.get("to"), "from": rec.get("from")}), Jsonb(versions), inputs))
        model_runs.append((est["tenant_id"], engine.RIGHTSIZER_VERSION, versions["rightsizer"], f"resource:{row['id']}", inputs,
                           Jsonb({"action": rec["action"], "set": rec.get("set"), "confidence": rec.get("confidence")})))
        if risk is not None:
            model_runs.append((est["tenant_id"], "change-risk", versions["risk"], f"resource:{row['id']}", engine.feature_hash(feats), Jsonb({"risk": round(risk, 4)})))
    db.load(c, "recommendation_run", ["id", "tenant_id", "clock_day", "summary", "model_versions", "created_by"],
            [(run_id, est["tenant_id"], clock, Jsonb({}), Jsonb(versions), uuid.UUID(job["payload"]["actor_id"]))])
    db.load(c, "recommendation", ["id", "tenant_id", "run_id", "resource_id", "action", "from_config", "to_config", "monthly_savings", "confidence", "risk", "status", "reason",
                                  "evidence", "model_versions", "inputs_hash"], recs)
    db.load(c, "model_run", ["tenant_id", "model_name", "version", "subject", "inputs_hash", "result"], model_runs)
    by = collections.defaultdict(lambda: {"count": 0, "monthly_savings": 0.0})
    for x in recs:
        k = f"{x[10]}:{x[4]}"
        by[k]["count"] += 1
        by[k]["monthly_savings"] = round(by[k]["monthly_savings"] + x[7], 2)
    ours = {x[3]: x for x in recs}
    disagree = []
    for row, nv, rec in naive_recs:
        mine = ours.get(row["id"])
        if mine and mine[10] == "open" and mine[6].obj == nv["set"]:
            continue
        h = H[row["id"]]
        r = rdict(row)
        p, extra = engine.slo_risk(r, h, h["t0"], nv, np.random.default_rng([est["model_seed"], 7]), k=100, policy=pol)
        a = row["attributes"]
        what = (f"{a.get('type')} -> {world.type_name(r['cloud'], row['kind'], nv['set']['size'])}" if "size" in nv["set"] else
                f"min nodes {a.get('min_nodes')} -> {nv['set']['min_nodes']}" if "min_nodes" in nv["set"] else "terminate" if row["kind"] == "vm" else "delete")
        last14 = slice(len(h["units"]) - 14 * 24, None)
        run14 = h["units"][last14] > 0
        disagree.append({"resource_id": row["id"], "name": row["name"], "kind": row["kind"], "naive_change": what, "naive_monthly_savings": nv["monthly_savings"],
                         "mean_cpu_14d": round(float(h["cpu_util"][last14][run14].mean()), 3) if run14.any() else None,
                         "p99_cpu_56d": round(float(np.quantile(h["cpu_util"][h["units"] > 0], 0.99)), 3) if (h["units"] > 0).any() else None,
                         "max_mem_56d": round(float(h["mem_util"].max()), 3), "attached_hours_56d": int(h["units"].sum()) if row["kind"] == "volume" else None,
                         "p_breach": round(p, 3), "ours": describe(row, r, mine[4], mine[6].obj) + f" ({mine[10]})" if mine else "no change"})
    disagree.sort(key=lambda d: -d["p_breach"] * d["naive_monthly_savings"])
    kept = [d for d in disagree if d["ours"] == "no change" and d["p99_cpu_56d"] and d["mean_cpu_14d"]]
    spotlight = max(kept, key=lambda d: d["p99_cpu_56d"] / d["mean_cpu_14d"]) if kept else None
    summary = {"run_id": run_id, "clock": at(clock), "resources_analysed": len(rows), "recommendations": len(recs), "by_status_action": dict(by),
               "open_monthly_savings": round(sum(x[7] for x in recs if x[10] == "open"), 2), "review_monthly_savings": round(sum(x[7] for x in recs if x[10] == "review"), 2),
               "baseline": {"rule": "14-day mean CPU < 2%: terminate; < 20%: the smallest size with a mean of 40% or less; pools: the fewest nodes needed in 14 days; volumes unattached now: delete",
                            "recommendations": len(naive_recs), "monthly_savings": round(sum(nv["monthly_savings"] for _, nv, _ in naive_recs), 2),
                            "where_we_differ": len(disagree), "expected_breaches": round(sum(d["p_breach"] for d in disagree), 1), "examples": disagree[:12],
                            "spotlight": spotlight},
               "risk_model": risk_metrics, "model_versions": versions, "stale_accounts": len(stale)}
    c.execute("UPDATE recommendation_run SET summary = %s WHERE id = %s", [Jsonb(jsonable_encoder(summary)), run_id])
    audit.record(c, worker_ctx(job), "recommendations.ran", "recommendation_run", run_id, {"recommendations": len(recs), "open_monthly_savings": summary["open_monthly_savings"], "risk_model": versions["risk"]})
    return summary


@app.get("/v1/recommendations", tags=["recommendations"], summary="(+) Current recommendations with their evidence, most valuable first")
def recommendations(status: Literal["open", "review", "in_change_request", "applied", "current", "all"] = "current", limit: int = Query(200, ge=1, le=1000),
                    ctx: Ctx = Depends(auth("estate:read"))):
    with db.tx(ctx.tenant_id) as c:
        rows = c.execute("""SELECT x.id, x.resource_id, r.name, r.kind, a.name AS account, a.provider, x.action, x.from_config, x.to_config, x.monthly_savings, x.confidence,
                                   x.risk, x.status, x.reason, x.evidence, x.model_versions, x.inputs_hash
                              FROM recommendation x JOIN resource r ON r.id = x.resource_id JOIN cloud_account a ON a.id = r.cloud_account_id
                             WHERE (%s = 'all' AND x.status <> 'superseded') OR x.status = %s OR (%s = 'current' AND x.status IN ('open', 'review'))
                             ORDER BY x.monthly_savings DESC LIMIT %s""", [status, status, status, limit]).fetchall()
    return jsonable_encoder({"items": rows})


# --- commitments ----------------------------------------------------------------------------------------------------------------
class OptimizeIn(BaseModel):
    horizon_weeks: int = Field(13, ge=4, le=26)
    after_recommendations: bool = Field(True, description="forecast usage after the open recommendations are applied")
    budget_per_month: float | None = Field(None, gt=0, description="cap on new commitment fees per month")


@app.post("/v1/commitments/optimize", status_code=202, tags=["commitments"], summary="(+) A one-year commitment portfolio (compute savings plans per cloud, database reservations per type) as a mixed-integer programme over forecast scenarios of usage after the planned rightsizing, against committing to last month's minimum")
def optimize(body: OptimizeIn, ctx: Ctx = Depends(auth("commitments:propose")), idem: str | None = IdemKey):
    def work(c):
        estate(c)
        return 202, jobs.enqueue(c, ctx, "commitments.optimize", body.model_dump())
    return run(ctx, idem, body, work)


def price_of_type(cloud, typ):
    return world.price(cloud, "db", next(k for k in range(len(world.SIZES)) if world.type_name(cloud, "db", k) == typ))


@jobs.handler("commitments.optimize")
def optimize_job(c, job):
    p = job["payload"]
    est = estate(c)
    pol = policy(c)
    clock = est["clock_day"]
    rows = c.execute("SELECT * FROM resource WHERE status = 'running'").fetchall()
    H = histories(c, 0, clock)
    hours = p["horizon_weeks"] * engine.WEEK
    planned = {}
    if p["after_recommendations"]:
        planned = {r["resource_id"]: r["to_config"] for r in c.execute("SELECT resource_id, to_config FROM recommendation WHERE status IN ('open', 'in_change_request')")}
    rng = np.random.default_rng([est["model_seed"], clock, 3])
    pools, dbs = {}, collections.Counter()
    for row in rows:
        h = H.get(row["id"])
        if not h:
            continue
        r = rdict(row)
        cfg = {"size": r["size"], "min_nodes": r["min_nodes"], **planned.get(row["id"], {})}
        if row["kind"] == "db" and not cfg.get("terminate"):
            dbs[(r["cloud"], world.type_name(r["cloud"], "db", cfg["size"]))] += 1
            continue
        sp = engine.future_spend(r, h, cfg, clock * 24, hours, pol["scenarios"], rng)
        if sp is not None:
            pools[r["cloud"]] = pools.get(r["cloud"], 0) + sp
    plan = engine.optimise(pools, dict(dbs), hours, p["budget_per_month"])
    # the baseline, from the last 30 days as billed (before any rightsizing)
    lo = clock - 30
    units = {(r["resource_id"], r["day"]): np.asarray(r["units"], float) for r in c.execute("SELECT resource_id, day, units FROM resource_metric WHERE day >= %s", [world.day_date(lo)])}
    elig, db_days = collections.defaultdict(lambda: np.zeros(30 * 24)), collections.Counter()
    for ln in c.execute("SELECT resource_id, day, pricing_pool, unit_price, usage_amount FROM cost_line WHERE line_type = 'usage' AND day >= %s", [world.day_date(lo)]):
        k = day_of(ln["day"]) - lo
        if ln["pricing_pool"].startswith("compute:"):
            elig[ln["pricing_pool"].split(":")[1]][k * 24:(k + 1) * 24] += units[(ln["resource_id"], ln["day"])] * ln["unit_price"]
        elif ln["pricing_pool"].startswith("db:") and ln["usage_amount"] >= 24:
            db_days[(ln["resource_id"], ln["pricing_pool"])] += 1
    db_run = collections.Counter()
    for (rid, pool), n in db_days.items():
        if n == 30:
            _, cloud, typ = pool.split(":", 2)
            db_run[(cloud, typ)] += 1
    base = engine.last_month_minimum(dict(elig), db_run)
    for k in base["db_ri"]:
        cloud, typ = k.split("|")
        dbs.setdefault((cloud, typ), 0)
    cost = {name: engine.portfolio_cost(pl, pools, dict(dbs), hours) for name, pl in (("none", {"compute_sp": {}, "db_ri": {}}), ("baseline", base), ("optimised", plan))}
    clouds = []
    for cloud, sc in sorted(pools.items()):
        d = world.CLOUDS[cloud]["sp"]
        mean = np.sort(sc.mean(0))[::-1]
        q = np.linspace(0, len(mean) - 1, 60).astype(int)
        lo_, hi_ = np.sort(np.quantile(sc, 0.1, axis=0))[::-1], np.sort(np.quantile(sc, 0.9, axis=0))[::-1]
        a = plan["compute_sp"].get(cloud, 0.0)
        clouds.append({"provider": cloud, "commit_per_hour": a, "baseline_commit_per_hour": base["compute_sp"].get(cloud, 0.0), "discount": d,
                       "hourly_fee": round(a * (1 - d), 2), "expected_coverage": round(float(np.minimum(sc, a).sum() / sc.sum()), 3),
                       "expected_utilisation": round(float(np.minimum(sc, a).sum() / max(a * sc.size, 1e-9)), 3) if a else None,
                       "last_30d": {"min": round(float(elig[cloud].min()), 2), "mean": round(float(elig[cloud].mean()), 2)} if cloud in elig else None,
                       "forecast_mean": round(float(sc.mean()), 2), "duration_curve": {"mean": mean[q].round(2).tolist(), "p10": lo_[q].round(2).tolist(), "p90": hi_[q].round(2).tolist()}})
    reservations = [{"provider": k.split("|")[0], "instance_type": k.split("|")[1], "count": n, "baseline_count": base["db_ri"].get(k, 0),
                     "will_run": dbs.get(tuple(k.split("|")), 0), "hourly_fee_each": round(price_of_type(*k.split("|")) * (1 - world.CLOUDS[k.split("|")[0]]["ri"]), 4)}
                    for k, n in sorted({**{kk: 0 for kk in base["db_ri"]}, **plan["db_ri"]}.items())]
    pid = uuid.uuid4()
    inputs = engine.feature_hash({"pools": {k: float(v.mean()) for k, v in pools.items()}, "dbs": {f"{a}|{b}": n for (a, b), n in dbs.items()}, "hours": hours})
    result = {"portfolio_id": pid, "status": "proposed", "horizon_weeks": p["horizon_weeks"], "term_months": pol["commitment_term_months"],
              "after_recommendations": p["after_recommendations"], "planned_changes": len(planned), "scenarios": pol["scenarios"],
              "solver": {"optimal": plan["optimal"], "objective": plan["objective"]}, "compute": clouds, "reservations": reservations,
              "expected_cost": cost, "monthly_fees": round((sum(x["hourly_fee"] for x in clouds) + sum(x["count"] * x["hourly_fee_each"] for x in reservations)) * world.HOURS_MONTH, 2),
              "expected_savings_vs_none": round(cost["none"]["total"] - cost["optimised"]["total"], 2), "baseline_expected_savings_vs_none": round(cost["none"]["total"] - cost["baseline"]["total"], 2),
              "baseline_rule": "commit to the lowest hourly compute spend of the last 30 days, reserve every database that ran all of them (both before any rightsizing)",
              "model_version": engine.PORTFOLIO_VERSION, "inputs_hash": inputs}
    c.execute("""INSERT INTO commitment_portfolio (id, tenant_id, request, result, model_version, inputs_hash, proposed_by) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
              [pid, est["tenant_id"], Jsonb(p), Jsonb(jsonable_encoder(result)), engine.PORTFOLIO_VERSION, inputs, uuid.UUID(p["actor_id"])])
    cm = [(uuid.uuid4(), est["tenant_id"], pid, x["provider"], "compute_savings_plan", None, x["commit_per_hour"], x["hourly_fee"], x["discount"], pol["commitment_term_months"], "proposed")
          for x in clouds if x["commit_per_hour"] > 0]
    cm += [(uuid.uuid4(), est["tenant_id"], pid, x["provider"], "db_reservation", x["instance_type"], x["count"], x["count"] * x["hourly_fee_each"],
            world.CLOUDS[x["provider"]]["ri"], pol["commitment_term_months"], "proposed") for x in reservations if x["count"] > 0]
    db.load(c, "commitment", ["id", "tenant_id", "portfolio_id", "provider", "instrument", "instance_type", "amount", "hourly_fee", "discount", "term_months", "status"], cm)
    c.execute("INSERT INTO model_run (tenant_id, model_name, version, subject, inputs_hash, result) VALUES (%s,%s,%s,%s,%s,%s)",
              [est["tenant_id"], "commitment-optimizer", engine.PORTFOLIO_VERSION, f"portfolio:{pid}", inputs, Jsonb({"objective": plan["objective"]})])
    audit.record(c, worker_ctx(job), "commitments.proposed", "commitment_portfolio", pid, {"monthly_fees": result["monthly_fees"], "expected_savings": result["expected_savings_vs_none"]})
    return result


@app.post("/v1/commitments/{portfolio_id}/approve", tags=["commitments"], summary="(+) A FinOps lead who did not propose it approves or rejects a portfolio. Approval buys nothing: the purchase is made by a person in the cloud console (in the demo, by telling the simulator)")
def approve_portfolio(portfolio_id: uuid.UUID, decision: Literal["approved", "rejected"] = "approved", ctx: Ctx = Depends(auth("commitments:approve")), idem: str | None = IdemKey):
    def work(c):
        p = c.execute("SELECT * FROM commitment_portfolio WHERE id = %s FOR UPDATE", [portfolio_id]).fetchone()
        if not p:
            raise Problem(404, "portfolio_not_found")
        if p["status"] != "proposed":
            raise Problem(409, "already_decided", f"this portfolio is {p['status']}")
        if p["proposed_by"] == ctx.actor_id:
            raise Problem(403, "proposer_cannot_approve", "a commitment needs a second person")
        c.execute("UPDATE commitment_portfolio SET status = %s, decided_by = %s, decided_at = now() WHERE id = %s", [decision, ctx.actor_id, portfolio_id])
        c.execute("UPDATE commitment SET status = %s WHERE portfolio_id = %s", [decision, portfolio_id])
        audit.record(c, ctx, f"commitments.{decision}", "commitment_portfolio", portfolio_id, {"monthly_fees": p["result"]["monthly_fees"]})
        return 200, {"portfolio_id": portfolio_id, "status": decision, "monthly_fees": p["result"]["monthly_fees"], "purchased": False,
                     "next": "a person buys the approved commitments in each cloud console; nothing is bought by this service"}
    return run(ctx, idem, {"decision": decision}, work)


# --- SLO-risk simulation ----------------------------------------------------------------------------------------------------------
class SimulationIn(BaseModel):
    plans: list[Literal["slo_aware", "naive_average", "aggressive"]] = Field(default_factory=lambda: ["slo_aware", "naive_average", "aggressive"], min_length=1, max_length=3)
    weeks: int = Field(4, ge=1, le=8)
    paths: int = Field(200, ge=50, le=1000)


@app.post("/v1/simulations", status_code=202, tags=["simulations"], summary="Simulate SLO risk: each plan's changes run through forecast sample paths of the next weeks; probability of a breach per change, expected breaches and savings, side by side")
def simulate(body: SimulationIn, ctx: Ctx = Depends(auth("simulations:run")), idem: str | None = IdemKey):
    def work(c):
        estate(c)
        return 202, jobs.enqueue(c, ctx, "simulation.run", body.model_dump())
    return run(ctx, idem, body, work)


@jobs.handler("simulation.run")
def simulate_job(c, job):
    p = job["payload"]
    est = estate(c)
    pol = policy(c)
    clock = est["clock_day"]
    rows = {r["id"]: r for r in c.execute("SELECT * FROM resource WHERE status = 'running'")}
    H = histories(c, 0, clock)
    plans = {}
    for name in p["plans"]:
        if name == "slo_aware":
            plans[name] = [(x["resource_id"], {"set": x["to_config"], "action": x["action"], "monthly_savings": x["monthly_savings"]})
                           for x in c.execute("SELECT resource_id, to_config, action, monthly_savings FROM recommendation WHERE status = 'open'") if x["resource_id"] in rows]
            continue
        changes = []
        aggressive = {**pol, "cpu_p99_target": 0.95, "mem_p99_target": 0.98, "path_quantile": 0.5, "max_steps": 3}
        rng = np.random.default_rng([est["model_seed"], clock, 5])
        for rid, row in rows.items():
            h = H.get(rid)
            if not h:
                continue
            x = engine.naive(rdict(row), h, pol) if name == "naive_average" else engine.rightsize(rdict(row), h, h["t0"], rng, aggressive)
            if x and x["action"] != "review":
                changes.append((rid, x))
        plans[name] = changes
    out = []
    for name, changes in plans.items():
        rng = np.random.default_rng([est["model_seed"], clock, 11])
        rows_out = []
        for rid, ch in changes:
            h = H[rid]
            prob, extra = engine.slo_risk(rdict(rows[rid]), h, h["t0"], ch, rng, k=p["paths"], weeks=p["weeks"], policy=pol)
            rows_out.append({"resource_id": rid, "name": rows[rid]["name"], "kind": rows[rid]["kind"], "action": ch["action"], "set": ch["set"],
                             "monthly_savings": ch["monthly_savings"], "p_breach": round(prob, 3), "extra_hot_hours_share": round(extra, 4)})
        rows_out.sort(key=lambda x: -x["p_breach"])
        ps = np.array([x["p_breach"] for x in rows_out]) if rows_out else np.zeros(0)
        out.append({"plan": name, "changes": len(rows_out), "monthly_savings": round(sum(x["monthly_savings"] for x in rows_out), 2),
                    "expected_breaches": round(float(ps.sum()), 2), "changes_over_10pct": int((ps > 0.1).sum()),
                    "p_any_breach": round(float(1 - np.prod(1 - ps)), 3), "riskiest": rows_out[:8],
                    "savings_at_risk": round(sum(x["monthly_savings"] * x["p_breach"] for x in rows_out), 2)})
    sid = uuid.uuid4()
    result = {"simulation_id": sid, "weeks": p["weeks"], "paths": p["paths"], "plans": out,
              "slo": f"a breach: hours above {pol['breach_cpu']:.0%} CPU more than 1% of running hours beyond today's, memory above 100%, or a terminated or deleted resource needed",
              "how": "every change is replayed against forecast sample paths of the resource's own demand (hour-of-week profile, trend, whole-day residuals); the probability is the share of paths that break the SLO",
              "model_version": engine.FORECAST_VERSION}
    c.execute("INSERT INTO simulation (id, tenant_id, request, result, created_by) VALUES (%s,%s,%s,%s,%s)", [sid, est["tenant_id"], Jsonb(p), Jsonb(jsonable_encoder(result)), uuid.UUID(p["actor_id"])])
    audit.record(c, worker_ctx(job), "simulation.ran", "simulation", sid, {x["plan"]: x["expected_breaches"] for x in out})
    return result


# --- the Terraform pull request ----------------------------------------------------------------------------------------------------
class PullRequestIn(BaseModel):
    recommendation_ids: list[uuid.UUID] | None = Field(None, max_length=500, description="default: every open recommendation")
    title: str = Field("Rightsize idle and oversized resources", min_length=3, max_length=120)
    apply: bool = Field(False, description="apply the change directly; refused unless the tenant's policy allows direct mutation (it does not by default)")


def pr_row(r):
    risk = "" if r["risk"] is None else f"{r['risk']:.2f}"
    ev = ", ".join(f"{k} {v}" for k, v in r["evidence"].items() if not isinstance(v, (dict, str)))[:160]
    return f"| `{r['address']}` | {r['change']} | {r['monthly_savings']:,.0f} | {risk} | {ev} |"


def state_of(c, account_id):
    return {r["external_id"]: {"size": r["attributes"].get("size_index"), "min_nodes": r["attributes"].get("min_nodes"), "alive": r["status"] == "running"}
            for r in c.execute("SELECT external_id, attributes, status FROM resource WHERE cloud_account_id = %s", [account_id])}


@app.post("/v1/iac/pull-request", status_code=201, tags=["iac"], summary="Turn recommendations into Terraform changes: a unified diff per account repository and a pull request description with the evidence, risk and rollback. A draft until a second person approves it; this service never applies it")
def pull_request(body: PullRequestIn, ctx: Ctx = Depends(auth("changes:propose")), idem: str | None = IdemKey):
    def work(c):
        est = estate(c)
        pol = policy(c)
        if body.apply and not pol["allow_direct_mutation"]:
            raise Problem(403, "direct_mutation_disabled", "this service changes infrastructure only through reviewed pull requests; the tenant's policy does not allow direct mutation")
        if body.recommendation_ids is None:
            recs = c.execute("SELECT x.*, r.external_id, r.name, r.kind, r.cloud_account_id, r.attributes FROM recommendation x JOIN resource r ON r.id = x.resource_id WHERE x.status = 'open' ORDER BY x.monthly_savings DESC").fetchall()
        else:
            recs = c.execute("SELECT x.*, r.external_id, r.name, r.kind, r.cloud_account_id, r.attributes FROM recommendation x JOIN resource r ON r.id = x.resource_id WHERE x.id = ANY(%s)", [body.recommendation_ids]).fetchall()
            missing = set(body.recommendation_ids) - {x["id"] for x in recs}
            if missing:
                raise Problem(404, "recommendation_not_found", ", ".join(map(str, sorted(missing, key=str))))
        not_open = [str(x["id"]) for x in recs if x["status"] != "open"]
        if not_open:
            raise Problem(409, "recommendation_not_open", f"{len(not_open)} recommendations are not open (in review, already in a change request, or superseded)")
        if not recs:
            raise Problem(422, "nothing_to_change", "no open recommendations")
        accts = {a["id"]: a for a in c.execute("SELECT * FROM cloud_account")}
        files, rows = {}, []
        for aid in sorted({x["cloud_account_id"] for x in recs}, key=str):
            a = accts[aid]
            before = state_of(c, aid)
            after = {k: dict(v) for k, v in before.items()}
            for x in recs:
                if x["cloud_account_id"] != aid:
                    continue
                s = x["to_config"]
                if s.get("terminate"):
                    after[x["external_id"]]["alive"] = False
                else:
                    after[x["external_id"]].update(s)
            key = a["metadata"]["simulator_key"]
            old, new = world.terraform(est["model_seed"], key, before), world.terraform(est["model_seed"], key, after)
            repo = a["metadata"]["iac_repo"]
            files[repo] = {path: "".join(difflib.unified_diff(old[path].splitlines(True), new.get(path, "").splitlines(True), f"a/{path}", f"b/{path}", n=2))
                           for path in old if old[path] != new.get(path, "")}
        for x in recs:
            ev = x["evidence"]
            rows.append({"resource": x["name"], "address": x["attributes"]["tf_address"], "change": f"{ev.get('from')} -> {ev.get('to')}", "monthly_savings": x["monthly_savings"],
                         "risk": x["risk"], "confidence": x["confidence"], "evidence": {k: v for k, v in ev.items() if k not in ("risk_features", "from", "to")}})
        total = round(sum(x["monthly_savings"] for x in recs), 2)
        risks = [x["risk"] for x in recs if x["risk"] is not None]
        body_md = "\n".join([f"## {body.title}", "", f"{len(recs)} changes across {len(files)} repositories, about **${total:,.0f} a month** at on-demand prices.",
                             "Generated by the FinOps optimizer from eight weeks of hourly utilisation. Every resize keeps forecast p99 CPU under "
                             f"{pol['cpu_p99_target']:.0%} and memory under {pol['mem_p99_target']:.0%} in {pol['path_quantile']:.0%} of sample paths; changes with "
                             f"a change risk above {pol['risk_review_above']} were left out for review.", "",
                             "| Resource | Change | $/month | Risk | Evidence |", "|---|---|---|---|---|"] +
                            [pr_row(r) for r in rows] +
                            ["", "**Before merging**: take a final snapshot of every volume and instance this removes (the runbook's step 2).",
                             "**Rollback**: revert this pull request; every change is a size, a node-pool floor or a removed block.",
                             "**After merging**: the savings verifier compares the bill with what the old configuration would have cost."])
        cid = uuid.uuid4()
        summary = {"changes": len(recs), "monthly_savings": total, "max_risk": round(max(risks), 3) if risks else None, "repositories": sorted(files),
                   "by_action": dict(collections.Counter(x["action"] for x in recs))}
        c.execute("""INSERT INTO change_request (id, tenant_id, title, recommendation_ids, files, body, summary, proposed_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                  [cid, ctx.tenant_id, body.title, [x["id"] for x in recs], Jsonb(files), body_md, Jsonb(summary), ctx.actor_id])
        c.execute("UPDATE recommendation SET status = 'in_change_request' WHERE id = ANY(%s)", [[x["id"] for x in recs]])
        audit.record(c, ctx, "change_request.proposed", "change_request", cid, summary)
        return 201, {"change_request_id": cid, "status": "draft", "title": body.title, "summary": summary, "files": files, "body": body_md, "changes": rows,
                     "infrastructure_mutated": False}
    return run(ctx, idem, body, work)


@app.post("/v1/change-requests/{cr_id}/approve", tags=["iac"], summary="(+) A second person approves (the pull request is opened for the team's pipeline) or rejects (the recommendations go back to open). The proposer cannot approve; nothing is applied")
def approve_change(cr_id: uuid.UUID, decision: Literal["approved", "rejected"] = "approved", ctx: Ctx = Depends(auth("changes:approve")), idem: str | None = IdemKey):
    def work(c):
        cr = c.execute("SELECT * FROM change_request WHERE id = %s FOR UPDATE", [cr_id]).fetchone()
        if not cr:
            raise Problem(404, "change_request_not_found")
        if cr["status"] != "draft":
            raise Problem(409, "already_decided", f"this change request is {cr['status']}")
        if cr["proposed_by"] == ctx.actor_id:
            raise Problem(403, "proposer_cannot_approve", "a change to infrastructure needs a second person")
        status = "opened" if decision == "approved" else "rejected"
        c.execute("UPDATE change_request SET status = %s, approved_by = %s, approved_at = now() WHERE id = %s", [status, ctx.actor_id, cr_id])
        if status == "rejected":
            c.execute("UPDATE recommendation SET status = 'open' WHERE id = ANY(%s)", [cr["recommendation_ids"]])
        audit.record(c, ctx, f"change_request.{status}", "change_request", cr_id, {"changes": cr["summary"]["changes"]})
        return 200, {"change_request_id": cr_id, "status": status, "approved_by": ctx.actor_name, "repositories": cr["summary"]["repositories"],
                     "branch": f"finops/{str(cr_id)[:8]}", "infrastructure_mutated": False,
                     "next": "the team's CI runs terraform plan on the pull request and their pipeline applies it on merge; this service has no write access to any cloud"}
    return run(ctx, idem, {"decision": decision}, work)


@app.get("/v1/change-requests/{cr_id}", tags=["iac"], summary="(+) A change request: status, diffs, description, approvals")
def change_request(cr_id: uuid.UUID, ctx: Ctx = Depends(auth("estate:read"))):
    with db.tx(ctx.tenant_id) as c:
        cr = c.execute("SELECT * FROM change_request WHERE id = %s", [cr_id]).fetchone()
    if not cr:
        raise Problem(404, "change_request_not_found")
    return jsonable_encoder(cr)


# --- the clock moves: merged pull requests, purchases, and four weeks of billing -----------------------------------------------------
class AdvanceIn(BaseModel):
    days: int = Field(ge=1, le=35)
    merge_change_requests: list[uuid.UUID] = Field(default_factory=list, max_length=10)
    purchase_portfolios: list[uuid.UUID] = Field(default_factory=list, max_length=5)
    apply_after_days: int = Field(1, ge=0, le=7)


@app.post("/v1/simulator:advance", status_code=202, tags=["simulator"], summary="(+) Run the simulated clouds forward. The simulator can be told that the team's pipeline merged and applied an opened pull request and that approved commitments were bought; the connectors then sync the new days and the savings verifier measures what the changes saved")
def advance(body: AdvanceIn, ctx: Ctx = Depends(auth("simulator:control")), idem: str | None = IdemKey):
    def work(c):
        est = estate(c)
        if body.apply_after_days >= body.days:
            raise Problem(422, "apply_outside_window", "changes must take effect inside the days being run")
        if est["clock_day"] + body.days > 120:
            raise Problem(422, "beyond_simulation", "the simulated estate runs to 2026-12-08")
        for cr in body.merge_change_requests:
            row = c.execute("SELECT status FROM change_request WHERE id = %s", [cr]).fetchone()
            if not row or row["status"] != "opened":
                raise Problem(409, "change_request_not_open", f"{cr}: only an approved (opened) pull request can be merged")
        for pf in body.purchase_portfolios:
            row = c.execute("SELECT status FROM commitment_portfolio WHERE id = %s", [pf]).fetchone()
            if not row or row["status"] != "approved":
                raise Problem(409, "portfolio_not_approved", f"{pf}: only an approved portfolio can be bought")
        return 202, jobs.enqueue(c, ctx, "simulator.advance", body.model_dump(mode="json"))
    return run(ctx, idem, body, work)


@jobs.handler("simulator.advance")
def advance_job(c, job):
    p = job["payload"]
    est = estate(c)
    d0, d1 = est["clock_day"], est["clock_day"] + p["days"]
    A = d0 + p["apply_after_days"]
    told = {"changes": list(est["told"]["changes"]), "commitments": list(est["told"]["commitments"])}
    merged, bought = [], []
    for cr_id in p["merge_change_requests"]:
        ids = c.execute("SELECT recommendation_ids FROM change_request WHERE id = %s", [cr_id]).fetchone()["recommendation_ids"]
        recs = c.execute("SELECT x.id, x.to_config, r.external_id FROM recommendation x JOIN resource r ON r.id = x.resource_id WHERE x.id = ANY(%s)", [ids]).fetchall()
        told["changes"] += [{"resource": x["external_id"], "day": A, "set": x["to_config"], "change_request": cr_id} for x in recs]
        c.execute("UPDATE change_request SET status = 'merged', applied_day = %s WHERE id = %s", [A, cr_id])
        c.execute("UPDATE recommendation SET status = 'applied' WHERE id = ANY(%s)", [[x["id"] for x in recs]])
        merged.append(cr_id)
    for pf in p["purchase_portfolios"]:
        for cm in c.execute("SELECT * FROM commitment WHERE portfolio_id = %s AND status = 'approved'", [pf]).fetchall():
            told["commitments"].append({"id": str(cm["id"]), "cloud": cm["provider"], "kind": "compute_sp" if cm["instrument"] == "compute_savings_plan" else "db_ri",
                                        "type": cm["instance_type"], "amount": cm["amount"], "start_day": A, "portfolio": pf})
        c.execute("UPDATE commitment SET status = 'active', start_day = %s WHERE portfolio_id = %s AND status = 'approved'", [A, pf])
        c.execute("UPDATE commitment_portfolio SET status = 'purchased' WHERE id = %s", [pf])
        bought.append(pf)
    c.execute("UPDATE estates SET told = %s, clock_day = %s", [Jsonb(told), d1])
    est = estate(c)
    accounts = c.execute("SELECT * FROM cloud_account WHERE status = 'connected'").fetchall()
    t0 = datetime.datetime.now(datetime.UTC)
    synced = sync(c, est, accounts, d0, d1)
    synced["seconds"] = round((datetime.datetime.now(datetime.UTC) - t0).total_seconds(), 2)
    verified, truth = [], {}
    for cr in c.execute("SELECT * FROM change_request WHERE status = 'merged' AND applied_day IS NOT NULL").fetchall():
        if d1 - cr["applied_day"] < MIN_POST_DAYS:
            continue
        v = verify_change_request(c, est, cr)
        verified.append(v)
        others = [x for x in told["changes"] if x.get("change_request") != str(cr["id"])]
        w = sim_for(est, d0, d1)
        wo = sim_for(est, d0, d1, {"changes": others, "commitments": told["commitments"]})
        lo = max(cr["applied_day"], d0)
        truth[str(cr["id"])] = round(world.bill(wo, (lo, d1)) - world.bill(w, (lo, d1)), 2)
    if bought:
        ncm = [x for x in told["commitments"] if x.get("portfolio") not in bought]
        wo = sim_for(est, d0, d1, {"changes": told["changes"], "commitments": ncm})
        truth["commitments_bought"] = round(world.bill(wo, (A, d1)) - world.bill(sim_for(est, d0, d1), (A, d1)), 2)
    audit.record(c, worker_ctx(job), "simulator.advanced", "estate", est["id"], {"days": p["days"], "merged": merged, "bought": bought, "verified": len(verified)})
    return {"from": at(d0), "to": at(d1), "applied_on": at(A), "merged_change_requests": merged, "purchased_portfolios": bought, "synced": synced,
            "verified": verified,
            "simulation_truth": {"true_savings_by_change_request": {k: v for k, v in truth.items() if k != "commitments_bought"},
                                 "true_commitment_savings": truth.get("commitments_bought"), "window_from": at(A), "window_to": at(d1),
                                 "note": "what the generator says the bill would have been without each change, re-run with the same demand; the analysis never reads this"}}


def verify_change_request(c, est, cr):
    """Counterfactual re-pricing over the days since the change, with the before/after, difference-in-differences and
    list-price estimates beside it, the SLO as it actually held, and a reconciliation of the re-pricing against the bill."""
    A, end = cr["applied_day"], est["clock_day"]
    H = (end - A) * 24
    lines = c.execute("""SELECT resource_id, commitment_id, day, line_type, pricing_pool, unit_price, usage_amount, on_demand_cost, effective_cost
                           FROM cost_line WHERE day >= %s AND day < %s""", [world.day_date(A - PRE_DAYS), world.day_date(end)]).fetchall()
    recs = c.execute("""SELECT x.*, r.kind, r.attributes, r.name, r.launched_on FROM recommendation x JOIN resource r ON r.id = x.resource_id
                         WHERE x.id = ANY(%s)""", [cr["recommendation_ids"]]).fetchall()
    treated_ids = {x["resource_id"] for x in recs}
    all_merged = {rid for row in c.execute("SELECT recommendation_ids FROM change_request WHERE status = 'merged'") for rid in
                  [x["resource_id"] for x in c.execute("SELECT resource_id FROM recommendation WHERE id = ANY(%s)", [row["recommendation_ids"]])]}
    post_metrics = histories(c, A, end)
    pre_metrics = histories(c, A - PRE_DAYS, A, list(treated_ids))
    full_pre = histories(c, 0, A, list(treated_ids))
    pools, rebuilt, billed = collections.defaultdict(lambda: np.zeros(H)), 0.0, 0.0
    by_res = collections.defaultdict(lambda: {"pre": 0.0, "post": 0.0, "pre_days": set(), "post_days": set(), "prices": set()})
    for ln in lines:
        k = day_of(ln["day"])
        if ln["line_type"] != "usage":
            continue
        b = by_res[ln["resource_id"]]
        b["pre" if k < A else "post"] += ln["effective_cost"]
        b["pre_days" if k < A else "post_days"].add(k)
        b["prices"].add(round(ln["unit_price"], 6))
        if k >= A:
            m = post_metrics.get(ln["resource_id"])
            u = m["units"][(k - A) * 24:(k - A + 1) * 24] if m is not None and len(m["units"]) >= (k - A + 1) * 24 else np.zeros(24)
            hourly = np.full(24, ln["usage_amount"] * ln["unit_price"] / 24) if ln["pricing_pool"].startswith("storage") else u * ln["unit_price"]
            pools[ln["pricing_pool"]][(k - A) * 24:(k - A + 1) * 24] += hourly
            rebuilt += float(hourly.sum())
            billed += ln["on_demand_cost"]
    cover, disc = collections.defaultdict(lambda: np.zeros(H)), {}
    for cm in c.execute("SELECT * FROM commitment WHERE status = 'active'"):
        key = f"compute:{cm['provider']}" if cm["instrument"] == "compute_savings_plan" else f"db:{cm['provider']}:{cm['instance_type']}"
        per = cm["amount"] if cm["instrument"] == "compute_savings_plan" else cm["amount"] * price_of_type(cm["provider"], cm["instance_type"])
        cover[key][max(0, (cm["start_day"] - A) * 24):] += per
        disc[key] = cm["discount"]
    pool_in = {k: (pools.get(k, np.zeros(H)), cover.get(k, np.zeros(H)), disc.get(k, 0.0)) for k in set(pools) | set(cover)}
    treated, slo = [], []
    for x in recs:
        rid = x["resource_id"]
        a = x["attributes"]
        old = {"size": x["from_config"].get("size"), "min_nodes": x["from_config"].get("min_nodes")}
        r = {"kind": x["kind"], "cloud": a["provider"], "gb": a.get("gb"), "max_nodes": a.get("max_nodes"), "size": old["size"], "min_nodes": old["min_nodes"]}
        m = post_metrics.get(rid)
        units = m["units"] if m is not None else np.zeros(H)
        units = np.pad(units, (0, H - len(units)))
        cpu = np.pad(m["cpu_util"], (0, H - len(m["cpu_util"]))) if m is not None else np.zeros(H)
        fp = full_pre.get(rid)
        run_pre = fp["units"] > 0 if fp else np.zeros(engine.WEEK, bool)
        t0 = fp["t0"] if fp else 0
        how = engine.running_share(run_pre, t0)
        prev = 0.0
        pm = pre_metrics.get(rid)
        if pm is not None and x["kind"] == "pool":
            prev = float(pm["cpu_util"][-1] * pm["units"][-1] * a.get("node_vcpu", 16))
        delta = engine.counterfactual_delta(r, old, x["to_config"], {"units": units, "cpu_util": cpu, "prev": prev}, how, A * 24)
        b = by_res[rid]
        treated.append({"id": str(rid), "cloud": a["provider"], "kind": x["kind"], "delta": delta, "eff_pre": b["pre"], "eff_post": b["post"], "name": x["name"]})
        if m is not None and x["kind"] in ("vm", "db") and not x["to_config"].get("terminate"):
            run_ = units > 0
            slo.append({"resource": x["name"], "hot_share": round(engine.hot_share(cpu, run_), 4), "max_mem": round(float(np.pad(m["mem_util"], (0, H - len(m["mem_util"]))).max()), 3),
                        "breached": bool(engine.hot_share(cpu, run_) > 0.01 or np.pad(m["mem_util"], (0, H - len(m["mem_util"]))).max() >= 0.999)})
        elif m is not None and x["kind"] == "pool" and pm is not None:
            hot_post = float(((cpu > 0.9) & (units > 0)).mean())
            hot_pre = float(((pm["cpu_util"] > 0.9) & (pm["units"] > 0)).mean())
            slo.append({"resource": x["name"], "hot_share": round(hot_post, 4), "hot_share_before": round(hot_pre, 4), "breached": hot_post - hot_pre > 0.01})
    controls = collections.defaultdict(lambda: [0.0, 0.0])
    kinds = {r["id"]: (r["attributes"]["provider"], r["kind"]) for r in c.execute("SELECT id, kind, attributes FROM resource")}
    n_controls = 0
    for rid, b in by_res.items():
        if rid in all_merged or len(b["pre_days"]) < PRE_DAYS or len(b["post_days"]) < end - A or len(b["prices"]) != 1:
            continue
        n_controls += 1
        controls[kinds[rid]][0] += b["pre"] / PRE_DAYS
        controls[kinds[rid]][1] += b["post"] / (end - A)
    rows, total = engine.verify(treated, pool_in, {k: tuple(v) for k, v in controls.items()}, PRE_DAYS, end - A)
    rate = sum(ln["on_demand_cost"] - ln["effective_cost"] for ln in lines if ln["line_type"] == "usage" and day_of(ln["day"]) >= A) - \
        sum(ln["effective_cost"] for ln in lines if ln["line_type"] == "commitment_unused" and day_of(ln["day"]) >= A)
    days = end - A
    detail = {"window_days": days, "pre_days": PRE_DAYS, "controls": n_controls, "realised_slo": slo, "slo_breaches": sum(s["breached"] for s in slo),
              "monthly_run_rate": round(total["counterfactual"] / days * 30.4, 2), "commitment_savings_measured": round(rate, 2),
              "reconciliation": {"rebuilt_on_demand": round(rebuilt, 2), "billed_on_demand": round(billed, 2), "difference": round((rebuilt - billed) / billed, 5) if billed else None},
              "how": "each pricing pool (compute per cloud, each database type, storage) is billed again with the old configurations' hourly on-demand cost put back, "
                     "through the savings plans and reservations in force: a dollar of usage above a commitment saves a dollar, one inside it saves nothing"}
    mid = uuid.uuid4()
    names = {t["id"]: t["name"] for t in treated}
    meas = [(mid, est["tenant_id"], cr["id"], None, world.day_date(A), world.day_date(end), "counterfactual_repricing", total["counterfactual"],
             Jsonb({k: v for k, v in total.items() if k != "counterfactual"}), Jsonb(detail), engine.VERIFIER_VERSION)]
    meas += [(uuid.uuid4(), est["tenant_id"], cr["id"], uuid.UUID(r["resource_id"]), world.day_date(A), world.day_date(end), "counterfactual_repricing", r["estimate"],
              Jsonb({"did": r["did"], "before_after": r["before_after"], "list_price": r["list_price"]}), Jsonb({"resource": names[r["resource_id"]]}), engine.VERIFIER_VERSION) for r in rows]
    c.execute("DELETE FROM savings_measurement WHERE change_request_id = %s", [cr["id"]])
    db.load(c, "savings_measurement", ["id", "tenant_id", "change_request_id", "resource_id", "window_from", "window_to", "method", "estimate", "baselines", "detail", "model_version"], meas)
    audit.record(c, Ctx(est["tenant_id"], cr["proposed_by"], "worker", "system"), "savings.verified", "change_request", cr["id"], {"estimate": total["counterfactual"], "days": days})
    return {"change_request_id": cr["id"], "estimate": total["counterfactual"], "baselines": {k: v for k, v in total.items() if k != "counterfactual"}, **detail}


@app.get("/v1/savings/verified", tags=["savings"], summary="Verified savings of every applied change request: the counterfactual estimate with the before/after, difference-in-differences and list-price figures beside it, per resource, the SLO as it held, and the commitments' savings measured from the bill")
def savings_verified(ctx: Ctx = Depends(auth("estate:read"))):
    with db.tx(ctx.tenant_id) as c:
        estate(c)
        summ = c.execute("""SELECT m.change_request_id, cr.title, m.window_from, m.window_to, m.method, m.estimate, m.baselines, m.detail, m.model_version, cr.summary
                              FROM savings_measurement m JOIN change_request cr ON cr.id = m.change_request_id WHERE m.resource_id IS NULL ORDER BY m.created_at""").fetchall()
        per = c.execute("""SELECT m.change_request_id, m.resource_id, r.name, r.kind, m.estimate, m.baselines FROM savings_measurement m JOIN resource r ON r.id = m.resource_id
                            ORDER BY m.estimate DESC""").fetchall()
    return jsonable_encoder({"items": [{**s, "promised_monthly": s["summary"]["monthly_savings"], "resources": [p for p in per if p["change_request_id"] == s["change_request_id"]][:40]}
                                       for s in summ]})


@app.get("/v1/policy", tags=["policy"], summary="(+) The tenant's policy: SLO targets, abstention and review thresholds, freshness, and whether direct mutation is allowed (it is not by default)")
def get_policy(ctx: Ctx = Depends(auth("estate:read"))):
    with db.tx(ctx.tenant_id) as c:
        return jsonable_encoder(policy(c))
