# Performance

Measured on the machine below with the API on two uvicorn workers, one job worker and Postgres 16, all on the same host as the
client, after the recorded demo (`python -m core.scenario http://127.0.0.1:8270 --record`) had run.

## Read endpoints

`make load-test`: the command-centre overview (84 days of spend by cloud and service), the recommendation list with evidence, the cost
explanation (two weeks of billing lines decomposed by resource) and the account list with inventory freshness; closed loop, 8 seconds per level.

Hardware: x86_64, 4 cores, Linux (client and server on the same machine)

| Concurrency | Requests | Throughput | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|---|
| 1 | 146 | 18.2 req/s | 59.8 ms | 80.0 ms | 104.5 ms | 0.00% |
| 4 | 540 | 67.0 req/s | 63.0 ms | 90.8 ms | 100.6 ms | 0.00% |
| 16 | 1123 | 138.6 req/s | 99.8 ms | 189.4 ms | 247.2 ms | 0.00% |

## Inventory freshness (the blueprint's bar: under 15 minutes)

An incremental sync of all six accounts (an inventory snapshot of every resource, one day of hourly utilisation and the day's billing
lines: 227 resources, 227 utilisation rows, 230 billing lines) took **72 to 117 ms** over four runs inside one transaction (the
simulator's own time to generate the day excluded; each run rolled back). At that rate one process refreshes about 1,900 resources a
second, so a 15-minute cadence is bounded by the clouds' API rate limits, not by this service; the slice syncs on connection and on
each simulated advance rather than on a timer. The backfill of an account (eight weeks: 28 to 62 resources, 1,505 to 3,422 billing
lines and as many utilisation rows) took 0.32 to 0.56 s in the recorded demo, and 1.54 s for the first account, which also pays for
generating the simulated estate. The four-week replay synced 254 resources and 6,441 billing lines in 1.7 s.

Freshness is enforced, not only measured: the account list reports each account's inventory age against the policy, and a
recommendation run turns every recommendation in an account whose inventory is older than 15 minutes into a review task
(`test_stale_inventory_becomes_a_review_task`).

## Jobs

The whole seven-step recorded demo, from starting the simulated clouds to the audit read, took 20.9 s of wall time through the API with
one worker, including the client's polling. From the jobs' queue times in the recording: the recommendation run (252 resources, with
the risk model's backtest) and the reads after it took 4.7 s, the commitment MILP (20 scenarios of 13 weeks) 1.6 s, and the SLO
simulation (three plans, 200 paths per change) together with all of step 6 took 4.0 s. `python -m finops.evaluate` (three estates, 21 weeks each, every model and the
truth re-runs) takes about 33 s.
