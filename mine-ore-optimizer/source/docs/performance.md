# Performance

Measured on the machine below with the API on two uvicorn workers, one job worker and Postgres 16, all on the same host as the
client (shared with other work at the time), after the recorded demo (`python -m core.scenario http://127.0.0.1:8280 --record`) had run.

## Read endpoints

`make load-test`: the command centre (12 hours of plant, fleet and alerts), one bench of the block model as a 4,800-block grid with
its assays, the fleet with four hours of engine deviations per truck, and the plant forecast under the plan in force; closed loop,
8 seconds per level.

Hardware: x86_64, 4 cores, Linux (client and server on the same machine)

| Concurrency | Requests | Throughput | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|---|
| 1 | 113 | 14.1 req/s | 56.5 ms | 143.2 ms | 152.9 ms | 0.00% |
| 4 | 284 | 35.0 req/s | 99.6 ms | 194.1 ms | 408.8 ms | 0.00% |
| 16 | 271 | 31.6 req/s | 328.1 ms | 1138.5 ms | 1286.5 ms | 0.00% |

Throughput flattens at four clients: the fleet and tiles reads are Python-side assembly (28 trucks' telemetry, 4,800 cells) on two
workers. A cache per clock tick would take most of it, since nothing changes between advances.

## Dispatch solve (the blueprint's bar: under 10 s for 200 vehicles)

From `docs/evaluation.md`: the dispatch MIP for 20 shovels and 200 trucks solves in 0.09 s (median of 3, stopped at the 0.5%
gap limit, 0.26% left) with trucks counted per shovel they are on, and in 0.33 s with one integer group per truck (4,089
variables). Through the API, `POST /v1/dispatch/optimize` on the demo mine (6 shovels, 25 trucks) took 0.44-0.80 s from the request
to the job's result over three runs (the solver's own time 136-154 ms; it builds the queueing curves and reads the estimates first).
The gap limit was 0.1% at first: in the Docker image (Python 3.14) the demo's solve then ran into the 10-second time limit, so the
limit is 0.5%.

## Telemetry ingestion

Engine telemetry posted to `POST /v1/telemetry` in batches of 500 ten-minute truck records, each validated, scored against its
truck's normal, checked for alerts and stored with a model-run row:

- concurrency 1: 4 batches, 2,000 records accepted, wall 0.9 s, p50 218 ms per batch; about 2,300 records a second
- concurrency 4: 16 batches, 8,000 records accepted, wall 1.9 s, p50 510 ms per batch; about 4,200 records a second

A fleet of 200 trucks reporting every 10 minutes is a third of a record a second, so ingestion is nowhere near a limit at this
granularity; one-second engine data (200 records a second per 200 trucks) would still fit, but its raw history belongs in a
time-series store, not these partitions.

## Jobs

In the recorded demo: loading the mine (generating 14 shifts, 13,691 truck cycles and 28,224 telemetry windows, fitting the
kriging variogram and estimating all 28,800 blocks, training and registering five models, issuing the baseline plan) took 21.0 s
in the worker (the job's own timer); re-estimating the block model after 72 blast-hole assays came back took 9.5 s; the twin's
20 replications of two plans over eight hours took 2.1 s; the blend MILP solved in 18 ms. The whole seven-step recorded demo,
from the load to the audit read, took 39 s of wall time.
