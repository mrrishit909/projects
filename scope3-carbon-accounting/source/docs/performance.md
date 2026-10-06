# Performance

Measured on the machine below with the API on two uvicorn workers, one job worker and Postgres 16, all on the same host as the
client (and sharing it with other work, so treat the numbers as indicative). The demo's company holds 2,039,340 activity lines
(1,998,764 invoice lines after duplicates and refusals, 40,000 shipments, 576 bills).

## Read endpoints under load

`make load-test CALC=... LINE=... SUPPLIER=...` after the recorded demo (the demo's calculation, its traced line and its largest supplier): the Scope 3 inventory, one line's full lineage, the largest supplier's drill-down (its six
vendor records and the spend under them, an aggregate over its 60,126 invoice lines) and the review inbox, closed loop, 8 seconds per level.

Hardware: x86_64, 4 cores, Linux (client and server on the same machine)

| Concurrency | Requests | Throughput | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|---|
| 1 | 83 | 10.2 req/s | 52.1 ms | 247.9 ms | 256.7 ms | 0.00% |
| 4 | 258 | 31.9 req/s | 55.9 ms | 360.2 ms | 379.7 ms | 0.00% |
| 16 | 829 | 100.5 req/s | 68.9 ms | 406.1 ms | 477.5 ms | 0.00% |

The tail is the supplier drill-down; the inventory and lineage reads take a few milliseconds each on their own.

## The blueprint's KPI: scenario recalculation under 60 s for 10 million activity rows

`scripts/bench_scenario.py` copied the demo calculation's activity and lineage rows five times in a scratch copy of the database
(10,196,700 lines in one calculation, 8,499,495 of them carrying CO2e) and ran the scenario job on it exactly as the worker does
(all non-urgent intercontinental air moved to ocean, the top 20 suppliers of the engagement ranking cutting intensity 30%, paired
Monte Carlo):

| Run | Total | Scan and aggregate in Postgres | Recalculate (incl. the engagement ranking) | Monte Carlo |
|---|---|---|---|---|
| 1 | 41.5 s | 30.0 s | 10.3 s | 1.2 s |
| 2 | 39.6 s | 25.8 s | 13.0 s | 0.8 s |
| 3 | 40.6 s | 27.5 s | 12.2 s | 0.9 s |

**About 40 s for 10.2 million lines, under the 60 s bar**, on one Postgres with four cores. The recalculation itself is cheap
(1,868 groups); the cost is the scan and the engagement ranking's aggregate, both linear in the lines, so on this machine the bar
would be crossed somewhere around 15 million lines. The same job on the demo's 2 million lines took 13.9 s.

## Jobs in the recorded demo (2 million invoice lines)

The whole seven-step demo took 4 min 15 s against the live API.

| Job | Time | What it does |
|---|---|---|
| Import | 107.7 s (19,022 lines a second) | six vendor masters; 2,008,046 invoice lines read, normalised, deduplicated, 105,620 distinct inputs classified, 16,321 review tasks; 40,000 shipments; 577 bills; 34 disclosures |
| Calculation | 74.6 s | read and calculate 18.5 s, uncertainty and totals 1.6 s, store 2,039,340 lineage rows 43.5 s, check every line's lineage in SQL 11.0 s |
| Reproduction | 19.7 s | recalculate from the stored activities and hash; hash the stored lineage rows; bridge to EF-2025.1 |
| Scenario | 13.9 s | as above, on 1,699,899 lines carrying CO2e |

Storing a lineage row per line is the most expensive step and the price of the 100% lineage coverage KPI; a columnar store
(the blueprint's analytical plane) would hold it more cheaply. The import runs in one process; it would parallelise by subsidiary
and month, which this slice does not do.
