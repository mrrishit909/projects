"""Tenants (a CRO's network, and a second sponsor that must see none of it) and demo tokens. The network itself arrives
through POST /v1/network:load.

    python -m trials.seed [--if-empty]
"""
import hashlib
import sys
import uuid

from core import db

TENANTS = {"net": "Halden Oncology Research Network", "other": "Calloway Therapeutics"}
ROLES = ["viewer", "feasibility_analyst", "study_director"]


def token(tenant, role):
    """Demo credentials for local use only."""
    return f"{tenant}-{role}-demo"


def main(if_empty=False):
    db.migrate()
    out = {}
    with db.tx() as c:
        if if_empty and c.execute("SELECT 1 FROM tenants LIMIT 1").fetchone():
            return print("already seeded")
        for key, name in TENANTS.items():
            t = uuid.uuid5(uuid.NAMESPACE_DNS, f"{key}.trial-site-optimizer.example")
            c.execute("INSERT INTO tenants (id, name) VALUES (%s,%s)", [t, name])
            for role in ROLES:
                c.execute("INSERT INTO api_tokens VALUES (%s,%s,%s,%s,%s)",
                          [hashlib.sha256(token(key, role).encode()).hexdigest(), t, uuid.uuid5(t, role), f"{role} ({name})", role])
            out[key] = t
    print("demo tokens:", ", ".join(token(t, r) for t in TENANTS for r in ROLES))
    return out


if __name__ == "__main__":
    main("--if-empty" in sys.argv)
