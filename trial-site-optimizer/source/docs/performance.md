# Performance

Measured after the recorded demo (`python -m core.scenario http://127.0.0.1:8300 --record`) with `make load-test`'s command: API with two
uvicorn workers, one job worker, Postgres 16, all on the same host as the client. Read endpoints after the demo (the command centre with
120 sites, a study's funnel and by-site pools, one site's history and investigators, a page of potentially eligible matches), closed
loop, 8 seconds per level.

Hardware: x86_64, 4 cores, Linux (client and server on the same machine)

| Concurrency | Requests | Throughput | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|---|
| 1 | 139 | 17.2 req/s | 56.1 ms | 63.9 ms | 64.2 ms | 0.00% |
| 4 | 545 | 67.9 req/s | 56.1 ms | 64.0 ms | 68.0 ms | 0.00% |
| 16 | 1020 | 125.8 req/s | 124.6 ms | 186.2 ms | 223.7 ms | 0.00% |

The funnel is computed once when the match job runs and stored with the study; computing it per request from 37,893 eligibility
events made p95 at concurrency 1 about 600 ms in the first measurement.

## The demo's work, call by call

Each call of the seven-step scenario timed end to end (request plus job polling every 0.1 s) on the second tenant of the same live stack:

| Call | Time | What it does |
|---|---|---|
| `POST /v1/network:load` | 16.0 s | generate 120 sites and their history, tokenise 37,893 records (787,524 events), store them, fit and backtest the enrolment and dropout models |
| `POST /v1/studies/parse` | 0.08 s | 22 criteria through the grammar and the validation |
| `POST /v1/match/evaluate` | 6.6 s | load every token, evaluate 22 criteria on 37,893 timelines, store 37,893 eligibility events and the population buckets: about 5,700 patients a second |
| `GET /v1/matches/{id}/explanation` | 0.08 s | re-derive one patient's decision with evidence and check it against the stored one |
| `POST /v1/sites/score` | 3.0 s | 120 sites, 2,000 predictive draws each, one model-run row per site |
| `POST /v1/portfolios/optimize` | 3.2 s | predictive draws again for the portfolio intervals, the MILP and two baselines |
| `POST /v1/network:advance` | 9.1 s | the simulator regenerates the network and runs twelve months at the plan's and the baseline's sites |

## The blueprint's optimisation KPI

"Optimization run < 2 min for 1,000 candidate sites": measured in `docs/evaluation.md` on a generated network of 1,000 sites and
4,974 historical studies. Fitting both models about 1 s, scoring all 1,000 sites with 2,000 predictive draws each about 1 s, the MILP
under 0.1 s to optimality; about 2 s end to end in one process. The MILP is small (one binary per site, a budget row, six region rows,
one academic row); the time that grows with the network is scoring, which is linear in sites and parallel by site.
