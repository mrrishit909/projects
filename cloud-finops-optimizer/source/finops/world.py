"""A synthetic multi-cloud estate: six accounts on AWS, Azure and GCP with virtual machines, Kubernetes node pools, managed
databases and block volumes; every workload has an hourly demand with a daily and weekly shape, growth, noise and spikes;
a price catalogue turns what runs into CUR-style billing lines, on demand or under a commitment.

Demand belongs to the workload, never to its configuration: resizing a machine changes its utilisation and its price, not
how much work arrives. The generator knows the truth about every resource (idle, oversized, legitimately bursty, a
month-end job, growing, memory-bound); the service only sees what a cloud API shows (inventory, hourly utilisation,
billing lines) and the Terraform in the account's repository.

Every random draw is keyed by (seed, resource, day), so a period can be re-run with or without a change and the same
workload sees the same demand: that is what gives the savings verifier a true answer to be scored against.
"""
import datetime
import functools
import math

import numpy as np

START = datetime.date(2026, 8, 10)          # day 0, a Monday
HISTORY_DAYS = 56                           # eight weeks of history when an estate is connected
SIZES = ["large", "xlarge", "2xlarge", "4xlarge", "8xlarge"]
VCPU = [2, 4, 8, 16, 32]
GB_PER_VCPU = 4
HOURS_MONTH = 730
NODE_SIZE = 3                                # node pools run 16-vCPU nodes
SCALE_TARGET = 0.7                           # the cluster autoscaler aims nodes at 70% CPU, one hour behind demand, and
                                             # removes at most one node an hour (the service models it without that delay)
CLOUDS = {   # on-demand $ per vCPU-hour, managed-database premium, $ per GB-month, 1-year commitment discounts
    "aws": {"vcpu_hour": 0.0480, "db_premium": 1.90, "gb_month": 0.080, "sp": 0.28, "ri": 0.34, "region": "us-east-1"},
    "azure": {"vcpu_hour": 0.0475, "db_premium": 1.95, "gb_month": 0.075, "sp": 0.26, "ri": 0.33, "region": "eastus"},
    "gcp": {"vcpu_hour": 0.0486, "db_premium": 1.85, "gb_month": 0.085, "sp": 0.28, "ri": 0.32, "region": "us-central1"},
}
ACCOUNTS = [   # key, cloud, external ref, name, env, (vms, node pools, databases, volumes)
    ("aws-payments", "aws", "418295730016", "Payments (prod)", "prod", (34, 2, 4, 22)),
    ("aws-data", "aws", "418295730027", "Data platform (prod)", "prod", (24, 2, 3, 18)),
    ("aws-dev", "aws", "418295730038", "Engineering (dev)", "dev", (26, 1, 1, 16)),
    ("azure-portal", "azure", "6f1c2d4e-8a3b-4c5d-9e7f-0a1b2c3d4e5f", "Customer portal (prod)", "prod", (22, 2, 3, 14)),
    ("gcp-ml", "gcp", "acme-ml-prod", "ML platform (prod)", "prod", (14, 3, 1, 12)),
    ("gcp-sandbox", "gcp", "acme-sandbox", "Sandbox (dev)", "dev", (16, 1, 1, 10)),
]
ACCOUNT = {a[0]: a for a in ACCOUNTS}
CLASSES = {   # truth class -> probability, by kind and environment
    ("vm", "prod"): {"right": .36, "oversized": .22, "idle": .06, "bursty": .12, "monthly": .06, "growing": .12, "membound": .06},
    ("vm", "dev"): {"right": .22, "oversized": .33, "idle": .25, "bursty": .10, "growing": .05, "membound": .05},
    ("db", "prod"): {"right": .40, "oversized": .35, "growing": .15, "membound": .10},
    ("db", "dev"): {"right": .30, "oversized": .50, "membound": .20},
    ("pool", "prod"): {"right": .5, "oversized": .5},
    ("pool", "dev"): {"right": .4, "oversized": .6},
    ("volume", "prod"): {"in_use": .75, "idle": .15, "weekly": .10},
    ("volume", "dev"): {"in_use": .60, "idle": .30, "weekly": .10},
}
NAMES = {"right": ["web", "api", "worker", "cache", "search", "gateway", "queue"], "oversized": ["api", "worker", "web", "admin", "cron"],
         "idle": ["test", "jenkins-old", "poc", "tmp", "migration"], "bursty": ["etl", "batch", "reindex", "nightly"],
         "monthly": ["billing-close", "invoicing", "month-end"], "growing": ["ingest", "events", "stream", "ledger"],
         "membound": ["jvm", "cache", "analytics"]}
DB_NAMES = ["orders", "ledger", "users", "catalog", "events", "reporting", "sessions"]
POOL_NAMES = ["general", "services", "jobs", "platform"]


def day_date(day):
    return START + datetime.timedelta(days=int(day))


def type_name(cloud, kind, size):
    v = VCPU[size]
    if kind in ("vm", "pool"):
        return {"aws": f"m6i.{SIZES[size]}", "azure": f"Standard_D{v}s_v5", "gcp": f"n2-standard-{v}"}[cloud]
    return {"aws": f"db.m6i.{SIZES[size]}", "azure": f"GP_Gen5_{v}", "gcp": f"db-custom-{v}-{v * GB_PER_VCPU * 1024}"}[cloud]


def price(cloud, kind, size=None, gb=None):
    """On-demand $ per hour: an instance or node of `size`, a database of `size`, or a volume of `gb`."""
    c = CLOUDS[cloud]
    if kind == "volume":
        return gb * c["gb_month"] / HOURS_MONTH
    return VCPU[size] * c["vcpu_hour"] * (c["db_premium"] if kind == "db" else 1.0)


def _ext_id(cloud, kind, account, name, rng):
    if cloud == "aws":
        prefix = {"vm": "i-", "volume": "vol-"}.get(kind)
        if prefix:
            return prefix + "".join(rng.choice(list("0123456789abcdef"), 17))
        return f"arn:aws:{'eks' if kind == 'pool' else 'rds'}:us-east-1:{ACCOUNT[account][2]}:{'nodegroup/main' if kind == 'pool' else 'db'}/{name}"
    if cloud == "azure":
        rtype = {"vm": "Microsoft.Compute/virtualMachines", "volume": "Microsoft.Compute/disks", "pool": "Microsoft.ContainerService/managedClusters/main/agentPools",
                 "db": "Microsoft.DBforPostgreSQL/flexibleServers"}[kind]
        return f"/subscriptions/{ACCOUNT[account][2]}/resourceGroups/portal/providers/{rtype}/{name}"
    rtype = {"vm": "zones/us-central1-a/instances", "volume": "zones/us-central1-a/disks", "pool": "locations/us-central1/clusters/main/nodePools", "db": "instances"}[kind]
    return f"projects/{ACCOUNT[account][2]}/{rtype}/{name}"


@functools.lru_cache(maxsize=8)
def estate(seed):
    """Every resource of the estate (including the ones teams will launch later), with its configuration on day 0 and
    the generator's truth. Returns a tuple of dicts."""
    rng = np.random.default_rng([seed, 1])
    out = []

    def pick(kind, env):
        p = CLASSES[(kind, env)]
        return str(rng.choice(list(p), p=list(p.values())))

    for acct, cloud, _ref, _name, env, (n_vm, n_pool, n_db, n_vol) in ACCOUNTS:
        used = {}

        def name_for(base):
            used[base] = used.get(base, 0) + 1
            return f"{base}-{used[base]:02d}"
        team = acct.split("-", 1)[1]
        extra = int(round(n_vm * 0.10))                       # teams launch about 10% more machines over the next weeks
        for i in range(n_vm + extra):
            cls = pick("vm", env)
            size = int(rng.integers(*{"right": (1, 5), "idle": (0, 4), "growing": (1, 4)}.get(cls, (2, 5))))
            r = {"kind": "vm", "cls": cls, "size": size, "schedule": "office" if env == "dev" and cls != "idle" and rng.random() < 0.6 else "always"}
            r["name"] = name_for(str(rng.choice(NAMES[cls])))
            r["launched_day"], r["terminated_day"] = 0, None
            if i >= n_vm:                                    # launched after the history: the replay's churn
                r["launched_day"] = int(rng.integers(HISTORY_DAYS + 1, HISTORY_DAYS + 90))
            elif rng.random() < 0.08:                         # launched during the history (some too recently to judge)
                r["launched_day"] = int(rng.integers(8, HISTORY_DAYS - 1))
            elif cls == "right" and rng.random() < 0.08:      # a service decommissioned by its team
                r["terminated_day"] = int(rng.integers(6, HISTORY_DAYS + 90))
            out.append({**r, **_demand_params(r, env, rng), "account": acct, "cloud": cloud, "env": env, "team": team})
        for i in range(n_pool):
            batch = acct == "gcp-ml" and i == n_pool - 1
            cls = "right" if batch else pick("pool", env)
            peak = float(rng.uniform(60, 150) if env == "prod" else rng.uniform(30, 70))
            r = {"kind": "pool", "cls": cls, "name": "training" if batch else POOL_NAMES[i], "size": NODE_SIZE, "batch": batch, "peak": peak,
                 "trough": float(rng.uniform(0.25, 0.4)), "growth": float(rng.uniform(0.0, 0.03)), "noise": 0.08, "launched_day": 0, "terminated_day": None}
            cap = VCPU[NODE_SIZE] * SCALE_TARGET
            if batch:
                r["min_nodes"], r["max_nodes"] = 0, 30
            else:
                low = math.ceil(peak * r["trough"] * 0.9 / cap)
                r["min_nodes"] = low if cls == "right" else max(low + 2, math.ceil(peak * rng.uniform(0.75, 1.05) / cap))
                r["max_nodes"] = math.ceil(peak * 1.6 * 2.2 / cap) + 2
            out.append({**r, "account": acct, "cloud": cloud, "env": env, "team": team})
        for i in range(n_db):
            cls = pick("db", env)
            size = int(rng.integers(2, 5) if cls != "growing" else rng.integers(1, 4))
            r = {"kind": "db", "cls": cls, "size": size, "schedule": "always", "name": f"{DB_NAMES[i % len(DB_NAMES)]}-{'prod' if env == 'prod' else 'dev'}",
                 "launched_day": 0, "terminated_day": None}
            out.append({**r, **_demand_params(r, env, rng, db=True), "account": acct, "cloud": cloud, "env": env, "team": team})
        for i in range(n_vol):
            cls = pick("volume", env)
            out.append({"kind": "volume", "cls": cls, "name": f"data-{i + 1:02d}", "gb": int(rng.choice([100, 200, 500, 1000, 2000])),
                        "iops": float(rng.uniform(200, 3000)), "launched_day": 0, "terminated_day": None, "account": acct, "cloud": cloud, "env": env, "team": team})
    for k, r in enumerate(out):
        r["idx"] = k
        r["external_id"] = _ext_id(r["cloud"], r["kind"], r["account"], r["name"], np.random.default_rng([seed, 2, k]))
        r["tf_address"] = tf_address(r)
    return tuple(out)


def _demand_params(r, env, rng, db=False):
    """Demand in vCPU relative to the size the workload was given on day 0 (its reference capacity)."""
    cls = r["cls"]
    p = {"vref": VCPU[r["size"]], "trough": float(rng.uniform(0.3, 0.45)), "weekend": 0.7 if env == "prod" else 0.5,
         "growth": 0.0, "noise": 0.10, "spike_rate": 1 / 300 if cls != "idle" else 0.0,
         "mem": float(rng.uniform(0.15, 0.38) if not db else rng.uniform(0.3, 0.42))}
    if cls == "right":
        p["level"] = float(rng.uniform(0.42, 0.6))
    elif cls in ("oversized", "membound"):
        p["level"] = float(rng.uniform(0.06, 0.18))
        if cls == "membound":
            p["mem"] = float(rng.uniform(0.47, 0.6))
    elif cls == "idle":
        p.update(level=float(rng.uniform(0.003, 0.012)), trough=1.0, weekend=1.0, mem=float(rng.uniform(0.05, 0.1)))
    elif cls in ("bursty", "monthly"):
        p.update(level=float(rng.uniform(0.04, 0.08)), trough=0.8, burst=float(rng.uniform(0.75, 0.95)),
                 burst_hour=int(rng.integers(0, 5)), burst_len=int(rng.integers(2, 4)), weekly=bool(rng.random() < 0.4))
    elif cls == "growing":
        p.update(level=float(rng.uniform(0.12, 0.18)), growth=float(rng.uniform(0.07, 0.10)))
    return p


def tf_address(r):
    kind, cloud, ident = r["kind"], r["cloud"], r["name"].replace("-", "_")
    rtype = {("vm", "aws"): "aws_instance", ("vm", "azure"): "azurerm_linux_virtual_machine", ("vm", "gcp"): "google_compute_instance",
             ("pool", "aws"): "aws_eks_node_group", ("pool", "azure"): "azurerm_kubernetes_cluster_node_pool", ("pool", "gcp"): "google_container_node_pool",
             ("db", "aws"): "aws_db_instance", ("db", "azure"): "azurerm_postgresql_flexible_server", ("db", "gcp"): "google_sql_database_instance",
             ("volume", "aws"): "aws_ebs_volume", ("volume", "azure"): "azurerm_managed_disk", ("volume", "gcp"): "google_compute_disk"}[(kind, cloud)]
    return f"{rtype}.{ident}"


# --- demand --------------------------------------------------------------------------------------------------------------
def _shape(trough, hours=np.arange(24)):
    return trough + (1 - trough) * (0.5 - 0.5 * np.cos(2 * np.pi * (hours - 4) / 24))      # trough at 04:00, peak at 16:00


def _workload_day(r, seed, day):
    """One day of one workload: (cpu demand in vCPU, memory demand in GB, attached hours, IOPS), each 24 hours."""
    rng = np.random.default_rng([seed, 3, r["idx"], day + 1000])
    dow, date, h = day % 7, day_date(day), np.arange(24)
    zero = np.zeros(24)
    if r["kind"] == "volume":
        if r["cls"] == "in_use":
            return zero, zero, np.ones(24), r["iops"] * _shape(0.3) * rng.lognormal(0, 0.15, 24)
        if r["cls"] == "weekly":                                         # attached on Sunday night for a restore test
            on = ((h >= 2) & (h < 5)).astype(float) if dow == 6 else zero
            return zero, zero, on, on * r["iops"] * 2
        return zero, zero, zero, zero
    noise = rng.lognormal(0, r["noise"], 24)
    growth = (1 + r["growth"]) ** ((day + h / 24) / 7)
    week = 1.0 if dow < 5 else r.get("weekend", 0.75)
    if r["kind"] == "pool":
        if r.get("batch"):                                              # training jobs: zero most of the time, then hundreds of vCPU
            d = np.zeros(24)
            for _ in range(rng.poisson(1.4)):
                s, ln = int(rng.integers(0, 24)), int(rng.integers(3, 9))
                d[s:s + ln] += rng.uniform(64, 256)
            return d, zero, zero, zero
        d = r["peak"] * _shape(r["trough"]) * week * growth * noise
        spikes = rng.random(24) < 1 / 250
        return d * np.where(spikes, rng.uniform(1.2, 1.5, 24), 1.0), zero, zero, zero
    vref = r["vref"]
    d = vref * r["level"] * _shape(r["trough"]) * week * growth * noise
    if r["cls"] in ("bursty", "monthly"):
        start, ln = r["burst_hour"], r["burst_len"]
        if r["cls"] == "bursty":
            if not r["weekly"] or dow == 6:
                ln = ln if not r["weekly"] else ln + 4
                d[start:start + ln] = vref * r["burst"] * rng.lognormal(0, 0.05, len(d[start:start + ln]))
        else:
            last = (date + datetime.timedelta(days=1)).month != date.month
            if last:
                d[12:] = vref * r["burst"] * rng.lognormal(0, 0.05, 12)
            elif date.day == 1:
                d[:7] = vref * r["burst"] * rng.lognormal(0, 0.05, 7)
    spikes = rng.random(24) < r["spike_rate"]
    d = d * np.where(spikes, rng.uniform(1.3, 1.8, 24), 1.0)
    if r.get("schedule") == "office":                                   # an instance scheduler stops dev machines nights and weekends
        d = d * ((h >= 7) & (h < 19) & (dow < 5))
    mem = vref * GB_PER_VCPU * r["mem"] * (0.92 + 0.08 * _shape(0.0)) * rng.lognormal(0, 0.02, 24) * growth ** 0.5
    return d, mem, zero, zero


@functools.lru_cache(maxsize=16)
def _demand(seed, d0, d1):
    res = estate(seed)
    n = d1 - d0
    cpu, mem, att, io = (np.zeros((len(res), n, 24)) for _ in range(4))
    for r in res:
        for k, day in enumerate(range(d0, d1)):
            cpu[r["idx"], k], mem[r["idx"], k], att[r["idx"], k], io[r["idx"], k] = _workload_day(r, seed, day)
    return cpu, mem, att, io


# --- configuration, usage and billing -----------------------------------------------------------------------------------------
def configs(seed, d0, d1, changes=()):
    """Per resource and day: alive, size (vm/db), min_nodes (pool). `changes`: [{resource: external_id, day, set: {...}}]."""
    res = estate(seed)
    days = np.arange(d0, d1)
    alive = np.zeros((len(res), len(days)), bool)
    size = np.zeros((len(res), len(days)), int)
    mins = np.zeros((len(res), len(days)), int)
    by = {}
    for ch in sorted(changes, key=lambda c: c["day"]):
        by.setdefault(ch["resource"], []).append(ch)
    for r in res:
        i = r["idx"]
        end = r["terminated_day"] if r["terminated_day"] is not None else 10 ** 9
        alive[i] = (days >= r["launched_day"]) & (days < end)
        size[i], mins[i] = r.get("size", 0), r.get("min_nodes", 0)
        for ch in by.get(r["external_id"], []):
            after = days >= ch["day"]
            s = ch["set"]
            if s.get("terminate"):
                alive[i] &= ~after
            if "size" in s:
                size[i][after] = s["size"]
            if "min_nodes" in s:
                mins[i][after] = s["min_nodes"]
    return alive, size, mins


def run(seed, d0, d1, changes=(), commitments=()):
    """Days d0..d1-1 of the estate under `changes` and `commitments`. Returns a dict of arrays (resource, day, hour):
    utilisation as a cloud API reports it, units running, on-demand and effective cost, plus the true demand, and the
    commitment lines. A commitment: {id, cloud, kind: compute_sp|db_ri, type (db_ri), amount ($/h of on-demand usage, or
    a count of instances), start_day}."""
    res = estate(seed)
    cpu_d, mem_d, att, io = _demand(seed, d0 - 1, d1)
    prev_cpu = cpu_d.reshape(len(res), -1)[:, 23:-1].reshape(len(res), d1 - d0, 24)   # demand one hour earlier, for the autoscaler
    cpu_d, mem_d, att, io = cpu_d[:, 1:], mem_d[:, 1:], att[:, 1:], io[:, 1:]
    alive, size, mins = configs(seed, d0, d1, changes)
    R, D = len(res), d1 - d0
    units, cpu_u, mem_u, od = (np.zeros((R, D, 24)) for _ in range(4))
    for r in res:
        i, cloud = r["idx"], r["cloud"]
        a = alive[i][:, None]
        if r["kind"] in ("vm", "db"):
            v = np.array(VCPU)[size[i]][:, None]
            run_h = (np.ones((D, 24)) if r.get("schedule") != "office" else
                     np.array([[(7 <= h < 19) and (d % 7 < 5) for h in range(24)] for d in range(d0, d1)], float))
            units[i] = a * run_h
            cpu_u[i] = np.where(units[i] > 0, np.minimum(cpu_d[i] / v, 1.0), 0)
            mem_u[i] = np.where(units[i] > 0, np.minimum(mem_d[i] / (v * GB_PER_VCPU), 1.0), 0)
            od[i] = units[i] * np.array([price(cloud, r["kind"], s) for s in size[i]])[:, None]
        elif r["kind"] == "pool":
            cap = VCPU[NODE_SIZE]
            want = np.clip(np.ceil(prev_cpu[i] / (cap * SCALE_TARGET)), mins[i][:, None], r["max_nodes"]).ravel()
            nodes = np.empty_like(want)
            for t in range(len(want)):                       # scale up at once, scale down one node an hour
                nodes[t] = want[t] if t == 0 or want[t] >= nodes[t - 1] else max(want[t], nodes[t - 1] - 1)
            units[i] = a * nodes.reshape(D, 24)
            cpu_u[i] = np.where(units[i] > 0, np.minimum(cpu_d[i] / np.maximum(units[i] * cap, 1e-9), 1.0), 0)
            od[i] = units[i] * price(cloud, "pool", NODE_SIZE)
        else:
            units[i] = a * att[i]
            od[i] = a * np.ones((D, 24)) * price(cloud, "volume", gb=r["gb"])
    eff = od.copy()
    lines = []
    kind = np.array([r["kind"] for r in res])
    cloud_of = np.array([r["cloud"] for r in res])
    for c in commitments:
        active = (np.arange(d0, d1) >= c["start_day"])[:, None] * np.ones((1, 24))
        if c["kind"] == "compute_sp":
            disc = CLOUDS[c["cloud"]]["sp"]
            mask = (cloud_of == c["cloud"]) & np.isin(kind, ["vm", "pool"])
            elig = od[mask].sum(0)
            cover = c["amount"] * active
            f = np.where(elig > 0, np.minimum(1.0, cover / np.maximum(elig, 1e-12)), 0.0)
            eff[mask] -= od[mask] * f[None] * disc
            used = np.minimum(cover, elig)
            unused = (cover - used) * (1 - disc)
            fee = cover * (1 - disc)
        else:
            disc = CLOUDS[c["cloud"]]["ri"]
            mask = (cloud_of == c["cloud"]) & (kind == "db")
            idx = np.nonzero(mask)[0]
            match = np.zeros((R, D, 24), bool)
            for i in idx:
                match[i] = (np.array([type_name(c["cloud"], "db", s) for s in size[i]])[:, None] == c["type"]) & (units[i] > 0)
            n = match.sum(0)
            cover = c["amount"] * active
            f = np.where(n > 0, np.minimum(1.0, cover / np.maximum(n, 1)), 0.0)
            eff -= od * match * f[None] * disc
            unit_price = price(c["cloud"], "db", next(k for k in range(len(SIZES)) if type_name(c["cloud"], "db", k) == c["type"]))
            used = np.minimum(cover, n)
            unused = (cover - used) * unit_price * (1 - disc)
            fee = cover * unit_price * (1 - disc)
        lines.append({"id": c["id"], "cloud": c["cloud"], "kind": c["kind"], "used": used, "unused_fee": unused, "fee": fee})
    return {"d0": d0, "d1": d1, "alive": alive, "size": size, "min_nodes": mins, "units": units, "cpu_util": cpu_u, "mem_util": mem_u, "io": io * (units > 0),
            "od": od, "eff": eff, "commit_lines": lines, "cpu_demand": cpu_d, "mem_demand": mem_d}


def bill(sim, days=None):
    """Everything paid in the run (or in the given absolute days): resource lines after commitments plus unused commitment fees."""
    sl = slice(None) if days is None else slice(days[0] - sim["d0"], days[1] - sim["d0"])
    return float(sim["eff"][:, sl].sum() + sum(c["unused_fee"][sl].sum() for c in sim["commit_lines"]))


# --- the account's Terraform repository ---------------------------------------------------------------------------------------
def _block(r, cfg):
    cloud, kind, ident, tags = r["cloud"], r["kind"], r["name"].replace("-", "_"), f'{{ Name = "{r["name"]}", env = "{r["env"]}", team = "{r["team"]}" }}'
    t = type_name(cloud, kind, cfg.get("size", r.get("size", 0))) if kind in ("vm", "db") else type_name(cloud, "pool", NODE_SIZE)
    if kind == "vm":
        body = {"aws": [f'ami           = "ami-0c55b159cbfafe1f0"', f'instance_type = "{t}"', "subnet_id     = var.private_subnet_id", f"tags          = {tags}"],
                "azure": [f'name                = "{r["name"]}"', "resource_group_name = azurerm_resource_group.portal.name", f'size                = "{t}"', "admin_username      = \"ops\""],
                "gcp": [f'name         = "{r["name"]}"', f'machine_type = "{t}"', 'zone         = "us-central1-a"']}[cloud]
    elif kind == "pool":
        mn = cfg.get("min_nodes", r["min_nodes"])
        body = {"aws": ["cluster_name    = aws_eks_cluster.main.name", f'node_group_name = "{r["name"]}"', f'instance_types  = ["{t}"]', "scaling_config {",
                        f"  min_size     = {mn}", f"  desired_size = {mn}", f"  max_size     = {r['max_nodes']}", "}",
                        "lifecycle {", "  ignore_changes = [scaling_config[0].desired_size]", "}"],
                "azure": [f'name                  = "{r["name"]}"', "kubernetes_cluster_id = azurerm_kubernetes_cluster.main.id", f'vm_size               = "{t}"',
                          "enable_auto_scaling   = true", f"min_count             = {mn}", f"max_count             = {r['max_nodes']}"],
                "gcp": [f'name    = "{r["name"]}"', "cluster = google_container_cluster.main.id", "node_config {", f'  machine_type = "{t}"', "}",
                        "autoscaling {", f"  min_node_count = {mn}", f"  max_node_count = {r['max_nodes']}", "}"]}[cloud]
    elif kind == "db":
        body = {"aws": ['engine            = "postgres"', f'instance_class    = "{t}"', "allocated_storage = 500", "multi_az          = true"],
                "azure": [f'name     = "{r["name"]}"', 'version  = "16"', f'sku_name = "{t}"'],
                "gcp": [f'name             = "{r["name"]}"', 'database_version = "POSTGRES_16"', "settings {", f'  tier = "{t}"', "}"]}[cloud]
    else:
        body = {"aws": ['availability_zone = "us-east-1a"', f"size              = {r['gb']}", 'type              = "gp3"'],
                "azure": [f'name                 = "{r["name"]}"', f"disk_size_gb         = {r['gb']}", 'storage_account_type = "Premium_LRS"', 'create_option        = "Empty"'],
                "gcp": [f'name = "{r["name"]}"', f"size = {r['gb']}", 'type = "pd-balanced"']}[cloud]
    rtype = r["tf_address"].split(".")[0]
    return [f'resource "{rtype}" "{ident}" {{'] + ["  " + b for b in body] + ["}", ""]


def terraform(seed, account, state):
    """The account's Terraform as it is today: {path: text}. `state`: {external_id: {size|min_nodes, alive}} from the inventory."""
    files = {}
    for r in estate(seed):
        if r["account"] != account:
            continue
        cfg = state.get(r["external_id"])
        if not cfg or not cfg.get("alive", True):
            continue
        path = {"vm": "compute.tf", "pool": "kubernetes.tf", "db": "databases.tf", "volume": "storage.tf"}[r["kind"]]
        files.setdefault(path, [f"# {ACCOUNT[account][3]}: managed by the platform team", ""]).extend(_block(r, cfg))
    return {p: "\n".join(v) for p, v in sorted(files.items())}
