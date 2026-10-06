"""Tenants, demo tokens, and the people the tokens sign in as. The enterprise arrives through POST /v1/corpus:load and the
connector sync, which also brings each person's groups: the role on the token decides what they may do (RBAC), their
groups decide what they may read (the source systems' own permissions).

    python -m ekg.seed [--if-empty]
"""
import hashlib
import sys
import uuid

from core import db

TENANTS = {"halden": "Halden Systems", "other": "Brightwater Bank"}
ROLES = {"viewer": ("samuel.okafor@halden.example", "Samuel Okafor"), "analyst": ("ines.duarte@halden.example", "Ines Duarte"),
         "steward": ("morgan.lee@halden.example", "Morgan Lee")}


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
            t = uuid.uuid5(uuid.NAMESPACE_DNS, f"{key}.enterprise-knowledge-graph.example")
            c.execute("INSERT INTO tenants (id, name) VALUES (%s,%s)", [t, name])
            for role, (email, person) in ROLES.items():
                actor = uuid.uuid5(t, role)
                c.execute("INSERT INTO api_tokens VALUES (%s,%s,%s,%s,%s)", [hashlib.sha256(token(key, role).encode()).hexdigest(), t, actor, f"{person} ({role})", role])
                c.execute("INSERT INTO principal (id, tenant_id, kind, external_ref, display_name, actor_id) VALUES (%s,%s,'user',%s,%s,%s)",
                          [uuid.uuid5(uuid.UUID(str(t)), f"principal:{email}"), t, email, person, actor])
            out[key] = t
    print("demo tokens:", ", ".join(token(t, r) for t in TENANTS for r in ROLES))
    return out


if __name__ == "__main__":
    main("--if-empty" in sys.argv)
