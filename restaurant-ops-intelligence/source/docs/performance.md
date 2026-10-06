# Performance

Measured on the machine below with the API on two uvicorn workers, one job worker and Postgres 16, all on the same host as the
client, after the recorded demo (`python -m core.scenario http://127.0.0.1:8320 --record`) had run.

## Forecast refresh (the blueprint's bar: p95 under 2 minutes)

`POST /v1/forecast:refresh` for the whole chain, 20 times in a row: 50 stores x 12 items x 2 days, 57,600 fifteen-minute
slots with their 90% intervals, the conditions read from the tables (weather forecast, events, promotions), 1,200 forecast rows
written and a model-run row per store and day.

- From the request to the finished job, as the client sees it (polling every 50 ms): p50 1.14 s, p95 1.22 s, max 1.27 s.
- Inside the job (its own timer, recorded on the forecast run): p50 632 ms, p95 711 ms, max 744 ms.

That is about a hundredth of the bar. The model is fitted once, at load (4-5 s for six weeks of 50 stores, see
docs/evaluation.md); a refresh only applies it. A refit is a separate, slower job and is not what the KPI measures.

## Read endpoints

`make load-test`: the command centre (yesterday at every store, two weeks of KPIs, notices, alerts, models), the forecast for the
next day with one store item by item (the chain curve and every store's interval are aggregated on read from 600 item-day rows),
the waste-risk list (the hazard model on every open lot), and the seven-day margin bridge; closed loop, 8 seconds per level.

Hardware: x86_64, 4 cores, Linux (client and server on the same machine)

| Concurrency | Requests | Throughput | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|---|
| 1 | 90 | 11.2 req/s | 92.0 ms | 104.0 ms | 111.9 ms | 0.00% |
| 4 | 251 | 31.1 req/s | 124.0 ms | 168.1 ms | 208.0 ms | 0.00% |
| 16 | 429 | 51.7 req/s | 258.8 ms | 468.1 ms | 556.2 ms | 0.00% |

With 16 clients on two workers the p95 rises to about half a second: each read assembles arrays in Python from hundreds to a
few thousand rows. Nothing in them changes between advances of the clock, so a cache keyed on the clock would take most of it.

## Jobs

In the recorded demo, from the job being queued to its audit record (so including up to half a second of the worker's
polling): loading the chain (generating 56 days for 50 stores; writing 33,600 sales rows of 2 x 48 slots, 20,375 lots,
42,000 counts and the waste and prep logs; fitting the demand model twice, the consumption ratios and the hazard model; the
shrinkage scan) 22.4 s, of which the job's own timer says 22.0 s; a forecast refresh 0.7-0.9 s; recommending tonight's orders
for 50 stores (599 and 689 lines with their evidence) 0.5-0.9 s; telling the generator about the truck and the storm 0.3 s;
advancing three business days on the approved plans and writing them back 2.2 s; the three-plan replay of those days 0.8 s.
The whole seven-step recorded demo took 33 s of wall time.
