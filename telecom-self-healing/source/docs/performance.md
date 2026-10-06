# Performance

Measured on the machine below with the API on two uvicorn workers, one job worker and Postgres 16, all on the same host as the
client, after the recorded demo (`python -m core.scenario http://127.0.0.1:8260 --record`) had run.

## Read endpoints

`make load-test`: the topology with each link's latest counters, the command-centre overview (12 hours of alarms by family),
one cell's 48 hours against its seasonal normal with tomorrow's forecast, and the incident list; closed loop, 8 seconds per level.

Hardware: x86_64, 4 cores, Linux (client and server on the same machine)

| Concurrency | Requests | Throughput | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|---|
| 1 | 137 | 17.1 req/s | 56.9 ms | 64.2 ms | 68.1 ms | 0.00% |
| 4 | 544 | 67.6 req/s | 56.1 ms | 68.1 ms | 82.0 ms | 0.00% |
| 16 | 1107 | 136.9 req/s | 104.6 ms | 149.4 ms | 172.9 ms | 0.00% |

## Telemetry processing (the blueprint's bar: p95 under 3 s)

**Inside the live path.** Each 15-minute interval of the demo (264 cells and 74 links of counters, the interval's vendor alarms,
the configuration log) is stored, every cell is scored against its normal range, KPI_ANOMALY alarms are raised, every alarm is
correlated and the changed incidents are re-ranked and written. In the recorded demo that took **p95 21.8 ms per interval**
(max 23.1 ms) over the 12 intervals of the alarm storm, and p95 26.9 ms (max 29.4 ms) over the 24 intervals after the plan.

**Through the API.** Full-interval batches posted to `POST /v1/telemetry/batch` as a probe would: every cell and link of the
metro (338 samples) plus that interval's alarms, 32 batches replayed from the stored counters of the demo's last eight hours:

- concurrency 1: 16 batches of 338 samples (+32 alarms on average), wall 2.2s, client p50 87 ms p95 129 ms max 129 ms; server processing p50 62 ms p95 67 ms; 2435 samples/s
- concurrency 4: 16 batches of 338 samples (+25 alarms on average), wall 1.2s, client p50 171 ms p95 263 ms max 263 ms; server processing p50 126 ms p95 186 ms; 4695 samples/s

Client time includes HTTP and JSON; server time is what the endpoint reports (validation, storing, scoring, correlating). Both are
far inside the 3-second bar. One metro produces about 340 samples every 15 minutes; a network of 50,000 cells and their links would
be about 150 batches of this size per interval, roughly 70 samples a second on average against the 4,695 a second measured here
with four concurrent clients. Storms, replays after an outage and retention are what would need partitioned ingestion (Kafka) and a
columnar store, not the average rate.

## Jobs

Loading the network (generating four weeks: 0.93 million counter rows and 6.8 million values, training and scoring both models,
correlating the history's 3,790 alarms interval by interval, storing a week of counters) took 10.9 s in the worker (the job's own
timer). The whole seven-step recorded demo, from the load to the audit read, took 16.6 s of wall time.
