"""Public API (modular monolith). Blueprint services map to: connector-workers (the sync job over six simulated source
systems, with cursors), document-normalizer (chunks), entity-extraction (mention detection and relation extraction),
entity-resolution (linking to the structured sources' anchors, NIL clusters, merge proposals a second person approves),
knowledge-graph (relationship, temporal_fact, evidence), temporal-index (ownership reconciled over time, per reader),
retrieval-router (BM25 + LSA + graph expansion, fused), permission-engine (principals, groups and container ACLs, turned
into the view every read goes through, before anything is ranked) and answer-service (answers built from the reader's facts,
every sentence cited and verified). Not built: an LLM, Kafka, Neo4j, OpenSearch, pgvector; see the README.

    uvicorn ekg.api:app          python -m core.jobs ekg.api      # the worker
"""
import collections
import datetime
import hashlib
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

from . import engine as E
from . import world

READ = {"kb:read", "jobs:read"}
ANALYST = READ | {"merges:propose", "connectors:sync"}
PERMISSIONS = {"viewer": READ, "analyst": ANALYST,
               "steward": ANALYST | {"merges:approve", "corpus:load", "simulator:advance", "audit:read", "security:run"}}
app = create_app("enterprise-knowledge-graph", PERMISSIONS)
auth = app.state.auth
IdemKey = Header(None, alias="Idempotency-Key")
EPOCH = datetime.datetime(2025, 8, 4, tzinfo=datetime.UTC)
VERSIONS = {"extractor": E.EXTRACTOR_VERSION, "linker": E.LINKER_VERSION, "retriever": E.RETRIEVER_VERSION, "answers": E.ANSWER_VERSION}


def at(day):
    return EPOCH + datetime.timedelta(days=int(day))


def U(t, natural):
    return uuid.uuid5(uuid.UUID(str(t)), natural)


def worker_ctx(job):
    return Ctx(job["tenant_id"], uuid.UUID(job["payload"]["actor_id"]), "worker", "system")


def corpus(c):
    f = c.execute("SELECT * FROM corpora").fetchone()
    if not f:
        raise Problem(409, "no_corpus", "load the simulated enterprise first: POST /v1/corpus:load")
    return f


def model_version(f):
    return f"ekg-{str(f['id'])[:8]}-1"


def artifact(c, name, version):
    r = c.execute("SELECT artifact FROM model_artifacts WHERE name = %s AND version = %s", [name, version]).fetchone()
    return pickle.loads(r["artifact"]) if r else None


# --- loading the simulated enterprise --------------------------------------------------------------------------------------
class LoadIn(BaseModel):
    seed: int = Field(7, ge=1, le=10 ** 6)


@app.post("/v1/corpus:load", status_code=202, tags=["corpus"], summary="(+) Create the simulated enterprise behind six source systems (HR, service catalog, wiki, tickets, CRM, chat) and train the extractor and the linker on its annotation export; nothing is ingested until a connector sync")
def load_corpus(body: LoadIn, ctx: Ctx = Depends(auth("corpus:load")), idem: str | None = IdemKey):
    def work(c):
        if c.execute("SELECT 1 FROM corpora").fetchone():
            raise Problem(409, "corpus_exists", "this tenant already has a corpus; `make reset` for a fresh demo")
        return 202, jobs.enqueue(c, ctx, "corpus.load", body.model_dump())
    return run(ctx, idem, body, work)


def with_ids(t, objs):
    for o in objs:
        o["id"] = str(U(t, f"obj:{o['system']}:{o['external_id']}"))
    return objs


@jobs.handler("corpus.load")
def load_job(c, job):
    t, seed = job["tenant_id"], job["payload"]["seed"]
    cid = U(t, "corpus")
    c.execute("INSERT INTO corpora (id, tenant_id, name, model_seed, clock) VALUES (%s,%s,'Halden Systems',%s,%s)", [cid, t, seed, world.NOW])
    co = world.company(seed)
    acl = world.containers(co)
    for key, name in world.SYSTEMS.items():
        c.execute("INSERT INTO source_system (id, tenant_id, external_ref, name, metadata) VALUES (%s,%s,%s,%s,%s)",
                  [U(t, f"system:{key}"), t, key, name, Jsonb({"containers": sorted(k for k in acl if k.startswith(key + ":")), "cursor_day": None})])
    objs = with_ids(t, world.view(world.objects(seed), world.NOW))
    ann, records = world.annotations(objs)
    m = E.train(objs, ann, records, holdout=0.25)
    version = model_version({"id": cid})
    snapshot = f"annotation export of seed {seed}: {len(ann)} documents ({m['card']['test_documents']} held out for the card), {len(records)} structured records"
    for name, obj, metrics in (("gazetteer", m["gazetteer"], {"persons": len(m["gazetteer"]["persons"]), "teams": len(m["gazetteer"]["teams"]),
                                                               "services": len(m["gazetteer"]["services"]), "vendors": len(m["gazetteer"]["vendors"])}),
                               ("relation-extractor", m["extractor"], m["card"]["extraction"]), ("entity-linker", m["linker"], m["card"]["linking"])):
        c.execute("INSERT INTO model_artifacts (tenant_id, name, version, data_snapshot, metrics, artifact, approved) VALUES (%s,%s,%s,%s,%s,%s,true)",
                  [t, name, version, snapshot, Jsonb(metrics), pickle.dumps(obj)])
    audit.record(c, worker_ctx(job), "corpus.loaded", "corpus", cid, {"seed": seed, "model_version": version})
    by_system = collections.Counter(o["system"] for o in objs)
    return {"corpus_id": cid, "company": "Halden Systems", "seed": seed, "clock": at(world.NOW).date(), "model_version": version,
            "sources": [{"system": k, "name": n, "objects_waiting": by_system[k], "containers": len([x for x in acl if x.startswith(k + ":")])} for k, n in world.SYSTEMS.items()],
            "people": len(co["people"]), "groups": len(co["groups"]), "annotation": {"documents": len(ann), "structured_records": len(records)},
            "models": {"extraction": {u: {k: v for k, v in x.items() if k != "by_relation"} for u, x in m["card"]["extraction"].items()},
                       "linking": m["card"]["linking"], "trained_on": m["card"]["train_documents"], "held_out": m["card"]["test_documents"]}}


# --- connector sync ------------------------------------------------------------------------------------------------------
class SyncIn(BaseModel):
    mode: Literal["full", "incremental"] = "incremental"
    systems: list[Literal["hr", "code", "wiki", "tickets", "crm", "chat"]] | None = Field(None, description="default: all six")


@app.post("/v1/connectors/sync", status_code=202, tags=["connectors"], summary="Pull from the source systems (everything, or what changed since each system's cursor), with their principals, groups and container ACLs; normalise, extract, resolve, reconcile and index what changed. 202 + job")
def sync(body: SyncIn, ctx: Ctx = Depends(auth("connectors:sync")), idem: str | None = IdemKey):
    def work(c):
        corpus(c)
        return 202, jobs.enqueue(c, ctx, "connectors.sync", body.model_dump())
    return run(ctx, idem, body, work)


def sync_principals(c, t, co):
    """Identity sync: users and their groups from the HR system, container ACLs from each system. Actor links survive."""
    users, groups = world.principals(co)
    acl = world.containers(co)
    rows = [(U(t, f"principal:{u['email']}"), t, "user", u["email"], u["name"]) for u in users] + [(U(t, f"principal:group:{g}"), t, "group", g, g) for g in groups]
    for r in rows:
        c.execute("""INSERT INTO principal (id, tenant_id, kind, external_ref, display_name) VALUES (%s,%s,%s,%s,%s)
                     ON CONFLICT (tenant_id, external_ref) DO UPDATE SET display_name = excluded.display_name""", list(r))
    ids = {r["external_ref"]: r["id"] for r in c.execute("SELECT id, external_ref FROM principal")}
    c.execute("DELETE FROM permission_edge")
    edges = [(t, ids[u["email"]], "member_of", g, U(t, "system:hr")) for u in users for g in u["groups"]]
    edges += [(t, ids[g], "can_read", cont, U(t, f"system:{cont.split(':')[0]}")) for cont, gs in acl.items() for g in gs]
    db.load(c, "permission_edge", ["tenant_id", "principal_id", "relation", "target", "source_system_id"], edges)
    return len(users), len(groups), len(edges)


@jobs.handler("connectors.sync")
def sync_job(c, job):
    p, t0 = job["payload"], time.perf_counter()
    f = corpus(c)
    t = f["tenant_id"]
    co = world.company(f["model_seed"])
    users, groups, edges = sync_principals(c, t, co)
    everything = world.objects(f["model_seed"], f["told"])
    systems = c.execute("SELECT * FROM source_system ORDER BY external_ref").fetchall()
    stats, changed, deleted = {}, [], []
    for s in systems:
        key = s["external_ref"]
        if p["systems"] and key not in p["systems"]:
            continue
        cur = s["metadata"].get("cursor_day")
        full = p["mode"] == "full" or cur is None
        fetched = [o for o in (world.view(everything, f["clock"]) if full else world.changed(everything, cur, f["clock"])) if o["system"] == key]
        have = {r["external_id"]: r for r in c.execute("SELECT id, external_id, content_hash FROM source_object WHERE source_system_id = %s AND status = 'active'", [s["id"]])}
        n_changed = 0
        for o in with_ids(t, fetched):
            o["hash"] = hashlib.sha256(o["body"].encode()).hexdigest()
            if o["external_id"] in have and have[o["external_id"]]["content_hash"] == o["hash"]:
                continue
            changed.append(o)
            n_changed += 1
        gone = [r["id"] for x, r in have.items() if full and x not in {o["external_id"] for o in fetched}]
        deleted += gone
        stats[key] = {"fetched": len(fetched), "changed": n_changed, "unchanged": len(fetched) - n_changed, "deleted": len(gone), "cursor_from": cur, "cursor_to": f["clock"]}
        c.execute("UPDATE source_system SET metadata = metadata || %s WHERE id = %s", [Jsonb({"cursor_day": f["clock"], "last_sync": datetime.datetime.now(datetime.UTC).isoformat()}), s["id"]])
    version = model_version(f)
    result = {"mode": p["mode"], "systems": stats, "principals": {"users": users, "groups": groups, "acl_edges": edges}, "objects_changed": len(changed), "objects_deleted": len(deleted)}
    if deleted:
        c.execute("DELETE FROM document_chunk WHERE source_object_id = ANY(%s)", [deleted])
        c.execute("UPDATE source_object SET status = 'deleted' WHERE id = ANY(%s)", [deleted])
    if changed:
        ids = [o["id"] for o in changed]
        c.execute("DELETE FROM document_chunk WHERE source_object_id = ANY(%s)", [ids])
        for o in changed:
            c.execute("""INSERT INTO source_object (id, tenant_id, source_system_id, external_id, container, kind, title, author, attributes, body, content_hash, observed_day, observed_at)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                         ON CONFLICT (tenant_id, source_system_id, external_id) DO UPDATE SET body = excluded.body, content_hash = excluded.content_hash, title = excluded.title,
                           version = source_object.version + 1, observed_day = excluded.observed_day, observed_at = excluded.observed_at, synced_at = now(), status = 'active'""",
                      [o["id"], t, U(t, f"system:{o['system']}"), o["external_id"], o["container"], o["kind"], o["title"], o["author"], Jsonb({"structured": o["structured"]}),
                       o["body"], o["hash"], o["observed_day"], at(o["observed_day"])])
        g = artifact(c, "gazetteer", version)
        ext, linker = artifact(c, "relation-extractor", version), artifact(c, "entity-linker", version)
        E.discover(changed, g)
        det, A = E.Detector(g), E.Anchors(g)
        chunks, mentions, asserts = E.process(changed, det, ext, A, linker)
        result |= store(c, t, chunks, mentions, asserts, A)
        c.execute("UPDATE model_artifacts SET artifact = %s WHERE name = 'gazetteer' AND version = %s", [pickle.dumps(g), version])
        runs = []
        for o in changed:
            h = hashlib.sha256(o["body"].encode()).hexdigest()[:16]
            runs.append((t, E.EXTRACTOR_VERSION, version, f"source_object:{o['id']}", h, Jsonb({"assertions": sum(a["object_id"] == o["id"] for a in asserts)})))
        per_obj = collections.Counter(m["object_id"] for m in mentions)
        runs += [(t, E.LINKER_VERSION, version, f"source_object:{o['id']}", hashlib.sha256(o["body"].encode()).hexdigest()[:16], Jsonb({"mentions": per_obj[o["id"]]})) for o in changed]
        db.load(c, "model_runs", ["tenant_id", "model_name", "version", "subject", "inputs_hash", "result"], runs)
    idx = refresh(c, f)
    pipeline = time.perf_counter() - t0
    ix = load_index(c, corpus(c))
    views = precompute_views(c, ix, idx)
    finished = datetime.datetime.now(datetime.UTC)
    result |= {"index_version": idx, "facts": c.execute("SELECT count(*) AS n FROM temporal_fact").fetchone()["n"], "views_precomputed": views,
               "pipeline_seconds": round(pipeline, 2), "seconds_from_request": round((finished - job["created_at"]).total_seconds(), 2),
               "clock": at(f["clock"]).date()}
    c.execute("INSERT INTO sync_runs (id, tenant_id, mode, from_day, to_day, stats, requested_at, finished_at, pipeline_seconds, index_version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
              [uuid.uuid4(), t, p["mode"], min((s["cursor_from"] for s in stats.values() if s["cursor_from"] is not None), default=None), f["clock"], Jsonb(jsonable_encoder(result)),
               job["created_at"], finished, pipeline, idx])
    audit.record(c, worker_ctx(job), "connectors.synced", "corpus", f["id"], {"mode": p["mode"], "changed": len(changed), "index_version": idx})
    return result


def store(c, t, chunks, mentions, asserts, A):
    """The pipeline's rows into the tables, natural ids turned into UUIDs; references to merged entities follow the merge."""
    merged = {str(r["id"]): str(r["merged_into"]) for r in c.execute("SELECT id, merged_into FROM entity WHERE status = 'merged'")}

    def eid(key):
        if key is None:
            return None
        u = str(U(t, f"entity:{key}"))
        return merged.get(u, u)
    ents = E.entities_from(mentions, asserts, A)
    for k, e in ents.items():
        c.execute("""INSERT INTO entity (id, tenant_id, type, canonical_key, canonical_name, anchored) VALUES (%s,%s,%s,%s,%s,%s)
                     ON CONFLICT (tenant_id, canonical_key) DO NOTHING""", [U(t, f"entity:{k}"), t, e["type"], k, e["name"], e["anchor"]])
    cid = lambda x: U(t, f"chunk:{x}")                                                  # noqa: E731
    db.load(c, "document_chunk", ["id", "tenant_id", "source_object_id", "ord", "start_offset", "end_offset", "text"],
            [(cid(ch["id"]), t, ch["object_id"], ch["ord"], ch["start"], ch["end"], ch["text"]) for ch in chunks])
    db.load(c, "mention", ["id", "tenant_id", "chunk_id", "source_object_id", "start_offset", "end_offset", "text", "type", "entity_id", "score", "method", "linker_version"],
            [(U(t, f"mention:{m['id']}"), t, cid(m["chunk_id"]), m["object_id"], m["start"], m["end"], m["text"], m["type"], eid(m["entity"]), m["score"], m["method"], E.LINKER_VERSION)
             for m in mentions])
    db.load(c, "relationship", ["id", "tenant_id", "chunk_id", "source_object_id", "predicate", "subject_id", "object_id", "value", "from_id", "effective_day", "asserted_day",
                                "sentence", "confidence", "method", "source_kind", "subject_mention", "object_mention", "extractor_version"],
            [(U(t, f"assertion:{a['id']}"), t, cid(a["chunk_id"]), a["object_id"], a["pred"], eid(a["subj"]), eid(a["obj"]), a["value"], eid(a["frm"]), a["effective"], a["day"],
              a["sent"], a["confidence"], a["method"], a["source_kind"], U(t, f"mention:{a['subj_mention']}") if a["subj_mention"] else None,
              U(t, f"mention:{a['obj_mention']}") if a["obj_mention"] else None, E.EXTRACTOR_VERSION) for a in asserts])
    new = 0
    for s in E.merge_suggestions(asserts):
        keep, merge = eid(s["keep"]), eid(s["merge"])
        if keep == merge:
            continue
        ev = [str(U(t, f"assertion:{x}")) for x in s["evidence"]]
        new += c.execute("""INSERT INTO merge_proposal (id, tenant_id, keep_entity, merge_entity, reason) VALUES (%s,%s,%s,%s,%s)
                            ON CONFLICT (tenant_id, keep_entity, merge_entity) DO NOTHING RETURNING id""",
                         [U(t, f"merge:{merge}>{keep}"), t, keep, merge, Jsonb({"why": s["reason"], "evidence": ev})]).fetchone() is not None
    return {"chunks": len(chunks), "mentions": len(mentions), "mentions_linked": sum(m["method"] in ("linker", "record", "slug", "taxonomy", "ticket-id") for m in mentions),
            "mentions_abstained": sum(m["method"] in ("ambiguous", "unresolved") for m in mentions), "mentions_new_entities": sum(m["method"] in ("nil", "nil-consolidated") for m in mentions),
            "assertions": len(asserts), "assertions_by_predicate": dict(collections.Counter(a["pred"] for a in asserts)), "entities_seen": len(ents),
            "merge_suggestions_new": new}


def refresh(c, f):
    """After any change: aliases and the reconciled facts over every container (the steward's view); bump the index version."""
    t = f["tenant_id"]
    c.execute("DELETE FROM entity_alias")
    c.execute("""INSERT INTO entity_alias (tenant_id, entity_id, alias, mentions)
                 SELECT tenant_id, entity_id, text, count(*) FROM mention WHERE entity_id IS NOT NULL GROUP BY 1, 2, 3""")
    asserts = load_assertions(c)
    facts = E.derive_facts(asserts, f["clock"])
    c.execute("DELETE FROM temporal_fact")
    idx = c.execute("UPDATE corpora SET index_version = index_version + 1 RETURNING index_version").fetchone()["index_version"]
    day = lambda d: at(d).date() if d is not None else None                              # noqa: E731
    db.load(c, "temporal_fact", ["id", "tenant_id", "subject_id", "predicate", "object_id", "value", "valid_from", "valid_to", "confidence", "method", "index_version"],
            [(x["id"], t, x["subj"], x["pred"], x["obj"], x["value"], day(x["valid_from"]), day(x["valid_to"]), x["confidence"], x["method"], idx) for x in facts])
    db.load(c, "evidence", ["tenant_id", "fact_id", "relationship_id", "role"],
            [(t, x["id"], a, "supports") for x in facts for a in x["evidence"]] + [(t, x["id"], a, "contradicts") for x in facts for a in x["against"]])
    return idx


# --- the index the read side uses -------------------------------------------------------------------------------------------
_INDEX = {}


def load_assertions(c):
    return [dict(r) for r in c.execute("""SELECT id::text AS id, chunk_id::text AS chunk_id, source_object_id::text AS object_id, predicate AS pred, subject_id::text AS subj,
                                                 object_id::text AS obj, value, from_id::text AS frm, effective_day AS effective, asserted_day AS day, sentence AS sent, confidence, method,
                                                 source_kind, subject_mention::text AS subj_mention, object_mention::text AS obj_mention FROM relationship""")]


def load_index(c, f):
    """The tenant's index at its current version (cached per process): every row, for views to filter."""
    key = (str(f["tenant_id"]), f["index_version"])
    if key in _INDEX:
        return _INDEX[key]
    objs = [dict(r) | {"id": str(r["id"]), "structured": r["attributes"].get("structured", False)} for r in c.execute(
        """SELECT o.id, s.external_ref AS system, o.container, o.kind, o.title, o.author, o.external_id, o.body, o.observed_day, o.attributes, o.version, o.synced_at
             FROM source_object o JOIN source_system s ON s.id = o.source_system_id WHERE o.status = 'active'""")]
    chunks = [dict(r) for r in c.execute("SELECT id::text AS id, source_object_id::text AS object_id, ord, start_offset AS start, end_offset AS end, text FROM document_chunk")]
    mentions = [dict(r) for r in c.execute("""SELECT id::text AS id, chunk_id::text AS chunk_id, source_object_id::text AS object_id, start_offset AS start, end_offset AS end, text, type,
                                                     entity_id::text AS entity, score, method FROM mention""")]
    ents = {str(r["id"]): {"id": str(r["id"]), "key": r["canonical_key"], "type": r["type"], "name": r["canonical_name"], "anchor": r["anchored"]}
            for r in c.execute("SELECT * FROM entity WHERE status = 'active'")}
    ix = E.Index(objs, chunks, mentions, load_assertions(c), ents, f["clock"])
    ix.version = f["index_version"]
    while len(_INDEX) >= 4:
        _INDEX.pop(next(iter(_INDEX)))
    _INDEX[key] = ix
    return ix


def containers_of(c, principal_id):
    """The permission engine: containers the principal's groups (or the principal itself) may read."""
    return [r["target"] for r in c.execute("""SELECT DISTINCT e.target FROM permission_edge e JOIN principal p ON p.id = e.principal_id
                                                WHERE e.relation = 'can_read' AND (p.id = %s OR (p.kind = 'group' AND p.external_ref IN
                                                      (SELECT target FROM permission_edge WHERE principal_id = %s AND relation = 'member_of')))
                                                ORDER BY 1""", [principal_id, principal_id])]


def lsa_name(view_key, version):
    return f"{view_key}@{version}"


def precompute_views(c, ix, version):
    """Fit and store the LSA basis and vectors of every view an API user has, so the API does not fit them on first read."""
    t = c.execute("SELECT tenant_id FROM corpora").fetchone()["tenant_id"]
    c.execute("DELETE FROM embedding WHERE index_version < %s", [version])
    c.execute("DELETE FROM model_artifacts WHERE name = 'lsa-view' AND version NOT LIKE %s", [f"%@{version}"])
    done = []
    for r in c.execute("SELECT id FROM principal WHERE actor_id IS NOT NULL").fetchall():
        v = ix.view(containers_of(c, r["id"]))
        if v.key in done or v.N < 3:
            continue
        cols, idf, comps, V = v.lsa()
        c.execute("INSERT INTO model_artifacts (tenant_id, name, version, data_snapshot, metrics, artifact, approved) VALUES (%s,'lsa-view',%s,%s,%s,%s,true) ON CONFLICT DO NOTHING",
                  [t, lsa_name(v.key, version), f"{v.N} chunks readable in view {v.key}", Jsonb({"dimensions": int(comps.shape[0]), "terms": int(len(cols))}), pickle.dumps((cols, idf, comps))])
        db.load(c, "embedding", ["tenant_id", "view_key", "index_version", "chunk_id", "model_version", "vector"],
                [(t, v.key, version, ix.chunks[i]["id"], "lsa-view-1", [float(x) for x in V[j]]) for j, i in enumerate(v.rows)])
        done.append(v.key)
    return len(done)


def view_for(c, ctx):
    """The calling person's view of the current index: the permission engine runs before anything is read or ranked."""
    f = corpus(c)
    ix = load_index(c, f)
    pr = c.execute("SELECT id, external_ref, display_name FROM principal WHERE actor_id = %s", [ctx.actor_id]).fetchone()
    v = ix.view(containers_of(c, pr["id"]) if pr else [])
    if v._lsa is None and v.N >= 3:
        art = artifact(c, "lsa-view", lsa_name(v.key, ix.version))
        if art:
            rows = {r["chunk_id"]: r["vector"] for r in c.execute("SELECT chunk_id::text AS chunk_id, vector FROM embedding WHERE view_key = %s AND index_version = %s",
                                                                    [v.key, ix.version])}
            if len(rows) == v.N:
                v._lsa = (*art, np.array([rows[ix.chunks[i]["id"]] for i in v.rows], dtype=np.float64))
    return f, ix, v, pr


def audit_query(c, ctx, pr, v, endpoint, text, objects=(), intent=None, abstained=None, t0=None):
    c.execute("""INSERT INTO query_audit (tenant_id, principal_id, actor_id, endpoint, query_sha256, intent, view_key, returned_objects, abstained, model_versions, latency_ms)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
              [ctx.tenant_id, pr["id"] if pr else None, ctx.actor_id, endpoint, hashlib.sha256(text.encode()).hexdigest(), intent, v.key, list(dict.fromkeys(objects)),
               abstained, Jsonb(VERSIONS), round(1000 * (time.perf_counter() - t0), 1) if t0 else 0])


def audit_miss(ctx, pr, v, endpoint, text, t0):
    """A lookup that found nothing the caller may see is audited too, in its own transaction (the request's rolls back)."""
    with db.tx(ctx.tenant_id) as c:
        audit_query(c, ctx, pr, v, endpoint, text, t0=t0)


def source_of(ix, oid):
    o = ix.objects[oid]
    return {"object_id": oid, "system": o["system"], "container": o["container"], "title": o["title"], "external_id": o["external_id"],
            "observed_on": E.date_str(o["observed_day"]), "author": o.get("author")}


# --- the simulated sources move on --------------------------------------------------------------------------------------------
class Inject(BaseModel):
    kind: Literal["service_failure"]
    service: str = Field(min_length=3, max_length=60)


class AdvanceIn(BaseModel):
    days: int = Field(ge=1, le=30)
    inject: Inject | None = None


@app.post("/v1/simulator:advance", status_code=202, tags=["corpus"], summary="(+) Move the simulated enterprise forward. The generator can be told about an event (the demo's failing service); the service sees only what the source systems then hold, at the next connector sync")
def advance(body: AdvanceIn, ctx: Ctx = Depends(auth("simulator:advance")), idem: str | None = IdemKey):
    def work(c):
        f = corpus(c)
        if body.inject and body.inject.service not in world.SERVICES:
            raise Problem(422, "unknown_service", f"the simulator has no service called {body.inject.service}")
        if f["clock"] + body.days > world.HORIZON:
            raise Problem(422, "beyond_horizon", f"the simulator runs to {world.iso(world.HORIZON)}")
        return 202, jobs.enqueue(c, ctx, "simulator.advance", {**body.model_dump(), "from_day": f["clock"]})
    return run(ctx, idem, body, work)


@jobs.handler("simulator.advance")
def advance_job(c, job):
    p = job["payload"]
    f = corpus(c)
    told = list(f["told"])
    if p.get("inject"):
        told.append({"kind": p["inject"]["kind"], "service": p["inject"]["service"], "day": p["from_day"] + 1})
    clock = p["from_day"] + p["days"]
    c.execute("UPDATE corpora SET clock = %s, told = %s", [clock, Jsonb(told)])
    pending = collections.Counter()
    everything = world.objects(f["model_seed"], told)
    for s in c.execute("SELECT external_ref, metadata FROM source_system"):
        cur = s["metadata"].get("cursor_day")
        if cur is not None:
            pending[s["external_ref"]] = sum(o["system"] == s["external_ref"] for o in world.changed(everything, cur, clock))
    audit.record(c, worker_ctx(job), "simulator.advanced", "corpus", f["id"], {"days": p["days"], "told": told[len(f["told"]):]})
    return {"from": at(p["from_day"]).date(), "clock": at(clock).date(), "changed_in_sources": dict(pending),
            "simulation_truth": {"told": told[len(f["told"]):], "note": "what the generator was told; the pipeline never reads this, it reads the source systems at the next sync"}}


# --- reading ---------------------------------------------------------------------------------------------------------------------
@app.get("/v1/overview", tags=["knowledge"], summary="(+) The command centre for the caller: sources and the containers they may read, freshness, what their view holds, the review queue, the models")
def overview(ctx: Ctx = Depends(auth("kb:read"))):
    with db.tx(ctx.tenant_id) as c:
        f, ix, v, pr = view_for(c, ctx)
        types = collections.Counter(ix.type.get(e) for e in v.aliases[1])
        preds = collections.Counter(x["pred"] for x in v.facts.values())
        by_cont = collections.Counter(ix.objects[o]["container"] for o in v.objects)
        sources = []
        for s in c.execute("SELECT external_ref, name, metadata FROM source_system ORDER BY external_ref"):
            mine = sorted(x for x in by_cont if x.startswith(s["external_ref"] + ":"))
            sources.append({"system": s["external_ref"], "name": s["name"], "readable_containers": [{"container": x, "objects": by_cont[x]} for x in mine],
                            "objects_readable": sum(by_cont[x] for x in mine), "cursor": at(s["metadata"]["cursor_day"]).date() if s["metadata"].get("cursor_day") is not None else None,
                            "last_sync": s["metadata"].get("last_sync")})
        runs = c.execute("SELECT mode, to_day, finished_at, pipeline_seconds, extract(epoch FROM finished_at - requested_at) AS seconds, stats->'objects_changed' AS changed FROM sync_runs ORDER BY finished_at DESC LIMIT 5").fetchall() \
            if "connectors:sync" in PERMISSIONS[ctx.role] else []
        queue = [m for m in c.execute("SELECT keep_entity::text AS k, merge_entity::text AS m, status FROM merge_proposal WHERE status IN ('suggested', 'proposed')")
                 if v.visible_entity(m["k"]) and v.visible_entity(m["m"])]
        models = c.execute("SELECT name, version, data_snapshot, metrics, approved FROM model_artifacts WHERE name <> 'lsa-view' ORDER BY name").fetchall()
    return jsonable_encoder({"company": f["name"], "clock": at(f["clock"]).date(), "index_version": f["index_version"], "you": {"name": pr["display_name"] if pr else None,
                             "role": ctx.role, "containers": len(v.containers), "view": v.key}, "sources": sources,
                             "view": {"objects": len(v.objects), "chunks": v.N, "entities": dict(types), "facts": len(v.facts), "facts_by_predicate": dict(preds)},
                             "sync_runs": runs, "review_queue": len(queue), "models": models})


@app.get("/v1/entities", tags=["knowledge"], summary="(+) Find entities by name or alias, among what the caller may read")
def find_entities(q: str = Query(min_length=2, max_length=120), type: Literal["person", "team", "service", "vendor", "decision", "incident"] | None = None,
                  ctx: Ctx = Depends(auth("kb:read"))):
    with db.tx(ctx.tenant_id) as c:
        f, ix, v, pr = view_for(c, ctx)
        low = q.lower()
        hits = {x["entity"] for x in v.link_query(q)} | {e for a, es in v.aliases[0].items() if a.startswith(low) for e in es}
        items = sorted(({"id": e, "type": ix.type.get(e), "name": v.name(e), "mentions": sum(v.aliases[1].get(e, {}).values())} for e in hits if not type or ix.type.get(e) == type),
                       key=lambda x: -x["mentions"])[:20]
    return jsonable_encoder({"items": items})


@app.get("/v1/entities/{entity_id}", tags=["knowledge"], summary="An entity as the caller may see it: name, aliases, facts (ownership as a timeline), the sources behind them. 404 when nothing the caller may read mentions it")
def get_entity(entity_id: uuid.UUID, ctx: Ctx = Depends(auth("kb:read"))):
    t0 = time.perf_counter()
    with db.tx(ctx.tenant_id) as c:
        f, ix, v, pr = view_for(c, ctx)
        eid, merged_from = str(entity_id), None
        row = c.execute("SELECT status, merged_into FROM entity WHERE id = %s", [entity_id]).fetchone()
        if row and row["status"] == "merged":
            eid, merged_from = str(row["merged_into"]), str(entity_id)
        e = v.entity(eid)
        if e is None:
            miss = (pr, v)
        else:
            miss = None
    if miss:
        audit_miss(ctx, *miss, "entity", str(entity_id), t0)
        raise Problem(404, "entity_not_found")
    with db.tx(ctx.tenant_id) as c:
        if e["type"] == "service":
            e["timeline"] = [v.fact_brief(x) for x in v.timeline(eid)]
            e["timeline_evidence"] = sorted(({"day": E.date_str(a["effective"] if a["pred"] == "HANDOVER" and a["effective"] is not None else a["day"]), "says": v.name(a["subj"]),
                                              "role": role, "predicate": a["pred"], **{k: source_of(ix, a["object_id"])[k] for k in ("system", "title")}}
                                             for x in v.timeline(eid) for role, ids in (("supports", x["evidence"]), ("contradicts", x["against"])) for a in map(ix.assertions.get, ids)),
                                            key=lambda r: r["day"])
            e["clock"] = at(f["clock"]).date()
        e["merged_from"] = merged_from
        e["merges"] = [dict(r) for r in c.execute("SELECT id, merge_entity, status, decided_at FROM merge_proposal WHERE keep_entity = %s AND status = 'approved'", [eid])]
        audit_query(c, ctx, pr, v, "entity", str(entity_id), t0=t0)
    return jsonable_encoder(e)


class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    k: int = Field(10, ge=1, le=50)
    mode: Literal["hybrid", "hybrid+lsa", "bm25", "vector", "bm25+vector", "graph"] = "hybrid"


@app.post("/v1/search", tags=["knowledge"], summary="Hybrid search over the chunks the caller may read: BM25 and graph expansion fused by reciprocal rank (LSA available as hybrid+lsa); the filter is applied before ranking and every statistic is computed inside the caller's view")
def search(body: SearchIn, ctx: Ctx = Depends(auth("kb:read")), idem: str | None = IdemKey):
    def work(c):
        t0 = time.perf_counter()
        f, ix, v, pr = view_for(c, ctx)
        hits = v.search(body.query, k=body.k, mode=body.mode)
        out = [{**h, "source": source_of(ix, h["object_id"])} for h in hits]
        audit_query(c, ctx, pr, v, "search", body.query, [h["object_id"] for h in hits], t0=t0)
        return 200, {"query": body.query, "mode": body.mode, "results": out, "linked_entities": [{"id": x["entity"], "name": v.name(x["entity"]), "alias": x["alias"]} for x in v.link_query(body.query)],
                     "view": {"chunks": v.N, "key": v.key}, "version": E.RETRIEVER_VERSION}
    return run(ctx, idem, body, work)


class GraphIn(BaseModel):
    entity_id: uuid.UUID | None = None
    name: str | None = Field(None, min_length=2, max_length=120)
    depth: int = Field(1, ge=1, le=2)
    predicates: list[Literal["OWNS", "SELECTED", "CONSIDERED", "REJECTED", "REASON", "DECIDED_BY", "CONTRACT_VALUE", "MEMBER_OF", "LEADS", "AFFECTS", "DEPENDS_ON", "RENAMED"]] | None = None
    as_of: datetime.date | None = None


@app.post("/v1/graph/query", tags=["knowledge"], summary="The neighbourhood of an entity (by id or name) in the caller's graph: facts as edges with their validity and evidence count, optionally as of a date. 404 when the caller may not see the entity")
def graph_query(body: GraphIn, ctx: Ctx = Depends(auth("kb:read")), idem: str | None = IdemKey):
    def work(c):
        t0 = time.perf_counter()
        if not body.entity_id and not body.name:
            raise Problem(422, "entity_required", "send entity_id or name")
        f, ix, v, pr = view_for(c, ctx)
        start = str(body.entity_id) if body.entity_id else next((x["entity"] for x in v.link_query(body.name)), None)
        g = v.graph(start, depth=body.depth, predicates=set(body.predicates) if body.predicates else None,
                    as_of=E.day_of(body.as_of) if body.as_of else None) if start else None
        if g is None:
            audit_miss(ctx, pr, v, "graph", str(body.entity_id or body.name), t0)
            raise Problem(404, "entity_not_found")
        audit_query(c, ctx, pr, v, "graph", str(body.entity_id or body.name), t0=t0)
        return 200, {"start": {"id": start, "name": v.name(start), "type": ix.type.get(start)}, "as_of": body.as_of, **g}
    return run(ctx, idem, body, work)


class AnswerIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.post("/v1/answers", tags=["knowledge"], summary="Answer a question from the caller's facts only: every sentence carries its citations, a verifier re-checks each against the cited chunks, and when nothing supports an answer it says so")
def answers(body: AnswerIn, ctx: Ctx = Depends(auth("kb:read")), idem: str | None = IdemKey):
    def work(c):
        t0 = time.perf_counter()
        f, ix, v, pr = view_for(c, ctx)
        a = v.answer(body.question)
        check = E.verify(v, a)
        cites = {cid: n + 1 for n, cid in enumerate(a["citations"])}
        sources = [{"n": cites[cid], "chunk_id": cid, "text": ix.chunks[ix.pos[cid]]["text"], **source_of(ix, ix.chunks[ix.pos[cid]]["object_id"])} for cid in a["citations"]]
        for s in a["sentences"]:
            s["cite"] = [cites[x] for x in s["citations"]]
        audit_query(c, ctx, pr, v, "answers", body.question, [s["object_id"] for s in sources], a["intent"], a["abstained"], t0)
        return 200, {**a, "sources": sources, "verification": check, "as_of": at(f["clock"]).date(), "reader": pr["display_name"] if pr else None,
                     "facts": [v.fact_brief(v.facts[x]) for s in a["sentences"] for x in s["facts"] if x in v.facts]}
    return run(ctx, idem, body, work)


@app.get("/v1/facts/{fact_id}/provenance", tags=["knowledge"], summary="Where a fact comes from, as the caller may see it: each supporting and contradicting assertion with its sentence, extractor and confidence, the chunk and source object (system, container, version, sync), and how each mention was resolved. 404 when the caller may not see the fact")
def provenance(fact_id: uuid.UUID, ctx: Ctx = Depends(auth("kb:read"))):
    t0 = time.perf_counter()
    with db.tx(ctx.tenant_id) as c:
        f, ix, v, pr = view_for(c, ctx)
        p = v.provenance(str(fact_id))
        if p is None:
            miss = (pr, v)
    if p is None:
        audit_miss(ctx, *miss, "provenance", str(fact_id), t0)
        raise Problem(404, "fact_not_found")
    with db.tx(ctx.tenant_id) as c:
        ids = list({e["source"]["id"] for e in p["evidence"] + p["contradicting"]})
        meta = {str(r["id"]): r for r in c.execute("SELECT id, version, content_hash, synced_at FROM source_object WHERE id = ANY(%s)", [ids])}
        for e in p["evidence"] + p["contradicting"]:
            m = meta[e["source"]["id"]]
            e["source"] |= {"version": m["version"], "content_hash": m["content_hash"][:16], "synced_at": m["synced_at"]}
        ents = [x for x in (p["fact"]["subject"]["id"], (p["fact"]["object"] or {}).get("id")) if x]
        p["merges"] = [dict(r) for r in c.execute("""SELECT id, keep_entity, merge_entity, status, proposed_by, decided_by, decided_at, reason->>'why' AS why FROM merge_proposal
                                                     WHERE status = 'approved' AND keep_entity = ANY(%s)""", [ents])]
        p["reader"] = pr["display_name"] if pr else None
        p["versions"] = VERSIONS
        audit_query(c, ctx, pr, v, "provenance", str(fact_id), ids, t0=t0)
    return jsonable_encoder(p)


# --- entity resolution and the second person ----------------------------------------------------------------------------------
@app.get("/v1/resolution", tags=["resolution"], summary="(+) Entity resolution as the caller may see it: names that resolve to different people by context, entities with the most surface forms, mentions the linker abstained on, and the merge queue with its evidence")
def resolution(ctx: Ctx = Depends(auth("kb:read"))):
    with db.tx(ctx.tenant_id) as c:
        f, ix, v, pr = view_for(c, ctx)
        by_alias, by_entity = v.aliases
        split = sorted(({"alias": a, "entities": [{"id": e, "name": v.name(e), "mentions": by_entity[e].get(next((x for x in by_entity[e] if x.lower() == a), a), 0)} for e in sorted(es)]}
                        for a, es in by_alias.items() if len(es) > 1 and all(ix.type.get(e) == "person" and ix.entities[e]["anchor"] for e in es)),
                       key=lambda x: (-len(x["alias"].split()), x["alias"]))[:8]
        rich = sorted(((e, cnt) for e, cnt in by_entity.items() if ix.type.get(e) in ("person", "team", "vendor")), key=lambda x: (-len(x[1]), -sum(x[1].values())))[:8]
        abstained = sum(1 for cid in v.chunk_ids for m in ix.m_by_chunk.get(cid, ()) if m["method"] in ("ambiguous", "unresolved"))
        mentions = sum(len(ix.m_by_chunk.get(cid, ())) for cid in v.chunk_ids)
        queue = []
        for m in c.execute("SELECT * FROM merge_proposal ORDER BY created_at, (SELECT canonical_name FROM entity WHERE id = merge_entity) DESC").fetchall():
            k, x = str(m["keep_entity"]), str(m["merge_entity"])
            if not (v.visible_entity(k) or m["status"] == "approved") or not (v.visible_entity(x) or m["status"] == "approved"):
                continue
            ev = [a for a in m["reason"].get("evidence", []) if a in ix.assertions and ix.assertions[a]["chunk_id"] in v.chunk_ids]
            queue.append({"id": m["id"], "status": m["status"], "keep": {"id": k, "name": v.name(k)}, "merge": {"id": x, "name": v.name(x)}, "why": m["reason"].get("why"),
                          "evidence": [{"sentence": ix.objects[ix.assertions[a]["object_id"]]["body"][ix.assertions[a]["sent"][0]:ix.assertions[a]["sent"][1]],
                                        **source_of(ix, ix.assertions[a]["object_id"])} for a in ev[:3]],
                          "keep_mentions": sum(by_entity.get(k, {}).values()), "merge_mentions": sum(by_entity.get(x, {}).values()),
                          "proposed_by": m["proposed_by"], "decided_by": m["decided_by"]})
    return jsonable_encoder({"mentions": mentions, "abstained": abstained, "same_name_different_entities": split,
                             "most_surface_forms": [{"id": e, "type": ix.type.get(e), "name": v.name(e), "forms": [{"alias": a, "mentions": n} for a, n in cnt.most_common(8)]} for e, cnt in rich],
                             "queue": queue, "linker": E.LINKER_VERSION})


class MergeIn(BaseModel):
    keep_id: uuid.UUID
    merge_id: uuid.UUID
    reason: str = Field("", max_length=500)


@app.post("/v1/merges", status_code=201, tags=["resolution"], summary="(+) Propose merging one entity into another (two names for one team, one person). A proposal changes nothing until a steward who did not propose it approves")
def propose_merge(body: MergeIn, ctx: Ctx = Depends(auth("merges:propose")), idem: str | None = IdemKey):
    def work(c):
        f, ix, v, pr = view_for(c, ctx)
        if body.keep_id == body.merge_id:
            raise Problem(422, "same_entity", "an entity cannot be merged into itself")
        rows = {str(r["id"]): r for r in c.execute("SELECT id, type, status FROM entity WHERE id = ANY(%s)", [[body.keep_id, body.merge_id]])}
        for x in (str(body.keep_id), str(body.merge_id)):
            if x not in rows or not v.visible_entity(x):
                raise Problem(404, "entity_not_found", x)
            if rows[x]["status"] != "active":
                raise Problem(409, "already_merged", x)
        if rows[str(body.keep_id)]["type"] != rows[str(body.merge_id)]["type"]:
            raise Problem(422, "type_mismatch", f"{rows[str(body.keep_id)]['type']} and {rows[str(body.merge_id)]['type']}")
        mid = U(ctx.tenant_id, f"merge:{body.merge_id}>{body.keep_id}")
        row = c.execute("""INSERT INTO merge_proposal (id, tenant_id, keep_entity, merge_entity, reason, status, proposed_by) VALUES (%s,%s,%s,%s,%s,'proposed',%s)
                           ON CONFLICT (tenant_id, keep_entity, merge_entity) DO UPDATE SET status = 'proposed', proposed_by = excluded.proposed_by,
                             reason = merge_proposal.reason || jsonb_build_object('note', %s::text)
                           WHERE merge_proposal.status = 'suggested' RETURNING id, reason""",
                        [mid, ctx.tenant_id, body.keep_id, body.merge_id, Jsonb({"why": "proposed by a person", "note": body.reason}), ctx.actor_id, body.reason]).fetchone()
        if not row:
            raise Problem(409, "already_proposed", "this merge is already proposed or decided")
        audit.record(c, ctx, "merge.proposed", "merge_proposal", mid, {"keep": str(body.keep_id), "merge": str(body.merge_id), "reason": body.reason})
        return 201, {"merge_id": mid, "status": "proposed", "keep": {"id": body.keep_id, "name": v.name(str(body.keep_id))}, "merge": {"id": body.merge_id, "name": v.name(str(body.merge_id))},
                     "reason": row["reason"], "effect": f"{sum(v.aliases[1].get(str(body.merge_id), {}).values())} mentions would move to {v.name(str(body.keep_id))}"}
    return run(ctx, idem, body, work)


@app.post("/v1/merges/{merge_id}/approve", tags=["resolution"], summary="(+) A steward approves or rejects a proposed merge; the proposer cannot. On approval the mentions, assertions and facts move to the kept entity and the index is rebuilt")
def approve_merge(merge_id: uuid.UUID, decision: Literal["approved", "rejected"] = "approved", ctx: Ctx = Depends(auth("merges:approve")), idem: str | None = IdemKey):
    def work(c):
        m = c.execute("SELECT * FROM merge_proposal WHERE id = %s FOR UPDATE", [merge_id]).fetchone()
        if not m:
            raise Problem(404, "merge_not_found")
        if m["status"] != "proposed":
            raise Problem(409, "not_proposed", f"this merge is {m['status']}")
        if m["proposed_by"] == ctx.actor_id:
            raise Problem(403, "proposer_cannot_approve", "a merge needs a second person")
        c.execute("UPDATE merge_proposal SET status = %s, decided_by = %s, decided_at = now() WHERE id = %s", [decision, ctx.actor_id, merge_id])
        moved = {}
        if decision == "approved":
            keep, merge = m["keep_entity"], m["merge_entity"]
            moved["mentions"] = c.execute("UPDATE mention SET entity_id = %s WHERE entity_id = %s", [keep, merge]).rowcount
            moved["assertions"] = sum(c.execute(f"UPDATE relationship SET {col} = %s WHERE {col} = %s", [keep, merge]).rowcount for col in ("subject_id", "object_id", "from_id"))
            c.execute("UPDATE entity SET status = 'merged', merged_into = %s WHERE id = %s", [keep, merge])
            c.execute("UPDATE merge_proposal SET status = 'rejected', decided_at = now(), decided_by = %s WHERE status IN ('suggested', 'proposed') AND (merge_entity = %s OR keep_entity = %s)",
                      [ctx.actor_id, merge, merge])
            moved["index_version"] = refresh(c, corpus(c))
        audit.record(c, ctx, f"merge.{decision}", "merge_proposal", merge_id, {"keep": str(m["keep_entity"]), "merge": str(m["merge_entity"]), **moved})
        return 200, {"merge_id": merge_id, "status": decision, "moved": moved, "kept": m["keep_entity"]}
    return run(ctx, idem, {"decision": decision}, work)


# --- the security suite ---------------------------------------------------------------------------------------------------------
@app.post("/v1/security/suite", status_code=202, tags=["security"], summary="(+) Try to extract restricted facts through search, graph queries, answers, entities and provenance as every principal with a distinct view; check non-interference for the API users; and show the same probes leak with the filter off. 202 + job")
def security_suite(ctx: Ctx = Depends(auth("security:run")), idem: str | None = IdemKey):
    def work(c):
        corpus(c)
        return 202, jobs.enqueue(c, ctx, "security.suite", {})
    return run(ctx, idem, {}, work)


@jobs.handler("security.suite")
def security_job(c, job):
    t0 = time.perf_counter()
    f = corpus(c)
    ix = load_index(c, f)
    every = sorted({r["target"] for r in c.execute("SELECT DISTINCT target FROM permission_edge WHERE relation = 'can_read'")})
    distinct = {}
    for r in c.execute("SELECT id, external_ref, actor_id FROM principal WHERE kind = 'user' ORDER BY external_ref").fetchall():
        distinct.setdefault(tuple(containers_of(c, r["id"])), (r["external_ref"], r["actor_id"] is not None))
    users = [(name, list(k)) for k, (name, _) in distinct.items()]
    personas = [(r["external_ref"], containers_of(c, r["id"])) for r in c.execute("SELECT id, external_ref FROM principal WHERE actor_id IS NOT NULL ORDER BY external_ref")]

    def reduced(conts):
        keep = {o for o, x in ix.objects.items() if x["container"] in conts}
        return E.Index([x for o, x in ix.objects.items() if o in keep], [ch for ch in ix.chunks if ch["object_id"] in keep],
                       [m for m in ix.mentions if m["object_id"] in keep], [a for a in ix.assertions.values() if a["object_id"] in keep], ix.entities, ix.clock)
    on = E.security_suite(ix, users, every)
    ni = E.security_suite(ix, personas, every, reduced_index=reduced)
    off = E.security_suite(ix, personas, every, filter_off=True)
    res = {"principals_probed": on["users"], "probes": on["probes"], "leaks": on["leaks"], "leak_rate": on["leak_rate"], "by_channel": on["by_channel"],
           "api_users": [{"principal": n, "containers": len(cs)} for n, cs in personas],
           "non_interference": {"checked": ni["non_interference_checked"], "failed": ni["non_interference_failed"]},
           "filter_off": {"probes": off["probes"], "leaks": off["leaks"], "leaks_by_channel": off["leaks_by_channel"]}, "seconds": round(time.perf_counter() - t0, 1),
           "index_version": ix.version}
    audit.record(c, worker_ctx(job), "security.suite", "corpus", f["id"], {k: res[k] for k in ("probes", "leaks", "principals_probed")})
    return res
