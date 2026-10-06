"""The knowledge pipeline and the query side, fitted and run on what the connectors bring in (bodies, titles, containers,
timestamps, authors), never on the generator's truth.

    normalize        source object -> sentences and chunks (paragraphs of at most three sentences)
    detect           entity mentions: the HR directory, service catalog and CRM as gazetteers, plus patterns (emails,
                     handles, initials, kebab-case service names, legal suffixes, "the X team", shortlists) learned in a
                     first pass over the corpus
    extract          relation candidates per sentence, each scored by a logistic regression over the words around and
                     between the two mentions (trained on an annotated sample); baseline: trigger words alone
    link             each mention scored against the anchors from the structured sources (a logistic pair scorer over
                     name similarity, form, and the mention's own context); NIL clusters for the rest; ambiguous
                     links abstain; baseline: string equality
    reconcile        a service's owner over time by Viterbi decoding over the dated assertions, weighted by source
                     reliability, with stated handovers as transitions; baselines: latest mention, majority
    View             everything a principal may read, computed from the rows they may read and nothing else: BM25
                     statistics, the LSA basis, entity aliases and names, facts and timelines. Search fuses BM25 and graph
                     expansion by reciprocal rank (LSA is measured and available, but lowered recall here); answers are
                     composed only from the view's facts, every sentence cites the chunks it rests on, and a verifier
                     re-checks every citation
    security_suite   tries to pull restricted facts out through search, graph queries, answers, entities and provenance,
                     and checks that a view on the full index answers exactly as an index built without the restricted
                     objects would
"""
import collections
import datetime
import hashlib
import json
import math
import re
import uuid

import numpy as np
from scipy import sparse
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

threadpool_limits(1)          # small models called often: thread pools only fight each other (and the API's workers)

EPOCH = datetime.date(2025, 8, 4)
EXTRACTOR_VERSION = "relation-lr-1"
LINKER_VERSION = "linker-lr-1"
RETRIEVER_VERSION = "hybrid-bm25-graph-1"
ANSWER_VERSION = "graph-answer-1"
LINK_MIN, LINK_MARGIN = 0.5, 0.2          # link when the best anchor scores >= 0.5 and beats the next by 0.2; otherwise abstain
FACT_NS = uuid.UUID("6f1c5f3e-2a4b-4c55-9d7e-0b4a1e2c9f10")
NICKNAMES = {"Bob": "Robert", "Rob": "Robert", "Bill": "William", "Will": "William", "Liz": "Elizabeth", "Beth": "Elizabeth", "Mike": "Michael",
             "Jon": "Jonathan", "Chris": "Christopher", "Maggie": "Margaret", "Tom": "Thomas", "Kate": "Katherine", "Katie": "Katherine",
             "Dan": "Daniel", "Sam": "Samuel", "Alex": "Alexander"}
SERVICE_SUFFIX = {"api", "service", "worker", "gateway", "renderer", "vault", "broker", "store", "collector", "loader", "indexer", "bff", "notifier",
                  "config", "runner", "orchestrator", "proxy", "logger", "router", "widget", "search", "sender", "hub", "rates", "scheduler",
                  "tracker", "page", "limiter", "registry", "processor", "builder", "reconciler", "pipeline"}
CATEGORY_TERMS = {   # a procurement taxonomy: category -> how people write it
    "observability": ["observability platform", "monitoring platform", "APM tool", "observability vendor"],
    "cdn": ["content delivery network", "edge network", "CDN"], "identity": ["identity provider", "SSO provider", "IdP"],
    "paging": ["on-call paging tool", "incident paging tool", "on-call tool"], "ci": ["CI system", "build system", "continuous integration service"],
    "support": ["support desk", "helpdesk", "customer support tool"], "backup": ["backup service", "backup vendor", "disaster recovery backup"],
    "analytics": ["product analytics tool", "analytics platform", "product analytics vendor"],
    "email": ["email delivery provider", "transactional email provider", "email provider"], "search": ["hosted search service", "search vendor", "managed search"]}
CATEGORY_LABEL = {k: v[0] if k != "cdn" else "CDN" for k, v in CATEGORY_TERMS.items()}
SOURCE_RELIABILITY = {"file_revision": 0.95, "ticket": 0.92, "transition": 0.97, "message": 0.75, "page": 0.65}
STOP = set("a an the of to in on for and or is are was were be been it its this that with by at from as we our you i".split())
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
                                      "november", "december"], 1)}


def day_of(d):
    return (d - EPOCH).days


def date_str(day):
    return (EPOCH + datetime.timedelta(days=int(day))).isoformat()


def stable_hash(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


# --- text -------------------------------------------------------------------------------------------------------------
TOKEN = re.compile(r"\$[0-9][0-9,]*|[a-z0-9]+(?:[-.][a-z0-9]+)*")


def stem(w):
    for suf in ("ation", "ing", "ed", "er", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def analyze(text):
    out = []
    for t in TOKEN.findall(text.lower()):
        if t in STOP:
            continue
        out.append(stem(t))
        if ("-" in t or "." in t) and not t.startswith("$"):
            out.extend(stem(p) for p in re.split(r"[-.]", t) if p and p not in STOP)
    return out


def sentences(text):
    """(start, end) of each sentence: lines, then sentence ends that are not an initial ("P. Raman") or "Inc."."""
    out = []
    pos = 0
    for line in text.split("\n"):
        s = pos
        for m in re.finditer(r"[.!?]\s+(?=[A-Za-z@#\"$])", line):
            before = line[: m.start()]
            if re.search(r"(?:^|\s)(?:[A-Z]|Inc|Ltd|vs|e\.g|i\.e)$", before):
                continue
            out.append((s, pos + m.start() + 1))
            s = pos + m.end()
        if line[s - pos:].strip():
            out.append((s, pos + len(line.rstrip())))
        pos += len(line) + 1
    return [(a, b) for a, b in out if b > a]


def chunk(obj):
    """Chunks with offsets into the body: a structured record or a chat message is one chunk; a page or ticket is split by
    paragraph into groups of at most three sentences, the title line joined to the first paragraph."""
    body = obj["body"]
    if obj["structured"] or obj["kind"] == "message":
        return [(0, len(body))]
    paras, pos = [], 0
    for line in body.split("\n"):
        if line.strip():
            paras.append((pos, pos + len(line)))
        pos += len(line) + 1
    if len(paras) > 1 and paras[0][1] - paras[0][0] < 90:
        paras = [(paras[0][0], paras[1][1])] + paras[2:]
    out = []
    sents = sentences(body)
    for a, b in paras:
        inside = [s for s in sents if s[0] >= a and s[1] <= b]
        for i in range(0, len(inside), 3):
            out.append((inside[i][0], inside[min(i + 2, len(inside) - 1)][1]))
        if not inside:
            out.append((a, b))
    return out


DATE_RES = [
    (re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b"), lambda m: datetime.date(int(m[1]), int(m[2]), int(m[3]))),
    (re.compile(r"\b([A-Z][a-z]+) (\d{1,2}), (20\d\d)\b"), lambda m: datetime.date(int(m[3]), MONTHS[m[1].lower()], int(m[2])) if m[1].lower() in MONTHS else None),
    (re.compile(r"\b(\d{1,2}) ([A-Z][a-z]+) (20\d\d)\b"), lambda m: datetime.date(int(m[3]), MONTHS[m[2].lower()], int(m[1])) if m[2].lower() in MONTHS else None),
]


def find_date(text):
    for rx, f in DATE_RES:
        m = rx.search(text)
        if m:
            try:
                d = f(m)
            except ValueError:
                d = None
            if d:
                return day_of(d)
    return None


def as_of_in(question, clock):
    """'in March 2026', 'in March', 'on 2026-03-15', 'on June 1, 2026' -> a day; None for 'now'."""
    d = find_date(question)
    if d is not None:
        return d
    m = re.search(r"\b(?:in|during|back in)\s+([A-Za-z]+)(?:\s+(20\d\d))?\b", question)
    if m and m[1].lower() in MONTHS:
        mo = MONTHS[m[1].lower()]
        now = EPOCH + datetime.timedelta(days=clock)
        yr = int(m[2]) if m[2] else (now.year if mo <= now.month else now.year - 1)
        return day_of(datetime.date(yr, mo, 15))
    return None


def jaro_winkler(a, b):
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if not la or not lb:
        return 0.0
    w = max(la, lb) // 2 - 1
    ma, mb = [False] * la, [False] * lb
    m = 0
    for i in range(la):
        for j in range(max(0, i - w), min(lb, i + w + 1)):
            if not mb[j] and a[i] == b[j]:
                ma[i] = mb[j] = True
                m += 1
                break
    if not m:
        return 0.0
    t, k = 0, 0
    for i in range(la):
        if ma[i]:
            while not mb[k]:
                k += 1
            t += a[i] != b[k]
            k += 1
    jaro = (m / la + m / lb + (m - t / 2) / m) / 3
    p = 0
    while p < min(4, la, lb) and a[p] == b[p]:
        p += 1
    return jaro + 0.1 * p * (1 - jaro)


def ed1(a, b):
    """Edit distance at most one."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return a[i + 1:] == b[i + 1:] or a[i + 1:] == b[i:] or a[i:] == b[i + 1:]


def norm(s, typ=None):
    s = s.lower().replace("&", "and").replace("#team-", "")
    if typ == "service":
        s = re.sub(r"^svc-", "", s.replace(" ", "-"))
        s = re.sub(r"^the-|-service$", "", s) if s.count("-") > 1 else s
        return s
    s = re.sub(r"[-_.]", " ", s)
    s = re.sub(r"\s+team$", "", s)
    return re.sub(r"\s+", " ", s).strip()


# --- the gazetteer: what the structured sources say exists -----------------------------------------------------------
def fields(body):
    out = collections.defaultdict(list)
    for line in body.split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip().lower()].append(v.strip())
    return out


def gazetteer(objs):
    """Anchors from the HR directory (people, org units), the service catalog (latest revision of each service) and the CRM
    (vendor accounts and contracts)."""
    g = {"persons": {}, "teams": {}, "services": {}, "vendors": {}, "extra_teams": set(), "extra_vendors": {}, "slugs": set(), "team_slugs": set()}
    latest = {}
    for o in objs:
        f = fields(o["body"])
        if o["kind"] == "person_record":
            first, last = f["name"][0].split(" ", 1)
            email = f["email"][0]
            g["persons"]["person:" + email.split("@")[0]] = {"first": first, "last": last, "email": email, "handle": f["handle"][0].lstrip("@"),
                                                             "team": norm(f["team"][0]) if f.get("team") else None}
        elif o["kind"] == "org_unit":
            g["teams"]["team:" + f["slug"][0]] = {"name": f["org unit"][0], "short": (f.get("short name") or [None])[0], "slug": f["slug"][0]}
        elif o["kind"] == "file_revision":
            slug = f["service"][0]
            if slug not in latest or latest[slug][0] < o["observed_day"]:
                latest[slug] = (o["observed_day"], f["owner"][0])
            g["team_slugs"].add(f["owner"][0])
        elif o["kind"] in ("account", "contract"):
            legal = (f.get("account") or f.get("contract"))[0]
            name = re.sub(r"\s+(Inc\.|Ltd|Labs|GmbH)$", "", legal)
            key = "vendor:" + name.lower().replace(" ", "-")
            v = g["vendors"].setdefault(key, {"legal": legal, "name": name, "short": name.split()[0], "domain": None, "category": None})
            if f.get("domain"):
                v["domain"] = f["domain"][0]
            if f.get("category"):
                v["category"] = category_of(f["category"][0])
    for slug, (_, owner) in latest.items():
        g["services"]["service:" + slug] = {"slug": slug, "owner": owner}
    return g


def category_of(text):
    low = text.lower()
    for k, terms in CATEGORY_TERMS.items():
        if any(t.lower() in low for t in terms):
            return k
    for k in CATEGORY_TERMS:
        if re.search(rf"\b{k}\b", low):
            return k
    return None


def _phrases(g):
    """Exact phrases -> type, for one alternation regex (longest first)."""
    ph = {}
    for p in g["persons"].values():
        ph[f"{p['first']} {p['last']}"] = "person"
        nick = [n for n, full in NICKNAMES.items() if full == p["first"]]
        for n in nick:
            ph[f"{n} {p['last']}"] = "person"
    for t in g["teams"].values():
        ph[t["name"]] = "team"
        ph[t["slug"]] = "team"
        if t["short"]:
            ph[t["short"]] = "team"
    for s in g["team_slugs"]:
        ph[s] = "team"
    for name in g["extra_teams"]:
        ph[name] = "team"
    for v in g["vendors"].values():
        for x in (v["legal"], v["name"], v["short"], v["domain"]):
            if x:
                ph[x] = "vendor"
    for name, (short, legal) in g["extra_vendors"].items():
        for x in (name, short, legal):
            if x and x not in ph:
                ph[x] = "vendor"
    for s in g["services"]:
        slug = s.split(":", 1)[1]
        ph[slug] = ph["svc-" + slug] = "service"
    for slug in g["slugs"]:
        ph[slug] = ph["svc-" + slug] = "service"
        ph[" ".join({"api": "API", "bff": "BFF", "fx": "FX", "waf": "WAF", "sms": "SMS", "kb": "KB"}.get(w, w.capitalize()) for w in slug.split("-"))] = "service"
    return ph


class Detector:
    def __init__(self, g):
        self.g = g
        ph = _phrases(g)
        self.types = ph
        alts = sorted(ph, key=len, reverse=True)
        self.rx = re.compile(r"(?<![\w-])(" + "|".join(re.escape(a) for a in alts) + r")(?![\w-])") if alts else None
        cats = sorted(((t, k) for k, ts in CATEGORY_TERMS.items() for t in ts), key=lambda x: -len(x[0]))
        self.cat_rx = re.compile(r"(?<![\w-])(" + "|".join(re.escape(t) for t, _ in cats) + r")(?![\w-])", re.I)
        self.cat_of = {t.lower(): k for t, k in cats}
        self.firsts = {p["first"] for p in g["persons"].values()} | {n for n, full in NICKNAMES.items() if full in {p["first"] for p in g["persons"].values()}}
        self.lasts = {p["last"] for p in g["persons"].values()}
        self.handles = {p["handle"] for p in g["persons"].values()}
        self.vshort = {v["short"] for v in g["vendors"].values()} | {s for s, _ in g["extra_vendors"].values() if s}

    def __call__(self, text):
        c = []    # (start, end, type, priority)
        for m in re.finditer(r"\b[a-z][a-z0-9.]*@[a-z0-9.-]+\.[a-z]+\b", text):
            c.append((m.start(), m.end(), "person", 9))
        for m in re.finditer(r"(?<![\w@#])@([a-z][a-z0-9]+)\b", text):
            if m[1] in self.handles:
                c.append((m.start(), m.end(), "person", 9))
        for m in re.finditer(r"\bINC-\d+\b", text):
            c.append((m.start(), m.end(), "incident", 9))
        if self.rx:
            for m in self.rx.finditer(text):
                c.append((m.start(), m.end(), self.types[m[1]], 7))
        for m in re.finditer(r"\b([A-Z][a-z]+) ([A-Z][a-z]+)\b", text):
            if m[1] in self.firsts and m[2] not in self.lasts and any(ed1(m[2], l) for l in self.lasts if abs(len(l) - len(m[2])) <= 1):
                c.append((m.start(), m.end(), "person", 6))
        for m in re.finditer(r"\b([A-Z])\. ([A-Z][a-z]+)\b", text):
            if m[2] in self.lasts:
                c.append((m.start(), m.end(), "person", 6))
        for m in re.finditer(r"\b(?:thanks|ping|cc|ask) ([A-Z][a-z]+)\b", text):
            if m[1] in self.firsts:
                c.append((m.start(1), m.end(1), "person", 6))
        for m in re.finditer(r"(?<![\w-])((?:svc-)?[a-z]+(?:-[a-z]+)+)(?![\w-])", text):
            if m[1].rsplit("-", 1)[1] in SERVICE_SUFFIX:
                c.append((m.start(), m.end(), "service", 5))
        for m in re.finditer(r"\b([A-Z][a-z]+ [A-Z][a-z]+ (?:Inc\.|Ltd|Labs|GmbH))", text):
            c.append((m.start(), m.end(), "vendor", 6))
        for m in re.finditer(r"\b[A-Z][a-z]{4,}\b", text):
            w = m[0]
            if w not in self.vshort and w not in self.firsts and w not in self.lasts and any(ed1(w, s) for s in self.vshort if len(s) >= 5 and abs(len(s) - len(w)) <= 1):
                c.append((m.start(), m.end(), "vendor", 3))
        for m in self.cat_rx.finditer(text):
            c.append((m.start(), m.end(), "decision", 5))
        for m in re.finditer(r"\bthe ([A-Z][\w]*(?: (?:&|[A-Z][\w]*))*) team\b", text):
            c.append((m.start(1), m.end(1), "team", 4))
        c.sort(key=lambda x: (-x[3], -(x[1] - x[0]), x[0]))
        taken, out = [], []
        for s, e, t, _ in c:
            if any(s < b and a < e for a, b in taken):
                continue
            taken.append((s, e))
            out.append({"start": s, "end": e, "text": text[s:e], "type": t})
        return sorted(out, key=lambda m: m["start"])

    def category(self, surface):
        return self.cat_of.get(surface.lower())


def discover(objs, g):
    """First pass: names the structured sources do not list (old team names, vendors only in shortlists, services not in
    the catalog) found by patterns, so the second pass can detect them everywhere."""
    for o in objs:
        b = o["body"]
        for m in re.finditer(r"\bthe ([A-Z][\w]*(?: (?:&|[A-Z][\w]*))*) team\b", b):
            g["extra_teams"].add(m[1])
        for m in re.finditer(r"\b([A-Z][\w&]*(?: (?:&|[A-Z][\w]*))*) (?:is now|has been renamed to) ", b):
            g["extra_teams"].add(m[1])
        for m in re.finditer(r"\b(([A-Z][a-z]+) [A-Z][a-z]+) (Inc\.|Ltd|Labs|GmbH)", b):
            g["extra_vendors"][m[1]] = (m[2], m[0])
        for m in re.finditer(r"(?:Candidates|Shortlist|shortlist is|evaluated)[: ]+([^.\n]+)", b):
            for item in re.split(r",\s*|\s+and\s+", m[1]):
                item = re.sub(r"\s+for the .*$", "", item.strip())
                if re.fullmatch(r"[A-Z][a-z]+(?: [A-Z][a-z]+)?(?: (?:Inc\.|Ltd|Labs|GmbH))?", item):
                    name = re.sub(r"\s+(Inc\.|Ltd|Labs|GmbH)$", "", item)
                    if name.split()[0] not in {p["first"] for p in g["persons"].values()}:
                        g["extra_vendors"].setdefault(name, (name.split()[0], item if item != name else None))
        for m in re.finditer(r"(?<![\w-])(?:svc-)?([a-z]+(?:-[a-z]+)+)(?![\w-])", b):
            if m[1].rsplit("-", 1)[1] in SERVICE_SUFFIX:
                g["slugs"].add(m[1])
    return g


# --- relation extraction --------------------------------------------------------------------------------------------
PAIRS = {"OWNS": ("team", "service"), "SELECTED": ("decision", "vendor"), "CONSIDERED": ("decision", "vendor"), "REJECTED": ("decision", "vendor"),
         "DECIDED_BY": ("decision", "person")}
TRIGGERS = {"OWNS": ["own", "owner", "responsible", "maintains", "belongs"], "SELECTED": ["selected", "chose", "chosen", "picked", "going with", "go with", "went with"],
            "CONSIDERED": ["candidates", "shortlist", "evaluated"], "REJECTED": ["rejected", "ruled out", "is out"], "DECIDED_BY": ["owner", "decided by", "signed off"],
            "HANDOVER": ["moves", "takes over", "previously", "take over"]}
CUES = {"neg": r"\b(?:not|no longer|never|n't|isn't|nothing)\b", "hedge": r"\b(?:might|may|could|if|whether|maybe|perhaps|considering|decided yet)\b",
        "question": r"\?", "prev": r"\bpreviously\b"}


def _tokens_tagged(text, s0, ments, a, b):
    """The sentence as tokens, each mention replaced by a tag: <A>, <B> or <type>."""
    out, pos = [], s0
    for m in sorted(ments, key=lambda m: m["start"]):
        out += [w for w in re.findall(r"[a-z0-9']+|[:?(),$]", text[pos - s0: m["start"] - s0].lower())]
        out.append("<A>" if m is a else "<B>" if m is b else f"<{m['type']}>")
        pos = m["end"]
    out += re.findall(r"[a-z0-9']+|[:?(),$]", text[pos - s0:].lower())
    return out


def pair_features(sent, s0, ments, a, b):
    toks = _tokens_tagged(sent, s0, ments, a, b)
    f = {f"cue:{k}": 1 for k, rx in CUES.items() if re.search(rx, sent, re.I)}
    if a is None:
        ib = toks.index("<B>")
        f["ctx"] = 1
        for w in toks[max(0, ib - 4): ib]:
            f[f"pre:{w}"] = 1
        for w in toks[ib + 1: ib + 4]:
            f[f"post:{w}"] = 1
        for w in toks:
            f[f"s:{w}"] = 1
        return f
    ia, ib = toks.index("<A>"), toks.index("<B>")
    lo, hi = min(ia, ib), max(ia, ib)
    between = toks[lo + 1: hi]
    f["order"] = int(ia < ib)
    f[f"nb:{min(len(between), 8)}"] = 1
    for w in between:
        f[f"b:{w}"] = 1
    for x, y in zip(between, between[1:]):
        f[f"bb:{x}_{y}"] = 1
    for w in toks[max(0, lo - 3): lo]:
        f[f"pre:{w}"] = 1
    for w in toks[hi + 1: hi + 4]:
        f[f"post:{w}"] = 1
    return f


def doc_context(obj, ments, det):
    """The decision (from the title, the first line or the channel) and the service (a ticket's Service field) a document
    is about."""
    ctx = {"decision": None, "service": None, "vendor": None}
    first_line = obj["body"].split("\n", 1)[0]
    for m in ments:
        if m["type"] == "decision" and m["start"] < len(first_line):
            ctx["decision"] = m
            break
    if not ctx["decision"]:
        ch = re.search(r"#vendor-eval-([a-z]+)", obj["container"])
        k = category_of(obj["title"]) or (ch[1] if ch and ch[1] in CATEGORY_TERMS else None) or category_of(fields(obj["body"]).get("category", [""])[0])
        if k:
            ctx["decision"] = {"type": "decision", "key": f"decision:{k}", "text": CATEGORY_LABEL[k], "start": -1, "end": -1, "context": True}
    svc = re.search(r"^Service: (.+)$", obj["body"], re.M)
    if svc:
        ctx["service"] = next((m for m in ments if m["type"] == "service" and m["start"] >= svc.start(1)), None)
    con = re.search(r"^(?:Contract|Account): (.+)$", obj["body"], re.M)
    if con:
        ctx["vendor"] = next((m for m in ments if m["type"] == "vendor" and m["start"] >= con.start(1)), None)
    return ctx


def candidates(obj, ments, det):
    """Every (relation, subject mention, object mention) the sentence could express, with its features and sentence."""
    body = obj["body"]
    ctx = doc_context(obj, ments, det)
    out = []
    for s0, s1 in sentences(body):
        sent = body[s0:s1]
        inside = [m for m in ments if m["start"] >= s0 and m["end"] <= s1]
        for rel, (ta, tb) in PAIRS.items():
            As = [m for m in inside if m["type"] == ta]
            Bs = [m for m in inside if m["type"] == tb]
            if ta == "decision" and not As and ctx["decision"]:
                As = [None]
            if rel == "OWNS" and not Bs and ctx["service"] is not None and As:
                Bs = [ctx["service"]]
            for a in As:
                for b in Bs:
                    if a is b:
                        continue
                    if ctx["service"] is not None and b is ctx["service"] and b not in inside:
                        f = pair_features(sent, s0, inside, None, a) | {"ctxsvc": 1}
                    else:
                        f = pair_features(sent, s0, inside, a, b)
                    out.append({"rel": rel, "a": a if a is not None else ctx["decision"], "b": b, "sent": (s0, s1), "f": f, "text": sent})
    return out, ctx


def rule_says(c):
    low = c["text"].lower()
    return any(t in low for t in TRIGGERS[c["rel"]])


def _span_key(m, gold):
    """The gold mention a detected mention overlaps most (for training labels and scoring)."""
    best, ov = None, 0
    for g in gold:
        o = min(m["end"], g["end"]) - max(m["start"], g["start"])
        if o > ov:
            best, ov = g, o
    return best


def gold_key(m, obj):
    if m is None:
        return None
    if m.get("context"):
        return m["key"]
    if m["type"] == "decision":
        return f"decision:{m.get('category') or ''}"
    g = _span_key(m, obj["truth"]["mentions"])
    return g["key"] if g else None


def train_extractor(objs, det):
    """Logistic regression per relation on the annotated documents' candidates; labels from the annotation."""
    X, y = collections.defaultdict(list), collections.defaultdict(list)
    sent_X, sent_y = [], []
    for o in objs:
        ments = annotate_categories(det(o["body"]), det)
        cands, _ = candidates(o, ments, det)
        gold = [f for f in o["truth"]["facts"] if f["asserted"] and f["polarity"]]
        for c in cands:
            ka, kb = gold_key(c["a"], o), gold_key(c["b"], o)
            pos = any(f["pred"] == c["rel"] and f["subj"] == ka and f["obj"] == kb and f["start"] <= c["sent"][0] < f["end"] + 1 for f in gold)
            X[c["rel"]].append(c["f"])
            y[c["rel"]].append(int(pos))
        for s0, s1, f in handover_candidates(o, ments):
            sent_X.append(f)
            sent_y.append(int(any(g["pred"] == "HANDOVER" and g["start"] <= s0 < g["end"] + 1 for g in gold)))
    models = {}
    for rel in PAIRS:
        if len(set(y[rel])) == 2:
            v = DictVectorizer()
            models[rel] = (v, LogisticRegression(C=2.0, class_weight="balanced", max_iter=2000).fit(v.fit_transform(X[rel]), y[rel]))
    if len(set(sent_y)) == 2:
        v = DictVectorizer()
        models["HANDOVER"] = (v, LogisticRegression(C=2.0, class_weight="balanced", max_iter=2000).fit(v.fit_transform(sent_X), sent_y))
    models["_train"] = {rel: {"candidates": len(y[rel]), "positives": int(sum(y[rel]))} for rel in PAIRS} | {"HANDOVER": {"candidates": len(sent_y), "positives": int(sum(sent_y))}}
    return models


def annotate_categories(ments, det):
    for m in ments:
        if m["type"] == "decision":
            m["category"] = det.category(m["text"])
    return ments


def handover_candidates(obj, ments):
    body = obj["body"]
    for s0, s1 in sentences(body):
        inside = [m for m in ments if m["start"] >= s0 and m["end"] <= s1]
        if sum(m["type"] == "team" for m in inside) >= 2 and any(m["type"] == "service" for m in inside):
            sent = body[s0:s1]
            f = {f"cue:{k}": 1 for k, rx in CUES.items() if re.search(rx, sent, re.I)}
            for w in _tokens_tagged(sent, s0, inside, None, None):
                f[f"s:{w}"] = 1
            f["date"] = int(find_date(sent) is not None)
            yield s0, s1, f


def _p(models, rel, f):
    if rel not in models:
        return None
    v, lr = models[rel]
    return float(lr.predict_proba(v.transform([f]))[0, 1])


def extract(obj, ments, det, models, use="model"):
    """-> assertions [{pred, a (mention or context), b (mention), value, effective, frm, sent, confidence, method}].
    use='rules' is the baseline: trigger words alone."""
    body, out = obj["body"], []
    if obj["structured"]:
        return extract_structured(obj, ments)
    cands, ctx = candidates(obj, ments, det)
    for c in cands:
        if use == "rules":
            ok, p = rule_says(c), 1.0
        else:
            p = _p(models, c["rel"], c["f"])
            ok = rule_says(c) if p is None else p >= 0.5
            p = 1.0 if p is None else p
        if ok:
            val = None
            if c["rel"] == "REJECTED":
                tail = c["text"][c["b"]["end"] - c["sent"][0]:]
                m = re.search(r"(?:because|:|,)\s+(.+?)\.?$", tail)
                val = m[1].strip() if m else None
            out.append({"pred": c["rel"], "a": c["a"], "b": c["b"], "value": val, "sent": c["sent"], "confidence": round(p, 3), "method": use})
    for s0, s1, f in handover_candidates(obj, ments):
        sent = body[s0:s1]
        if use == "rules":
            ok, p = any(t in sent.lower() for t in TRIGGERS["HANDOVER"]), 1.0
        else:
            p = _p(models, "HANDOVER", f)
            ok = any(t in sent.lower() for t in TRIGGERS["HANDOVER"]) if p is None else p >= 0.5
            p = 1.0 if p is None else p
        if not ok:
            continue
        inside = [m for m in ments if m["start"] >= s0 and m["end"] <= s1]
        teams = [m for m in inside if m["type"] == "team"]
        svc = next(m for m in inside if m["type"] == "service")
        frm = next((m for m in teams if re.search(r"(?:from|previously)\s*$", body[s0:m["start"]])), None)
        to = next((m for m in teams if re.search(r"\bto\s*$", body[s0:m["start"]])), None)
        if frm is None and to is not None:
            frm = next(m for m in teams if m is not to)
        if to is None and frm is not None:
            to = next(m for m in teams if m is not frm)
        if frm is None:
            frm, to = teams[1], teams[0]
        out.append({"pred": "HANDOVER", "a": to, "b": svc, "frm": frm, "effective": find_date(sent), "sent": (s0, s1), "confidence": round(p, 3), "method": use})
    for s0, s1 in sentences(body):
        sent = body[s0:s1]
        inside = [m for m in ments if m["start"] >= s0 and m["end"] <= s1]
        teams = [m for m in inside if m["type"] == "team"]
        if len(teams) >= 2 and re.search(r"\b(?:is now|renamed to|is called)\b", sent):
            out.append({"pred": "RENAMED", "a": teams[0], "b": teams[1], "effective": find_date(sent), "sent": (s0, s1), "confidence": 1.0, "method": "pattern"})
        if ctx["decision"]:
            m = re.search(r"(?:won on|deciding factors were|[Mm]ain reasons?:)\s+(.+?)\.?$", sent)
            if m:
                for r in re.split(r"\s+and\s+", m[1]):
                    out.append({"pred": "REASON", "a": ctx["decision"], "b": None, "value": r.strip(), "sent": (s0, s1), "confidence": 1.0, "method": "pattern"})
        money = re.search(r"\$[0-9][0-9,]+", sent)
        if money and re.search(r"price|value|a year|annual|contract", sent, re.I):
            v = next((m for m in inside if m["type"] == "vendor"), None) or ctx["vendor"]
            out.append({"pred": "CONTRACT_VALUE", "a": v, "b": None, "value": money[0], "sent": (s0, s1), "confidence": 1.0, "method": "pattern"})
    sel = next((x for x in out if x["pred"] == "SELECTED"), None)
    for x in out:
        if x["pred"] == "CONTRACT_VALUE" and x["a"] is None and sel:
            x["a"] = sel["b"]
    return [x for x in out if x.get("a") is not None]


def extract_structured(obj, ments):
    """Records from the HR directory, the catalog, the CRM and a ticket's fields: the schema says what each field means."""
    out, body = [], obj["body"]
    by_line = collections.defaultdict(list)
    for m in ments:
        by_line[body.rfind("\n", 0, m["start"]) + 1].append(m)

    def line(key):
        mm = re.search(rf"^{key}: ", body, re.M)
        return by_line.get(mm.start(), []) if mm else []

    def sent(m):
        a = body.rfind("\n", 0, m["start"]) + 1
        b = body.find("\n", m["start"])
        return (a, b if b >= 0 else len(body))
    k = obj["kind"]
    if k == "person_record":
        me = (line("Name") or [None])[0]
        for key, pred in (("Team", "MEMBER_OF"), ("Leads", "LEADS")):
            for t in line(key):
                if me and t["type"] == "team":
                    out.append({"pred": pred, "a": me, "b": t, "sent": sent(t), "confidence": 1.0, "method": "structured"})
    elif k == "org_unit":
        me = (line("Org unit") or [None])[0]
        for p in line("Lead"):
            if me:
                out.append({"pred": "LEADS", "a": p, "b": me, "sent": sent(p), "confidence": 1.0, "method": "structured"})
    elif k == "file_revision":
        svc = (line("service") or [None])[0]
        for t in line("owner"):
            out.append({"pred": "OWNS", "a": t, "b": svc, "sent": sent(t), "confidence": 1.0, "method": "structured"})
        for d in line("depends_on"):
            out.append({"pred": "DEPENDS_ON", "a": svc, "b": d, "sent": sent(d), "confidence": 1.0, "method": "structured"})
    elif k == "contract":
        v = (line("Contract") or [None])[0]
        m = re.search(r"^Annual value: (\$[0-9,]+)", body, re.M)
        if v and m:
            out.append({"pred": "CONTRACT_VALUE", "a": v, "b": None, "value": m[1], "sent": (m.start(), m.end()), "confidence": 1.0, "method": "structured"})
    return [x for x in out if x["a"] is not None and (x["b"] is not None or x.get("value"))]


def ticket_structured(obj, ments):
    """A ticket's Service field: the incident affects that service."""
    m = re.search(r"^Service: (.+)$", obj["body"], re.M)
    inc = next((x for x in ments if x["type"] == "incident"), None)
    svc = next((x for x in ments if x["type"] == "service" and m and x["start"] >= m.start(1)), None)
    if m and inc and svc:
        return [{"pred": "AFFECTS", "a": inc, "b": svc, "sent": (m.start(), m.end()), "confidence": 1.0, "method": "structured"}]
    return []


# --- entity linking -----------------------------------------------------------------------------------------------------
class Anchors:
    """Entity profiles from the structured sources, and the blocking that proposes candidates for a mention."""

    def __init__(self, g):
        self.g = g
        self.p = g["persons"]
        self.by_email = {p["email"]: k for k, p in self.p.items()}
        self.by_handle = {p["handle"]: k for k, p in self.p.items()}
        self.by_last = collections.defaultdict(list)
        self.by_first = collections.defaultdict(list)
        for k, p in self.p.items():
            self.by_last[p["last"]].append(k)
            self.by_first[p["first"]].append(k)
        self.teams = g["teams"]
        self.team_norms = {k: {norm(t["name"]), norm(t["slug"])} | ({norm(t["short"])} if t["short"] else set()) for k, t in self.teams.items()}
        self.vendors = g["vendors"]
        self.svc_owner = {s["slug"]: s["owner"] for s in g["services"].values()}

    def person_team(self, k):
        t = self.p[k]["team"]
        return next((tk for tk, ns in self.team_norms.items() if t in ns), None)

    def candidates(self, m):
        t, s = m["type"], m["text"]
        if t == "person":
            if "@" in s and "." in s:
                return [self.by_email[s]] if s in self.by_email else []
            if s.startswith("@"):
                return [self.by_handle[s[1:]]] if s[1:] in self.by_handle else []
            parts = s.replace(".", "").split()
            if len(parts) == 1:
                return list(dict.fromkeys(self.by_first.get(parts[0], []) + self.by_first.get(NICKNAMES.get(parts[0], ""), [])))
            last = parts[-1]
            out = list(self.by_last.get(last, []))
            out += [k for l, ks in self.by_last.items() if l != last and abs(len(l) - len(last)) <= 1 and ed1(l, last) for k in ks]
            return out
        if t == "team":
            n = norm(s)
            toks = set(n.split()) - {"and"}
            return [k for k, ns in self.team_norms.items() if n in ns or any(toks & (set(x.split()) - {"and"}) for x in ns)]
        if t == "vendor":
            first = re.split(r"[ .]", s)[0]
            return [k for k, v in self.vendors.items() if v["short"] == first or (v["domain"] and v["domain"] == s) or (len(first) >= 5 and ed1(first, v["short"]))]
        return []

    def aliases(self, k):
        if k in self.p:
            p = self.p[k]
            return [f"{p['first']} {p['last']}", p["email"], "@" + p["handle"]] + [f"{n} {p['last']}" for n, full in NICKNAMES.items() if full == p["first"]]
        if k in self.teams:
            t = self.teams[k]
            return [x for x in (t["name"], t["slug"], t["short"]) if x]
        if k in self.vendors:
            v = self.vendors[k]
            return [x for x in (v["legal"], v["name"], v["short"], v["domain"]) if x]
        return []


def link_features(m, k, cands, ctx, A):
    s = m["text"]
    f = {"n_cands": len(cands), f"type_{m['type']}": 1}
    al = A.aliases(k)
    ns = norm(s)
    f["exact"] = int(any(norm(a) == ns for a in al))
    f["jw"] = max((jaro_winkler(ns, norm(a)) for a in al), default=0)
    if m["type"] == "person":
        p = A.p[k]
        parts = s.replace(".", "").split()
        f["form_email"], f["form_handle"] = int("@" in s and "." in s), int(s.startswith("@"))
        f["form_initial"] = int(bool(re.fullmatch(r"[A-Z]\. \w+", s)))
        f["form_first"] = int(len(parts) == 1 and not s.startswith("@"))
        f["first_ok"] = int(parts[0] in (p["first"], *[n for n, full in NICKNAMES.items() if full == p["first"]]))
        f["initial_ok"] = int(parts[0][:1] == p["first"][0])
        f["last_exact"] = int(parts[-1] == p["last"])
        f["last_ed1"] = int(ed1(parts[-1], p["last"]))
        f["name_match"] = int(f["first_ok"] and f["last_ed1"] and len(parts) > 1)
        team = A.person_team(k)
        f["ctx_team"] = int(team in ctx["teams"])
        f["ctx_channel"] = int(team is not None and ctx["channel_team"] == team)
        f["ctx_author_team"] = int(team is not None and ctx["author_team"] == team)
        f["ctx_service"] = int(any(A.svc_owner.get(x) in A.team_norms.get(team, set()) or (team and A.svc_owner.get(x) == A.teams[team]["slug"]) for x in ctx["services"]))
        f["ctx_coworker"] = int(any(A.person_team(o) == team for o in ctx["persons"] if o != k))
    elif m["type"] == "team":
        toks = set(ns.split())
        f["tok"] = max((len(toks & set(norm(a).split())) / len(toks | set(norm(a).split())) for a in al), default=0)
    elif m["type"] == "vendor":
        v = A.vendors[k]
        f["short_eq"] = int(re.split(r"[ .]", s)[0] == v["short"])
        f["full_eq"] = int(s in (v["name"], v["legal"]))
        f["domain_eq"] = int(s == v["domain"])
        f["ctx_category"] = int(v["category"] is not None and v["category"] in ctx["categories"])
        f["ctx_category_other"] = int(v["category"] is not None and bool(ctx["categories"]) and v["category"] not in ctx["categories"])
        f["second_word"] = int(len(s.split()) > 1 and s.split()[1] == v["name"].split()[1])
    return f


def mention_context(obj, ments, A):
    """What else the document says, for disambiguation: its teams, services, categories, the people named in full, the
    channel's team and the author's team. Only the document itself: a link never depends on a document the reader
    of this one may not see."""
    teams = set()
    for m in ments:
        if m["type"] == "team":
            n = norm(m["text"])
            teams |= {k for k, ns in A.team_norms.items() if n in ns}
    ch = re.search(r"#team-([a-z-]+)", obj["container"])
    chteam = next((k for k, ns in A.team_norms.items() if ch and norm(ch[1]) in ns), None)
    author = A.by_email.get(obj.get("author") or "")
    return {"teams": teams, "services": {norm(m["text"], "service") for m in ments if m["type"] == "service"},
            "categories": {m.get("category") for m in ments if m["type"] == "decision"} | ({re.search(r"#vendor-eval-([a-z]+)", obj["container"])[1]} if "#vendor-eval-" in obj["container"] else set()) | ({category_of(obj["title"])} - {None}),
            "persons": {A.by_email.get(m["text"]) or A.by_handle.get(m["text"].lstrip("@")) or next(iter(A.by_last.get(m["text"].split()[-1], [])), None)
                        for m in ments if m["type"] == "person" and (len(m["text"].split()) > 1 or "@" in m["text"])} - {None},
            "channel_team": chteam, "author_team": A.person_team(author) if author else None}


def train_linker(objs, det, A, anchor_gold):
    """Logistic pair scorer on annotated mentions x blocked candidates (reads the mention in its context and the candidate's
    profile together, which is what a cross-encoder does with text)."""
    X, y = [], []
    for o in objs:
        ments = annotate_categories(det(o["body"]), det)
        ctx = mention_context(o, ments, A)
        for m in ments:
            if m["type"] not in ("person", "team", "vendor"):
                continue
            gk = gold_key(m, o)
            cands = A.candidates(m)
            for k in cands:
                X.append(link_features(m, k, cands, ctx, A))
                y.append(int(anchor_gold.get(k) == gk))
    v = DictVectorizer(sparse=False)
    clf = LogisticRegression(C=1.0, max_iter=5000).fit(v.fit_transform(X), y)
    return {"vec": v, "clf": clf, "pairs": len(y), "positives": int(sum(y))}


def link(m, ctx, A, linker):
    """-> (entity key or None for an abstention, score, method)."""
    t = m["type"]
    if t == "decision":
        return (f"decision:{m['category']}", 1.0, "taxonomy") if m.get("category") else (None, 0.0, "unknown-category")
    if t == "incident":
        return f"incident:{m['text']}", 1.0, "ticket-id"
    if t == "service":
        slug = norm(m["text"], "service")
        return f"service:{slug}", 1.0, "slug"
    cands = A.candidates(m)
    if t == "vendor" and ctx["categories"] and " " not in m["text"].strip():
        cands = [k for k in cands if A.vendors[k]["category"] is None or A.vendors[k]["category"] in ctx["categories"]]
    if cands:
        X = linker["vec"].transform([link_features(m, k, cands, ctx, A) for k in cands])
        p = linker["clf"].predict_proba(X)[:, 1]
        order = np.argsort(-p)
        best = float(p[order[0]])
        second = float(p[order[1]]) if len(order) > 1 else 0.0
        if best >= LINK_MIN and best - second >= LINK_MARGIN:
            return cands[order[0]], round(best, 3), "linker"
        if best >= LINK_MIN:
            return None, round(best, 3), "ambiguous"
        if t == "person":              # everyone is in the HR directory: a weak match is left unresolved, not made a new person
            return None, round(best, 3), "unresolved"
    return nil_key(m), 0.0, "nil"


def record_anchor(o):
    """A structured record's own identity lines refer to the record's entity: (key, end of those lines) or None."""
    f = fields(o["body"])
    lines = o["body"].split("\n")
    if o["kind"] == "person_record":
        return "person:" + f["email"][0].split("@")[0], len("\n".join(lines[:3]))
    if o["kind"] == "org_unit":
        return "team:" + f["slug"][0], len("\n".join(l for l in lines if not l.startswith("Lead:")))
    if o["kind"] in ("account", "contract"):
        legal = (f.get("account") or f.get("contract"))[0]
        return "vendor:" + re.sub(r"\s+(Inc\.|Ltd|Labs|GmbH)$", "", legal).lower().replace(" ", "-"), len(lines[0]) + (len(lines[1]) + 1 if o["kind"] == "account" else 0)
    return None


def consolidate(mentions):
    """NIL clusters of the same type whose names nest ("support tools" inside "customer support tools") are one entity."""
    count = collections.Counter(m["entity"] for m in mentions if m["entity"] and "~" in m["entity"])
    keys = sorted(count, key=lambda k: (-len(k), k))
    to = {}
    for k in keys:
        typ, name = k.split("~", 1)
        toks = set(name.split())
        if len(toks) < 2:
            continue
        for big in keys:
            if big != k and big.startswith(typ + "~") and big not in to and toks < set(big.split("~", 1)[1].split()):
                to[k] = big
                break
    for m in mentions:
        if m["entity"] in to:
            m["entity"] = to[m["entity"]]
            m["method"] = "nil-consolidated"
    return to


def nil_key(m):
    t, s = m["type"], m["text"]
    if t == "vendor":
        return "vendor~" + re.split(r"[ .]", s)[0].lower()
    return f"{t}~{norm(s)}"


# --- the pipeline ---------------------------------------------------------------------------------------------------------
def process(objs, det, models, A, linker):
    """Source objects -> chunks, mentions (linked) and assertions, all keyed by natural ids:
    chunk '<object id>#<n>', mention '<chunk id>@<start>', assertion '<chunk id>!<n>'."""
    chunks, mentions, assertions = [], [], []
    for o in objs:
        ments = annotate_categories(det(o["body"]), det)
        ctx = mention_context(o, ments, A)
        spans = chunk(o)
        cid = lambda pos: f"{o['id']}#{next((i for i, (a, b) in enumerate(spans) if a <= pos < b + 1), len(spans) - 1)}"   # noqa: E731
        for i, (a, b) in enumerate(spans):
            chunks.append({"id": f"{o['id']}#{i}", "object_id": o["id"], "ord": i, "start": a, "end": b, "text": o["body"][a:b]})
        own = record_anchor(o)
        for m in ments:
            key, score, method = link(m, ctx, A, linker)
            if own and m["start"] < own[1] and m["type"] == own[0].split(":")[0]:
                key, score, method = own[0], 1.0, "record"
            m.update({"id": f"{cid(m['start'])}@{m['start']}", "chunk_id": cid(m["start"]), "object_id": o["id"], "entity": key, "score": score, "method": method})
            mentions.append({k: m[k] for k in ("id", "chunk_id", "object_id", "start", "end", "text", "type", "entity", "score", "method")})
        found = extract(o, ments, det, models) + (ticket_structured(o, ments) if o["kind"] == "ticket" else [])
        kind = o["kind"]
        for j, x in enumerate(found):
            a, b, frm = x["a"], x.get("b"), x.get("frm")
            ent = lambda m: (m.get("key") if m.get("context") else m.get("entity")) if m else None    # noqa: E731
            if ent(a) is None or (b is not None and ent(b) is None):
                continue
            assertions.append({"id": f"{cid(x['sent'][0])}!{j}", "chunk_id": cid(x["sent"][0]), "object_id": o["id"], "pred": x["pred"], "subj": ent(a), "obj": ent(b),
                               "value": x.get("value"), "frm": ent(frm), "effective": x.get("effective"), "day": o["observed_day"], "sent": list(x["sent"]),
                               "confidence": x["confidence"], "method": x["method"], "source_kind": "transition" if x["pred"] == "HANDOVER" else kind,
                               "subj_mention": a.get("id") if a and not a.get("context") else None, "obj_mention": b.get("id") if b else None})
    moved = consolidate(mentions)
    for a in assertions:
        for k in ("subj", "obj", "frm"):
            a[k] = moved.get(a[k], a[k])
    return chunks, mentions, assertions


def entities_from(mentions, assertions, A):
    """Entity rows: one per anchor or NIL key that anything refers to, with a global display name."""
    seen = collections.defaultdict(collections.Counter)
    for m in mentions:
        if m["entity"]:
            seen[m["entity"]][m["text"]] += 1
    for a in assertions:
        for k in (a["subj"], a["obj"], a["frm"]):
            if k:
                seen[k]
    out = {}
    for k, c in seen.items():
        typ = re.split(r"[:~]", k)[0]
        anchor = k in A.p or k in A.teams or k in A.vendors or (typ == "service" and k in A.g["services"])
        name = (A.aliases(k) or [None])[0] if anchor and typ != "service" else (k.split(":", 1)[1] if typ in ("service", "incident") else
                                                                                 CATEGORY_LABEL.get(k.split(":", 1)[1], k) if typ == "decision" else
                                                                                 c.most_common(1)[0][0] if c else k)
        if typ == "vendor" and k in A.vendors:
            name = A.vendors[k]["name"]
        out[k] = {"id": k, "key": k, "type": typ, "name": name, "anchor": bool(anchor)}
    return out


def merge_suggestions(assertions):
    """Renames stated in the corpus become merge proposals: a person approves them, the system never merges on its own."""
    out = {}
    for a in assertions:
        if a["pred"] == "RENAMED" and a["subj"] != a["obj"]:
            out.setdefault((a["subj"], a["obj"]), []).append(a["id"])
    return [{"merge": s, "keep": o, "evidence": ev, "reason": "the corpus states a rename"} for (s, o), ev in out.items()]


# --- temporal reconciliation ---------------------------------------------------------------------------------------------
def reliability(a):
    return SOURCE_RELIABILITY.get(a["source_kind"], 0.7) * (a["confidence"] if a["method"] != "structured" else 1.0)


SWITCH_COST = 1.0        # nats, tuned on the demo corpus only: a catalog revision (log .95/.05 = 2.9), a ticket (2.4) or a chat line (1.1)
                         # can move the owner; a stale service page (0.6) cannot


def reconcile(asserts, clock, switch_cost=SWITCH_COST):
    """A service's owner over time from dated assertions: Viterbi over days with one state per candidate owner.
    Emissions: each state assertion on its day (P(says o | owner s) = r if s == o, else (1 - r)/(K - 1), r its source's
    reliability). Changing owner costs a constant penalty; a stated handover makes the switch to the new owner free on
    its effective day and is evidence for the old owner the day before. Returns segments [{owner, start, end, support, against}] with end exclusive (None = now)."""
    states = sorted({a["subj"] for a in asserts} | {a["frm"] for a in asserts if a["frm"]})
    if not states:
        return []
    K = len(states)
    idx = {s: i for i, s in enumerate(states)}
    obs = collections.defaultdict(list)
    trans = {}
    for a in asserts:
        r = reliability(a)
        if a["pred"] == "HANDOVER" and a["effective"] is not None:
            d = a["effective"]
            trans[d] = (idx[a["subj"]], r)
            obs[d].append((idx[a["subj"]], r))
            if a["frm"]:
                obs[d - 1].append((idx[a["frm"]], r))
        else:
            obs[a["day"]].append((idx[a["subj"]], r))
    lo = min(obs)
    hi = max(clock, max(obs))
    if K == 1:
        return [{"owner": states[0], "start": lo, "end": None, "support": [a["id"] for a in asserts], "against": []}]
    stay, move = 0.0, -switch_cost
    score = np.zeros(K)
    back = []
    for d in range(lo, hi + 1):
        if d > lo:
            T = np.full((K, K), move)
            np.fill_diagonal(T, stay + 1e-9)          # on a tie, stay: the owner changes on the first evidence of the new one
            if d in trans:                    # a stated handover: moving to the new owner today is free, staying put costs
                j, r = trans[d]
                T[:, :] = move - math.log(r / (1 - r))
                T[:, j] = 0.0
            cand = score[:, None] + T
            back.append(cand.argmax(0))
            score = cand.max(0)
        for i, r in obs.get(d, ()):
            em = np.full(K, math.log((1 - r) / (K - 1)))
            em[i] = math.log(r)
            score = score + em
    path = [int(score.argmax())]
    for b in reversed(back):
        path.append(int(b[path[-1]]))
    path.reverse()
    segs = []
    for d, s in zip(range(lo, hi + 1), path):
        if not segs or segs[-1]["owner"] != states[s]:
            if segs:
                segs[-1]["end"] = d
            segs.append({"owner": states[s], "start": d, "end": None, "support": [], "against": []})
    for a in asserts:
        d = a["effective"] if a["pred"] == "HANDOVER" and a["effective"] is not None else a["day"]
        seg = next((s for s in segs if s["start"] <= d and (s["end"] is None or d < s["end"])), segs[-1])
        (seg["support"] if seg["owner"] == a["subj"] else seg["against"]).append(a["id"])
        if a["pred"] == "HANDOVER" and a["frm"]:
            prev = next((s for s in segs if s["end"] == seg["start"]), None)
            if prev and prev["owner"] == a["frm"]:
                prev["support"].append(a["id"])
    return segs


def owner_baseline(asserts, day, rule):
    """'latest' : whoever the latest assertion on or before the day names; 'majority': most named in the 180 days before."""
    pts = []
    for a in asserts:
        if a["pred"] == "HANDOVER" and a["effective"] is not None:
            pts.append((a["day"], a["subj"]))
        else:
            pts.append((a["day"], a["subj"]))
    pts = [p for p in pts if p[0] <= day]
    if not pts:
        return None
    if rule == "latest":
        return max(pts)[1]
    c = collections.Counter(o for d, o in pts if d > day - 180) or collections.Counter(o for _, o in pts)
    return c.most_common(1)[0][0]


def fact_id(subj, pred, obj, value, valid_from=None):
    return str(uuid.uuid5(FACT_NS, f"{subj}|{pred}|{obj}|{value}|{valid_from}"))


def derive_facts(asserts, clock):
    """Reconciled facts from assertions: ownership as time segments per service, everything else one fact per distinct
    (subject, predicate, object, value), with its evidence."""
    facts = []
    by_svc = collections.defaultdict(list)
    rest = collections.defaultdict(list)
    for a in asserts:
        if a["pred"] in ("OWNS", "HANDOVER"):
            by_svc[a["obj"]].append(a)
        elif a["pred"] != "RENAMED":
            rest[(a["subj"], a["pred"], a["obj"], (a["value"] or "").lower().rstrip("."))].append(a)
        elif a["subj"] != a["obj"]:
            rest[(a["subj"], a["pred"], a["obj"], "")].append(a)
    for svc, xs in by_svc.items():
        for s in reconcile(xs, clock):
            if not s["support"]:
                continue
            conf = round(sum(reliability(a) for a in xs if a["id"] in s["support"]) / max(1e-9, sum(reliability(a) for a in xs if a["id"] in s["support"] + s["against"])), 3)
            facts.append({"id": fact_id(s["owner"], "OWNS", svc, None, s["start"]), "pred": "OWNS", "subj": s["owner"], "obj": svc, "value": None,
                          "valid_from": s["start"], "valid_to": s["end"], "evidence": s["support"], "against": s["against"], "confidence": conf,
                          "method": "viterbi-reconciliation"})
    for (subj, pred, obj, _), xs in rest.items():
        conf = 1 - np.prod([1 - min(0.999, a["confidence"]) for a in xs])
        value = xs[0]["value"]
        facts.append({"id": fact_id(subj, pred, obj, (value or "").lower().rstrip(".")), "pred": pred, "subj": subj, "obj": obj, "value": value,
                      "valid_from": min(a["day"] if a["effective"] is None else a["effective"] for a in xs), "valid_to": None,
                      "evidence": [a["id"] for a in xs], "against": [], "confidence": round(float(conf), 3), "method": "aggregate"})
    return facts


# --- the index and per-principal views ----------------------------------------------------------------------------------
HASH = HashingVectorizer(n_features=2 ** 15, analyzer=analyze, alternate_sign=False, norm=None)
K1, B = 1.2, 0.75


def derived_aliases(text, typ):
    """A visible name and the shorter forms people use for it ("Ember Observability Inc." -> "Ember Observability",
    "Ember"; "ledger-api" -> "Ledger API", "svc-ledger-api"). Derived from what the reader can already see, so they reveal
    nothing new."""
    out = [text]
    if typ == "vendor":
        name = re.sub(r"\s+(Inc\.|Ltd|Labs|GmbH)$", "", text)
        out += [name] + ([name.split()[0]] if " " in name and len(name.split()[0]) >= 4 else [])
    elif typ == "service":
        slug = norm(text, "service")
        out += [slug, "svc-" + slug, " ".join({"api": "API", "bff": "BFF"}.get(w, w.capitalize()) for w in slug.split("-"))]
    return list(dict.fromkeys(out))


class Index:
    """Everything the connectors and the pipeline produced, in one tenant. Never queried directly: every read goes
    through a View, which sees only the rows of the containers its principal may read."""

    def __init__(self, objects, chunks, mentions, assertions, entities, clock):
        self.clock = clock
        self.objects = {o["id"]: o for o in objects}
        self.chunks = sorted(chunks, key=lambda c: (c["object_id"], c["ord"]))
        self.pos = {c["id"]: i for i, c in enumerate(self.chunks)}
        self.container = np.array([self.objects[c["object_id"]]["container"] for c in self.chunks])
        self.X = HASH.transform([c["text"] for c in self.chunks]).tocsr().astype(np.float64) if self.chunks else sparse.csr_matrix((0, 2 ** 15))
        self.Xc = self.X.tocsc()
        self.dl = np.asarray(self.X.sum(1)).ravel()
        self.mentions = mentions
        self.m_by_chunk = collections.defaultdict(list)
        for m in mentions:
            self.m_by_chunk[m["chunk_id"]].append(m)
        self.assertions = {a["id"]: a for a in assertions}
        self.entities = entities
        self.type = {eid: e["type"] for eid, e in entities.items()}
        self.by_key = {e["key"]: eid for eid, e in entities.items()}
        self.views = {}

    def view(self, containers):
        key = view_key(containers)
        if key not in self.views:
            self.views[key] = View(self, set(containers), key)
        return self.views[key]


def view_key(containers):
    return hashlib.sha1("|".join(sorted(containers)).encode()).hexdigest()[:12]


class View:
    def __init__(self, ix, containers, key):
        self.ix, self.containers, self.key = ix, containers, key
        self.mask = np.isin(ix.container, list(containers)) if len(ix.chunks) else np.zeros(0, bool)
        self.rows = np.nonzero(self.mask)[0]
        self.chunk_ids = {ix.chunks[i]["id"] for i in self.rows}
        self.objects = {ix.chunks[i]["object_id"] for i in self.rows}
        self.N = len(self.rows)
        self.avgdl = float(ix.dl[self.rows].mean()) if self.N else 1.0
        self._lsa = self._facts = self._aliases = self._alias_rx = None

    # -- what this view may see
    def visible_assertions(self):
        return [a for a in self.ix.assertions.values() if a["chunk_id"] in self.chunk_ids]

    @property
    def facts(self):
        if self._facts is None:
            fs = derive_facts(self.visible_assertions(), self.ix.clock)
            self._facts = {f["id"]: f for f in fs}
            self.by_entity = collections.defaultdict(list)
            for f in fs:
                for k in (f["subj"], f["obj"]):
                    if k:
                        self.by_entity[k].append(f)
        return self._facts

    @property
    def aliases(self):
        """alias -> entity ids, and entity -> alias counts, from mentions in readable chunks only."""
        if self._aliases is None:
            by_alias, by_entity = collections.defaultdict(set), collections.defaultdict(collections.Counter)
            for cid in self.chunk_ids:
                for m in self.ix.m_by_chunk.get(cid, ()):
                    if m["entity"]:
                        by_entity[m["entity"]][m["text"]] += 1
                        for a in derived_aliases(m["text"], m["type"]):
                            by_alias[a.lower()].add(m["entity"])
            self._aliases = (by_alias, by_entity)
        return self._aliases

    def visible_entity(self, eid):
        return eid in self.aliases[1] or bool(self.facts and self.by_entity.get(eid))

    def name(self, eid):
        e = self.ix.entities.get(eid)
        counts = self.aliases[1].get(eid)
        if e and e["type"] in ("service", "incident", "decision"):
            return e["name"]
        if e and e["anchor"] and counts and any(e["name"] in derived_aliases(a, e["type"]) for a in counts):
            return e["name"]
        if counts:
            return counts.most_common(1)[0][0]
        return e["name"] if e and e["type"] == "decision" else eid

    # -- retrieval
    def bm25(self, query, k=50):
        q = HASH.transform([query]).tocsr()
        scores = np.zeros(len(self.ix.chunks))
        for j in set(q.indices):
            col = self.ix.Xc[:, j]
            rows, tf = col.indices, col.data
            keep = self.mask[rows]
            rows, tf = rows[keep], tf[keep]
            df = len(rows)
            if not df:
                continue
            idf = math.log(1 + (self.N - df + 0.5) / (df + 0.5))
            scores[rows] += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * self.ix.dl[rows] / self.avgdl))
        return self._top(scores, k)

    def _top(self, scores, k):
        cand = [i for i in self.rows if scores[i] > 0]
        cand.sort(key=lambda i: (-scores[i], i))
        return [(self.ix.chunks[i]["id"], float(scores[i])) for i in cand[:k]]

    def lsa(self):
        """TF-IDF and a 96-dimension SVD fitted on this view's chunks only: the basis carries no trace of what the view
        cannot read."""
        if self._lsa is None:
            X = self.ix.X[self.rows]
            df = np.asarray((X > 0).sum(0)).ravel()
            cols = np.nonzero(df)[0]
            idf = np.log((1 + self.N) / (1 + df[cols])) + 1
            T = X[:, cols].multiply(idf).tocsr()
            T = sparse.diags(1 / np.maximum(1e-9, np.sqrt(T.multiply(T).sum(1).A.ravel()))) @ T
            n = max(2, min(96, self.N - 1, len(cols) - 1))
            svd = TruncatedSVD(n_components=n, random_state=0, algorithm="randomized", n_iter=5).fit(T)
            V = svd.transform(T)
            V /= np.maximum(1e-9, np.linalg.norm(V, axis=1, keepdims=True))
            self._lsa = (cols, idf, svd.components_, V.astype(np.float32).astype(np.float64))    # float32 so a stored copy is identical
        return self._lsa

    def vector(self, query, k=50):
        if self.N < 3:
            return []
        cols, idf, comps, V = self.lsa()
        q = HASH.transform([query]).tocsc()[:, cols].multiply(idf)
        qv = np.asarray(sparse.csr_matrix(q) @ comps.T).ravel()
        nq = np.linalg.norm(qv)
        if nq == 0:
            return []
        s = V @ (qv / nq)
        order = sorted(range(len(s)), key=lambda i: (-s[i], self.rows[i]))[:k]
        return [(self.ix.chunks[self.rows[i]]["id"], float(s[i])) for i in order if s[i] > 0]

    def link_query(self, text):
        """Entities named in a query, by the aliases this view knows (longest match first)."""
        by_alias = self.aliases[0]
        if self._alias_rx is None:
            alts = sorted((a for a in by_alias if len(a) >= 3), key=len, reverse=True)
            self._alias_rx = re.compile(r"(?<![\w-])(" + "|".join(re.escape(a) for a in alts) + r")(?![\w-])") if alts else False
        low = text.lower()
        found = []
        for m in (self._alias_rx.finditer(low) if self._alias_rx else ()):
            for e in sorted(by_alias[m[1]]):
                found.append({"entity": e, "alias": text[m.start():m.end()], "start": m.start()})
        for k, terms in CATEGORY_TERMS.items():
            did = self.ix.by_key.get(f"decision:{k}")
            if did and any(re.search(r"(?<![\w-])" + re.escape(t.lower()) + r"(?![\w-])", low) for t in terms) and self.visible_entity(did):
                found.append({"entity": did, "alias": CATEGORY_LABEL[k], "start": -1})
        return found

    def graph_chunks(self, query, k=50):
        """Chunks that are evidence for facts about the entities the query names, one hop out (a vendor's decision, a
        decision's vendors), weighted toward what the question asks."""
        low = query.lower()
        linked = {f["entity"] for f in self.link_query(query)}
        if not linked:
            return []
        self.facts
        hop = set(linked)
        for e in linked:
            for f in self.by_entity.get(e, ()):
                if f["pred"] in ("SELECTED", "CONSIDERED", "REJECTED"):
                    hop |= {f["subj"], f["obj"]}
        want = {"OWNS": 2 if re.search(r"own|responsib|maintain|team", low) else 0.5, "REASON": 2 if re.search(r"why|reason", low) else 0.5,
                "SELECTED": 2 if re.search(r"why|select|chose|pick|vendor", low) else 0.5, "REJECTED": 1.5 if re.search(r"why|alternativ|reject|consider", low) else 0.3,
                "CONSIDERED": 1.5 if re.search(r"alternativ|consider|compet", low) else 0.3, "DECIDED_BY": 2 if re.search(r"who decid|decision owner|signed", low) else 0.3,
                "CONTRACT_VALUE": 2 if re.search(r"cost|price|pay|contract|worth|much", low) else 0.2}
        score = collections.Counter()
        for e in hop:
            for f in self.by_entity.get(e, ()):
                w = want.get(f["pred"], 0.3) * (1.0 if e in linked or f["subj"] in linked or f["obj"] in linked else 0.5)
                if f["pred"] == "OWNS" and f["valid_to"] is None:
                    w *= 1.5
                for aid in f["evidence"]:
                    score[self.ix.assertions[aid]["chunk_id"]] += w
        ranked = sorted(score.items(), key=lambda x: (-x[1], -self.ix.objects[self.ix.chunks[self.ix.pos[x[0]]]["object_id"]]["observed_day"], x[0]))
        return ranked[:k]

    def search(self, query, k=10, mode="hybrid"):
        """mode: 'hybrid' (BM25 and graph expansion, the default), 'hybrid+lsa' (all three), 'bm25', 'vector', 'bm25+vector',
        'graph'. LSA is out of the default because on held-out corpora it lowered recall (docs/evaluation.md)."""
        lists = {}
        if mode in ("hybrid", "hybrid+lsa", "bm25", "bm25+vector"):
            lists["bm25"] = self.bm25(query)
        if mode in ("hybrid+lsa", "vector", "bm25+vector"):
            lists["vector"] = self.vector(query)
        if mode in ("hybrid", "hybrid+lsa", "graph"):
            lists["graph"] = self.graph_chunks(query)
        fused = collections.Counter()
        ranks = collections.defaultdict(dict)
        for name, lst in lists.items():
            for r, (cid, _) in enumerate(lst):
                fused[cid] += 1 / (60 + r + 1)
                ranks[cid][name] = r + 1
        order = sorted(fused, key=lambda c: (-fused[c], self.ix.pos[c]))[:k]
        return [{"chunk_id": c, "object_id": self.ix.chunks[self.ix.pos[c]]["object_id"], "score": round(fused[c], 6), "ranks": ranks[c],
                 "text": self.ix.chunks[self.ix.pos[c]]["text"]} for c in order]

    # -- graph, entities, provenance
    def timeline(self, svc):
        self.facts
        return sorted([f for f in self.by_entity.get(svc, ()) if f["pred"] == "OWNS" and f["obj"] == svc], key=lambda f: f["valid_from"])

    def entity(self, eid):
        if not self.visible_entity(eid):
            return None
        self.facts
        e = self.ix.entities.get(eid, {"type": None, "anchor": False})
        counts = self.aliases[1].get(eid, collections.Counter())
        facts = sorted(self.by_entity.get(eid, ()), key=lambda f: (f["pred"], f["valid_from"] or 0))
        return {"id": eid, "type": e["type"], "name": self.name(eid), "aliases": [{"alias": a, "mentions": n} for a, n in counts.most_common()],
                "mentions": sum(counts.values()), "facts": [self.fact_brief(f) for f in facts]}

    def fact_brief(self, f):
        return {"id": f["id"], "predicate": f["pred"], "subject": {"id": f["subj"], "name": self.name(f["subj"])},
                "object": {"id": f["obj"], "name": self.name(f["obj"])} if f["obj"] else None, "value": f["value"],
                "valid_from": date_str(f["valid_from"]) if f["valid_from"] is not None else None, "valid_to": date_str(f["valid_to"]) if f["valid_to"] is not None else None,
                "confidence": f["confidence"], "evidence": len(f["evidence"]), "contradicting": len(f["against"])}

    def graph(self, start, depth=1, predicates=None, as_of=None):
        if not self.visible_entity(start):
            return None
        self.facts
        nodes, edges, frontier = {start}, {}, {start}
        for _ in range(depth):
            nxt = set()
            for e in frontier:
                for f in self.by_entity.get(e, ()):
                    if predicates and f["pred"] not in predicates:
                        continue
                    if as_of is not None and f["pred"] == "OWNS" and not (f["valid_from"] <= as_of and (f["valid_to"] is None or as_of < f["valid_to"])):
                        continue
                    edges[f["id"]] = f
                    for k in (f["subj"], f["obj"]):
                        if k and k not in nodes:
                            nodes.add(k)
                            nxt.add(k)
            frontier = nxt
        return {"nodes": [{"id": n, "type": self.ix.type.get(n), "name": self.name(n)} for n in sorted(nodes)],
                "edges": [self.fact_brief(f) for f in sorted(edges.values(), key=lambda f: (f["pred"], f["subj"], f["obj"] or "", f["valid_from"] or 0))]}

    def provenance(self, fid):
        f = self.facts.get(fid)
        if not f:
            return None

        def ev(aid):
            a = self.ix.assertions[aid]
            c = self.ix.chunks[self.ix.pos[a["chunk_id"]]]
            o = self.ix.objects[a["object_id"]]
            ms = [m for m in self.ix.m_by_chunk.get(a["chunk_id"], ()) if m["id"] in (a["subj_mention"], a["obj_mention"])]
            return {"assertion_id": aid, "sentence": o["body"][a["sent"][0]:a["sent"][1]], "asserted_on": date_str(a["day"]),
                    "effective": date_str(a["effective"]) if a["effective"] is not None else None, "extractor": a["method"], "confidence": a["confidence"],
                    "reliability": round(reliability(a), 3), "chunk": {"id": c["id"], "text": c["text"]},
                    "source": {"id": o["id"], "system": o["system"], "container": o["container"], "external_id": o["external_id"], "title": o["title"],
                               "observed_on": date_str(o["observed_day"]), "author": o.get("author")},
                    "resolution": [{"mention": m["text"], "entity": m["entity"], "entity_name": self.name(m["entity"]), "score": m["score"], "method": m["method"]} for m in ms]}
        return {"fact": self.fact_brief(f), "method": f["method"], "evidence": [ev(a) for a in f["evidence"]], "contradicting": [ev(a) for a in f["against"]]}

    # -- answers
    def answer(self, question):
        return compose(self, question)


def cite(view, fact, n=3):
    """The chunks behind a fact, best first: stated transitions, then the most reliable and most recent."""
    ass = [view.ix.assertions[a] for a in fact["evidence"]]
    ass.sort(key=lambda a: (-(a["pred"] == "HANDOVER"), -reliability(a), -a["day"], a["chunk_id"]))
    out = []
    for a in ass:
        if a["chunk_id"] not in out:
            out.append(a["chunk_id"])
    return out[:n]


def compose(v, q):
    """Answer a question from the view's facts only. Each sentence carries the facts it states and the chunks it cites;
    when nothing supports an answer, it says so instead of guessing."""
    clock = v.ix.clock
    low = q.lower()
    linked = v.link_query(q)
    ents = [x["entity"] for x in linked]
    sents = []

    def say(text, facts, cites=None):
        cs = []
        for f in facts:
            for c in (cites or cite(v, f)):
                if c not in cs:
                    cs.append(c)
        sents.append({"text": text, "facts": [f["id"] for f in facts], "citations": cs} | ({"said": [f["assertion"] for f in facts if "assertion" in f]} if any("assertion" in f for f in facts) else {}))

    def abstain(text):
        sents.append({"text": text, "facts": [], "citations": [], "abstain": True})
    intent = None
    T = v.ix.type
    svc = next((e for e in ents if T.get(e) == "service"), None)
    vendor = next((e for e in ents if T.get(e) == "vendor"), None)
    decision = next((e for e in ents if T.get(e) == "decision"), None)
    team = next((e for e in ents if T.get(e) == "team"), None)
    v.facts
    if svc and re.search(r"\bown|owner|responsib|maintain|on.?call|who runs|which team", low):
        intent = "owner"
        tl = v.timeline(svc)
        as_of = as_of_in(q, clock)
        if not tl:
            abstain(f"I found no evidence of who owns {v.name(svc)}.")
        else:
            day = clock if as_of is None else as_of
            cur = next((f for f in tl if f["valid_from"] <= day and (f["valid_to"] is None or day < f["valid_to"])), None)
            if cur is None:
                abstain(f"I found no evidence of who owned {v.name(svc)} on {date_str(day)}.")
            else:
                if as_of is None:
                    say(f"{v.name(svc)} is owned by {v.name(cur['subj'])} (since {date_str(cur['valid_from'])}).", [cur])
                else:
                    say(f"On {date_str(day)}, {v.name(svc)} was owned by {v.name(cur['subj'])}.", [cur])
                prev = [f for f in tl if f["valid_to"] is not None and f["valid_to"] <= cur["valid_from"]]
                if prev:
                    p = prev[-1]
                    say(f"Before {date_str(cur['valid_from'])} it was owned by {v.name(p['subj'])}.", [p])
                lead = next((f for f in v.by_entity.get(cur["subj"], ()) if f["pred"] == "LEADS" and f["obj"] == cur["subj"]), None)
                if lead:
                    say(f"{v.name(cur['subj'])} is led by {v.name(lead['subj'])}.", [lead])
                stale = [v.ix.assertions[a] for a in cur["against"] if v.ix.assertions[a]["pred"] == "OWNS"]
                if stale and as_of is None:
                    s = max(stale, key=lambda a: a["day"])
                    o = v.ix.objects[s["object_id"]]
                    old = Fact(s)
                    say(f"{len(stale)} source{'s' if len(stale) > 1 else ''} still name{'' if len(stale) > 1 else 's'} another owner; the latest is \"{o['title']}\" "
                        f"({date_str(s['day'])}), which says {v.name(s['subj'])}.", [old], cites=[s["chunk_id"]])
                incs = sorted((f for f in v.by_entity.get(svc, ()) if f["pred"] == "AFFECTS"), key=lambda f: -f["valid_from"])
                if incs and as_of is None:
                    f = incs[0]
                    say(f"The latest incident on {v.name(svc)} is {v.name(f['subj'])}, last updated {date_str(f['valid_from'])}.", [f])
    elif (vendor or decision) and re.search(r"how much|cost|price|pay|worth|contract value", low):
        intent = "contract"
        target = vendor or next((f["obj"] for f in v.by_entity.get(decision, ()) if f["pred"] == "SELECTED"), None)
        fs = [f for f in v.by_entity.get(target, ()) if f["pred"] == "CONTRACT_VALUE"] if target else []
        if fs:
            f = max(fs, key=lambda f: len(f["evidence"]))
            say(f"The {v.name(target)} contract is worth {f['value']} a year.", [f])
        else:
            abstain(f"I found no evidence of what {next((x['alias'] for x in linked), 'that')} costs.")
    elif vendor or decision:
        intent = "decision"
        sel = [f for f in v.by_entity.get(vendor or decision, ()) if f["pred"] == "SELECTED" and (not vendor or f["obj"] == vendor)]
        if not sel and vendor:
            con = [f for f in v.by_entity.get(vendor, ()) if f["pred"] in ("CONSIDERED", "REJECTED")]
            if con:
                d = con[0]["subj"]
                rej = [f for f in con if f["pred"] == "REJECTED"]
                if rej:
                    for f in rej:
                        say(f"{v.name(vendor)} was considered for the {v.name(d)} and rejected because {f['value']}.", [f])
                else:
                    say(f"{v.name(vendor)} was considered for the {v.name(d)}.", [con[0]])
                sel = [f for f in v.by_entity.get(d, ()) if f["pred"] == "SELECTED"]
                if sel:
                    f = max(sel, key=lambda f: len(f["evidence"]))
                    say(f"{v.name(f['obj'])} was selected instead.", [f])
            else:
                abstain(f"I found no evidence that {next(x['alias'] for x in linked if x['entity'] == vendor)} was selected for anything.")
        elif not sel:
            abstain(f"I found no evidence of a decision on the {v.name(decision)}.")
        else:
            f = max(sel, key=lambda f: (len(f["evidence"]), f["obj"]))
            d, w = f["subj"], f["obj"]
            say(f"{v.name(w)} was selected as the {v.name(d)} ({date_str(f['valid_from'])}).", [f])
            dfs = v.by_entity.get(d, ())
            reasons = sorted((x for x in dfs if x["pred"] == "REASON"), key=lambda x: (-len(x["evidence"]), x["value"]))
            if reasons:
                say("Reasons given: " + "; ".join(x["value"] for x in reasons[:3]) + ".", reasons[:3])
            by = [x for x in dfs if x["pred"] == "DECIDED_BY"]
            if by:
                say(f"The decision owner was {v.name(by[0]['obj'])}.", by[:1])
            alts = sorted({x["obj"] for x in dfs if x["pred"] in ("CONSIDERED", "REJECTED") and x["obj"] != w})
            if alts:
                cons = [x for x in dfs if x["pred"] == "CONSIDERED" and x["obj"] in alts]
                if cons:
                    say("Also considered: " + " and ".join(v.name(a) for a in alts if any(x["obj"] == a for x in cons)) + ".", cons)
                for a in alts:
                    rj = [x for x in dfs if x["pred"] == "REJECTED" and x["obj"] == a]
                    for x in sorted(rj, key=lambda x: (-len(x["evidence"]), x["value"] or ""))[:2]:
                        say(f"{v.name(a)} was rejected because {x['value']}.", [x])
    elif team and re.search(r"\blead|manag|head", low):
        intent = "lead"
        lead = [f for f in v.by_entity.get(team, ()) if f["pred"] == "LEADS" and f["obj"] == team]
        if lead:
            say(f"{v.name(team)} is led by {v.name(lead[0]['subj'])}.", lead[:1])
        else:
            abstain(f"I found no evidence of who leads {v.name(team)}.")
    asks_owner = re.search(r"\bwho (?:owns|owned|maintains|runs)\b|\bowner of\b|\bresponsible for\b", low)
    asks_vendor = re.search(r"\bwhy (?:was|did we|were)\b.*\b(?:select|chose|chosen|pick|go with)|\bhow much\b|\bcontract\b", low)
    if intent is None and (asks_owner or asks_vendor):
        intent = "owner" if asks_owner else "decision"           # asked about something the reader's sources do not name
        named = re.findall(r"(?<![\w-])[a-z0-9]+(?:-[a-z0-9]+)+(?![\w-])|\b[A-Z][\w.]+(?: [A-Z][\w.]+)*", q[1:])
        abstain(f"I found nothing about {named[0] if named else 'that'} in the sources you can read.")
    if intent is None:
        intent = "search"
        hits = v.search(q, k=3)
        for h in hits:
            o = v.ix.objects[h["object_id"]]
            best = max((h["text"][a:b] for a, b in sentences(h["text"])), key=lambda s: len(set(analyze(s)) & set(analyze(q))), default=h["text"])
            sents.append({"text": f"From \"{o['title']}\": \"{best.strip()}\"", "facts": [], "citations": [h["chunk_id"]], "quote": True})
        if not hits:
            abstain("I found nothing that answers this.")
    if not any(not s.get("abstain") for s in sents) and not sents:
        abstain("I found nothing that answers this.")
    cited = []
    for s in sents:
        for c in s["citations"]:
            if c not in cited:
                cited.append(c)
    return {"question": q, "intent": intent, "sentences": sents, "citations": cited, "entities": [{"id": e, "name": v.name(e), "alias": x["alias"]} for x in linked for e in [x["entity"]]],
            "abstained": all(s.get("abstain") for s in sents), "version": ANSWER_VERSION}


def Fact(a):
    """A one-assertion fact (for 'this source says X')."""
    return {"id": fact_id(a["subj"], "SAYS_" + a["pred"], a["obj"], a["id"]), "pred": a["pred"], "subj": a["subj"], "obj": a["obj"], "value": a["value"],
            "evidence": [a["id"]], "against": [], "valid_from": a["day"], "valid_to": None, "confidence": a["confidence"], "assertion": a["id"]}


def verify(v, ans):
    """Re-check an answer: every non-abstaining sentence cites at least one chunk this view may read, and every fact it
    states is backed by a cited chunk that names the fact's subject and object (or holds its value)."""
    out = []
    for s in ans["sentences"]:
        if s.get("abstain"):
            continue
        ok = bool(s["citations"]) and all(c in v.chunk_ids for c in s["citations"])
        if s.get("quote"):
            c = v.ix.chunks[v.ix.pos[s["citations"][0]]]["text"] if ok else ""
            ok = ok and s["text"].split(": \"", 1)[1][:-1] in c
        said = {Fact(v.ix.assertions[x])["id"]: Fact(v.ix.assertions[x]) for x in s.get("said", ()) if x in v.ix.assertions and v.ix.assertions[x]["chunk_id"] in v.chunk_ids}
        for fid in s["facts"]:
            f = v.facts.get(fid) or said.get(fid)
            if f is None:
                ok = False
                continue
            backed = False
            for aid in f["evidence"]:
                a = v.ix.assertions[aid]
                if a["chunk_id"] not in s["citations"]:
                    continue
                text = v.ix.objects[a["object_id"]]["body"]
                names = [m["text"] for m in v.ix.m_by_chunk.get(a["chunk_id"], ()) if m["entity"] in (f["subj"], f["obj"])]
                need = [k for k in (f["subj"], f["obj"]) if k and v.ix.type.get(k) != "decision"]
                has = all(any(m["entity"] == k and m["start"] >= a["sent"][0] - 400 for m in v.ix.m_by_chunk.get(a["chunk_id"], ())) for k in need)
                if f["value"]:
                    has = has and f["value"].lower().rstrip(".") in text.lower()
                backed = backed or (has and bool(names or not need))
            ok = ok and backed
        out.append(ok)
    return {"sentences": len(out), "supported": sum(out), "coverage": round(sum(out) / len(out), 4) if out else None}


# --- the security suite ---------------------------------------------------------------------------------------------------
def response_text(r):
    return json.dumps(r, sort_keys=True, default=str)


def security_suite(ix, users, full_containers, reduced_index=None, filter_off=False, max_users=None):
    """Probe every user's view for restricted content. users: [(name, containers)].
    A probe leaks when its response carries an object, chunk, fact or entity the user's view cannot see, or a literal
    (a contract value, a rejection reason, a codename, a name) that appears only in objects the user cannot read.
    filter_off=True runs the same probes against the unfiltered index, to show the suite would notice a leak.
    reduced_index(containers) -> Index built from the readable objects only: the non-interference check."""
    full = ix.view(full_containers)
    full.facts
    out = {"users": 0, "probes": 0, "leaks": 0, "by_channel": collections.Counter(), "leaks_by_channel": collections.Counter(),
           "non_interference_checked": 0, "non_interference_failed": 0, "examples": []}
    for name, conts in users[:max_users]:
        v = ix.view(full_containers if filter_off else conts)
        mine = ix.view(conts)
        hidden_chunks = {c["id"] for i, c in enumerate(ix.chunks) if not mine.mask[i]}
        if not hidden_chunks:
            continue
        out["users"] += 1
        hidden_objects = {ix.chunks[ix.pos[c]]["object_id"] for c in hidden_chunks} - mine.objects
        hidden_facts = set(full.facts) - set(mine.facts)
        hidden_entities = {e for e in full.aliases[1] if not mine.visible_entity(e)}
        readable = " ".join(ix.chunks[i]["text"].lower() for i in mine.rows)
        canaries = set()
        for fid in hidden_facts:
            f = full.facts[fid]
            if f["value"] and f["value"].lower() not in readable:
                canaries.add(f["value"].lower())
        for e in hidden_entities:
            for a in full.aliases[1][e]:
                if len(a) >= 4 and a.lower() not in readable:
                    canaries.add(a.lower())
        for cid in hidden_chunks:
            for m in re.findall(r"Project [A-Z][a-z]+|\$[0-9][0-9,]{3,}", ix.chunks[ix.pos[cid]]["text"]):
                if m.lower() not in readable:
                    canaries.add(m.lower())
        forbidden = hidden_chunks | hidden_objects | hidden_facts | hidden_entities
        probes = []
        for fid in sorted(hidden_facts)[:60]:
            probes.append(("provenance", fid, lambda fid=fid: v.provenance(fid)))
        for e in sorted(hidden_entities)[:40]:
            probes.append(("entity", e, lambda e=e: v.entity(e)))
            probes.append(("graph", e, lambda e=e: v.graph(e, depth=2)))
        for d in sorted({f["subj"] for f in full.facts.values() if f["pred"] in ("SELECTED", "CONSIDERED")}):
            if mine.visible_entity(d):
                probes.append(("graph", d, lambda d=d: v.graph(d, depth=2)))
        names = sorted({a for e in full.aliases[1] if ix.type.get(e) in ("vendor", "decision") for a in full.aliases[1][e]})[:60]
        for a in names:
            probes.append(("answers", a, lambda a=a: v.answer(f"Why was {a} selected?")))
            probes.append(("answers", a, lambda a=a: v.answer(f"How much does the {a} contract cost?")))
            probes.append(("search", a, lambda a=a: v.search(f"{a} contract price rejected because", k=10)))
        for c in sorted(canaries)[:60]:
            probes.append(("search", c, lambda c=c: v.search(c, k=10)))
            probes.append(("answers", c, lambda c=c: v.answer(f"What do we know about {c}?")))
        for o in sorted(hidden_objects)[:40]:
            probes.append(("search", ix.objects[o]["title"], lambda o=o: v.search(ix.objects[o]["title"], k=10)))
        for ch, asked, p in probes:
            r = p()
            if isinstance(r, dict):
                r = {k: x for k, x in r.items() if k != "question"}
            txt = response_text(r).lower()
            asked = asked.lower()
            leak = r is not None and (any(x.lower() in txt for x in forbidden) or any(c in txt and c not in asked for c in canaries))
            out["probes"] += 1
            out["by_channel"][ch] += 1
            if leak:
                out["leaks"] += 1
                out["leaks_by_channel"][ch] += 1
                if len(out["examples"]) < 5:
                    out["examples"].append({"user": name, "channel": ch, "response": txt[:300]})
        if reduced_index is not None and not filter_off:
            rix = reduced_index(conts)
            rv = rix.view(conts)
            qs = [f"Why was {a} selected?" for a in names[:15]] + [ix.objects[o]["title"] for o in sorted(mine.objects)[:15]] + sorted(canaries)[:10]
            for q in qs:
                for f in (lambda vv: [(h["chunk_id"], round(h["score"], 6)) for h in vv.search(q, k=10)],
                          lambda vv: [(h["chunk_id"], round(h["score"], 6)) for h in vv.search(q, k=10, mode="hybrid+lsa")],
                          lambda vv: [(s["text"], s["citations"]) for s in vv.answer(q)["sentences"]]):
                    out["non_interference_checked"] += 1
                    if f(mine) != f(rv):
                        out["non_interference_failed"] += 1
    out["leak_rate"] = round(out["leaks"] / out["probes"], 4) if out["probes"] else None
    out["by_channel"], out["leaks_by_channel"] = dict(out["by_channel"]), dict(out["leaks_by_channel"])
    return out


def anchor_labels(objs, records):
    """anchor key -> the annotation's identity for it, from the structured records."""
    out = {}
    for o in objs:
        ra = record_anchor(o) if o["structured"] else None
        if ra and o["external_id"] in records:
            out[ra[0]] = records[o["external_id"]]
    return out


def train(objs, annotated, records, holdout=0.0):
    """Gazetteer from the structured sources plus a discovery pass; the extractor and the linker trained on the annotated
    documents. With holdout > 0 a share of the annotated documents is kept back and both are scored on it (the model
    card); production models are then refit on all of them."""
    g = gazetteer([o for o in objs if o["structured"]])
    discover(objs, g)
    det, A = Detector(g), Anchors(g)
    labels = anchor_labels(objs, records)
    card = None
    if holdout:
        test = {o["id"] for o in annotated if int(hashlib.sha1(o["id"].encode()).hexdigest(), 16) % 100 < 100 * holdout}
        tr = [o for o in annotated if o["id"] not in test]
        te = [o for o in annotated if o["id"] in test]
        card = {"annotated_documents": len(annotated), "train_documents": len(tr), "test_documents": len(te),
                "extraction": extraction_scores(te, det, train_extractor(tr, det)),
                "linking": linking_scores(te, det, A, train_linker(tr, det, A, labels), labels)}
    return {"gazetteer": g, "extractor": train_extractor(annotated, det), "linker": train_linker(annotated, det, A, labels), "card": card}


FREE_TEXT = {"OWNS", "HANDOVER", "SELECTED", "CONSIDERED", "REJECTED", "DECIDED_BY", "REASON", "CONTRACT_VALUE", "RENAMED"}
VALUED = ("REASON", "CONTRACT_VALUE", "REJECTED")


def _vn(v):
    return (v or "").lower().rstrip(".").strip()


def extraction_scores(objs, det, models):
    """Precision and recall of the assertions extracted from free text against the annotation, for the model and the
    trigger-word baseline. An assertion counts when its relation, both arguments (by the annotated mention they overlap)
    and its value match."""
    out = {}
    for use in ("model", "rules"):
        tp, fp, fn = collections.Counter(), collections.Counter(), collections.Counter()
        for o in objs:
            if o["structured"]:
                continue
            ments = annotate_categories(det(o["body"]), det)
            pred = {(x["pred"], gold_key(x["a"], o), gold_key(x.get("b"), o), _vn(x.get("value")) if x["pred"] in VALUED else "")
                    for x in extract(o, ments, det, models, use=use)}
            gold = {(f["pred"], f["subj"], f["obj"], _vn(f["value"]) if f["pred"] in VALUED else "") for f in o["truth"]["facts"]
                    if f["asserted"] and f["polarity"] and f["pred"] in FREE_TEXT}
            for p in pred:
                (tp if p in gold else fp)[p[0]] += 1
            for g in gold - pred:
                fn[g[0]] += 1
        T, F_, N = sum(tp.values()), sum(fp.values()), sum(fn.values())
        out[use] = {"precision": round(T / max(1, T + F_), 3), "recall": round(T / max(1, T + N), 3), "assertions": T + N,
                    "by_relation": {r: {"tp": tp[r], "fp": fp[r], "fn": fn[r]} for r in sorted(FREE_TEXT)}}
    return out


def linking_scores(objs, det, A, linker, labels):
    """Of the annotated person/team/vendor mentions with at least one candidate: linked to the right anchor, linked wrong,
    abstained (ambiguous), or left unlinked."""
    c = collections.Counter()
    inv = collections.defaultdict(set)
    for k, g in labels.items():
        inv[g].add(k)
    for o in objs:
        ments = annotate_categories(det(o["body"]), det)
        ctx = mention_context(o, ments, A)
        for m in ments:
            if m["type"] not in ("person", "team", "vendor"):
                continue
            gk = gold_key(m, o)
            if not inv.get(gk):
                continue
            key, _, method = link(m, ctx, A, linker)
            c["mentions"] += 1
            c["right" if key in inv[gk] else "abstained" if method in ("ambiguous", "unresolved") else "unlinked" if method == "nil" else "wrong"] += 1
    return dict(c) | {"accuracy": round(c["right"] / max(1, c["mentions"]), 3), "precision": round(c["right"] / max(1, c["right"] + c["wrong"]), 4)}


def readable_containers(acl, groups):
    """The permission engine: containers whose ACL names any of the principal's groups."""
    return sorted(c for c, gs in acl.items() if set(gs) & set(groups))
