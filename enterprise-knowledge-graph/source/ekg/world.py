"""A synthetic enterprise and everything its source systems hold, generated with the truth attached.

Halden Systems (invented) has about a hundred people in fourteen teams, 45 services whose owners change over the fourteen
months, ten procurement decisions with three candidate vendors each, and six source systems: an HR directory, a git service
catalog, a wiki, a ticket tracker, a CRM and a chat tool. Every system has containers (spaces, projects, channels, record
types) with their own read permissions, as in the real thing: the evaluation of vendors lives in procurement's space and a
private channel, the security review in security's, the contract value in the CRM's contract records.

The corpus is built to be hard in the ways an enterprise's is:
  * duplicate names: the same person as "Priya Raman", "P. Raman", "@praman", "priya.raman@..."; two people who share an
    initial and a surname; two different people with the same full name; nicknames; typos
  * renamed teams: older documents say "Data Platform", newer ones "Analytics Engineering"; the HR directory knows only the
    new name
  * stale facts: service pages that still name the old owner months after a handover, sometimes edited since; people in chat
    who misremember who owns what; a catalog that catches up days or weeks after a change
  * hedges, questions and negations that look like facts ("X might take over Y next quarter")

Every random draw is keyed by (seed, what it is for), so the same seed gives the same company and the same documents. The
generator records, for every document, where each entity is mentioned and what each sentence asserts (the truth). The
service never reads that: it sees bodies, titles, containers and timestamps. The truth is used by the annotation sample (the
labels a human annotator would have produced for a fifth of the documents), by the tests and by the evaluation.
"""
import datetime
import random

EPOCH = datetime.date(2025, 8, 4)        # day 0 of the corpus
NOW = 427                                # the demo's "today": 2026-10-05
HORIZON = NOW + 60                       # the generator runs ahead so the clock can be advanced
DOMAIN = "halden.example"


def date_of(d):
    return EPOCH + datetime.timedelta(days=int(d))


def iso(d):
    return date_of(d).isoformat()


def long_date(d):
    x = date_of(d)
    return f"{x:%B} {x.day}, {x.year}"


def rng(seed, *key):
    return random.Random("/".join(map(str, (seed,) + key)))


# --- the company -------------------------------------------------------------------------------------------------------
TEAMS = [   # (name, slug, kind, short name or None)
    ("Payments Platform", "payments-platform", "eng", "PayPlat"),
    ("Core Ledger", "core-ledger", "eng", None),
    ("Identity & Access", "identity-access", "eng", "IAM"),
    ("Data Platform", "data-platform", "eng", None),
    ("Site Reliability", "site-reliability", "eng", "SRE"),
    ("Mobile Apps", "mobile-apps", "eng", None),
    ("Search & Discovery", "search-discovery", "eng", None),
    ("Developer Experience", "developer-experience", "eng", "DevEx"),
    ("Security Engineering", "security-engineering", "eng", "SecEng"),
    ("Customer Support Tools", "support-tools", "eng", None),
    ("Growth Engineering", "growth-engineering", "eng", None),
    ("Messaging", "messaging", "eng", None),
    ("Procurement", "procurement", "business", None),
    ("Finance", "finance", "business", None),
]
RENAMES = {"data-platform": ("Analytics Engineering", "analytics-engineering", (150, 250)),
           "support-tools": ("Support Engineering", "support-engineering", (280, 370))}
FIRST = ["Aisha", "Tariq", "Mei", "Hiro", "Olga", "Ivan", "Fatima", "Omar", "Chloe", "Ethan", "Grace", "Noah", "Hannah", "Lucas",
         "Zoe", "Mateo", "Amara", "Kofi", "Elena", "Jonas", "Freya", "Ravi", "Anika", "Diego", "Camila", "Yusuf", "Leila", "Arjun",
         "Nadia", "Felix", "Ingrid", "Rosa", "Viktor", "Mira", "Owen", "Clara", "Bruno", "Esther", "Hugo", "Robert", "William",
         "Elizabeth", "Michael", "Jonathan", "Christopher", "Margaret", "Thomas", "Alexander", "Sophie", "Nikolai"]
NICK = {"Robert": "Bob", "William": "Bill", "Elizabeth": "Liz", "Michael": "Mike", "Jonathan": "Jon", "Christopher": "Chris",
        "Margaret": "Maggie", "Thomas": "Tom", "Katherine": "Kate", "Daniel": "Dan", "Samuel": "Sam", "Alexander": "Alex"}
LAST = ["Novak", "Hoff", "Kowalski", "Tanaka", "Petrov", "Mensah", "Garcia", "Nilsson", "Brennan", "Moreau", "Rossi", "Kaplan",
        "Ibrahim", "Larsen", "Fischer", "Costa", "Varga", "Osei", "Lindqvist", "Patel", "Dubois", "Schmidt", "Nakamura",
        "Ferreira", "Horvat", "Quinn", "Adeyemi", "Sato", "Weber", "Castillo", "Byrne", "Yilmaz", "Johansson", "Romero", "Bauer",
        "Ahmed", "Hale", "Pike", "Marsh", "Achterberg", "Okonkwo", "Strand", "Vidal", "Keller", "Barros"]
PERSONAS = [   # the demo's people: (first, last, team slug, title, lead)
    ("Samuel", "Okafor", "site-reliability", "Site Reliability Engineer", False),
    ("Ines", "Duarte", "procurement", "Procurement Analyst", False),
    ("Morgan", "Lee", "developer-experience", "Engineering Manager", True),
    ("Dana", "Whitfield", "procurement", "Head of Procurement", True),
]
COLLISIONS = [("Priya", "Pradeep", "Raman"), ("Marcus", "Maria", "Chen"), ("Kevin", "Katherine", "Silva"), ("Lena", "Leo", "Haddad")]
TWINS = ("Daniel", "Kim")                # two different people with the same full name
SERVICES = ["ledger-api", "ledger-reconciler", "payment-gateway", "refund-worker", "invoice-renderer", "card-vault", "auth-service",
            "token-broker", "session-store", "permissions-api", "event-pipeline", "metrics-collector", "warehouse-loader",
            "feature-store", "search-indexer", "query-api", "ranking-service", "mobile-bff", "push-notifier", "app-config",
            "build-runner", "artifact-store", "deploy-orchestrator", "secrets-proxy", "audit-logger", "waf-gateway", "ticket-router",
            "chat-widget", "kb-search", "experiment-api", "referral-service", "email-sender", "sms-gateway", "notification-hub",
            "fx-rates", "payout-scheduler", "dispute-tracker", "status-page", "edge-proxy", "rate-limiter", "schema-registry",
            "stream-processor", "report-builder", "consent-api", "profile-service"]
UPPER = {"api": "API", "bff": "BFF", "fx": "FX", "waf": "WAF", "sms": "SMS", "kb": "KB"}
PURPOSES = ["card payments", "the general ledger", "refunds", "login and sessions", "event ingestion", "search results",
            "push notifications", "builds and deploys", "audit trails", "support tickets", "experiments", "outbound email",
            "currency conversion", "payouts to merchants", "rate limiting at the edge", "reporting"]
CATEGORIES = [   # (key, label, synonyms used in questions and chat, word in vendor names, unit for cost reasons)
    ("observability", "observability platform", ["monitoring platform", "APM tool", "observability vendor"], "Observability", "GB ingested"),
    ("cdn", "CDN", ["content delivery network", "edge network"], "Edge", "TB served"),
    ("identity", "identity provider", ["SSO provider", "IdP"], "Identity", "user"),
    ("paging", "on-call paging tool", ["incident paging tool", "on-call tool"], "Alerting", "seat"),
    ("ci", "CI system", ["build system", "continuous integration service"], "Build", "build minute"),
    ("support", "support desk", ["helpdesk", "customer support tool"], "Desk", "agent"),
    ("backup", "backup service", ["backup vendor", "disaster recovery backup"], "Backup", "TB stored"),
    ("analytics", "product analytics tool", ["analytics platform", "product analytics vendor"], "Analytics", "event"),
    ("email", "email delivery provider", ["transactional email provider", "email provider"], "Mail", "thousand emails"),
    ("search", "hosted search service", ["search vendor", "managed search"], "Search", "query"),
]
VENDOR_PREFIX = ["Northwind", "Grafton", "Kestrel", "Corvid", "Bluepeak", "Tessera", "Halcyon", "Quarry", "Meridian", "Osprey",
                 "Lattice", "Fennel", "Juniper", "Arbor", "Vireo", "Sable", "Larkspur", "Tamarack", "Wren", "Ibis", "Pallas",
                 "Cinder", "Marlow", "Thistle", "Ember", "Solstice", "Garnet", "Basalt", "Heron", "Alder", "Cobalt"]
LEGAL = ["Inc.", "Ltd", "Labs", "GmbH"]
CRITERIA = ["cost", "security", "integration", "support"]
REASONS = {"cost": ["lower cost per {unit}", "the lowest three-year cost"], "security": ["SOC 2 Type II with EU data residency", "the cleanest security review"],
           "integration": ["native OpenTelemetry support", "a Terraform provider with SCIM provisioning"], "support": ["round-the-clock support with a 30-minute response SLA", "a named support engineer"]}
REJECTS = {"cost": "its pricing was {pct}% higher", "security": "its SOC 2 report had expired", "integration": "it had no SAML support",
           "support": "support was business hours only"}
CODENAMES = ["Bluefin", "Kingfisher", "Marlin", "Plover", "Sturgeon", "Avocet", "Barracuda", "Curlew"]
SYMPTOMS = ["returning 503s", "latency above SLO", "queue backlog growing", "elevated error rate", "failing health checks", "timeouts to the database"]
IMPACTS = ["checkout degraded for 14 minutes", "some customers saw errors", "no customer impact", "delayed notifications", "partial outage in eu-west"]
FIXES = ["rolling back the last deploy", "raising the connection pool", "restarting the stuck workers", "failing over to the replica", "purging a bad cache entry"]


def team_at(co, key, day):
    """(name, slug, short) of a team on a day: renamed teams change name, not identity."""
    t = co["teams"][key]
    if t["renamed"] and day >= t["renamed"]["day"]:
        return t["renamed"]["name"], t["renamed"]["slug"], None
    return t["name"], t["slug"], t["short"]


def owner_at(co, svc, day):
    """The team that owns a service on a day (truth), or None before the service exists."""
    s = co["services"][svc]
    if day < s["created"]:
        return None
    return [k for d, k in s["owners"] if d <= day][-1]


def company(seed):
    r = rng(seed, "company")
    teams = {}
    for name, slug, kind, short in TEAMS:
        rn = RENAMES.get(slug)
        teams[f"team:{slug}"] = {"key": f"team:{slug}", "name": name, "slug": slug, "kind": kind, "short": short, "members": [], "lead": None,
                                 "renamed": {"name": rn[0], "slug": rn[1], "day": r.randint(*rn[2])} if rn else None}
    eng = [k for k, t in teams.items() if t["kind"] == "eng"]
    people, names = {}, set()

    def add(first, last, team, title=None, lead=False):
        local = f"{first}.{last}".lower()
        k = 2
        while f"person:{local}" in people:
            local, k = f"{first}.{last}{k}".lower(), k + 1
        handle = (first[0] + last).lower()
        while handle in {p["handle"] for p in people.values()}:
            handle = handle.rstrip("0123456789") + str(k)
            k += 1
        key = f"person:{local}"
        eng_team = teams[team]["kind"] == "eng"
        people[key] = {"key": key, "first": first, "last": last, "nick": NICK.get(first), "email": f"{local}@{DOMAIN}", "handle": handle,
                       "team": team, "lead": lead, "title": title or (("Engineering Manager" if eng_team else f"Head of {teams[team]['name']}") if lead else
                                                                       r.choice(["Software Engineer", "Senior Software Engineer", "Staff Engineer"]) if eng_team else
                                                                       r.choice(["Analyst", "Specialist"]))}
        teams[team]["members"].append(key)
        if lead:
            teams[team]["lead"] = key
        names.add((first, last))
        return key

    for first, last, slug, title, lead in PERSONAS:
        add(first, last, f"team:{slug}", title, lead)
    spread = r.sample(eng, 2 * len(COLLISIONS) + 2)
    for i, (a, b, last) in enumerate(COLLISIONS):
        add(a, last, spread[2 * i])
        add(b, last, spread[2 * i + 1])
    add(*TWINS, spread[-2])
    add(*TWINS, spread[-1])
    pool = [(f, s) for f in FIRST for s in LAST]
    r.shuffle(pool)
    for key, t in teams.items():
        size = 8 if t["kind"] == "eng" else 5
        while len(t["members"]) < size:
            f, s = pool.pop()
            if (f, s) in names:
                continue
            add(f, s, key, lead=t["lead"] is None)
        if t["lead"] is None:            # a team filled only by fixed people still needs a lead
            t["lead"] = t["members"][-1]
            people[t["lead"]]["lead"] = True
    groups = {"all-staff": set(people), "eng-all": {p for p, x in people.items() if teams[x["team"]]["kind"] == "eng"},
              "procurement": set(teams["team:procurement"]["members"]), "finance": set(teams["team:finance"]["members"]),
              "security": set(teams["team:security-engineering"]["members"]), "leadership": {p for p, x in people.items() if x["lead"]}}

    services = {}
    for i, slug in enumerate(SERVICES):
        rs = rng(seed, "service", slug)
        created = 0 if rs.random() < 0.7 else rs.randint(20, 300)
        first = rs.choice(eng)
        owners = [(created, first)]
        if rs.random() < 0.35:
            d = rs.randint(max(created + 40, 40), 405)
            owners.append((d, rs.choice([t for t in eng if t != first])))
            if rs.random() < 0.2 and d < 340:
                owners.append((rs.randint(d + 60, 405), rs.choice([t for t in eng if t != owners[-1][1]])))
        services[f"service:{slug}"] = {"key": f"service:{slug}", "slug": slug, "created": created, "owners": owners, "in_catalog": rs.random() < 0.6,
                                       "tier": rs.choice([1, 1, 2, 2, 3]), "purpose": rs.choice(PURPOSES),
                                       "depends": rs.sample([s for s in SERVICES if s != slug], 2), "page": rs.random() < 0.8}
    recent = [k for k, s in services.items() if any(220 <= d <= 390 for d, _ in s["owners"][1:])]
    for k in [k for k in services if len(services[k]["owners"]) == 1][: max(0, 6 - len(recent))]:   # the demo needs recent handovers
        s, rs = services[k], rng(seed, "handover", k)
        s["owners"].append((rs.randint(max(s["created"] + 40, 220), 390), rs.choice([t for t in eng if t != s["owners"][0][1]])))
        s["page"] = True
    prefixes = VENDOR_PREFIX[:-1]
    r.shuffle(prefixes)
    vendors, decisions = {}, {}
    cobalt = r.sample(range(len(CATEGORIES)), 2)                # two vendors in different categories share a name
    used_days = set()
    for ci, (cat, label, syn, word, unit) in enumerate(CATEGORIES):
        rc = rng(seed, "decision", cat)
        cands = []
        for j in range(3):
            prefix = "Cobalt" if (ci in cobalt and j == 0) else prefixes.pop()
            name = f"{prefix} {word}"
            key = f"vendor:{prefix.lower()}-{word.lower()}"
            vendors[key] = {"key": key, "short": prefix, "name": name, "legal": f"{name} {rc.choice(LEGAL)}", "domain": f"{prefix.lower()}.{rc.choice(['io', 'com', 'dev'])}",
                            "category": cat}
            cands.append(key)
        scores = {v: {c: rc.randint(1, 5) for c in CRITERIA} for v in cands}
        total = lambda v: sum(scores[v].values()) + 0.01 * cands.index(v)                       # noqa: E731
        sel = max(cands, key=total)
        top = sorted(CRITERIA, key=lambda c: -scores[sel][c])[:2]
        reasons = [rc.choice(REASONS[c]).format(unit=unit) for c in top]
        day = rc.randint(30, 395)
        while any(abs(day - u) < 9 for u in used_days):
            day = rc.randint(30, 395)
        used_days.add(day)
        lead_team = rc.choice(eng)
        panel = [teams[lead_team]["lead"], "person:ines.duarte", rc.choice(teams["team:security-engineering"]["members"]), rc.choice(teams[lead_team]["members"])]
        rejected = {}
        for v in cands:
            if v == sel:
                continue
            worst = min(CRITERIA, key=lambda c: scores[v][c])
            rejected[v] = {"criterion": worst, "reason": REJECTS[worst].format(pct=rc.choice([25, 30, 40, 60]))}
        breach = None
        if rc.random() < 0.5:
            v = rc.choice([v for v in cands if v != sel])
            breach = {"vendor": v, "month": f"{date_of(rc.randint(-200, day - 20)):%B %Y}"}
        decisions[f"decision:{cat}"] = {"key": f"decision:{cat}", "category": cat, "label": label, "synonyms": syn, "day": day, "candidates": cands, "selected": sel,
                                        "scores": scores, "reasons": reasons, "rejected": rejected, "breach": breach,
                                        "decider": "person:dana.whitfield" if rc.random() < 0.6 else teams[lead_team]["lead"], "requested_by": teams[lead_team]["lead"],
                                        "panel": panel, "value": rc.randrange(48, 960) * 1000, "term": rc.randint(1, 3), "signed": day + rc.randint(7, 25),
                                        "codename": f"Project {CODENAMES[ci % len(CODENAMES)]}" if rc.random() < 0.5 else None, "ticket": 100 + ci * 7 + rc.randint(0, 5)}
        groups[f"panel-{cat}"] = set(panel) | groups["procurement"]
    return {"seed": seed, "teams": teams, "people": people, "groups": groups, "services": services, "vendors": vendors, "decisions": decisions}


# Containers and who can read them: the source systems' own permission model, synced by the connectors.
def containers(co):
    acl = {"hr:directory": ["all-staff"], "code:service-catalog": ["eng-all"], "wiki:ENG": ["eng-all"], "wiki:ANN": ["all-staff"],
           "wiki:PROC": ["procurement", "leadership"], "wiki:SEC": ["security", "leadership"], "tickets:OPS": ["eng-all"],
           "tickets:SECREV": ["security", "leadership"], "tickets:PROCURE": ["procurement", "finance", "leadership"],
           "crm:accounts": ["all-staff"], "crm:contracts": ["procurement", "finance", "leadership"], "chat:#announcements": ["all-staff"],
           "chat:#eng-announce": ["eng-all"], "chat:#eng-decisions": ["eng-all"], "chat:#incidents": ["eng-all"]}
    for k, t in co["teams"].items():
        if t["kind"] == "eng":
            acl[f"chat:#team-{t['slug']}"] = ["eng-all"]
    for d in co["decisions"].values():
        acl[f"chat:#vendor-eval-{d['category']}"] = [f"panel-{d['category']}"]
    return acl


SYSTEMS = {"hr": "HR directory", "code": "Git service catalog", "wiki": "Wiki", "tickets": "Ticket tracker", "crm": "CRM", "chat": "Chat"}


# --- surface forms: how people write about an entity --------------------------------------------------------------------
def typo(word, r):
    i = r.randrange(1, len(word) - 1)
    return word[:i] + word[i + 1:] if r.random() < 0.5 else word[:i] + r.choice("aeiou") + word[i + 1:]


def person_form(p, r, chat=False):
    roll = r.random()
    if chat and roll < 0.12:
        return "@" + p["handle"]
    if roll < 0.18:
        return f"{p['first'][0]}. {p['last']}"
    if roll < 0.26 and p["nick"]:
        return f"{p['nick']} {p['last']}"
    if roll < 0.31:
        return p["email"]
    if roll < 0.34:
        t = typo(p["last"], r)
        return f"{p['first']} {t}" if t != p["last"] else f"{p['first']} {p['last']}"
    return f"{p['first']} {p['last']}"


def service_title(slug):
    return " ".join(UPPER.get(w, w.capitalize()) for w in slug.split("-"))


def service_form(slug, r):
    roll = r.random()
    if roll < 0.2:
        return service_title(slug)
    if roll < 0.3:
        return "svc-" + slug
    return slug


def team_form(co, key, day, r):
    name, slug, short = team_at(co, key, day)
    roll = r.random()
    if roll < 0.1:
        return slug
    if roll < 0.2 and short:
        return short
    return name


def vendor_form(v, r):
    roll = r.random()
    if roll < 0.25:
        return v["name"]
    if roll < 0.38:
        return v["legal"]
    if roll < 0.45:
        return v["domain"]
    if roll < 0.51:
        return typo(v["short"], r)
    return v["short"]


# --- documents ----------------------------------------------------------------------------------------------------------
class Text:
    """A document body built piece by piece, recording the truth: each entity mention's span and each sentence's assertions."""

    def __init__(self):
        self.buf, self.n, self.mentions, self.facts = [], 0, [], []

    def put(self, s):
        self.buf.append(s)
        self.n += len(s)

    def ent(self, surface, key, typ):
        self.mentions.append({"start": self.n, "end": self.n + len(surface), "text": surface, "key": key, "type": typ})
        self.put(surface)

    def say(self, *parts, facts=(), end="\n"):
        """One sentence. parts: plain strings or (surface, key, type); facts: what the sentence asserts."""
        start = self.n
        for p in parts:
            if isinstance(p, tuple):
                self.ent(*p)
            else:
                self.put(p)
        for f in facts:
            self.facts.append({"asserted": True, "polarity": True, **f, "start": start, "end": self.n})
        self.put(end)

    @property
    def body(self):
        return "".join(self.buf).rstrip()


def F(pred, subj, obj=None, value=None, **kw):
    return {"pred": pred, "subj": subj, "obj": obj, "value": value, **kw}


def doc(system, container, external_id, kind, title, text, day, author=None, structured=False, versions=None):
    v = versions or [day]
    return {"system": system, "container": container, "external_id": external_id, "kind": kind, "title": title, "author": author,
            "structured": structured, "versions": [{"day": d, "body": text.body, "mentions": text.mentions, "facts": text.facts} for d in v]}


def objects(seed, told=()):
    """Every source object the six systems will ever hold up to the horizon (with their versions), plus what `told` adds."""
    co = company(seed)
    out = []
    P, T, S, V, D = co["people"], co["teams"], co["services"], co["vendors"], co["decisions"]

    def per(k, r, day=0, chat=False):
        return (person_form(P[k], r, chat), k, "person")

    def team(k, day, r):
        return (team_form(co, k, day, r), k, "team")

    def svc(k, r):
        return (service_form(S[k]["slug"], r), k, "service")

    def ven(k, r):
        return (vendor_form(V[k], r), k, "vendor")

    def cat(d, r, plain=False):
        return (D[d]["label"] if plain or r.random() < 0.6 else r.choice(D[d]["synonyms"]), d, "decision")

    # HR directory: one record per person and per org unit, as of today (it knows current names only)
    for k, p in P.items():
        t = Text()
        tk = p["team"]
        renamed = T[tk]["renamed"]
        day = renamed["day"] if renamed else rng(seed, "hrday", k).randint(0, 200)
        name = team_at(co, tk, NOW)[0]
        t.say("Name: ", (f"{p['first']} {p['last']}", k, "person"))
        t.say("Email: ", (p["email"], k, "person"))
        t.say("Handle: ", ("@" + p["handle"], k, "person"))
        t.say(f"Title: {p['title']}")
        t.say("Team: ", (name, tk, "team"), facts=[F("MEMBER_OF", k, tk)])
        if p["lead"]:
            t.say("Leads: ", (name, tk, "team"), facts=[F("LEADS", k, tk)])
        elif T[tk]["lead"]:
            lead = P[T[tk]["lead"]]
            t.say("Manager: ", (f"{lead['first']} {lead['last']}", lead["key"], "person"))
        out.append(doc("hr", "hr:directory", f"worker/{p['email'].split('@')[0]}", "person_record", f"{p['first']} {p['last']}", t, day, structured=True))
    for k, tm in T.items():
        t = Text()
        name, slug, short = team_at(co, k, NOW)
        t.say("Org unit: ", (name, k, "team"))
        if short:
            t.say("Short name: ", (short, k, "team"))
        t.say("Slug: ", (slug, k, "team"))
        lead = P[tm["lead"]]
        t.say("Lead: ", (f"{lead['first']} {lead['last']}", lead["key"], "person"), facts=[F("LEADS", lead["key"], k)])
        out.append(doc("hr", "hr:directory", f"org/{slug}", "org_unit", name, t, tm["renamed"]["day"] if tm["renamed"] else 0, structured=True))

    # Git service catalog: one source object per revision of each service.yaml; the catalog catches up after a handover
    for k, s in S.items():
        if not s["in_catalog"]:
            continue
        rs = rng(seed, "catalog", k)
        revs = [max(s["created"], rs.randint(0, 25))] + [min(d + rs.randint(0, 21), NOW - 1) for d, _ in s["owners"][1:]]
        for i, d in enumerate(revs):
            t, owner = Text(), owner_at(co, k, d)
            t.say("service: ", (s["slug"], k, "service"))
            t.say("owner: ", (team_at(co, owner, d)[1], owner, "team"), facts=[F("OWNS", owner, k, kind="state")])
            t.say(f"tier: {s['tier']}")
            t.say("depends_on: ", (s["depends"][0], f"service:{s['depends'][0]}", "service"), ", ", (s["depends"][1], f"service:{s['depends'][1]}", "service"),
                  facts=[F("DEPENDS_ON", k, f"service:{x}") for x in s["depends"]])
            out.append(doc("code", "code:service-catalog", f"service-catalog/{s['slug']}/service.yaml@r{i + 1}", "file_revision", f"{s['slug']}/service.yaml (r{i + 1})",
                           t, d, structured=True))

    # Wiki: service pages (often stale), handover pages, design docs, renames, procurement and security pages
    own_templates = [
        lambda tm, sv: (sv, " is owned by ", tm, "."),
        lambda tm, sv: (tm, " owns ", sv, "."),
        lambda tm, sv: ("Owning team for ", sv, ": ", tm, "."),
        lambda tm, sv: (tm, " is responsible for ", sv, "."),
        lambda tm, sv: (tm, " maintains ", sv, " and carries its pager."),
        lambda tm, sv: (sv, " belongs to ", tm, "."),
    ]
    for k, s in S.items():
        if not s["page"]:
            continue
        rs = rng(seed, "page", k)
        c = max(s["created"], rs.randint(0, 200))
        later = [d for d, _ in s["owners"] if d > c]
        state_day, mod = c, c
        if later:
            if rs.random() < 0.45:
                state_day = mod = min(later[-1] + rs.randint(5, 40), NOW - 1)              # updated after the handover
            elif rs.random() < 0.6:
                mod = rs.randint(later[-1] + 1, NOW - 1)                                   # edited since, owner line left stale
        owner = owner_at(co, k, state_day)
        t = Text()
        t.say((s["slug"], k, "service"), " service overview")
        t.say((s["slug"], k, "service"), f" handles {s['purpose']}.", end=" ")
        t.say(*own_templates[rs.randrange(len(own_templates))](team(owner, state_day, rs), svc(k, rs)), facts=[F("OWNS", owner, k, kind="state")], end=" ")
        t.say("It depends on ", svc(f"service:{s['depends'][0]}", rs), " and ", svc(f"service:{s['depends'][1]}", rs), ".")
        t.say(f"On-call questions go to the team channel. Runbooks are linked from the dashboard.")
        out.append(doc("wiki", "wiki:ENG", f"ENG/{s['slug']}-overview", "page", f"{s['slug']} service overview", t, c, versions=sorted({c, mod})))
        for i, (d, new) in enumerate(s["owners"][1:]):
            old = s["owners"][i][1]
            rh = rng(seed, "handover", k, i)
            if rh.random() < 0.75:
                t = Text()
                t.say("Ownership handover: ", (s["slug"], k, "service"))
                form = rh.randrange(3)
                tr = F("HANDOVER", new, k, kind="transition", effective=d, frm=old)
                when = rh.choice([long_date(d), iso(d)])
                if form == 0:
                    t.say(f"Effective {when}, ownership of ", svc(k, rh), " moves from ", team(old, d, rh), " to ", team(new, d, rh), ".", facts=[tr], end=" ")
                elif form == 1:
                    t.say(team(new, d, rh), " takes over ", svc(k, rh), " from ", team(old, d, rh), f" on {when}.", facts=[tr], end=" ")
                else:
                    t.say(f"Starting {when}, ", svc(k, rh), " is owned by ", team(new, d, rh), " (previously ", team(old, d, rh), ").", facts=[tr], end=" ")
                t.say(per(T[new]["lead"], rh), " is the new primary contact.", end=" ")
                t.say(team(old, d, rh), " stays on the pager rotation for two weeks.")
                out.append(doc("wiki", "wiki:ENG", f"ENG/handover-{s['slug']}-{i + 1}", "page", f"Ownership handover: {s['slug']}", t, max(1, d - rh.randint(0, 14))))
            if rh.random() < 0.6:
                t = Text()
                t.say("heads up: ", svc(k, rh), " moves to ", team(new, d, rh), f" on {long_date(d)}, ", team(old, d, rh), " keeps the pager until then",
                      facts=[F("HANDOVER", new, k, kind="transition", effective=d, frm=old)])
                out.append(doc("chat", "chat:#eng-announce", f"eng-announce/{seed}-{k}-{i}", "message", "#eng-announce", t, max(1, d - rh.randint(1, 10)), author=T[new]["lead"]))
            if rh.random() < 0.4:              # talk before the move: a hedge, not a fact
                t = Text()
                t.say(team(new, d - 60, rh), " might take over ", svc(k, rh), " next quarter, nothing decided yet",
                      facts=[F("OWNS", new, k, kind="state", asserted=False)])
                out.append(doc("chat", f"chat:#team-{T[old]['slug']}", f"team/{seed}-{k}-{i}-hedge", "message", f"#team-{T[old]['slug']}", t, max(1, d - rh.randint(40, 90)),
                               author=T[old]["lead"]))
    for k, tm in T.items():
        rn = tm["renamed"]
        if not rn:
            continue
        rr = rng(seed, "rename", k)
        t = Text()
        t.say("Team rename: ", (tm["name"], k, "team"), " is now ", (rn["name"], k, "team"))
        t.say(f"From {long_date(rn['day'])} the ", (tm["name"], k, "team"), " team is called ", (rn["name"], k, "team"), ".",
              facts=[F("RENAMED", k, k, effective=rn["day"])], end=" ")
        t.say("Nothing else changes: same people, same services, same on-call.")
        out.append(doc("wiki", "wiki:ANN", f"ANN/rename-{tm['slug']}", "page", f"Team rename: {tm['name']} is now {rn['name']}", t, rn["day"] - rr.randint(1, 7)))
        t = Text()
        t.say((tm["name"], k, "team"), " has been renamed to ", (rn["name"], k, "team"), f" (effective {iso(rn['day'])}).",
              facts=[F("RENAMED", k, k, effective=rn["day"])])
        out.append(doc("chat", "chat:#announcements", f"announcements/{seed}-rename-{tm['slug']}", "message", "#announcements", t, rn["day"], author=tm["lead"]))

    # Procurement: the request, the evaluation, the private channel, the security review, the contract, the announcement
    for k, d in D.items():
        rd = rng(seed, "proc", k)
        sel, cands, day = d["selected"], d["candidates"], d["day"]
        others = [v for v in cands if v != sel]
        t = Text()
        t.say(f"PROC-{d['ticket']}: Select a {d['label']}")
        t.say("Requested by ", per(d["requested_by"], rd), " (", team(P[d["requested_by"]]["team"], day, rd), ").")
        order = cands[:]
        rd.shuffle(order)
        t.say(rd.choice(["Candidates: ", "Shortlist: "]), ven(order[0], rd), ", ", ven(order[1], rd), " and ", ven(order[2], rd), ".",
              facts=[F("CONSIDERED", k, v) for v in cands])
        t.say("Budget owner: ", per(d["decider"], rd), ".")
        t.say(f"Status: decided on {iso(day)}.")
        out.append(doc("tickets", "tickets:PROCURE", f"PROC-{d['ticket']}", "ticket", f"PROC-{d['ticket']}: Select a {d['label']}", t, day - rd.randint(20, 40),
                       versions=[day - rd.randint(20, 40), day]))
        t = Text()
        t.say("RFP evaluation: ", cat(k, rd, plain=True))
        t.say("The panel evaluated ", ven(order[0], rd), ", ", ven(order[1], rd), " and ", ven(order[2], rd), " for the ", cat(k, rd), ".",
              facts=[F("CONSIDERED", k, v) for v in cands], end=" ")
        for v in order:
            sc = d["scores"][v]
            t.say("Scores for ", ven(v, rd), f": cost {sc['cost']}, security {sc['security']}, integration {sc['integration']}, support {sc['support']}.", end=" ")
        t.say("\n", end="")
        form = rd.randrange(3)
        reasons = d["reasons"]
        if form == 0:
            t.say(ven(sel, rd), f" won on {reasons[0]} and {reasons[1]}.", facts=[F("REASON", k, value=x) for x in reasons], end=" ")
        elif form == 1:
            t.say(f"The deciding factors were {reasons[0]} and {reasons[1]}.", facts=[F("REASON", k, value=x) for x in reasons], end=" ")
        else:
            t.say(f"Main reasons: {reasons[0]} and {reasons[1]}.", facts=[F("REASON", k, value=x) for x in reasons], end=" ")
        for v in others:
            rj = d["rejected"][v]
            why = "it failed the security review" if d["breach"] and d["breach"]["vendor"] == v else rj["reason"]
            if rd.random() < 0.5:
                t.say(ven(v, rd), f" was rejected because {why}.", facts=[F("REJECTED", k, v, value=why)], end=" ")
            else:
                t.say("We ruled out ", ven(v, rd), f": {why}.", facts=[F("REJECTED", k, v, value=why)], end=" ")
        t.say("\n", end="")
        t.say("Decision owner: ", per(d["decider"], rd), ".", facts=[F("DECIDED_BY", k, d["decider"])], end=" ")
        t.say(f"The negotiated price is ${d['value']:,} a year for {d['term']} year{'s' if d['term'] > 1 else ''}.", facts=[F("CONTRACT_VALUE", sel, value=f"${d['value']:,}")], end=" ")
        if rd.random() < 0.5:
            t.say("We selected ", ven(sel, rd), " as our ", cat(k, rd), ".", facts=[F("SELECTED", k, sel)])
        else:
            t.say(ven(sel, rd), " was chosen for the ", cat(k, rd), ".", facts=[F("SELECTED", k, sel)])
        if d["codename"]:
            t.say(f"Internal codename: {d['codename']}.")
        out.append(doc("wiki", "wiki:PROC", f"PROC/rfp-{d['category']}", "page", f"RFP evaluation: {d['label']}", t, day))
        ch = f"chat:#vendor-eval-{d['category']}"
        msgs = []
        msgs.append((day - 25, [f"{d['codename'] or 'RFP'} kickoff: the shortlist is ", ven(order[0], rd), ", ", ven(order[1], rd), " and ", ven(order[2], rd)],
                     [F("CONSIDERED", k, v) for v in cands]))
        for v in others:
            msgs.append((day - rd.randint(5, 20), ["we might go with ", ven(v, rd), " if they fix the pricing"], [F("SELECTED", k, v, asserted=False)]))
            msgs.append((day - rd.randint(2, 6), ["honestly ", ven(v, rd), f" is out, {d['rejected'][v]['reason']}"], [F("REJECTED", k, v, value=d["rejected"][v]["reason"])]))
        msgs.append((day - 3, ["pricing came back: ", ven(sel, rd), f" is ${d['value']:,} a year"], [F("CONTRACT_VALUE", sel, value=f"${d['value']:,}")]))
        msgs.append((day, ["ok, we're going with ", ven(sel, rd), " for the ", cat(k, rd)], [F("SELECTED", k, sel)]))
        for j, (md, parts, facts) in enumerate(msgs):
            t = Text()
            t.say(*parts, facts=facts)
            out.append(doc("chat", ch, f"vendor-eval-{d['category']}/{seed}-{j}", "message", ch.split(":")[1], t, md, author=rd.choice(d["panel"])))
        if d["breach"]:
            v = d["breach"]["vendor"]
            t = Text()
            t.say("Vendor security review: ", (V[v]["name"], v, "vendor"), " for the ", (d["label"], k, "decision"))
            t.say((V[v]["short"], v, "vendor"), f" disclosed a breach in {d['breach']['month']} and did not provide remediation evidence.", end=" ")
            t.say((V[v]["short"], v, "vendor"), f" was rejected because it disclosed a breach in {d['breach']['month']} without remediation evidence.",
                  facts=[F("REJECTED", k, v, value=f"it disclosed a breach in {d['breach']['month']} without remediation evidence")], end=" ")
            t.say("Reviewer: ", per(d["panel"][2], rd), ".")
            out.append(doc("wiki", "wiki:SEC", f"SEC/review-{V[v]['short'].lower()}", "page", f"Vendor security review: {V[v]['name']} for the {d['label']}", t, day - rd.randint(8, 15)))
        t = Text()
        t.say("Contract: ", (V[sel]["legal"], sel, "vendor"))
        t.say(f"Category: {d['label']}")
        t.say(f"Annual value: ${d['value']:,}", facts=[F("CONTRACT_VALUE", sel, value=f"${d['value']:,}")])
        t.say(f"Term: {d['term']} years")
        t.say(f"Signed: {iso(d['signed'])}")
        t.say("Owner: ", (f"{P[d['decider']]['first']} {P[d['decider']]['last']}", d["decider"], "person"))
        out.append(doc("crm", "crm:contracts", f"contract/{V[sel]['short'].lower()}-{d['category']}", "contract", f"Contract: {V[sel]['legal']}", t, d["signed"], structured=True))
        t = Text()
        t.say("Account: ", (V[sel]["legal"], sel, "vendor"))
        t.say("Domain: ", (V[sel]["domain"], sel, "vendor"))
        t.say(f"Category: {d['label']}")
        t.say(f"Status: active vendor since {iso(d['signed'])}")
        t.say("Internal owner: ", (f"{P[d['decider']]['first']} {P[d['decider']]['last']}", d["decider"], "person"))
        out.append(doc("crm", "crm:accounts", f"account/{V[sel]['short'].lower()}-{d['category']}", "account", V[sel]["legal"], t, d["signed"], structured=True))
        t = Text()
        form = rd.randrange(2)
        if form == 0:
            t.say("Decision: we selected ", ven(sel, rd), " as our ", cat(k, rd, plain=True), ".", facts=[F("SELECTED", k, sel)], end=" ")
        else:
            t.say("After evaluating three vendors we picked ", ven(sel, rd), " for the ", cat(k, rd, plain=True), ".", facts=[F("SELECTED", k, sel)], end=" ")
        t.say(f"Main reason: {d['reasons'][0]}.", facts=[F("REASON", k, value=d["reasons"][0])], end=" ")
        t.say("Questions to ", ("@" + P[d["decider"]]["handle"], d["decider"], "person"), ".")
        out.append(doc("chat", "chat:#eng-decisions", f"eng-decisions/{seed}-{d['category']}", "message", "#eng-decisions", t, d["signed"] + 1, author=d["decider"]))

    # Design docs: background prose with people, services and vendors in it
    for i in range(55):
        rd = rng(seed, "design", i)
        day = rd.randint(5, NOW - 5)
        tk = rd.choice([k for k, t in T.items() if t["kind"] == "eng"])
        owned = [k for k in S if owner_at(co, k, day) == tk] or list(S)
        s1, s2 = rd.choice(owned), rd.choice(list(S))
        a, b = rd.sample(T[tk]["members"], 2)
        t = Text()
        t.say("Design: ", rd.choice(["event sourcing for ", "multi-region failover for ", "rate limits in ", "schema migration for "]), (S[s1]["slug"], s1, "service"))
        t.say("Authors: ", per(a, rd), " and ", per(b, rd), ".", end=" ")
        t.say("This proposal changes how ", svc(s1, rd), " talks to ", svc(s2, rd), ".", end=" ")
        live = [D[x]["selected"] for x in D if D[x]["signed"] < day]
        if live:
            t.say(svc(s1, rd), " will send its traces and alerts to ", ven(rd.choice(live), rd), ".", end=" ")
        t.say("Reviewers from ", team(tk, day, rd), " signed off.")
        out.append(doc("wiki", "wiki:ENG", f"ENG/design-{i}", "page", t.body.split("\n")[0], t, day))

    # Tickets: incidents, each assigned to whoever owned the service that day
    incidents = []
    for k, s in S.items():
        ri = rng(seed, "incidents", k)
        d = s["created"] + ri.randint(5, 80)
        while d < HORIZON:
            incidents.append((d, k))
            d += ri.randint(25, 140)
    incidents.sort()
    for n, (d, k) in enumerate(incidents):
        out.append(incident(co, seed, 1000 + n, k, d))
        ri = rng(seed, "inc-chat", n)
        if ri.random() < 0.5:
            owner = owner_at(co, k, d)
            t = Text()
            t.say(svc(k, ri), " is paging again, ", per(ri.choice(T[owner]["members"]), ri, chat=True), " is on it")
            out.append(doc("chat", "chat:#incidents", f"incidents/{seed}-{n}", "message", "#incidents", t, d, author=ri.choice(T["team:site-reliability"]["members"])))

    # Chat: everyday talk in team channels, some of it about who owns what (sometimes misremembered)
    noise = ["standup moves to 10:30 tomorrow", "deploy freeze starts Friday", "reminder: retro at 4pm", "who has the staging credentials?",
             "the build is green again", "lunch order is in", "postmortem doc is up for review", "please review my PR when you can"]
    for k, tm in T.items():
        if tm["kind"] != "eng":
            continue
        rc = rng(seed, "chat", k)
        day = rc.randint(0, 4)
        j = 0
        while day < HORIZON:
            ch = f"chat:#team-{tm['slug']}"
            t = Text()
            roll = rc.random()
            owned = [s for s in S if owner_at(co, s, day) == k]
            if roll < 0.18 and owned:
                s = rc.choice(owned)
                prev = [o for dd, o in S[s]["owners"] if dd <= day]
                stale = len(prev) > 1 and day - max(dd for dd, _ in S[s]["owners"] if dd <= day) < 45 and rc.random() < 0.3
                o = prev[-2] if stale else k
                form = rc.randrange(3)
                if form == 0:
                    t.say(svc(s, rc), " is ", team(o, day, rc), "'s, ping ", per(rc.choice(T[o]["members"]), rc, chat=True), facts=[F("OWNS", o, s, kind="state")])
                elif form == 1:
                    t.say("pretty sure ", team(o, day, rc), " owns ", svc(s, rc), " now", facts=[F("OWNS", o, s, kind="state")])
                else:
                    t.say("is ", svc(s, rc), " still owned by ", team(o, day, rc), "?", facts=[F("OWNS", o, s, kind="state", asserted=False)])
            elif roll < 0.42:
                m = rc.choice(tm["members"])
                if rc.random() < 0.3:
                    t.say(rc.choice(["thanks ", "ping ", "cc "]), (P[m]["first"], m, "person"), rc.choice(["!", ", can you take a look?", " for the review"]))
                else:
                    t.say(per(m, rc, chat=True), rc.choice([" is out today", " is leading the migration", " fixed the flaky test", " is on call this week"]))
            elif roll < 0.55 and owned:
                s = rc.choice(owned)
                t.say("deploying ", svc(s, rc), " to prod, shout if you see errors")
            else:
                t.say(rc.choice(noise))
            out.append(doc("chat", ch, f"team-{tm['slug']}/{seed}-{j}", "message", f"#team-{tm['slug']}", t, day, author=rc.choice(tm["members"])))
            j += 1
            day += rc.randint(1, 6)

    for ev in told:
        out.extend(told_objects(co, seed, ev))
    for o in out:
        ra = rng(seed, "annotated", o["external_id"])
        o["annotated"] = (not o["structured"]) and ra.random() < 0.2
    return out


def incident(co, seed, n, k, d, failing=False):
    S, T, P = co["services"], co["teams"], co["people"]
    ri = rng(seed, "incident", n)
    owner = owner_at(co, k, d)
    symptom = "elevated 5xx errors" if failing else ri.choice(SYMPTOMS)
    t = Text()
    t.say(f"INC-{n}: ", (S[k]["slug"], k, "service"), f" {symptom}")
    t.say("Service: ", (S[k]["slug"], k, "service"), facts=[F("AFFECTS", f"incident:INC-{n}", k)])
    t.say("Severity: " + ("SEV1" if failing else ri.choice(["SEV2", "SEV3", "SEV3"])))
    if ri.random() < 0.85:
        t.say("Assigned to ", (team_form(co, owner, d, ri), owner, "team"), " (owner of ", (service_form(S[k]["slug"], ri), k, "service"), ").",
              facts=[F("OWNS", owner, k, kind="state")], end=" ")
    else:
        t.say("Owning team: ", (team_form(co, owner, d, ri), owner, "team"), ".", facts=[F("OWNS", owner, k, kind="state")], end=" ")
    responder = T[owner]["lead"] if failing else ri.choice(T[owner]["members"])
    t.say("Paged ", (person_form(P[responder], ri), responder, "person"), ".")
    first = t.body
    if failing:
        return {"system": "tickets", "container": "tickets:OPS", "external_id": f"INC-{n}", "kind": "ticket", "title": f"INC-{n}: {S[k]['slug']} {symptom}",
                "author": None, "structured": False, "versions": [{"day": d, "body": first, "mentions": list(t.mentions), "facts": list(t.facts)}]}
    t.say(f"Impact: {ri.choice(IMPACTS)}.", end=" ")
    t.say("Resolved by ", (person_form(P[responder], ri), responder, "person"), f" after {ri.choice(FIXES)}.")
    return doc("tickets", "tickets:OPS", f"INC-{n}", "ticket", f"INC-{n}: {S[k]['slug']} {symptom}", t, d)


def told_objects(co, seed, ev):
    """What the generator produces after being told about an event (the demo's injection)."""
    if ev["kind"] != "service_failure":
        raise ValueError(ev["kind"])
    k, d = f"service:{ev['service']}", ev["day"]
    S, T, P = co["services"], co["teams"], co["people"]
    owner = owner_at(co, k, d)
    n = 9000 + rng(seed, "told", k, d).randint(0, 899)
    inc = incident(co, seed, n, k, d, failing=True)
    # second version a day later: mitigated; rebuild the text so the truth spans stay right
    v2 = Text()
    first = inc["versions"][0]
    v2.buf, v2.n, v2.mentions, v2.facts = [first["body"] + "\n"], len(first["body"]) + 1, list(first["mentions"]), list(first["facts"])
    v2.say("Update: mitigated by failing over to the replica; ", (P[T[owner]["lead"]]["first"] + " " + P[T[owner]["lead"]]["last"], T[owner]["lead"], "person"),
           " is writing the postmortem.")
    inc["versions"].append({"day": d + 1, "body": v2.body, "mentions": v2.mentions, "facts": v2.facts})
    out = [inc]
    r = rng(seed, "told-chat", k, d)
    prev = [o for dd, o in S[k]["owners"] if dd <= d]
    lines = [[(S[k]["slug"], k, "service"), " is throwing 5xx in prod, SEV1 opened"]]
    if len(prev) > 1:
        changed = max(dd for dd, _ in S[k]["owners"] if dd <= d)
        lines.append(["isn't ", (S[k]["slug"], k, "service"), " still ", (team_at(co, prev[-2], d)[0], prev[-2], "team"), "'s?"])
        lines.append(["no, ", (team_at(co, owner, d)[0], owner, "team"), " owns ", (S[k]["slug"], k, "service"), f" since {long_date(changed)}, paging ",
                      ("@" + P[T[owner]["lead"]]["handle"], T[owner]["lead"], "person")])
    for j, parts in enumerate(lines):
        t = Text()
        facts = []
        if j == 1:
            facts = [F("OWNS", prev[-2], k, kind="state", asserted=False)]
        if j == 2:
            facts = [F("OWNS", owner, k, kind="state")]
        t.say(*parts, facts=facts)
        out.append(doc("chat", "chat:#incidents", f"incidents/{seed}-told-{ev['service']}-{d}-{j}", "message", "#incidents", t, d,
                       author=r.choice(T["team:site-reliability"]["members"])))
    return out


def view(objs, day):
    """The source systems as they stand on `day`: each object's latest version, if it existed by then."""
    out = []
    for o in objs:
        vs = [v for v in o["versions"] if v["day"] <= day]
        if vs:
            v = vs[-1]
            out.append({**{k: x for k, x in o.items() if k not in ("versions", "author")}, "author": o["author"] and o["author"].split(":", 1)[1] + "@" + DOMAIN,
                        "observed_day": v["day"], "created_day": o["versions"][0]["day"],
                        "body": v["body"], "truth": {"mentions": v["mentions"], "facts": v["facts"]}})
    return out


def changed(objs, after, upto):
    """Objects with a version in (after, upto]: what an incremental sync has to fetch."""
    keep = [o for o in objs if any(after < v["day"] <= upto for v in o["versions"])]
    return view(keep, upto)


def principals(co):
    """Users and groups as the identity source reports them (email, display name, group memberships)."""
    users = [{"email": p["email"], "name": f"{p['first']} {p['last']}", "groups": sorted(g for g, m in co["groups"].items() if k in m)} for k, p in co["people"].items()]
    return users, sorted(co["groups"])


def annotations(objs_view):
    """The annotation export: a human annotator's mentions and assertions for about a fifth of the free-text documents,
    and the identity of each structured record (the HR directory, catalog and CRM know who or what each record is)."""
    docs = [o for o in objs_view if o["annotated"]]
    records = {o["external_id"]: o["truth"]["mentions"][0]["key"] for o in objs_view if o["structured"] and o["truth"]["mentions"]}
    return docs, records
