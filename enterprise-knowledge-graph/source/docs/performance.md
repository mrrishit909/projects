# Performance

Measured after the recorded demo (`python -m core.scenario http://127.0.0.1:8290 --record`), then `make load-test`, on the machine below:
API with two uvicorn workers, one job worker, Postgres 16, all on the same host as the client. Read endpoints as the on-call
engineer (the command centre for his view, an entity lookup by name, the entity-resolution page), closed loop, 8 seconds per level.

Hardware: x86_64, 4 cores, Linux (client and server on the same machine)

| Concurrency | Requests | Throughput | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|---|
| 1 | 146 | 18.1 req/s | 52.0 ms | 59.9 ms | 70.0 ms | 0.00% |
| 4 | 609 | 75.7 req/s | 52.0 ms | 56.1 ms | 62.3 ms | 0.00% |
| 16 | 1785 | 221.6 req/s | 64.0 ms | 89.8 ms | 110.2 ms | 0.00% |

## Answers and search

One hundred sequential `POST /v1/answers` as the engineer (ten questions in rotation: owners now and in a past month, why a
vendor was chosen, a contract price he may not see, a team lead, a free-text question): **p50 52.0 ms, p95 56.1 ms**, max 75.8 ms.
One hundred `POST /v1/search` (hybrid, k = 10): p50 52.0 ms, p95 56.1 ms. Each includes resolving the caller's principal, groups and
readable containers, the view's BM25 statistics and facts (cached per index version and view), the answer's verifier, and a
`query_audit` row. The index is held in each API process and rebuilt from Postgres when the index version changes; views are
cached per set of readable containers.

## Incremental sync (the blueprint's freshness bar: under 5 minutes)

| Sync | Objects changed | Chunks / assertions | Pipeline in the worker | From the request to queryable |
|---|---|---|---|---|
| Full, demo step 1 | 2,165 | 3,028 / 1,108 | 3.8 s | 6.1 s |
| Incremental, demo step 4 (two days, a failing service) | 10 | 13 / 5 | 0.42 s | 2.6 s |
| Incremental after 20 more simulated days | 79 | 109 / 27 | 0.43 s | 2.7 s |

"From the request to queryable" is the job's creation to the commit of the new index version, including the queue wait, the
principal and ACL sync, reconciling every fact again, and fitting and storing the LSA basis for the three API users' views. Most
of the incremental time is that fixed work, not the changed objects. With a connector polling every minute, a change in a
source is answerable within about a minute and three seconds here. Nothing in this slice was run at a real enterprise's volume:
the corpus is about 2,200 objects, and the in-memory index per API process is the first thing that would have to change (see the
README).

## Jobs

The security suite (23 principals, 9,303 probes, the non-interference rebuilds and the filter-off run) took 20.1 s in the worker.
The whole seven-step demo, including the corpus load, both syncs and the suite, took 34 s through the API.
