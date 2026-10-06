"""Scenario recalculation at the blueprint's scale: copies one calculation's activity and lineage rows until it has
`--lines` lines, then times the scenario job on it exactly as the worker runs it. Run it on a scratch copy of the
database, never on one you keep (it adds millions of rows).

    DATABASE_URL=.../carbon_bench python scripts/bench_scenario.py <calculation_id> --lines 10000000
"""
import argparse
import json
import time
import uuid

from core import db
from carbon import api

ACT = [c for c in api.AP_COLS if c != "tenant_id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("calculation_id")
    ap.add_argument("--lines", type=int, default=10_000_000)
    a = ap.parse_args()
    with db.tx() as c:
        calc = c.execute("SELECT * FROM calculation WHERE id = %s", [a.calculation_id]).fetchone()
        n = c.execute("SELECT count(*) AS n, max(activity_id) AS m FROM calculation_lineage WHERE calculation_id = %s", [calc["id"]]).fetchone()
        copies = -(-a.lines // n["n"])
        new = uuid.uuid4()
        c.execute("""INSERT INTO calculation (tenant_id, id, factor_version, lines, totals, result_hash, inputs_hash, lineage_coverage, model_versions, created_by)
                     SELECT tenant_id, %s, factor_version, lines * %s, totals, result_hash, inputs_hash, lineage_coverage, model_versions, created_by FROM calculation WHERE id = %s""",
                  [new, copies, calc["id"]])
        t0 = time.time()
        for k in range(copies):
            off = k * (n["m"] + 1)
            if k:
                c.execute(f"""INSERT INTO activity (id, tenant_id, {', '.join(ACT)})
                              SELECT id + %s, tenant_id, {', '.join(x if x != 'source_ref' else "source_ref || ':copy' || %s::text" for x in ACT)}
                                FROM activity WHERE id <= %s""", [off, k, n["m"]])
            c.execute("""INSERT INTO calculation_lineage (tenant_id, calculation_id, activity_id, supplier_key, scope, category, method, factor_id, co2e_kg)
                         SELECT tenant_id, %s, activity_id + %s, supplier_key, scope, category, method, factor_id, co2e_kg FROM calculation_lineage WHERE calculation_id = %s""",
                      [new, off, calc["id"]])
        total = c.execute("SELECT count(*) AS n FROM calculation_lineage WHERE calculation_id = %s", [new]).fetchone()["n"]
        c.execute("ANALYZE activity")
        c.execute("ANALYZE calculation_lineage")
        build = time.time() - t0
    job = {"tenant_id": calc["tenant_id"], "payload": {"name": "bench", "calculation_id": str(new), "actor_id": str(calc["created_by"]),
                                                       "freight_shift": {"from_mode": "air", "to_mode": "ocean", "share": 1.0, "exclude_urgent": True},
                                                       "supplier_decarbonisation": {"top_n": 20, "reduction": 0.3}}}
    runs = []
    for _ in range(3):
        t0 = time.time()
        with db.tx(calc["tenant_id"]) as c:
            r = api.scenario_job(c, job)
        runs.append((time.time() - t0, r["recalculation"]))
    print(json.dumps({"lines_in_calculation": total, "copies": copies, "build_seconds": round(build), "runs": runs}, indent=1))


if __name__ == "__main__":
    main()
