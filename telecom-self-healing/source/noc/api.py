"""Public API (modular monolith). Blueprint services map to: telemetry-ingest (counters and alarms, validated, scored and
correlated as they land), topology-graph (sites, routers, links, neighbour relations, the current routing), anomaly-detection
(per-cell multivariate normal ranges), alarm-correlation (incidents and ranked root causes), capacity-forecast (per-cell
traffic, rolled up to every link), digital-twin (link loads for a routing over the next hours), policy-engine (the declared
envelope, checked when a plan is recommended, proposed and approved) and change-orchestrator (a second person approves, then
the change is applied and logged). Not built: Kafka, Flink, ClickHouse, Neo4j, a graph neural network; see the README.

    uvicorn noc.api:app          python -m core.jobs noc.api      # the worker
"""
import datetime
import functools
import io
import pickle
import time
import uuid
from typing import Literal

import numpy as np
from fastapi import Depends, Header, Query
from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from core import audit, db, jobs
from core.app import Ctx, Problem, create_app, run

from . import engine, world

READ = {"network:read", "jobs:read"}
ENGINEER = READ | {"telemetry:ingest", "incidents:correlate", "recommendations:run", "twin:run", "changes:propose"}
PERMISSIONS = {"viewer": READ, "noc_engineer": ENGINEER,
               "noc_manager": ENGINEER | {"network:load", "network:advance", "changes:approve", "audit:read"}}
app = create_app("telecom-self-healing", PERMISSIONS)
auth = app.state.auth
IdemKey = Header(None, alias="Idempotency-Key")
START = datetime.datetime(2026, 9, 7, 0, 0, tzinfo=datetime.UTC)        # a Monday
HISTORY = 28 * world.PER_DAY + 56            # four weeks, ending Monday 14:00
TRAIN_END = 21 * world.PER_DAY               # models learn on three weeks and are scored on the rest
HISTORY_FAULTS = 30
HOT_DAYS = 7                                 # counters kept in the transactional store; older history is the analytical store's job
EVIDENCE_LOOKBACK = 48
ENVELOPE = {"max_link_utilisation": 0.8, "forecast_margin": 0.05, "max_elements_changed": 3, "allowed_actions": ["reroute_site", "rollback_config"],
            "horizon_hours": 24, "approval": "a noc_manager who did not propose the plan"}


def at(t):
    return START + datetime.timedelta(minutes=world.STEP_MIN * int(t))


def worker_ctx(job):
    return Ctx(job["tenant_id"], uuid.UUID(job["payload"]["actor_id"]), "worker", "system")


def network_row(c):
    f = c.execute("SELECT * FROM networks").fetchone()
    if not f:
        raise Problem(409, "no_network", "load a network first: POST /v1/network:load")
    return f


def version(f):
    return f"noc-{str(f['id'])[:8]}-1"


# --- topology as stored -----------------------------------------------------------------------------------------------
def as_stored(net):
    """The generator's network in the shape the service keeps (sorted by id), without the generator's traffic bases."""
    links = {l["id"]: l for l in net["links"]}
    sites = [{**{k: s[k] for k in ("id", "x", "y", "role", "cluster", "area", "parent", "link", "alt_parent", "alt_link", "csr", "protected", "label")},
              "medium": links[s["link"]]["medium"]} for s in sorted(net["sites"], key=lambda s: s["id"])]
    return {"nodes": net["nodes"], "sites": sites, "links": sorted(({k: l[k] for k in ("id", "a", "b", "medium", "capacity", "role")} for l in net["links"]), key=lambda l: l["id"]),
            "cells": sorted(({k: c[k] for k in ("id", "site", "sector", "band", "capacity", "azimuth")} for c in net["cells"]), key=lambda c: c["id"]),
            "neighbours": net["neighbours"]}


@functools.lru_cache(maxsize=16)
def _net(tenant_id, network_id):
    with db.tx(tenant_id) as c:
        nodes = {r["id"]: {"id": r["id"], "kind": r["kind"], "x": r["x"], "y": r["y"], "cluster": r["cluster"]}
                 for r in c.execute("SELECT * FROM device WHERE kind IN ('core', 'agg') ORDER BY id")}
        links = {r["id"]: {"id": r["id"], "a": r["a_device"], "b": r["b_device"], "medium": r["medium"], "capacity": r["capacity_mbps"], "role": r["role"]}
                 for r in c.execute("SELECT * FROM link ORDER BY id")}
        sites = [{"id": r["id"], "x": r["x"], "y": r["y"], "role": r["role"], "cluster": r["cluster"], "area": r["area"], "parent": r["parent"],
                  "link": r["link_id"], "alt_parent": r["alt_parent"], "alt_link": r["alt_link_id"], "csr": f"CSR-{r['id']}", "protected": r["protected"],
                  "label": r["label"] or "", "medium": links[r["link_id"]]["medium"]} for r in c.execute("SELECT * FROM site ORDER BY id")]
        cells = [{"id": r["id"], "site": r["site_id"], "sector": r["sector_id"], "band": r["band"], "capacity": r["capacity_mbps"]}
                 for r in c.execute("SELECT * FROM cell ORDER BY id")]
        nb = [(r["src"], r["dst"], r["weight"]) for r in c.execute("SELECT src, dst, weight FROM topology_edge WHERE kind = 'neighbour' ORDER BY src, dst")]
    return {"nodes": nodes, "sites": sites, "links": list(links.values()), "cells": cells, "neighbours": nb}


def stored_net(f):
    return _net(str(f["tenant_id"]), str(f["id"]))


@functools.lru_cache(maxsize=16)
def _models(tenant_id, ver):
    with db.tx(tenant_id) as c:
        return {r["name"]: pickle.loads(r["artifact"]) for r in c.execute("SELECT name, artifact FROM model_artifacts WHERE version = %s", [ver])}


def models(f):
    return _models(str(f["tenant_id"]), version(f))


def envelope(c):
    r = c.execute("SELECT version, envelope FROM policy_envelope ORDER BY version DESC LIMIT 1").fetchone()
    return r["version"], r["envelope"]


def fast_load(c, table, cols, lines):
    """COPY text lines into a temp table, then insert through the RLS policy (core.db.load does the same row by row)."""
    c.execute(f"CREATE TEMP TABLE _fl (LIKE {table} INCLUDING DEFAULTS) ON COMMIT DROP")
    buf = io.StringIO()
    n = 0
    with c.cursor().copy(f"COPY _fl ({', '.join(cols)}) FROM STDIN") as cp:
        for line in lines:
            buf.write(line)
            n += 1
            if n % 20000 == 0:
                cp.write(buf.getvalue())
                buf = io.StringIO()
        cp.write(buf.getvalue())
    c.execute(f"INSERT INTO {table} ({', '.join(cols)}) SELECT {', '.join(cols)} FROM _fl")
    c.execute("DROP TABLE _fl")


def _arr(v):
    return "{" + ",".join(f"{x:.4g}" for x in v) + "}"


def _txt(v):
    return "\\N" if v is None else str(v).replace("\\", "\\\\").replace("\t", " ").replace("\n", " ")


def sample_lines(t, ids, vals, kind, tenant, source="oss", anomaly=None, flagged=None):
    ts = at(t).isoformat()
    for i, el in enumerate(ids):
        a = "\\N" if anomaly is None or not np.isfinite(anomaly[i]) else f"{min(float(anomaly[i]), 1e6):.4g}"
        fl = "t" if flagged is not None and flagged[i] else "f"
        yield f"{tenant}\t{el}\t{t}\t{ts}\t{source}\t{kind}\t{_arr(vals[i])}\t{a}\t{fl}\n"


SAMPLE_COLS = ["tenant_id", "element_id", "t", "ts", "source", "kind", "kpis", "anomaly", "flagged"]
ALARM_COLS = ["id", "tenant_id", "element_id", "t", "raised_at", "type", "severity", "related_element", "source", "incident_id"]


def alarm_line(a, tenant, incident_id):
    return "\t".join([a["id"], str(tenant), a["element"], str(a["t"]), (at(a["t"]) + datetime.timedelta(minutes=a.get("minute", 0))).isoformat(),
                      a["type"], a["severity"], _txt(a.get("related")), a.get("source", "element"), _txt(incident_id)]) + "\n"


def link_health(link_vals, net):
    cap = np.array([l["capacity"] for l in net["links"]])
    lv = np.asarray(link_vals)
    return (lv[:, 1] < 0.9 * cap) | (lv[:, 3] > 0.2)


# --- incidents: persistence ---------------------------------------------------------------------------------------------
def incident_row(topo, inc, tenant):
    alarms = inc["alarms"]
    return [inc["id"], tenant, inc["opened"], inc["last"], inc["status"], inc.get("merged_into"),
            engine.incident_kind(topo, inc["root"], alarms) if alarms else "merged", inc["root"], inc.get("confidence", 0.0), len(alarms),
            len({a["element"] for a in alarms}), Jsonb(inc.get("ranking", [])[:12]), Jsonb(engine.rank_by_count(alarms)[:5] if alarms else []),
            inc.get("ticket"), Jsonb({"correlator": engine.CORRELATOR_VERSION, "ranker": engine.RANKER_VERSION, "anomaly": engine.ANOMALY_VERSION})]


INCIDENT_UPSERT = """INSERT INTO incident (id, tenant_id, opened_t, last_t, status, merged_into, kind, root_element, confidence, alarm_count, element_count,
                                          ranking, baseline_top, ticket_root_cause, model_versions)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                     ON CONFLICT (id) DO UPDATE SET opened_t = EXCLUDED.opened_t, last_t = EXCLUDED.last_t, status = EXCLUDED.status,
                       merged_into = EXCLUDED.merged_into, kind = EXCLUDED.kind, root_element = EXCLUDED.root_element, confidence = EXCLUDED.confidence,
                       alarm_count = EXCLUDED.alarm_count, element_count = EXCLUDED.element_count, ranking = EXCLUDED.ranking,
                       baseline_top = EXCLUDED.baseline_top, updated_at = now()"""


class State:
    """What the live path needs between intervals: the correlator with its open incidents, the previous interval's anomaly
    flags and the evidence of the last twelve hours."""

    def __init__(self, c, f, net, m):
        t = f["next_t"]
        self.topo = engine.Topology(net, f["rerouted"])
        self.cell_ix = {x["id"]: i for i, x in enumerate(net["cells"])}
        evidence, configs = {}, {}
        for r in c.execute("SELECT element_id, t FROM metric_sample WHERE t >= %s AND flagged", [t - EVIDENCE_LOOKBACK]):
            evidence.setdefault(r["element_id"], set()).add(r["t"])
        for r in c.execute("SELECT element_id, t FROM configuration WHERE t >= %s ORDER BY t", [t - EVIDENCE_LOOKBACK]):
            configs.setdefault(r["element_id"], []).append(r["t"])
        self.cor = engine.Correlator(self.topo, evidence, configs)
        incs = c.execute("SELECT * FROM incident WHERE status = 'open'").fetchall()
        by = {i["id"]: {"id": str(i["id"]), "root": i["root_element"], "alarms": [], "opened": i["opened_t"], "last": i["last_t"], "status": "open",
                        "merged_into": None, "ranking": i["ranking"], "confidence": i["confidence"]} for i in incs}
        if by:
            for a in c.execute("SELECT id, element_id, t, raised_at, type, related_element, incident_id FROM alarm WHERE incident_id = ANY(%s)", [list(by)]):
                by[a["incident_id"]]["alarms"].append(alarm_dict(a))
        for inc in by.values():
            self.cor.add_incident(inc)
        self.prev_single = np.zeros(len(net["cells"]), bool)
        self.prev_vendor = np.zeros(len(net["cells"]), bool)
        self.standing = set()
        thr = m["anomaly-detector"].threshold
        for r in c.execute("SELECT element_id, anomaly, flagged FROM metric_sample WHERE t = %s AND kind = 'cell' AND source = 'oss'", [t - 1]):
            i = self.cell_ix[r["element_id"]]
            self.prev_single[i] = r["anomaly"] is None or r["anomaly"] > thr
            if r["flagged"]:
                self.standing.add(i)
        for r in c.execute("SELECT DISTINCT element_id FROM alarm WHERE t = %s AND source = 'element'", [t - 1]):
            if r["element_id"] in self.cell_ix:
                self.prev_vendor[self.cell_ix[r["element_id"]]] = True


def alarm_dict(a):
    t = a["t"]
    return {"id": str(a["id"]), "t": t, "minute": int((a["raised_at"] - at(t)).total_seconds() // 60), "element": a["element_id"], "type": a["type"],
            "related": a["related_element"]}


def persist(c, tenant, st, changed):
    """Write the incidents the correlator changed, and move the alarms of merged incidents."""
    rows = []
    for iid in changed:
        inc = st.cor.incidents[iid]
        rows.append(incident_row(st.topo, inc, tenant))
    if rows:
        db.many(c, INCIDENT_UPSERT, rows)
    for iid in changed:
        inc = st.cor.incidents[iid]
        if inc["status"] == "merged":
            c.execute("UPDATE alarm SET incident_id = %s WHERE incident_id = %s", [inc["merged_into"], iid])


def process(c, f, net, m, st, t, cell_vals, link_vals, alarms, configs, source="oss", log=True):
    """The telemetry path for one interval: store the counters, score every cell, raise KPI_ANOMALY where no vendor alarm
    explains an anomaly, store the alarms and configuration changes, correlate, persist. -> summary."""
    tenant = f["tenant_id"]
    ad = m["anomaly-detector"]
    d2, Z = ad.score(cell_vals[None], np.array([t]))
    d2, Z = d2[0], Z[0]
    single = d2 > ad.threshold
    vendor = np.zeros(len(net["cells"]), bool)
    for a in alarms:
        if a["element"] in st.cell_ix:
            vendor[st.cell_ix[a["element"]]] = True
    pers = single & st.prev_single
    derived = engine.derived_alarms(st.prev_single, single, vendor | st.prev_vendor, st.standing)
    for i in derived:
        alarms.append({"id": str(uuid.uuid4()), "t": t, "minute": 14, "element": net["cells"][i]["id"], "type": "KPI_ANOMALY", "severity": "minor",
                       "related": None, "source": "anomaly-detection",
                       "detail": engine.AnomalyModel.explain(Z[i])})
    lflag = link_health(link_vals, net)
    for i in np.nonzero(pers)[0]:
        st.cor.evidence.setdefault(net["cells"][i]["id"], set()).add(t)
    for j in np.nonzero(lflag)[0]:
        st.cor.evidence.setdefault(net["links"][j]["id"], set()).add(t)
    for row in configs:
        st.cor.configs.setdefault(row[1], []).append(t)
    changed = st.cor.feed(t, alarms)
    fast_load(c, "metric_sample", SAMPLE_COLS, list(sample_lines(t, [x["id"] for x in net["cells"]], cell_vals, "cell", tenant, source, d2, pers))
              + list(sample_lines(t, [x["id"] for x in net["links"]], link_vals, "link", tenant, source, None, lflag)))
    if alarms:
        fast_load(c, "alarm", ALARM_COLS, (alarm_line(a, tenant, st.cor.alarm_incident.get(a["id"])) for a in alarms))
    if configs:
        db.many(c, "INSERT INTO configuration (tenant_id, element_id, t, at, parameter, old_value, new_value, changed_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                [(tenant, r[1], t, at(t), r[2], str(r[3]), str(r[4]), r[5]) for r in configs])
    persist(c, tenant, st, changed)
    if log:
        c.execute("INSERT INTO model_runs (tenant_id, model_name, version, subject, inputs_hash, result) VALUES (%s,%s,%s,%s,%s,%s)",
                  [tenant, engine.ANOMALY_VERSION, version(f), f"interval:{t}", engine.feature_hash(Z), Jsonb({"cells": len(Z), "anomalous": int(pers.sum()),
                   "kpi_anomaly_raised": [net["cells"][i]["id"] for i in derived]})])
    st.prev_single, st.prev_vendor = single, vendor
    fam = {}
    for a in alarms:
        k = engine.family(a["type"])
        fam[k] = fam.get(k, 0) + 1
    return {"t": t, "at": at(t), "alarms": len(alarms), "by_family": fam, "kpi_anomaly": len(derived), "anomalous_cells": int(pers.sum()),
            "unhealthy_links": int(lflag.sum()), "incidents_changed": len(changed), "open_incidents": len(st.cor.open(t))}


# --- loading the network ------------------------------------------------------------------------------------------------
class LoadIn(BaseModel):
    seed: int = Field(7, ge=1, le=10 ** 6)


@app.post("/v1/network:load", status_code=202, tags=["network"], summary="(+) Load the synthetic metro: topology, four weeks of counters, alarms and configuration changes with thirty faults in them, all over before today; train the anomaly detector and the traffic forecaster on three weeks and score them on the rest; correlate the history's alarms and check the ranking against the closed tickets")
def load_network(body: LoadIn, ctx: Ctx = Depends(auth("network:load")), idem: str | None = IdemKey):
    def work(c):
        if c.execute("SELECT 1 FROM networks").fetchone():
            raise Problem(409, "network_exists", "this tenant already has a network; `make reset` for a fresh demo")
        return 202, jobs.enqueue(c, ctx, "network.load", body.model_dump())
    return run(ctx, idem, body, work)


def store_topology(c, t, net):
    db.load(c, "device", ["tenant_id", "id", "kind", "site_id", "cluster", "x", "y"],
            [(t, n["id"], n["kind"], None, n.get("cluster"), n["x"], n["y"]) for n in net["nodes"].values()]
            + [(t, s["csr"], "csr", s["id"], s["cluster"], s["x"], s["y"]) for s in net["sites"]])
    db.load(c, "site", ["tenant_id", "id", "cluster", "role", "area", "x", "y", "parent", "link_id", "alt_parent", "alt_link_id", "protected", "label"],
            [(t, s["id"], s["cluster"], s["role"], s["area"], s["x"], s["y"], s["parent"], s["link"], s["alt_parent"], s["alt_link"], s["protected"], s["label"] or None) for s in net["sites"]])
    sectors = sorted({(c_["sector"], c_["site"], c_["azimuth"]) for c_ in net["cells"]})
    db.load(c, "sector", ["tenant_id", "id", "site_id", "azimuth"], [(t, a, b, az) for a, b, az in sectors])
    db.load(c, "cell", ["tenant_id", "id", "sector_id", "site_id", "band", "capacity_mbps"], [(t, x["id"], x["sector"], x["site"], x["band"], x["capacity"]) for x in net["cells"]])
    db.load(c, "link", ["tenant_id", "id", "a_device", "b_device", "medium", "role", "capacity_mbps", "active"],
            [(t, l["id"], l["a"], l["b"], l["medium"], l["role"], l["capacity"], l["role"] != "alternate") for l in net["links"]])
    edges = [(t, s["id"], s["parent"], "backhaul", s["link"], None, True) for s in net["sites"]]
    edges += [(t, s["id"], s["alt_parent"], "standby", s["alt_link"], None, False) for s in net["sites"] if s["alt_parent"]]
    edges += [(t, a, b, "neighbour", None, w, True) for a, b, w in net["neighbours"]]
    db.load(c, "topology_edge", ["tenant_id", "src", "dst", "kind", "via", "weight", "active"], edges)


def to_stored_order(sim, net):
    """Index arrays mapping the generator's element order to the stored (sorted) order."""
    return (np.array([sim.cell_ix[x["id"]] for x in net["cells"]]), np.array([sim.link_ix[x["id"]] for x in net["links"]]))


@jobs.handler("network.load")
def load_job(c, job):
    t0 = time.perf_counter()
    tenant, seed = job["tenant_id"], job["payload"]["seed"]
    nid = uuid.uuid5(tenant, "network")
    gen = world.network(seed)
    faults = world.random_faults(gen, seed, 2 * world.PER_DAY, HISTORY, HISTORY_FAULTS)
    sim = world.Sim(gen, seed)
    out = sim.run(0, HISTORY, faults)
    net = as_stored(gen)
    store_topology(c, tenant, net)
    ci, li = to_stored_order(sim, net)
    T, ts = HISTORY, np.arange(HISTORY)
    cell = np.array([o["cell"] for o in out])[:, ci]
    link = np.array([o["link"] for o in out])[:, li]
    topo = engine.Topology(net)
    vendor = [(o["t"], a) for o in out for a in o["alarms"]]
    avail = cell[..., world.CELL_KPIS.index("available")] > 0.5
    quiet = engine.quiet_mask(topo, [(t_, a[2], a[3]) for t_, a in vendor], 0, T) & avail
    ad = engine.AnomalyModel().fit(cell[:TRAIN_END], ts[:TRAIN_END], quiet[:TRAIN_END])
    fc = engine.Forecaster().fit(cell[:TRAIN_END, :, 0], ts[:TRAIN_END], quiet[:TRAIN_END])
    d2, _ = ad.score(cell, ts)
    single = d2 > ad.threshold
    pers = engine.persistent(single)
    truth = np.array([o["impaired"] for o in out])[:, ci]
    metrics = {"anomaly-detector": anomaly_metrics(ad, cell, ts, truth, single), "traffic-forecaster": forecast_metrics(fc, cell[..., 0], ts, quiet, net)}
    # the history, interval by interval, as the live path would have seen it (in memory, stored in bulk below)
    cfg_rows = [r for o in out for r in o["config"]]
    configs = {}
    for r in cfg_rows:
        configs.setdefault(r[1], []).append(r[0])
    lflag = np.array([link_health(link[t_], net) for t_ in range(T)])
    evidence = {}
    for t_, i in zip(*np.nonzero(pers)):
        evidence.setdefault(net["cells"][i]["id"], set()).add(int(t_))
    for t_, j in zip(*np.nonzero(lflag)):
        evidence.setdefault(net["links"][j]["id"], set()).add(int(t_))
    cor = engine.Correlator(topo, evidence, configs)
    cell_ix = {x["id"]: i for i, x in enumerate(net["cells"])}
    by_t = {}
    for t_, a in vendor:
        by_t.setdefault(t_, []).append({"id": str(uuid.uuid4()), "t": t_, "minute": a[1], "element": a[2], "type": a[3], "severity": a[4], "related": a[5],
                                        "source": "element", "cause": a[6]})
    standing, prev_v, all_alarms = set(), np.zeros(len(net["cells"]), bool), []
    for t_ in range(T):
        batch = by_t.get(t_, [])
        v = np.zeros(len(net["cells"]), bool)
        for a in batch:
            if a["element"] in cell_ix:
                v[cell_ix[a["element"]]] = True
        if t_:
            for i in engine.derived_alarms(single[t_ - 1], single[t_], v | prev_v, standing):
                batch.append({"id": str(uuid.uuid4()), "t": t_, "minute": 14, "element": net["cells"][i]["id"], "type": "KPI_ANOMALY", "severity": "minor",
                              "related": None, "source": "anomaly-detection", "cause": out[t_]["cause"][ci[i]] or ""})
        prev_v = v
        cor.feed(t_, batch)
        all_alarms += batch
    fault_el = {fa["id"]: fa["element"] for fa in faults}
    incs = [i for i in cor.incidents.values() if i["status"] != "merged"]
    rca = {"incidents_with_ticket": 0, "top1": 0, "top3": 0, "baseline_top3": 0}
    for inc in incs:          # the closed tickets: what the NOC recorded as each incident's cause
        causes = [a["cause"] for a in inc["alarms"] if a["cause"]]
        if causes and inc["last"] < T - engine.HOLD:
            top = max(set(causes), key=causes.count)
            inc["ticket"] = fault_el[top]
            if causes.count(top) >= 3:
                ranked = [r["element"] for r in inc["ranking"]]
                rca["incidents_with_ticket"] += 1
                rca["top1"] += ranked[:1] == [inc["ticket"]]
                rca["top3"] += inc["ticket"] in ranked[:3]
                rca["baseline_top3"] += inc["ticket"] in engine.rank_by_count(inc["alarms"])[:3]
    fault_alarms = [a for a in all_alarms if a["cause"]]
    metrics["alarm-correlation"] = {"raw_alarms": len(all_alarms), "incidents": len(incs), "ratio": round(len(all_alarms) / max(1, len(incs)), 1),
                                    "dedup_groups": engine.baseline_groups(topo, all_alarms, "dedup"), "site_groups": engine.baseline_groups(topo, all_alarms, "site"),
                                    "fault_alarms": len(fault_alarms), "fault_incidents": sum(1 for i in incs if any(a["cause"] for a in i["alarms"])),
                                    "root_cause": rca}
    fa = metrics["alarm-correlation"]
    fa["fault_ratio"] = round(fa["fault_alarms"] / max(1, fa["fault_incidents"]), 1)
    for inc in cor.incidents.values():           # what was over before the demo is resolved
        if inc["status"] == "open" and inc["last"] < T - engine.HOLD:
            inc["status"] = "resolved"
    # store: a week of counters (the hot window), every alarm, every incident, the configuration log
    hot = T - HOT_DAYS * world.PER_DAY
    lines = []
    for t_ in range(hot, T):
        lines += sample_lines(t_, [x["id"] for x in net["cells"]], cell[t_], "cell", tenant, "oss", d2[t_], pers[t_])
        lines += sample_lines(t_, [x["id"] for x in net["links"]], link[t_], "link", tenant, "oss", None, lflag[t_])
    fast_load(c, "metric_sample", SAMPLE_COLS, lines)
    fast_load(c, "alarm", ALARM_COLS, (alarm_line(a, tenant, cor.alarm_incident.get(a["id"])) for a in all_alarms))
    for inc in cor.incidents.values():
        if inc["status"] == "merged":
            inc["alarms"] = []
    db.many(c, INCIDENT_UPSERT, [incident_row(topo, inc, tenant) for inc in cor.incidents.values() if inc["status"] != "merged"])
    db.many(c, "INSERT INTO configuration (tenant_id, element_id, t, at, parameter, old_value, new_value, changed_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            [(tenant, r[1], r[0], at(r[0]), r[2], str(r[3]), str(r[4]), r[5]) for r in cfg_rows])
    c.execute("INSERT INTO networks (id, tenant_id, name, model_seed, next_t, start_at, history_intervals, told) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
              [nid, tenant, "Rivermouth metro", seed, T, START, T, Jsonb(faults)])
    env = {**ENVELOPE, "protected_sites": sorted(s["id"] for s in net["sites"] if s["protected"])}
    c.execute("INSERT INTO policy_envelope (tenant_id, version, envelope) VALUES (%s, 1, %s)", [tenant, Jsonb(env)])
    ver = f"noc-{str(nid)[:8]}-1"
    snap = f"intervals 0-{T - 1} (train < {TRAIN_END}), {len(net['cells'])} cells, {len(net['links'])} links, seed {seed}"
    for name, obj in (("anomaly-detector", ad), ("traffic-forecaster", fc)):
        c.execute("INSERT INTO model_artifacts (tenant_id, name, version, data_snapshot, metrics, artifact, approved) VALUES (%s,%s,%s,%s,%s,%s,true)",
                  [tenant, name, ver, snap, Jsonb(metrics[name]), pickle.dumps(obj)])
    c.execute("INSERT INTO model_artifacts (tenant_id, name, version, data_snapshot, metrics, artifact, approved) VALUES (%s,%s,%s,%s,%s,%s,true)",
              [tenant, "alarm-correlation", ver, snap, Jsonb(metrics["alarm-correlation"]), pickle.dumps({"weights": engine.WEIGHTS, "hold": engine.HOLD, "lambda": engine.LAMBDA})])
    audit.record(c, worker_ctx(job), "network.loaded", "network", nid, {"intervals": T, "alarms": len(all_alarms), "model_version": ver})
    return {"network_id": nid, "sites": len(net["sites"]), "cells": len(net["cells"]), "links": len(net["links"]), "routers": len(net["sites"]) + len(net["nodes"]),
            "hubs": sum(s["role"] == "hub" for s in net["sites"]), "clusters": len(world.CLUSTERS), "protected_sites": env["protected_sites"],
            "days": T / world.PER_DAY, "counter_rows": int(T * (len(net["cells"]) + len(net["links"]))), "counter_values": int(T * (len(net["cells"]) * 8 + len(net["links"]) * 5)),
            "stored_counter_rows": (T - hot) * (len(net["cells"]) + len(net["links"])), "history_faults": len(faults), "alarms": len(all_alarms),
            "configuration_changes": len(cfg_rows), "clock": at(T), "models": {"version": ver, **metrics}, "seconds": round(time.perf_counter() - t0, 1)}


def anomaly_metrics(ad, cell, ts, truth, single):
    """Cell-intervals after the training weeks, against what broke (the history's tickets)."""
    te = slice(TRAIN_END, len(ts))
    tr = truth[te]
    flags = {"model": engine.persistent(single)[te], "static": engine.static_flags(cell[te])}
    out = {"threshold": round(ad.threshold, 1), "test_cell_intervals": int(tr.size), "impaired": int(tr.sum())}
    for k, fl in flags.items():
        tp, fp, fn = int((fl & tr).sum()), int((fl & ~tr).sum()), int((~fl & tr).sum())
        p, r = tp / max(1, tp + fp), tp / max(1, tp + fn)
        out[k] = {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / max(p + r, 1e-9), 3),
                  "false_per_1000": round(1000 * fp / max(1, int((~tr).sum())), 2)}
    return out


def forecast_metrics(fc, dl, ts, quiet, net):
    """24-hour forecasts from every 6 hours of the test window, against seasonal naive (same slot last week)."""
    errs, naive = [], []
    for o in range(TRAIN_END + 8, len(ts) - world.PER_DAY, 24):
        pred, _ = fc.forecast(dl[o - 8:o], ts[o - 8:o], world.PER_DAY)
        act, nv, ok = dl[o:o + world.PER_DAY], dl[o - world.PER_WEEK:o - world.PER_WEEK + world.PER_DAY], quiet[o:o + world.PER_DAY]
        errs.append(engine.wape(pred[ok], act[ok]))
        naive.append(engine.wape(nv[ok], act[ok]))
    return {"wape": round(float(np.mean(errs)), 3), "baseline_wape": round(float(np.mean(naive)), 3), "origins": len(errs), "horizon_hours": 24,
            "weekly_growth": round(fc.growth, 4)}


# --- the clock moves ----------------------------------------------------------------------------------------------------
class Inject(BaseModel):
    kind: Literal["backhaul_degradation", "fibre_degradation", "site_power_outage", "handover_misconfig", "sleeping_cell"]
    element: str = Field(min_length=3, max_length=40)
    after_intervals: int = Field(0, ge=0, le=96)
    for_intervals: int | None = Field(None, ge=1, le=672)
    cap_factor: float = Field(1.0, gt=0, le=1)
    loss_pct: float = Field(0.0, ge=0, le=20)
    fail_share: float = Field(0.7, gt=0, le=1)
    traffic_factor: float = Field(0.1, gt=0, le=1)


class AdvanceIn(BaseModel):
    intervals: int = Field(ge=1, le=96)
    inject: list[Inject] = Field(default_factory=list, max_length=4)


def check_inject(net, inj):
    links = {l["id"]: l for l in net["links"]}
    cells = {x["id"] for x in net["cells"]}
    if inj.kind == "backhaul_degradation" and (inj.element not in links or links[inj.element]["medium"] != "mw"):
        return "backhaul_degradation needs a microwave link"
    if inj.kind == "fibre_degradation" and (inj.element not in links or links[inj.element]["medium"] != "fibre"):
        return "fibre_degradation needs a fibre link"
    if inj.kind == "site_power_outage" and inj.element[4:] not in {s["id"] for s in net["sites"]}:
        return "site_power_outage needs a cell-site router (CSR-Sxx)"
    if inj.kind in ("handover_misconfig", "sleeping_cell") and inj.element not in cells:
        return f"{inj.kind} needs a cell"
    return None


@app.post("/v1/network:advance", status_code=202, tags=["network"], summary="(+) Run the network forward in 15-minute intervals. The generator can be told about faults (the demo's injection); the service sees counters, alarms and configuration changes, never the telling")
def advance(body: AdvanceIn, ctx: Ctx = Depends(auth("network:advance")), idem: str | None = IdemKey):
    def work(c):
        f = network_row(c)
        for inj in body.inject:
            why = check_inject(stored_net(f), inj)
            if why:
                raise Problem(422, "fault_does_not_fit_element", f"{inj.element}: {why}")
        return 202, jobs.enqueue(c, ctx, "network.advance", {**body.model_dump(), "from_t": f["next_t"]})
    return run(ctx, idem, body, work)


@jobs.handler("network.advance")
def advance_job(c, job):
    p = job["payload"]
    f = network_row(c)
    t0, n = p["from_t"], p["intervals"]
    told = list(f["told"])
    for k, inj in enumerate(p["inject"]):
        start = t0 + inj["after_intervals"]
        told.append({"id": f"D{len(told) + 1:02d}", "kind": inj["kind"], "element": inj["element"], "start": start,
                     "end": start + inj["for_intervals"] if inj.get("for_intervals") else None,
                     **{k2: inj[k2] for k2 in ("cap_factor", "loss_pct", "fail_share", "traffic_factor")}})
    net, m = stored_net(f), models(f)
    gen = world.network(f["model_seed"])
    sim = world.Sim(gen, f["model_seed"])
    ci, li = to_stored_order(sim, net)
    st = State(c, f, net, m)
    summary, ms = [], []
    for o in sim.run(t0, t0 + n, told):
        tt = time.perf_counter()
        alarms = [{"id": str(uuid.uuid4()), "t": a[0], "minute": a[1], "element": a[2], "type": a[3], "severity": a[4], "related": a[5], "source": "element"}
                  for a in o["alarms"]]
        s = process(c, f, net, m, st, o["t"], o["cell"][ci].astype(float), o["link"][li].astype(float), alarms, o["config"])
        ms.append((time.perf_counter() - tt) * 1000)
        s["processing_ms"] = round(ms[-1], 1)
        summary.append(s)
    c.execute("UPDATE networks SET next_t = %s, told = %s", [t0 + n, Jsonb(told)])
    audit.record(c, worker_ctx(job), "network.advanced", "network", f["id"], {"intervals": n, "from_t": t0, "alarms": sum(s["alarms"] for s in summary)})
    return {"from_t": t0, "intervals": summary, "clock": at(t0 + n), "last_interval": at(t0 + n - 1),
            "processing_ms": {"p50": round(float(np.percentile(ms, 50)), 1), "p95": round(float(np.percentile(ms, 95)), 1), "max": round(max(ms), 1)},
            "simulation_truth": {"told": told[len(f["told"]):], "note": "what the generator was told; the analysis never reads this"}}


# --- telemetry ingest ----------------------------------------------------------------------------------------------------
class SampleIn(BaseModel):
    element: str = Field(min_length=3, max_length=40)
    kpis: dict[str, float]


class AlarmIn(BaseModel):
    element: str = Field(min_length=3, max_length=40)
    type: str = Field(pattern=r"^[A-Z0-9_]{3,40}$")
    severity: Literal["critical", "major", "minor", "warning"]
    minute: int = Field(0, ge=0, le=14)
    related: str | None = None


class BatchIn(BaseModel):
    interval: datetime.datetime = Field(description="start of the 15-minute interval the counters cover")
    source: Literal["probe", "oss"] = "probe"
    samples: list[SampleIn] = Field(default_factory=list, max_length=2000)
    alarms: list[AlarmIn] = Field(default_factory=list, max_length=2000)


KNOWN_ALARMS = {a[3] for a in world.CELL_ALARMS} | {a[3] for a in world.LINK_ALARMS} | {a[0] for a in world.BACKGROUND} | {
    "MW_CAPACITY_DEGRADED", "LINK_DOWN", "POWER_MAINS_FAIL", "NODE_UNREACHABLE", "CELL_UNAVAILABLE"}
RANGES = {"prb_util": (0, 1), "loss_pct": (0, 100), "ho_success_pct": (0, 100), "available": (0, 1), "util": (0, 1)}


def check_sample(s, kind):
    want = world.CELL_KPIS if kind == "cell" else world.LINK_KPIS
    if set(s.kpis) != set(want):
        return f"a {kind} sample needs exactly: {', '.join(want)}"
    for k, v in s.kpis.items():
        lo, hi = RANGES.get(k, (0, 1e6))
        if not (lo <= v <= hi) or v != v:
            return f"{k} = {v} is outside {lo}..{hi:g}"
    return None


@app.post("/v1/telemetry/batch", status_code=201, tags=["telemetry"], summary="Counters and alarms for one 15-minute interval from an OSS export or a probe. Each sample and alarm is validated on its own; accepted samples are scored against the cell's normal range, accepted alarms are correlated into incidents straight away. Returns what was refused and why, and the processing time")
def telemetry_batch(body: BatchIn, ctx: Ctx = Depends(auth("telemetry:ingest")), idem: str | None = IdemKey):
    def work(c):
        t_start = time.perf_counter()
        f = network_row(c)
        net, m = stored_net(f), models(f)
        delta = (body.interval - START).total_seconds() / 60
        if delta % world.STEP_MIN or delta < 0:
            raise Problem(422, "interval_not_aligned", "interval must start on a quarter hour")
        t = int(delta // world.STEP_MIN)
        if t >= f["next_t"]:
            raise Problem(422, "interval_ahead_of_clock", f"the network clock is at {at(f['next_t']).isoformat()}")
        if t < f["next_t"] - world.PER_DAY:
            raise Problem(422, "interval_too_old", "late data older than a day goes to the backfill path")
        cells = {x["id"]: i for i, x in enumerate(net["cells"])}
        links = {x["id"]: j for j, x in enumerate(net["links"])}
        seen = {r["element_id"] for r in c.execute("SELECT element_id FROM metric_sample WHERE ts = %s AND source = %s", [at(t), body.source])}
        accepted, refused, cell_rows, link_rows = [], [], [], []
        for s in body.samples:
            kind = "cell" if s.element in cells else "link" if s.element in links else None
            why = "unknown element" if not kind else "duplicate sample for this interval and source" if s.element in seen else check_sample(s, kind)
            if why:
                refused.append({"element": s.element, "why": why})
                continue
            seen.add(s.element)
            vals = [s.kpis[k] for k in (world.CELL_KPIS if kind == "cell" else world.LINK_KPIS)]
            (cell_rows if kind == "cell" else link_rows).append((s.element, vals))
            accepted.append(s.element)
        scored = []
        if cell_rows:
            ad = m["anomaly-detector"]
            idx = [cells[e] for e, _ in cell_rows]
            X = np.zeros((len(net["cells"]), 8))
            for (e, v), i in zip(cell_rows, idx):
                X[i] = v
            d2, Z = ad.score(X[None], np.array([t]))
            for (e, v), i in zip(cell_rows, idx):
                scored.append({"element": e, "distance": round(float(min(d2[0, i], 1e6)), 1), "anomalous": bool(d2[0, i] > ad.threshold),
                               "threshold": round(ad.threshold, 1), "moved": engine.AnomalyModel.explain(Z[0, i])})
            fast_load(c, "metric_sample", SAMPLE_COLS, list(sample_lines(t, [e for e, _ in cell_rows], [v for _, v in cell_rows], "cell", ctx.tenant_id, body.source,
                                                                          [d2[0, i] for i in idx])))
            c.execute("INSERT INTO model_runs (tenant_id, model_name, version, subject, inputs_hash, result) VALUES (%s,%s,%s,%s,%s,%s)",
                      [ctx.tenant_id, engine.ANOMALY_VERSION, version(f), f"batch:{t}:{body.source}", engine.feature_hash(Z[0, idx]),
                       Jsonb({"anomalous": [s_["element"] for s_ in scored if s_["anomalous"]]})])
        if link_rows:
            fast_load(c, "metric_sample", SAMPLE_COLS, list(sample_lines(t, [e for e, _ in link_rows], [v for _, v in link_rows], "link", ctx.tenant_id, body.source)))
        good, bad = [], []
        for a in body.alarms:
            if a.element not in cells and a.element not in links and not a.element.startswith(("CSR-", "AGG-", "CORE-")):
                bad.append({"element": a.element, "type": a.type, "why": "unknown element"})
            elif a.type not in KNOWN_ALARMS:
                bad.append({"element": a.element, "type": a.type, "why": "unknown alarm type"})
            elif a.related and a.related not in cells:
                bad.append({"element": a.element, "type": a.type, "why": "unknown related cell"})
            else:
                good.append({"id": str(uuid.uuid4()), "t": t, "minute": a.minute, "element": a.element, "type": a.type, "severity": a.severity,
                             "related": a.related, "source": body.source})
        joined = []
        if good:
            st = State(c, f, net, m)
            changed = st.cor.feed(t, good)
            fast_load(c, "alarm", ALARM_COLS, (alarm_line(a, ctx.tenant_id, st.cor.alarm_incident.get(a["id"])) for a in good))
            persist(c, ctx.tenant_id, st, changed)
            for a in good:
                inc = st.cor.incidents[st.cor.alarm_incident[a["id"]]]
                joined.append({"element": a["element"], "type": a["type"], "incident_id": inc["id"], "incident_root": inc["root"], "incident_alarms": len(inc["alarms"])})
        audit.record(c, ctx, "telemetry.ingested", "interval", at(t).isoformat(), {"source": body.source, "accepted": len(accepted), "refused": len(refused) + len(bad)})
        return 201, {"interval": at(t), "source": body.source, "accepted": accepted, "refused": refused, "anomaly": scored, "alarms_accepted": joined,
                     "alarms_refused": bad, "processing_ms": round((time.perf_counter() - t_start) * 1000, 1)}
    return run(ctx, idem, body, work)


# --- reading the network -------------------------------------------------------------------------------------------------
@app.get("/v1/network/topology", tags=["network"], summary="Sites, routers, links and the current routing, with each link's latest utilisation, capacity and loss, alarms in the last hour per element, and the roots of open incidents")
def topology(ctx: Ctx = Depends(auth("network:read"))):
    with db.tx(ctx.tenant_id) as c:
        f = network_row(c)
        net = stored_net(f)
        t = f["next_t"] - 1
        latest = {r["element_id"]: r for r in c.execute("SELECT element_id, kpis, flagged FROM metric_sample WHERE t = %s AND kind = 'link' AND source = 'oss'", [t])}
        active = {r["id"]: r["active"] for r in c.execute("SELECT id, active FROM link")}
        counts = {r["element_id"]: r["n"] for r in c.execute("SELECT element_id, count(*) AS n FROM alarm WHERE t > %s GROUP BY element_id", [t - 4])}
        roots = c.execute("""SELECT id, root_element, kind, alarm_count, confidence FROM incident WHERE status = 'open' AND alarm_count >= 3
                              ORDER BY alarm_count DESC LIMIT 10""").fetchall()
    site_alarms, cell_site = {}, {x["id"]: x["site"] for x in net["cells"]}
    for el, n in counts.items():
        if el in cell_site or el.startswith("CSR-"):
            s = engine.site_of(cell_site, el)
            site_alarms[s] = site_alarms.get(s, 0) + n
    links = []
    for l in net["links"]:
        k = latest.get(l["id"])
        links.append({**l, "active": active[l["id"]], "util": round(float(k["kpis"][0]), 3) if k else None, "capacity_now": float(k["kpis"][1]) if k else None,
                      "loss_pct": round(float(k["kpis"][3]), 2) if k else None, "unhealthy": bool(k["flagged"]) if k else False, "alarms": counts.get(l["id"], 0)})
    return jsonable_encoder({"at": at(t), "nodes": list(net["nodes"].values()), "rerouted": f["rerouted"],
                             "sites": [{**s, "cells": sum(1 for x in net["cells"] if x["site"] == s["id"]), "alarms_last_hour": site_alarms.get(s["id"], 0)} for s in net["sites"]],
                             "links": links, "incident_roots": roots, "neighbour_relations": len(net["neighbours"])})


@app.get("/v1/network/overview", tags=["network"], summary="(+) The command centre: alarms per interval by family, open incidents, models and their scores against baselines, the policy envelope, recent change plans")
def overview(hours: int = Query(12, ge=1, le=72), ctx: Ctx = Depends(auth("network:read"))):
    with db.tx(ctx.tenant_id) as c:
        f = network_row(c)
        lo = f["next_t"] - hours * 4
        per = c.execute("SELECT t, type, count(*) AS n FROM alarm WHERE t >= %s GROUP BY t, type ORDER BY t", [lo]).fetchall()
        incs = c.execute("""SELECT id, kind, root_element, confidence, alarm_count, element_count, opened_t, last_t, status FROM incident
                             WHERE status = 'open' ORDER BY alarm_count DESC LIMIT 12""").fetchall()
        mdl = c.execute("SELECT name, version, data_snapshot, metrics, approved FROM model_artifacts ORDER BY name").fetchall()
        hist = c.execute("SELECT count(*) AS alarms, count(DISTINCT incident_id) AS incidents FROM alarm WHERE t < %s", [f["history_intervals"]]).fetchone()
        plans = c.execute("SELECT id, status, actions, created_at, applied_t FROM change_plan ORDER BY created_at DESC LIMIT 5").fetchall()
        pv, env = envelope(c)
    series = {}
    for r in per:
        d = series.setdefault(r["t"], {"t": r["t"], "at": at(r["t"])})
        fam = engine.family(r["type"])
        d[fam] = d.get(fam, 0) + r["n"]
    return jsonable_encoder({"clock": at(f["next_t"]), "intervals_processed": f["next_t"], "alarms_per_interval": [series.get(t, {"t": t, "at": at(t)}) for t in range(lo, f["next_t"])],
                             "open_incidents": incs, "history": {"alarms": hist["alarms"], "incidents": hist["incidents"]}, "models": mdl,
                             "policy": {"version": pv, **env}, "change_plans": plans, "rerouted": f["rerouted"]})


@app.get("/v1/cells/{cell_id}/kpis", tags=["network"], summary="(+) One cell's counters over the last hours against its seasonal normal, the anomaly distance, the traffic forecast for the next day, and its alarms")
def cell_kpis(cell_id: str, hours: int = Query(48, ge=1, le=168), ctx: Ctx = Depends(auth("network:read"))):
    with db.tx(ctx.tenant_id) as c:
        f = network_row(c)
        net, m = stored_net(f), models(f)
        ix = {x["id"]: i for i, x in enumerate(net["cells"])}
        if cell_id not in ix:
            raise Problem(404, "cell_not_found")
        i = ix[cell_id]
        rows = c.execute("SELECT t, kpis, anomaly, flagged FROM metric_sample WHERE element_id = %s AND source = 'oss' AND t >= %s ORDER BY t",
                         [cell_id, f["next_t"] - hours * 4]).fetchall()
        alarms = c.execute("SELECT t, type, severity, related_element, incident_id FROM alarm WHERE element_id = %s AND t >= %s ORDER BY t", [cell_id, f["next_t"] - hours * 4]).fetchall()
    ts = np.array([r["t"] for r in rows])
    ad, fc = m["anomaly-detector"], m["traffic-forecaster"]
    dt, sl = engine.slot_key(ts)
    normal_dl = np.expm1(ad.med[dt, sl, i, 0]) if len(ts) else []
    recent = np.array([r["kpis"][0] for r in rows[-8:]])
    pred, pts = fc.forecast(np.tile(recent[:, None], (1, len(net["cells"]))) if len(recent) else np.zeros((8, len(net["cells"]))), ts[-8:] if len(ts) >= 8 else np.arange(f["next_t"] - 8, f["next_t"]), world.PER_DAY)
    nbrs = [{"cell": b, "share": w} for a, b, w in net["neighbours"] if a == cell_id]
    return jsonable_encoder({"cell": cell_id, "site": net["cells"][i]["site"], "band": net["cells"][i]["band"], "capacity_mbps": net["cells"][i]["capacity"],
                             "kpi_names": world.CELL_KPIS, "anomaly_threshold": round(ad.threshold, 1),
                             "series": [{"t": r["t"], "at": at(r["t"]), "kpis": [round(float(v), 3) for v in r["kpis"]], "normal_dl": round(float(n_), 1),
                                         "anomaly": None if r["anomaly"] is None else round(float(r["anomaly"]), 1), "flagged": r["flagged"]} for r, n_ in zip(rows, normal_dl)],
                             "forecast": [{"t": int(t_), "at": at(t_), "dl_mbps": round(float(v), 1)} for t_, v in zip(pts, pred[:, i])],
                             "forecast_model": {"name": engine.FORECAST_VERSION, "version": version(f)}, "alarms": alarms, "neighbours": nbrs})


@app.get("/v1/links/{link_id}/kpis", tags=["network"], summary="(+) One link's utilisation, capacity, latency and loss over the last hours")
def link_kpis(link_id: str, hours: int = Query(24, ge=1, le=168), ctx: Ctx = Depends(auth("network:read"))):
    with db.tx(ctx.tenant_id) as c:
        f = network_row(c)
        if not c.execute("SELECT 1 FROM link WHERE id = %s", [link_id]).fetchone():
            raise Problem(404, "link_not_found")
        rows = c.execute("SELECT t, kpis, flagged FROM metric_sample WHERE element_id = %s AND source = 'oss' AND t >= %s ORDER BY t",
                         [link_id, f["next_t"] - hours * 4]).fetchall()
    l = next(x for x in stored_net(f)["links"] if x["id"] == link_id)
    return jsonable_encoder({"link": link_id, "nominal_mbps": l["capacity"], "medium": l["medium"], "kpi_names": world.LINK_KPIS,
                             "series": [{"t": r["t"], "at": at(r["t"]), "util": round(float(r["kpis"][0]), 3), "capacity_mbps": float(r["kpis"][1]),
                                         "latency_ms": round(float(r["kpis"][2]), 2), "loss_pct": round(float(r["kpis"][3]), 3), "unhealthy": r["flagged"]} for r in rows]})


# --- alarm correlation ------------------------------------------------------------------------------------------------------
class CorrelateIn(BaseModel):
    hours: int = Field(4, ge=1, le=48)


@app.post("/v1/incidents/correlate", status_code=202, tags=["incidents"], summary="Correlate the alarms of the last hours into incidents (anything not yet correlated, then every open incident re-ranked on the latest evidence). Returns raw alarms against incidents, the de-duplication and per-site baselines, and each incident's ranked root causes against the most-alarmed-element baseline")
def correlate(body: CorrelateIn, ctx: Ctx = Depends(auth("incidents:correlate")), idem: str | None = IdemKey):
    def work(c):
        network_row(c)
        return 202, jobs.enqueue(c, ctx, "incidents.correlate", body.model_dump())
    return run(ctx, idem, body, work)


@jobs.handler("incidents.correlate")
def correlate_job(c, job):
    f = network_row(c)
    net, m = stored_net(f), models(f)
    lo = f["next_t"] - job["payload"]["hours"] * 4
    st = State(c, f, net, m)
    loose = c.execute("SELECT id, element_id, t, raised_at, type, related_element, incident_id FROM alarm WHERE t >= %s AND incident_id IS NULL ORDER BY t", [lo]).fetchall()
    changed = set()
    by_t = {}
    for a in loose:
        by_t.setdefault(a["t"], []).append(alarm_dict(a))
    for t in sorted(by_t):
        changed |= st.cor.feed(t, by_t[t])
    for a in loose:
        c.execute("UPDATE alarm SET incident_id = %s WHERE id = %s", [st.cor.alarm_incident[str(a["id"])], a["id"]])
    for inc in st.cor.open(f["next_t"]):
        st.cor.rerank(inc)
        changed.add(inc["id"])
    persist(c, f["tenant_id"], st, changed)
    rows = c.execute("SELECT id, element_id, t, raised_at, type, related_element, incident_id FROM alarm WHERE t >= %s ORDER BY t", [lo]).fetchall()
    alarms = [alarm_dict(a) | {"incident": str(a["incident_id"])} for a in rows]
    incs = {str(r["id"]): r for r in c.execute("SELECT * FROM incident WHERE id = ANY(%s)", [list({a["incident"] for a in alarms})])}
    per_inc = {}
    for a in alarms:
        per_inc.setdefault(a["incident"], []).append(a)
    top = sorted(per_inc, key=lambda k: -len(per_inc[k]))[:6]
    fam = {}
    for a in alarms:
        k = engine.family(a["type"])
        fam[k] = fam.get(k, 0) + 1
    out_incs = []
    for k in top:
        r = incs[k]
        al = per_inc[k]
        tl = {}
        for a in al:
            tl[a["t"]] = tl.get(a["t"], 0) + 1
        out_incs.append({"incident_id": k, "kind": r["kind"], "status": r["status"], "root": r["root_element"], "confidence": r["confidence"],
                         "alarms_in_window": len(al), "alarm_count": r["alarm_count"], "elements": r["element_count"], "opened": at(r["opened_t"]),
                         "alarm_types": sorted({a["type"] for a in al}), "ranking": r["ranking"][:5], "baseline_most_alarms": r["baseline_top"][:3],
                         "timeline": [{"t": t, "at": at(t), "alarms": tl.get(t, 0)} for t in range(lo, f["next_t"])]})
    audit.record(c, worker_ctx(job), "incidents.correlated", "window", f"{lo}-{f['next_t'] - 1}", {"alarms": len(alarms), "incidents": len(per_inc)})
    return {"window": {"from": at(lo), "to": at(f["next_t"]), "intervals": f["next_t"] - lo}, "raw_alarms": len(alarms), "incidents": len(per_inc),
            "reduction_ratio": round(len(alarms) / max(1, len(per_inc)), 1), "by_family": fam,
            "baselines": {"dedup_by_element_and_type": engine.baseline_groups(st.topo, alarms, "dedup"), "grouped_by_site": engine.baseline_groups(st.topo, alarms, "site")},
            "top_incidents": out_incs, "versions": {"correlator": engine.CORRELATOR_VERSION, "ranker": engine.RANKER_VERSION},
            "how": "an alarm is explained by its element or anything upstream on the current routing (handover alarms by the cell or its neighbour); "
                   "each incident's root is the element that explains the most alarmed elements while leaving the fewest of its own cells silent, "
                   "then ranked on its own alarms, telemetry and configuration changes"}


@app.get("/v1/incidents", tags=["incidents"], summary="(+) Incidents, newest first")
def incidents(status: Literal["open", "resolved", "all"] = "open", min_alarms: int = Query(1, ge=1), ctx: Ctx = Depends(auth("network:read"))):
    with db.tx(ctx.tenant_id) as c:
        rows = c.execute("""SELECT id, kind, status, root_element, confidence, alarm_count, element_count, opened_t, last_t, ticket_root_cause FROM incident
                             WHERE status <> 'merged' AND (%s = 'all' OR status = %s) AND alarm_count >= %s ORDER BY last_t DESC, alarm_count DESC LIMIT 200""",
                         [status, status, min_alarms]).fetchall()
    return jsonable_encoder({"items": [{**r, "opened": at(r["opened_t"]), "last": at(r["last_t"])} for r in rows]})


@app.get("/v1/incidents/{incident_id}", tags=["incidents"], summary="(+) One incident: ranked root causes with their evidence, alarms by element and type, recommendations")
def incident(incident_id: uuid.UUID, ctx: Ctx = Depends(auth("network:read"))):
    with db.tx(ctx.tenant_id) as c:
        r = c.execute("SELECT * FROM incident WHERE id = %s", [incident_id]).fetchone()
        if not r:
            raise Problem(404, "incident_not_found")
        by = c.execute("SELECT element_id, type, count(*) AS n, min(t) AS first_t FROM alarm WHERE incident_id = %s GROUP BY element_id, type ORDER BY n DESC", [incident_id]).fetchall()
        recs = c.execute("SELECT id, kind, inside_envelope, created_at FROM recommendation WHERE incident_id = %s ORDER BY created_at", [incident_id]).fetchall()
    return jsonable_encoder({**r, "opened": at(r["opened_t"]), "last": at(r["last_t"]), "alarms_by_element": by, "recommendations": recs})


# --- capacity forecast, digital twin, policy ----------------------------------------------------------------------------------
def forecast_now(c, f, net, m, hours):
    t = f["next_t"]
    rows = c.execute("SELECT element_id, t, kpis FROM metric_sample WHERE kind = 'cell' AND source = 'oss' AND t >= %s ORDER BY t", [t - 8]).fetchall()
    ix = {x["id"]: i for i, x in enumerate(net["cells"])}
    recent = np.zeros((8, len(net["cells"])))
    up = np.ones(len(net["cells"]), bool)
    for r in rows:
        recent[r["t"] - (t - 8), ix[r["element_id"]]] = r["kpis"][0]
        if r["t"] == t - 1:
            up[ix[r["element_id"]]] = r["kpis"][7] > 0.5
    pred, hts = m["traffic-forecaster"].forecast(recent, np.arange(t - 8, t), hours * 4, up)
    caps = {r["element_id"]: float(r["kpis"][1]) for r in c.execute("SELECT element_id, kpis FROM metric_sample WHERE kind = 'link' AND source = 'oss' AND t = %s", [t - 1])}
    capacity = np.array([caps.get(l["id"]) or l["capacity"] for l in net["links"]])
    c.execute("INSERT INTO model_runs (tenant_id, model_name, version, subject, inputs_hash, result) VALUES (%s,%s,%s,%s,%s,%s)",
              [f["tenant_id"], engine.FORECAST_VERSION, version(f), f"forecast:{t}:{hours}h", engine.feature_hash(recent), Jsonb({"cells": len(net["cells"]), "horizon": hours * 4})])
    return pred, hts, capacity


def link_series(util, hts, net, ids):
    li = {l["id"]: j for j, l in enumerate(net["links"])}
    return {k: [{"t": int(t), "at": at(t), "util": round(float(util[n, li[k]]), 3)} for n, t in enumerate(hts)] for k in ids if k in li}


def twin_summary(util, hts, net, watch=()):
    peak = util.max(0)
    order = np.argsort(-peak)[:8]
    ids = [net["links"][j]["id"] for j in order]
    return {"peaks": [{"link": net["links"][j]["id"], "peak": round(float(peak[j]), 3), "at": at(hts[int(np.argmax(util[:, j]))]),
                       "capacity_now_mbps": None} for j in order], "series": link_series(util, hts, net, list(dict.fromkeys([*watch, *ids[:3]])))}


@app.get("/v1/capacity/forecast", tags=["capacity"], summary="(+) The traffic forecast rolled up to every link on today's routing and each link's measured capacity: where load will pass the envelope in the coming hours")
def capacity_forecast(hours: int = Query(24, ge=1, le=48), ctx: Ctx = Depends(auth("network:read"))):
    with db.tx(ctx.tenant_id) as c:
        f = network_row(c)
        net, m = stored_net(f), models(f)
        pred, hts, capacity = forecast_now(c, f, net, m, hours)
        pv, env = envelope(c)
    util = engine.twin(net, f["rerouted"], pred, capacity)
    s = twin_summary(util, hts, net)
    for p_ in s["peaks"]:
        p_["capacity_now_mbps"] = round(float(capacity[[l["id"] for l in net["links"]].index(p_["link"])]))
        p_["nominal_mbps"] = next(l["capacity"] for l in net["links"] if l["id"] == p_["link"])
    met = m["traffic-forecaster"]
    return jsonable_encoder({"from": at(hts[0]), "hours": hours, "envelope_max": env["max_link_utilisation"], **s,
                             "over_envelope": [p_["link"] for p_ in s["peaks"] if p_["peak"] > env["max_link_utilisation"]],
                             "model": {"name": engine.FORECAST_VERSION, "version": version(f), "growth_per_week": round(met.growth, 4)},
                             "how": "per-cell traffic forecast (seasonal profile x growth x recent level) summed along each site's path, over the link's capacity measured now"})


class RecommendIn(BaseModel):
    incident_id: uuid.UUID
    horizon_hours: int = Field(24, ge=1, le=48)


@app.post("/v1/recommendations", status_code=202, tags=["recommendations"], summary="A remediation for an incident, inside the policy envelope: for a transport incident, every subset of the possible reroutes is run through the digital twin over the forecast and the feasible plan with the fewest changes wins; for a handover incident caused by a configuration change, a rollback. Each candidate carries the rules it breaks")
def recommend(body: RecommendIn, ctx: Ctx = Depends(auth("recommendations:run")), idem: str | None = IdemKey):
    def work(c):
        network_row(c)
        if not c.execute("SELECT 1 FROM incident WHERE id = %s AND status <> 'merged'", [body.incident_id]).fetchone():
            raise Problem(404, "incident_not_found")
        return 202, jobs.enqueue(c, ctx, "recommendation.build", body.model_dump(mode="json"))
    return run(ctx, idem, body, work)


@jobs.handler("recommendation.build")
def recommend_job(c, job):
    p = job["payload"]
    f = network_row(c)
    net, m = stored_net(f), models(f)
    inc = c.execute("SELECT * FROM incident WHERE id = %s", [p["incident_id"]]).fetchone()
    pv, env = envelope(c)
    topo = engine.Topology(net, f["rerouted"])
    root = inc["root_element"]
    pred, hts, capacity = forecast_now(c, f, net, m, p["horizon_hours"])
    link_ids = [l["id"] for l in net["links"]]
    result, actions, kind, inside = {}, [], "none", False
    if topo.kind(root) in ("link", "router") and inc["kind"] in ("transport", "power"):
        opt = engine.optimise(net, root, pred, capacity, env, f["rerouted"], hts)
        util0 = engine.twin(net, f["rerouted"], pred, capacity)
        watch = [root] if root in link_ids else []
        nothing = {**opt["do_nothing"], "label": "do nothing"}
        cands = opt["candidates"]
        result = {"root": root, "reroute_options": opt["options"], "candidates_tried": len(cands), "feasible": sum(x["feasible"] for x in cands),
                  "do_nothing": nothing, "candidates": cands[:10], "forecast_from": at(hts[0]), "horizon_hours": p["horizon_hours"],
                  "twin_do_nothing": link_series(util0, hts, net, watch)}
        if opt["best"]:
            best = opt["best"]
            util1 = engine.twin(net, set(f["rerouted"]) | {a["site"] for a in best["actions"]}, pred, capacity)
            moved = sorted({x for a in best["actions"] for x in engine.subtree_sites(net, a["site"], f["rerouted"])})
            touched = sorted({l for a in best["actions"] for l in world.paths(net, set(f["rerouted"]) | {a["site"]})[a["site"]] if l.startswith(("L-", "A-"))})
            kind, actions, inside = "reroute", best["actions"], True
            result.update(best=best, twin_plan=link_series(util1, hts, net, list(dict.fromkeys(watch + touched))), sites_moved=moved,
                          expected_impact={"root_peak_before": nothing.get("root_link_peak"), "root_peak_after": best["root_link_peak"],
                                           "network_peak_after": best["peak"], "worst_link_after": best["worst_link"],
                                           "intervals_over_envelope_before": int((util0.max(1) > env["max_link_utilisation"]).sum()),
                                           "intervals_over_envelope_after": int((util1.max(1) > env["max_link_utilisation"]).sum())},
                          note="rerouting protects capacity while the link is degraded; the link itself still needs a field visit")
        elif nothing["feasible"]:
            result["reason"] = "the forecast stays inside the envelope without a change; dispatch field maintenance"
        else:
            result["reason"] = "no plan inside the envelope: escalate to a person with the candidates and the rules each breaks"
    elif topo.kind(root) == "cell" and inc["kind"] == "handover":
        chg = c.execute("SELECT * FROM configuration WHERE element_id = %s AND t BETWEEN %s AND %s ORDER BY t DESC LIMIT 1", [root, inc["opened_t"] - 12, inc["last_t"]]).fetchone()
        if chg:
            actions = [{"type": "rollback_config", "element": root, "parameter": chg["parameter"], "from": chg["new_value"], "to": chg["old_value"], "change_at": at(chg["t"])}]
            v = engine.policy_check(net, actions, None, env, f["rerouted"])
            nbr = [b for a, b, w in net["neighbours"] if a == root] + [a for a, b, w in net["neighbours"] if b == root]
            ho = {}
            for r in c.execute("""SELECT element_id, t, kpis[6] AS ho FROM metric_sample WHERE element_id = ANY(%s) AND source = 'oss'
                                   AND (t BETWEEN %s AND %s OR t >= %s)""", [[root, *nbr], chg["t"] - 96, chg["t"] - 1, f["next_t"] - 4]):
                ho.setdefault("before" if r["t"] < chg["t"] else "now", []).append(r["ho"])
            kind, inside = "rollback", not v
            result = {"root": root, "change": {"parameter": chg["parameter"], "from": chg["old_value"], "to": chg["new_value"], "at": at(chg["t"]), "by": chg["changed_by"]},
                      "violations": v, "expected_impact": {"handover_success_before_change": round(float(np.median(ho.get("before", [np.nan]))), 1),
                                                           "handover_success_now": round(float(np.median(ho.get("now", [np.nan]))), 1), "cells": 1 + len(set(nbr))},
                      "how": "the cell and its neighbours' handover success over the day before the change, against the last hour"}
        else:
            result["reason"] = "no configuration change on the cell before the incident; investigate"
    else:
        result["reason"] = f"no automated remedy for a {inc['kind']} incident rooted at a {topo.kind(root)}; dispatch"
    rid = uuid.uuid4()
    versions = {"forecast": engine.FORECAST_VERSION, "twin": "link-load-1", "optimiser": "enumerate-subsets-1", "models": version(f)}
    c.execute("""INSERT INTO recommendation (id, tenant_id, incident_id, kind, actions, inside_envelope, result, policy_version, model_versions, created_by)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
              [rid, f["tenant_id"], inc["id"], kind, Jsonb(jsonable_encoder(actions)), inside, Jsonb(jsonable_encoder(result)), pv, Jsonb(versions), uuid.UUID(p["actor_id"])])
    audit.record(c, worker_ctx(job), "recommendation.built", "recommendation", rid, {"incident": str(inc["id"]), "kind": kind, "actions": len(actions), "inside_envelope": inside})
    return {"recommendation_id": rid, "incident_id": inc["id"], "incident_kind": inc["kind"], "root": root, "kind": kind, "actions": actions,
            "inside_envelope": inside, "policy_version": pv, "envelope": env, "model_versions": versions, **result}


class Change(BaseModel):
    type: Literal["reroute_site", "rollback_config"]
    site: str | None = None
    element: str | None = None


class TwinIn(BaseModel):
    changes: list[Change] = Field(default_factory=list, max_length=8)
    horizon_hours: int = Field(24, ge=1, le=48)
    label: str = Field("what-if", max_length=80)
    watch: list[str] = Field(default_factory=list, max_length=6)


@app.post("/v1/twin/simulate", status_code=202, tags=["twin"], summary="Run a what-if through the digital twin: link loads over the forecast horizon for a set of reroutes, checked against the policy envelope")
def twin_simulate(body: TwinIn, ctx: Ctx = Depends(auth("twin:run")), idem: str | None = IdemKey):
    def work(c):
        f = network_row(c)
        net = stored_net(f)
        sites = {s["id"]: s for s in net["sites"]}
        for ch in body.changes:
            if ch.type == "reroute_site" and (ch.site not in sites or not sites[ch.site]["alt_parent"]):
                raise Problem(422, "bad_change", f"{ch.site}: unknown site or no standby link")
        return 202, jobs.enqueue(c, ctx, "twin.simulate", body.model_dump())
    return run(ctx, idem, body, work)


@jobs.handler("twin.simulate")
def twin_job(c, job):
    p = job["payload"]
    f = network_row(c)
    net, m = stored_net(f), models(f)
    pv, env = envelope(c)
    pred, hts, capacity = forecast_now(c, f, net, m, p["horizon_hours"])
    actions = [{"type": ch["type"], "site": ch["site"]} if ch["type"] == "reroute_site" else {"type": ch["type"], "element": ch["element"]} for ch in p["changes"]]
    sites = {a["site"] for a in actions if a["type"] == "reroute_site"}
    try:
        util = engine.twin(net, set(f["rerouted"]) | sites, pred, capacity)
        v = engine.policy_check(net, actions, util, env, f["rerouted"], hts, [l["id"] for l in net["links"]])
        s = twin_summary(util, hts, net, p["watch"])
    except ValueError as e:
        util, v, s = None, [{"rule": "routing", "detail": str(e)}], {}
    tid = uuid.uuid4()
    result = {"twin_run_id": tid, "label": p["label"], "actions": actions, "inside_envelope": not v, "violations": v, "from": at(f["next_t"]),
              "horizon_hours": p["horizon_hours"], "policy_version": pv, **s, "how": "the per-cell forecast summed along each site's path under the proposed routing, over each link's capacity measured now"}
    c.execute("INSERT INTO twin_run (id, tenant_id, from_t, request, result, inside_envelope, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s)",
              [tid, f["tenant_id"], f["next_t"], Jsonb(p), Jsonb(jsonable_encoder(result)), not v, uuid.UUID(p["actor_id"])])
    audit.record(c, worker_ctx(job), "twin.simulated", "twin_run", tid, {"label": p["label"], "inside_envelope": not v, "violations": len(v)})
    return result


# --- change orchestration ----------------------------------------------------------------------------------------------------
class PlanIn(BaseModel):
    recommendation_ids: list[uuid.UUID] = Field(default_factory=list, max_length=4)
    twin_run_id: uuid.UUID | None = None


def fresh_check(c, f, actions):
    """The policy engine's check, on a fresh forecast and today's routing."""
    net, m = stored_net(f), models(f)
    pv, env = envelope(c)
    pred, hts, capacity = forecast_now(c, f, net, m, env["horizon_hours"])
    sites = {a["site"] for a in actions if a["type"] == "reroute_site"}
    try:
        util = engine.twin(net, set(f["rerouted"]) | sites, pred, capacity)
    except ValueError as e:
        return {"policy_version": pv, "violations": [{"rule": "routing", "detail": str(e)}], "inside_envelope": False}
    v = engine.policy_check(net, actions, util, env, f["rerouted"], hts, [l["id"] for l in net["links"]])
    return {"policy_version": pv, "violations": v, "inside_envelope": not v, "network_peak": round(float(util.max()), 3), "checked_at": at(f["next_t"])}


@app.post("/v1/change-plans", status_code=201, tags=["changes"], summary="(+) Propose a change plan from recommendations (or a twin run). The policy engine re-checks it on a fresh forecast: a plan outside the envelope cannot be proposed. A proposal changes nothing until a noc_manager who did not propose it approves")
def propose(body: PlanIn, ctx: Ctx = Depends(auth("changes:propose")), idem: str | None = IdemKey):
    def work(c):
        f = network_row(c)
        actions, recs = [], []
        if body.twin_run_id:
            tr = c.execute("SELECT * FROM twin_run WHERE id = %s", [body.twin_run_id]).fetchone()
            if not tr:
                raise Problem(404, "twin_run_not_found")
            if not tr["inside_envelope"]:
                raise Problem(422, "outside_policy_envelope", "; ".join(v["detail"] for v in tr["result"]["violations"]))
            actions = tr["result"]["actions"]
        for rid in body.recommendation_ids:
            r = c.execute("SELECT * FROM recommendation WHERE id = %s", [rid]).fetchone()
            if not r:
                raise Problem(404, "recommendation_not_found")
            if not r["actions"]:
                raise Problem(422, "nothing_to_change", f"recommendation {rid} has no actions: {r['result'].get('reason', '')}")
            actions += r["actions"]
            recs.append(rid)
        if not actions:
            raise Problem(422, "nothing_to_change", "give recommendation_ids or a twin_run_id")
        chk = fresh_check(c, f, actions)
        if not chk["inside_envelope"]:
            raise Problem(422, "outside_policy_envelope", "; ".join(v["detail"] for v in chk["violations"]))
        pid = uuid.uuid4()
        c.execute("INSERT INTO change_plan (id, tenant_id, recommendation_ids, actions, policy_check, proposed_by) VALUES (%s,%s,%s,%s,%s,%s)",
                  [pid, ctx.tenant_id, recs, Jsonb(jsonable_encoder(actions)), Jsonb(jsonable_encoder({"at_proposal": chk})), ctx.actor_id])
        audit.record(c, ctx, "change.proposed", "change_plan", pid, {"actions": len(actions), "policy_version": chk["policy_version"]})
        return 201, {"change_plan_id": pid, "status": "proposed", "actions": actions, "policy_check": chk}
    return run(ctx, idem, body, work)


@app.post("/v1/changes/{plan_id}/approve", tags=["changes"], summary="A noc_manager approves or rejects a proposed plan; the proposer cannot. On approval the policy engine checks it once more, then the change orchestrator applies it (reroutes take effect from the next interval) and logs every configuration change")
def approve(plan_id: uuid.UUID, decision: Literal["approved", "rejected"] = "approved", ctx: Ctx = Depends(auth("changes:approve")), idem: str | None = IdemKey):
    def work(c):
        f = c.execute("SELECT * FROM networks FOR UPDATE").fetchone()
        if not f:
            raise Problem(409, "no_network")
        d = c.execute("SELECT * FROM change_plan WHERE id = %s FOR UPDATE", [plan_id]).fetchone()
        if not d:
            raise Problem(404, "change_plan_not_found")
        if d["status"] != "proposed":
            raise Problem(409, "already_decided", f"this plan is {d['status']}")
        if d["proposed_by"] == ctx.actor_id:
            raise Problem(403, "proposer_cannot_approve", "a change plan needs a second person")
        if decision == "rejected":
            c.execute("UPDATE change_plan SET status = 'rejected', decided_by = %s, decided_at = now() WHERE id = %s", [ctx.actor_id, plan_id])
            audit.record(c, ctx, "change.rejected", "change_plan", plan_id, {})
            return 200, {"change_plan_id": plan_id, "status": "rejected", "applied": []}
        chk = fresh_check(c, f, d["actions"])
        if not chk["inside_envelope"]:
            raise Problem(409, "outside_policy_envelope_now", "; ".join(v["detail"] for v in chk["violations"]))
        net = stored_net(f)
        sites = {s["id"]: s for s in net["sites"]}
        told, rerouted, applied, t = list(f["told"]), list(f["rerouted"]), [], f["next_t"]
        for a in d["actions"]:
            if a["type"] == "reroute_site":
                s = sites[a["site"]]
                told.append({"kind": "reroute", "site": s["id"], "start": t})
                rerouted.append(s["id"])
                c.execute("UPDATE link SET active = (id = %s) WHERE id IN (%s, %s)", [s["alt_link"], s["link"], s["alt_link"]])
                c.execute("UPDATE topology_edge SET active = (kind = 'standby') WHERE src = %s AND kind IN ('backhaul', 'standby')", [s["id"]])
                cfg = (s["csr"], "backhaul_parent", s["parent"], s["alt_parent"])
            else:
                told.append({"kind": "config_restore", "element": a["element"], "start": t})
                cfg = (a["element"], a["parameter"], a["from"], a["to"])
            c.execute("INSERT INTO configuration (tenant_id, element_id, t, at, parameter, old_value, new_value, changed_by, change_plan_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                      [ctx.tenant_id, cfg[0], t, at(t), cfg[1], cfg[2], cfg[3], f"change plan {str(plan_id)[:8]}", plan_id])
            applied.append({"element": cfg[0], "parameter": cfg[1], "from": cfg[2], "to": cfg[3], "from_interval": at(t)})
        c.execute("UPDATE networks SET told = %s, rerouted = %s", [Jsonb(told), sorted(set(rerouted))])
        c.execute("UPDATE change_plan SET status = 'applied', decided_by = %s, decided_at = now(), applied_t = %s, policy_check = policy_check || %s WHERE id = %s",
                  [ctx.actor_id, t, Jsonb(jsonable_encoder({"at_approval": chk})), plan_id])
        audit.record(c, ctx, "change.approved", "change_plan", plan_id, {"actions": len(applied)})
        audit.record(c, ctx, "change.applied", "change_plan", plan_id, {"configuration": applied})
        return 200, {"change_plan_id": plan_id, "status": "applied", "applied": applied, "policy_check": chk}
    return run(ctx, idem, {"decision": decision}, work)


@app.get("/v1/changes", tags=["changes"], summary="(+) Change plans and their decisions")
def changes(ctx: Ctx = Depends(auth("network:read"))):
    with db.tx(ctx.tenant_id) as c:
        return jsonable_encoder({"items": c.execute("SELECT id, status, actions, policy_check, proposed_by, decided_by, created_at, decided_at, applied_t FROM change_plan ORDER BY created_at DESC").fetchall()})


@app.get("/v1/policy", tags=["changes"], summary="(+) The declared policy envelope automation must stay inside")
def policy(ctx: Ctx = Depends(auth("network:read"))):
    with db.tx(ctx.tenant_id) as c:
        network_row(c)
        pv, env = envelope(c)
    return {"version": pv, **env}
