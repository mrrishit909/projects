# Performance

Measured after recording the demo against a live stack: the API with two uvicorn workers, one job worker, Postgres 16, all on
the same host as the client. Read endpoints after the demo (the fleet state with all 250 robots, the open-task list, the
re-plan log, the battery forecast), closed loop, 8 seconds per level (`make load-test`).

Hardware: x86_64, 4 cores, Linux (client and server on the same machine)

| Concurrency | Requests | Throughput | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|---|
| 1 | 131 | 16.3 req/s | 60.0 ms | 72.0 ms | 76.0 ms | 0.00% |
| 4 | 466 | 57.9 req/s | 64.3 ms | 87.4 ms | 98.8 ms | 0.00% |
| 16 | 879 | 107.8 req/s | 131.5 ms | 195.4 ms | 224.2 ms | 0.00% |

## The control loop

One `POST /v1/fleet:advance` of 120 simulated seconds, after the demo (250 robots at the peak rate, CP-SAT dispatch every
three seconds, two aisles closed), took **4.6 s** end to end through the API and the job worker: **26 times faster than real
time**. Inside it, one simulated second (telemetry in, events, dispatch, every robot's next cell out) took p50 1.21 ms and p95
106.48 ms; the slowest was 495.4 ms, and none took a second. That is the margin behind the freshness bar (telemetry fresher
than one second): the fleet state trails the floor by one tick plus the tick's compute. The held-out evaluation gives the same
picture over 2,700 timed seconds ([evaluation.md](evaluation.md), control-loop freshness).

## Stopping a robot through the API

After the demo, each of the eight robots standing in the busiest aisle cells was stopped with `POST /v1/robots/{id}/pause`
and released with `POST /v1/robots/{id}/resume`, one at a time:

| Robot | Robots re-planned at once | Due later (next epoch) | Re-plan (ms) | Stop, HTTP end to end (ms) | Resume re-plan (ms) | Resume, HTTP (ms) |
|---|---|---|---|---|---|---|
| R-232 | 7 | 4 | 86.83 | 304.7 | 2.46 | 236.0 |
| R-017 | 2 | 3 | 11.27 | 255.8 | 2.22 | 243.9 |
| R-007 | 3 | 6 | 141.78 | 360.0 | 1.65 | 223.8 |
| R-021 | 1 | 5 | 2.08 | 215.9 | 2.51 | 220.0 |
| R-030 | 3 | 4 | 45.31 | 260.0 | 3.43 | 231.9 |
| R-034 | 1 | 3 | 2.59 | 259.8 | 4.91 | 252.1 |
| R-095 | 4 | 8 | 30.46 | 275.8 | 1.57 | 203.9 |
| R-146 | 13 | 6 | 350.82 | 595.9 | 1.86 | 223.9 |

The re-plan itself (the blueprint's local-replan KPI, under 250 ms) was under 250 ms for seven of the eight; the eighth touched
13 robots at once and took 351 ms. The HTTP round trip adds about 200 ms on top: each request loads the 1.2 MB state, and
writes it back with the whole read model (250 robot states, every task, 250 route plans, the audit row) in its transaction.
That is this slice's shape, not the planner's cost: a production controller keeps the state in memory in one control-loop
process and writes the read model behind it.

## The demo

The seven-step demo, recorded with `python -m core.scenario http://127.0.0.1:8240 --record` against this stack, took 62 s:
loading the warehouse (graph, 250 robots, 168,622 battery cycles, the battery model fitted and backtested) and three advances
of 300, 150 and 240 simulated seconds, the recompute (two 240-second projections), and a 450-second sandbox run under three
dispatchers. The test suite (15 tests, the demo journey included) took 80 to 144 s in separate runs here, depending on what else the
machine was doing, and 83 s inside Docker.
