# Performance

Measured with `make demo` then `make load-test` on the machine below: API with two uvicorn workers, one job worker, Postgres 16, all on the same host as the client. Read endpoints after the demo (48 lots of overview, a tool with 240 runs per chamber and its change-point series, the alert list), closed loop, 8 seconds per level.

Hardware: x86_64, 4 cores, Linux (client and server on the same machine)

| Concurrency | Requests | Throughput | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|---|
| 1 | 96 | 12.0 req/s | 75.9 ms | 140.2 ms | 384.9 ms | 0.00% |
| 4 | 326 | 40.2 req/s | 100.0 ms | 168.0 ms | 191.8 ms | 0.00% |
| 16 | 515 | 62.3 req/s | 210.0 ms | 480.0 ms | 592.2 ms | 0.00% |

## Ingestion

One `POST /v1/lots/ingest` with 4 lots (100 wafers, 54,000 die measurements) took 1.05 s end to end: validation, storing lots, wafers and process events, the pattern classifier and the yield model on every wafer, a model-run row per inference, and the drift and excursion checks per lot. That is about **51,000 die measurements a second (3.1 million a minute) on one request in one process**. The blueprint's target is 10 million a minute sustained; this slice does not reach it in one process, and the path to it is the obvious one: batch ingestion in parallel workers (the work per lot is independent apart from the alert check) and the die arrays in a columnar store rather than Postgres.

## Jobs

Loading the fab (448 lots, 11,200 wafers, 6.0 million die measurements, training and registering three models) takes about 20 s in the worker; advancing 40 lots about 9 s; root cause about 1 s; the counterfactual for 11 lots with two alternatives about 3 s. The whole seven-step demo takes about 35 s.
