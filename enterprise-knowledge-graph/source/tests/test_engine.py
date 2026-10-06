"""The generator, the pipeline and the query side, without a database."""
import pytest

from ekg import engine as E
from ekg import evaluate as V
from ekg import world

SAM, INES = "samuel.okafor@halden.example", "ines.duarte@halden.example"


@pytest.fixture(scope="module")
def b():
    return V.build(11)                     # a corpus neither the demo (7) nor the evaluation (101-103) uses


def test_corpus_is_deterministic_and_its_truth_is_consistent():
    a, b2 = world.objects(5), world.objects(5)
    assert [o["versions"][-1]["body"] for o in a] == [o["versions"][-1]["body"] for o in b2]
    co = world.company(5)
    now = world.view(a, world.NOW)
    assert len({o["external_id"] for o in now}) == len(now) and all(o["body"][m["start"]:m["end"]] == m["text"] for o in now for m in o["truth"]["mentions"])
    assert all(d["selected"] in d["candidates"] and len(set(d["candidates"])) == 3 for d in co["decisions"].values())
    assert all([x for x, _ in s["owners"]] == sorted(x for x, _ in s["owners"]) for s in co["services"].values())
    assert sum(len(s["owners"]) > 1 and s["owners"][-1][0] > 220 for s in co["services"].values()) >= 6     # recent handovers for the demo
    assert {"Priya Raman", "Pradeep Raman"} <= {f"{p['first']} {p['last']}" for p in co["people"].values()}
    told = [{"kind": "service_failure", "service": "ledger-api", "day": world.NOW + 1}]
    new = world.changed(world.objects(5, told), world.NOW, world.NOW + 2)
    inc = [o for o in new if o["kind"] == "ticket" and "SEV1" in o["body"]]
    assert len(inc) == 1 and "Update: mitigated" in inc[0]["body"] and not world.changed(a, world.NOW, world.NOW)
    assert all(o["created_day"] <= world.NOW + 2 for o in new) and not any(o["external_id"] == inc[0]["external_id"] for o in now)


def test_extraction_reads_hedges_that_trigger_words_do_not(b):
    det, m = b["det"], b["models"]["extractor"]
    scores = E.extraction_scores([o for o in b["objs"] if not o["annotated"]], det, m)
    assert scores["model"]["precision"] > 0.95 and scores["model"]["recall"] > 0.9
    assert scores["rules"]["precision"] < scores["model"]["precision"] - 0.1                  # trigger words take hedges and "budget owner" as facts
    hedge = {"system": "chat", "container": "chat:#team-messaging", "kind": "message", "title": "#team-messaging", "structured": False, "author": None,
             "body": "Messaging might take over rate-limiter next quarter, nothing decided yet", "observed_day": 100}
    fact = dict(hedge, body="pretty sure Messaging owns rate-limiter now")
    got = lambda o, use: [x["pred"] for x in E.extract(o, E.annotate_categories(det(o["body"]), det), det, m, use)]    # noqa: E731
    assert got(hedge, "model") == [] and got(fact, "model") == ["OWNS"] and got(fact, "rules") == ["OWNS"]
    budget = {"system": "tickets", "container": "tickets:PROCURE", "kind": "ticket", "title": "PROC-1: Select a CDN", "structured": False, "author": None,
              "body": "PROC-1: Select a CDN\nBudget owner: Dana Whitfield.", "observed_day": 100}
    assert "DECIDED_BY" not in got(budget, "model") and "DECIDED_BY" in got(budget, "rules")


def test_resolution_tells_people_apart_by_context_and_abstains_on_twins(b):
    r = V.resolution(b)
    assert r["system"]["b3_f1"] > 0.95 and r["system"]["b3_precision"] > 0.99 and r["string equality"]["b3_f1"] < 0.8
    assert r["system + approved merges"]["b3_f1"] >= r["system"]["b3_f1"] and r["_merge_proposals"] == r["_merge_proposals_correct"] == 2
    A, linker = b["A"], b["models"]["linker"]
    raman = [k for k, p in A.p.items() if p["last"] == "Raman"]
    assert len(raman) == 2
    for k in raman:
        team = A.person_team(k)
        o = {"container": f"chat:#team-{A.teams[team]['slug']}", "author": None, "title": "", "body": "P. Raman fixed the flaky test", "kind": "message"}
        ments = E.annotate_categories(b["det"](o["body"]), b["det"])
        assert E.link(ments[0], E.mention_context(o, ments, A), A, linker)[0] == k                 # the same initial and surname, resolved by the channel
    twins = [k for k, p in A.p.items() if (p["first"], p["last"]) == world.TWINS]
    o = {"container": "chat:#incidents", "author": None, "title": "", "body": "Paged Daniel Kim.", "kind": "message"}
    ments = E.annotate_categories(b["det"](o["body"]), b["det"])
    assert len(twins) == 2 and E.link(ments[0], E.mention_context(o, ments, A), A, linker)[2] == "ambiguous"


def test_reconciliation_follows_the_handover_and_outvotes_a_stale_page():
    def a(i, subj, day, kind, pred="OWNS", **kw):
        return {"id": f"a{i}", "pred": pred, "subj": subj, "obj": "svc", "frm": kw.get("frm"), "effective": kw.get("effective"), "day": day,
                "confidence": 1.0, "method": "model", "source_kind": kind}
    xs = [a(1, "A", 10, "file_revision"), a(2, "A", 60, "ticket"), a(3, "B", 95, "transition", "HANDOVER", frm="A", effective=100), a(4, "B", 130, "ticket"),
          a(5, "A", 200, "page")]                                                                  # a service page edited after the handover, owner line unchanged
    segs = E.reconcile(xs, 250)
    assert [(s["owner"], s["start"], s["end"]) for s in segs] == [("A", 10, 100), ("B", 100, None)] and segs[1]["against"] == ["a5"]
    assert E.owner_baseline(xs, 250, "latest") == "A"                                             # the baseline believes the stale page
    facts = E.derive_facts(xs, 250)
    assert {(f["subj"], f["valid_from"], f["valid_to"]) for f in facts} == {("A", 10, 100), ("B", 100, None)}


def test_statistics_live_inside_each_view(b):
    ix = b["ix"]
    sam, full = ix.view(b["users"][SAM]), ix.view(sorted(b["acl"]))
    red = V.reducer(b)(b["users"][SAM]).view(b["users"][SAM])
    for q in ("why did we pick the observability vendor", "who owns rate-limiter", "contract price breach"):
        assert [(h["chunk_id"], round(h["score"], 6)) for h in sam.search(q)] == [(h["chunk_id"], round(h["score"], 6)) for h in red.search(q)]
    assert sam.N < full.N and sam.bm25("standup")[0][1] != full.bm25("standup")[0][1]       # N and document frequencies come from what the view may read
    assert set(sam.facts) < set(full.facts) or set(sam.facts) != set(full.facts)


def test_answers_cite_every_sentence_and_abstain_without_evidence(b):
    co, ix = b["co"], b["ix"]
    full, sam = ix.view(sorted(b["acl"])), ix.view(b["users"][SAM])
    d = co["decisions"]["decision:observability"]
    q = f"Why was {co['vendors'][d['selected']]['short']} selected?"
    a = full.answer(q)
    assert a["intent"] == "decision" and E.verify(full, a)["coverage"] == 1.0 and len(a["sentences"]) >= 4
    assert not sam.answer(f"How much does the {co['vendors'][d['selected']]['name']} contract cost?")["sentences"][0].get("facts")
    assert full.answer("Who owns quantum-ledger-api?")["intent"] == "search" or full.answer("Who owns quantum-ledger-api?")["abstained"]
    bad = dict(a, sentences=[dict(s) for s in a["sentences"]])
    bad["sentences"][0]["citations"] = [next(c["id"] for c in ix.chunks if "standup" in c["text"])]    # a citation that does not say it
    assert E.verify(full, bad)["supported"] == len(a["sentences"]) - 1
    svc = next(k for k, s in co["services"].items() if len(s["owners"]) > 1 and s["owners"][-1][0] < world.NOW - 60)
    own = full.answer(f"Who owns {co['services'][svc]['slug']}?")
    assert own["intent"] == "owner" and E.verify(full, own)["coverage"] == 1.0
    assert V.answers(b, full)["unanswerable_claims"] == 0


def test_security_suite_finds_no_leak_and_sees_one_with_the_filter_off(b):
    ix, full = b["ix"], sorted(b["acl"])
    users = [(SAM, b["users"][SAM]), (INES, b["users"][INES])]
    on = E.security_suite(ix, users, full, reduced_index=V.reducer(b))
    off = E.security_suite(ix, users, full, filter_off=True)
    assert on["probes"] > 500 and on["leaks"] == 0 and on["non_interference_checked"] > 50 and on["non_interference_failed"] == 0
    assert off["leaks"] > 0.5 * off["probes"]
    sam = ix.view(b["users"][SAM])
    hidden = next(f for f in ix.view(full).facts.values() if f["pred"] == "CONTRACT_VALUE")
    assert sam.provenance(hidden["id"]) is None and sam.provenance("00000000-0000-0000-0000-000000000000") is None
