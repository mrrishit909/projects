# Evaluation

Three held-out warehouses (seeds 101, 102, 103; 37 to 45 aisles, 10 to 14 rows a block, 18 to 22 pack stations, 250 robots each), never used by the demo. Each runs two 15-minute waves from the start of a shift: **steady** at 7,000 orders an hour, and **peak** at 10,000 an hour, more than the fleet can finish, during which two aisles close (at 5 and 6 minutes), a charger fails (7 minutes) and an operator stops the robot in the busiest aisle cell every 30 seconds from minute 3, releasing it a minute later. Every run uses the same planner and the same collision checker; the policies differ only in who gets which task, and see the same orders at the same moments. `python -m wh.evaluate` reproduces this file.

## The collision-free invariant

The floor's checker looks at every robot every second for a vertex conflict (two robots in one cell), an edge swap (two robots trading cells), a move into a closed aisle from outside, a paused robot moving, and a move that is not along an edge. Across all 18 runs it checked **4,050,000 robot-steps and found 0 conflicts**. The blueprint's bar is 99.99% collision-free; the measured rate is 100%. Execution here is exact (a robot moves when told), so this is the planner's and the repairs' invariant, not robustness to wheel slip or a late start, which the simulator does not model.

## Task assignment against FIFO

Cells travelled per completed order (one cell is 1.2 m), throughput and SLA (orders due within 10 minutes):

| Warehouse | Wave | FIFO nearest-free | Greedy best pair | CP-SAT | CP-SAT vs FIFO | Throughput FIFO → CP-SAT (orders/h) | Greedy (orders/h) | On time FIFO / CP-SAT | Overdue at end FIFO / CP-SAT |
|---|---|---|---|---|---|---|---|---|---|
| 101 | steady | 58.7 | 57.7 | 57.5 | -2.0% | 6,624 → 6,616 | 6,648 | 100.0% / 100.0% | 0 / 0 |
| 101 | peak | 74.1 | 56.5 | 56.6 | -23.6% | 6,632 → 7,232 | 7,300 | 100.0% / 100.0% | 6 / 5 |
| 102 | steady | 65.9 | 66.2 | 64.8 | -1.7% | 6,488 → 6,488 | 6,484 | 100.0% / 100.0% | 0 / 0 |
| 102 | peak | 84.0 | 65.9 | 64.9 | -22.7% | 6,076 → 6,604 | 6,648 | 100.0% / 100.0% | 6 / 6 |
| 103 | steady | 52.2 | 52.1 | 51.2 | -1.9% | 6,816 → 6,816 | 6,824 | 100.0% / 100.0% | 0 / 0 |
| 103 | peak | 65.2 | 50.4 | 48.1 | -26.2% | 7,468 → 8,164 | 8,100 | 100.0% / 100.0% | 2 / 1 |

**Steady wave**: travel per order, CP-SAT against FIFO -2.0% to -1.7%, greedy against FIFO -1.7% to +0.5%, CP-SAT against greedy -2.1% to -0.3%; throughput, CP-SAT against FIFO -0.1% to +0.0%.

**Peak wave**: travel per order, CP-SAT against FIFO -26.2% to -22.7%, greedy against FIFO -23.8% to -21.5%, CP-SAT against greedy -4.6% to +0.2%; throughput, CP-SAT against FIFO +8.7% to +9.3%.

The blueprint's bar is a travel-distance reduction above 15% against FIFO: met in every peak wave, not met in the steady ones. When the fleet keeps up, the backlog is small and the nearest free robot is already about the best choice for the oldest order, so there is little to gain; when orders pile up beyond what the fleet can finish, FIFO still sends robots across the floor to the oldest order while the other two choose an order near each free robot, and that choice is nearly all of the gain. CP-SAT's joint assignment with station capacity adds a little over greedy pairing at these sizes (a few robots free up each three-second epoch) and costs more solver time (below). On time is the share of completed orders delivered within their 10-minute SLA; overdue counts orders past due and not delivered when the window ends. All three policies share one station rule, in the baseline's favour: the least busy of the three nearest stations (the first FIFO version sent every robot to the nearest station, queued robots at the dead-end stations and gridlocked; that was a strawman, so it was changed).

## Replanning after a single robot stops

72 operator stops across the CP-SAT peak runs, each of the robot in the busiest aisle cell (the hardest case the rule can find). The stop is a local re-plan: every robot due through the stopped robot's cell within 30 s is re-planned at once (4.0 robots at the median, 10.5 at p95, 21 at most); robots due through it later (8.0 at the median, 16 at most) keep their plans until the next dispatch epoch, at most three seconds later and at least 27 s before they would reach it. Latency on one core, Python, including the D* Lite field repairs, timed with the three runs repeated one at a time so that nothing else competed for the CPU (the repeats reproduced the parallel runs' outcomes exactly; in the parallel runs, sharing four cores three ways, the same events took p50 41.1 and p95 240.8 ms):

| | p50 | p95 | max |
|---|---|---|---|
| Local re-plan, whole event (ms) | 34.1 | 204.4 | 628.0 |
| Local re-plan, per affected robot (ms) | 4.9 | 38.2 | 110.8 |
| Deferred re-plan at the next epoch, whole batch (ms; 72 batches, 605 robots) | 45.6 | 120.4 | 274.2 |

The blueprint's bar is under 250 ms for a local re-plan after a single-robot obstacle event: 69 of 72 events (96%) were under it as a whole, and 100.0% of per-robot re-plans. How the local re-plans were resolved: prioritized 32, prioritized+gave_way 22, cbs 15, prioritized+pulled 3 (CBS when 3 robots or fewer and it finishes within 16 search nodes; *gave_way* means a stuck robot handed its task back or switched station so the others could pass; *pulled* means a robot that had to wait where it stood pulled the robots due through its cell into the re-plan). Robots left without a plan after a stop: 0 (they wait in place, which every other plan respects, and are retried every epoch); still waiting at the end of the runs: 0.

Aisle closures in the same runs (6 events): 3.5 robots re-planned at the median, whole-event latency p50 25.8 ms, p95 79.2 ms, max 87.6 ms. Orders whose pick face is in a closed aisle are held, not failed: 42, 39, 35 held at the end of the CP-SAT peak runs.

## Control-loop freshness

The fleet state is one tick behind the floor plus the time that tick takes to compute. In the CP-SAT peak runs timed alone, one simulated second (telemetry in, events handled, dispatch every third second, every robot's next cell out) took p50 1.12–1.16 ms and p95 130.88–149.75 ms. 0 of 2,700 simulated seconds took longer than one second (the slowest took 717 ms; the slow ones are dispatch epochs, which carry the assignment solve and any deferred re-plans). Against the blueprint's bar of telemetry fresher than one second, that is 100.00% of seconds, on one Python process (in the parallel runs, all policies and waves, 1 of 16,200 seconds took longer than one second). Assignment solve per epoch (p50 / p95), CP-SAT: 47.77 / 137.58, 46.71 / 121.9, 44.36 / 95.33 ms; greedy (parallel runs): 8.34 / 24.15, 14.86 / 47.18, 9.36 / 26.39 ms.

## CBS against prioritized planning

A robot in an aisle at minute 7 of a peak run (warehouse 101) is stopped, and the *k* working robots nearest it are re-planned together against everyone else's reservations, eight different places per size. CBS gets two seconds; prioritized is the repair the system uses (with CBS switched off). Cost is the sum of the group's plan lengths in seconds.

| Robots | CBS solved | CBS median ms | CBS median nodes | Prioritized solved | Prioritized median ms | Cost, prioritized vs CBS (both solved) |
|---|---|---|---|---|---|---|
| 2 | 7 / 8 | 14.6 | 1.0 | 8 / 8 | 15.3 | +0.24% (7) |
| 4 | 2 / 8 | 44.2 | 3.5 | 8 / 8 | 45.9 | +4.55% (2) |
| 6 | 0 / 8 | – | – | 8 / 8 | 51.0 | – |
| 8 | 0 / 8 | – | – | 8 / 8 | 76.2 | – |
| 12 | 0 / 8 | – | – | 8 / 8 | 94.0 | – |
| 16 | 0 / 8 | – | – | 8 / 8 | 118.3 | – |
| 24 | 0 / 8 | – | – | 8 / 8 | 244.5 | – |
| 32 | 0 / 8 | – | – | 8 / 8 | 313.6 | – |

CBS's search grows with the number of conflicts among the group, and a dense group at peak has many: past two or three robots it stops finishing within its budget, while prioritized planning (with its give-way and pull-in steps) solved every group, at a total length close to CBS's where CBS did finish. Hence the split the system uses: CBS for a group of 3 or fewer when it finishes within 16 search nodes, prioritized otherwise, and never CBS over 250 robots.

## D* Lite against recomputing a distance field

A goal's distance field (3,452 cells) repaired in place after an obstacle appears, against computing it again from scratch (breadth-first, same Python), 150 random goals each. Mismatches between the two: 0.

| Change | Repair ms (median) | Recompute ms (median) | Vertices the repair touched (median) | Distances that changed (median) |
|---|---|---|---|---|
| one cell (a stopped robot) | 0.02 | 0.78 | 5 | 3 |
| a whole aisle closed | 0.05 | 0.80 | 12 | 12 |

The repair touches only the vertices whose distance changed (a median of 5 for a stopped robot and 12 for a closed aisle, of 3,452) and is 36 and 16 times faster than recomputing at the median. A closed aisle changes few distances because the highways and cross-aisles route around it; one field serves every robot heading to its goal, so each repair is paid once. On a map this size a recompute is also under a millisecond, so the saving matters for the number of fields kept (one per pick face in use), not for any single one.

## Battery fade forecast

Each pack's capacity fade fitted on its cycles up to a cutoff (square root of cumulative cycle stress, deeper and hotter cycles weighing more, plus a calendar term; each pack's coefficient shrunk toward its vendor's), forecast to the end of its history and scored against the generator's true state of health. Baseline: a straight line through the pack's own measured capacity over its last 90 days.

| Warehouse | Held out | Packs | MAE, points of SoH | Baseline | p90 | Baseline p90 | Packs with an unmodelled knee: MAE / baseline | Below 80% at the end: caught by model / baseline |
|---|---|---|---|---|---|---|---|---|
| 101 | 120 days | 238 | 0.21 | 0.57 | 0.43 | 1.21 | 0.39 / 0.49 (29) | 3 / 3 of 3 (false alarms 1 / 0) |
| 101 | 365 days | 173 | 0.49 | 2.30 | 0.88 | 5.57 | 0.87 / 1.88 (19) | 3 / 3 of 3 (false alarms 1 / 8) |
| 102 | 120 days | 235 | 0.33 | 0.47 | 0.46 | 0.95 | 0.98 / 0.66 (23) | 3 / 4 of 4 (false alarms 0 / 0) |
| 102 | 365 days | 183 | 0.67 | 2.32 | 1.00 | 6.18 | 1.66 / 3.20 (18) | 3 / 3 of 4 (false alarms 0 / 6) |
| 103 | 120 days | 243 | 0.14 | 0.53 | 0.29 | 1.07 | 0.15 / 0.50 (27) | 1 / 1 of 1 (false alarms 0 / 0) |
| 103 | 365 days | 182 | 0.28 | 2.28 | 0.63 | 5.37 | 0.25 / 1.61 (20) | 1 / 0 of 1 (false alarms 0 / 6) |

The state of health the battery planner uses today (fitted on everything) is off by 0.05–0.21 points against the truth. The model's form is the generator's own fade law, so on these packs it is the best case. About one pack in eight has a knee (faster fade below about 86%) the model does not know about: its error on those packs is above its overall error in 5 of 6 rows, and above the baseline's in 1 (warehouse 102 at 120 days, 0.98 against 0.66). Real packs would need the form itself checked against capacity-test or teardown data.

## Every run

| Warehouse | Wave | Policy | Orders in | Completed | Orders/h | Cells/order | Loaded share | On time | Overdue at end | Held | Collisions | Tick p95 ms | Wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 101 | peak | cpsat | 2,516 | 1,808 | 7,232 | 56.6 | 48% | 100.0% | 5 | 42 | 0 | 196.99 | 44.0 |
| 101 | peak | fifo | 2,516 | 1,658 | 6,632 | 74.1 | 36% | 100.0% | 6 | 43 | 0 | 145.31 | 33.7 |
| 101 | peak | greedy | 2,516 | 1,825 | 7,300 | 56.5 | 48% | 100.0% | 4 | 41 | 0 | 79.0 | 18.6 |
| 101 | steady | cpsat | 1,793 | 1,654 | 6,616 | 57.5 | 44% | 100.0% | 0 | 0 | 0 | 115.17 | 25.3 |
| 101 | steady | fifo | 1,793 | 1,656 | 6,624 | 58.7 | 44% | 100.0% | 0 | 0 | 0 | 29.39 | 6.6 |
| 101 | steady | greedy | 1,793 | 1,662 | 6,648 | 57.7 | 44% | 100.0% | 0 | 0 | 0 | 28.3 | 6.3 |
| 102 | peak | cpsat | 2,576 | 1,651 | 6,604 | 64.9 | 49% | 100.0% | 6 | 39 | 0 | 231.05 | 55.6 |
| 102 | peak | fifo | 2,576 | 1,519 | 6,076 | 84.0 | 37% | 100.0% | 6 | 39 | 0 | 170.01 | 37.6 |
| 102 | peak | greedy | 2,576 | 1,662 | 6,648 | 65.9 | 49% | 100.0% | 7 | 40 | 0 | 135.44 | 31.8 |
| 102 | steady | cpsat | 1,791 | 1,622 | 6,488 | 64.8 | 45% | 100.0% | 0 | 0 | 0 | 167.68 | 31.8 |
| 102 | steady | fifo | 1,791 | 1,622 | 6,488 | 65.9 | 45% | 100.0% | 0 | 0 | 0 | 45.6 | 9.6 |
| 102 | steady | greedy | 1,791 | 1,621 | 6,484 | 66.2 | 46% | 100.0% | 0 | 0 | 0 | 66.26 | 14.0 |
| 103 | peak | cpsat | 2,557 | 2,041 | 8,164 | 48.1 | 45% | 100.0% | 1 | 35 | 0 | 140.96 | 34.0 |
| 103 | peak | fifo | 2,557 | 1,867 | 7,468 | 65.2 | 34% | 100.0% | 2 | 36 | 0 | 128.05 | 28.9 |
| 103 | peak | greedy | 2,557 | 2,025 | 8,100 | 50.4 | 45% | 100.0% | 1 | 35 | 0 | 111.28 | 25.1 |
| 103 | steady | cpsat | 1,813 | 1,704 | 6,816 | 51.2 | 42% | 100.0% | 0 | 0 | 0 | 186.68 | 36.3 |
| 103 | steady | fifo | 1,813 | 1,704 | 6,816 | 52.2 | 42% | 100.0% | 0 | 0 | 0 | 35.48 | 7.7 |
| 103 | steady | greedy | 1,813 | 1,706 | 6,824 | 52.1 | 43% | 100.0% | 0 | 0 | 0 | 37.43 | 7.6 |
