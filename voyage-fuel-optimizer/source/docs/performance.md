# Performance

Measured after recording the demo (`python -m core.scenario --record`), then `make load-test` on the machine below: API with two uvicorn workers, one job worker, Postgres 16, all on the same host as the client. Read endpoints after the demo (the fleet overview, the demo voyage with its AIS track, events and plans, its plan-against-actual variance over 266 sailed hours, and a vessel's fuel-against-speed performance), closed loop, 8 seconds per level.

Hardware: x86_64, 4 cores, Linux (client and server on the same machine)

| Concurrency | Requests | Throughput | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|---|
| 1 | 149 | 18.6 req/s | 52.1 ms | 60.0 ms | 60.1 ms | 0.00% |
| 4 | 591 | 73.4 req/s | 52.1 ms | 60.0 ms | 67.3 ms | 0.00% |
| 16 | 1353 | 167.7 req/s | 84.1 ms | 133.0 ms | 151.4 ms | 0.00% |

## Route solve (the blueprint's KPI: under 30 s)

Time-dependent A* over the 0.5-degree North Atlantic grid (7,283 ocean nodes, 16 courses each), with the forecast read at the hour the ship would reach each node: **1.96 s** for a Rotterdam to New York voyage on the live stack above, and on the held-out evaluation a median of 1.7 s and a worst of 3.0 s over 132 solves ([evaluation.md](evaluation.md)), in one process.

## Jobs (live stack, timed from the client, including queueing and polling)

| Job | Time |
|---|---|
| Load the fleet (a year for six ships: 194 voyages, 1,710 noon reports, six fuel models fitted and scored) | 23.7 s in the worker (measured in-process) |
| `route.optimize` (forecast on the grid for 18 days, A* and the shortest route, both sailed through the forecast) | 3.6 s |
| `speed.optimize` (dynamic programming, 24-member ensemble, the P90 rule, and the service-speed comparison) | 2.7 s |
| `voyage.advance`, 48 hours (sailing, AIS, engine samples, noon reports, the monitor twice) | 2.3 s |
| `scenario.compare`, four alternatives from the ship's position | 13.7 s |
| The seven-step demo end to end | 54 s |

## Reporting gateway

One `POST /v1/noon-reports` with 200 reports, each validated and scored by its vessel's fuel model with an inference log row: 0.21 s, **about 950 reports a second** on one request. A fleet of 500 ships files 500 noon reports a day; the gateway is not the bottleneck, and hourly engine telemetry at that scale would go to a time-series store rather than this table (see the README).
