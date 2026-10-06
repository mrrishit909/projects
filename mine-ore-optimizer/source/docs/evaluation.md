# Evaluation

Three held-out mines (seeds 101, 102, 103): each a different orebody, shovel panels and fleet. Each runs 14 shifts of history under its legacy dispatch; the models are trained on shifts 0-9 exactly as the service trains them and scored on shifts 10-13. Truth comes from the generator, which the service never reads. `python -m mine.evaluate` reproduces this file.

## Grade estimation (exploration holes only, scored on every block without a hole)

| Mine | Blocks | Kriging RMSE (%Cu) | IDW² RMSE | Nearest hole RMSE | Kriging: class wrong at the cut-offs | IDW² | Nearest | 80% interval coverage | As RMSE ppm (kriging / IDW²) | BWi RMSE (kriging / IDW²) |
|---|---|---|---|---|---|---|---|---|---|---|
| 101 | 28,020 | 0.0492 | 0.0693 | 0.0871 | 11.5% | 16.1% | 21.3% | 89% | 25.7 / 49.1 | 0.23 / 0.44 |
| 102 | 28,020 | 0.0515 | 0.0785 | 0.0885 | 11.1% | 14.3% | 18.9% | 86% | 31.1 / 60.3 | 0.22 / 0.44 |
| 103 | 28,020 | 0.0496 | 0.08 | 0.1046 | 11.0% | 16.7% | 20.6% | 85% | 32.1 / 60.0 | 0.24 / 0.41 |

A block's class (high grade, low grade, waste at 0.45 and 0.25 %Cu) decides where it is hauled, so the misclassification rate is the number that costs money. The 80% interval is the posterior's 10th to 90th percentile; it held 85%-89% of the true grades, so the stated spread is a little wider than it needs to be on these mines.

## Truck cycle time (blueprint bar: MAPE under 10%)

| Mine | Test cycles | Model MAPE | Physics baseline MAPE | On wet shifts: model | baseline | Fuel model MAPE |
|---|---|---|---|---|---|---|
| 101 | 4,115 | 4.48% | 11.21% | 4.64% | 16.22% | 4.46% |
| 102 | 3,726 | 4.29% | 9.82% | 4.26% | 13.52% | 3.94% |
| 103 | 3,516 | 4.93% | 12.0% | 5.28% | 14.51% | 4.05% |

The baseline is the haul profile over the manufacturer's speed-on-grade curve at nominal payload on a dry road, plus nominal loading and dumping: it knows the geometry exactly and nothing else. The model learns queues (from what the dispatcher saw when it sent the truck), wet roads, payload and truck age. Most of the remaining error is queueing that had not formed yet when the truck was dispatched.

## Engine anomaly detection

Scored on six further shifts per mine with eight failures told to the generator in each (cooling and oil failures have a precursor; tyres and electrics do not), because the history's four test shifts hold only a handful. A precursor failure counts as detected when an alarm fires on that truck in the three hours before it; any other alarm is false.

| Mine | Rule | Detected / precursor failures | Median lead (min) | False alarms | per 1,000 truck-hours |
|---|---|---|---|---|---|
| 101 | Per-truck normal, 2 windows > 4 sd | 37 / 37 | 64 | 1 | 0.58 |
| 101 | Manufacturer thresholds | 27 / 37 | 25 | 44 | 25.47 |
| 102 | Per-truck normal, 2 windows > 4 sd | 30 / 30 | 63 | 1 | 0.58 |
| 102 | Manufacturer thresholds | 18 / 30 | 18 | 54 | 31.36 |
| 103 | Per-truck normal, 2 windows > 4 sd | 33 / 33 | 60 | 3 | 1.72 |
| 103 | Manufacturer thresholds | 19 / 33 | 32 | 54 | 31.0 |

On the history's own test shifts: mine 101: model 1/1, 0.0 false per 1,000 h, thresholds 0/1, 21.94; mine 102: model 4/4, 1.66 false per 1,000 h, thresholds 3/4, 24.94; mine 103: model 4/4, 0.0 false per 1,000 h, thresholds 1/4, 25.47.
The thresholds' false alarms are hot afternoons on hard-working trucks and one-window sensor glitches; the per-truck normal knows the duty and the air temperature, and the two-window rule ignores glitches. Tyre and electrical failures have no precursor and neither rule sees them coming.

## Mill throughput forecast

| Mine | Test hours | Mean t/h | Forecast MAE (t/h) | Trailing 12-hour mean MAE |
|---|---|---|---|---|
| 101 | 48 | 3,413.9 | 118.8 | 683.8 |
| 102 | 48 | 3,860.5 | 365.4 | 692.6 |
| 103 | 48 | 3,885.1 | 220.0 | 357.2 |

One fitted parameter on top of the mill's hardness curve, fed the estimator's hardness of the bin's blend and what the bin and the feed can supply. Unplanned mill trips fall in the test hours too, and nothing here forecasts them.

## Dispatch, blend and the economic objective

Each mine runs its next shift three times: a dyke (true grade at 30% over a 45 m radius) ahead of S1 with three breakdowns in the first four hours, the same ahead of S2, and an undisturbed shift. Four hours in, each method re-plans from the service's estimates (the lab's blast-hole assays have come back), and the generator plays out the last eight hours under it on the same random draws. Net value: mill value less fuel and rehandle, plus the change in what the stockpiles and the bin are worth. All differences are against the baseline plan kept.

| Mine | Scenario | Trucks up | baseline plan, kept | heuristic re-plan | nearest free shovel | MIP + robust blend | MIP + mean-only blend | MIP, proportional reclaim | MIP rates by need-based dispatch |
|---|---|---|---|---|---|---|---|---|---|
| 101 | dyke ahead of S1, three breakdowns | 25 | $1.15M | -36k | -141k | +101k | +104k | +67k | +64k |
| 101 | dyke ahead of S2, three breakdowns | 25 | $1.50M | +257k | +102k | +195k | +191k | +135k | +194k |
| 101 | no disruption | 28 | $2.01M | +0k | +62k | +92k | +95k | +60k | +85k |
| 102 | dyke ahead of S1, three breakdowns | 25 | $1.14M | +87k | -66k | +157k | +156k | +151k | +102k |
| 102 | dyke ahead of S2, three breakdowns | 25 | $1.79M | +95k | +61k | +53k | +47k | +32k | +10k |
| 102 | no disruption | 28 | $2.02M | +0k | +52k | +97k | +97k | +84k | +13k |
| 103 | dyke ahead of S1, three breakdowns | 25 | $0.99M | -3k | -109k | -62k | -58k | -122k | -53k |
| 103 | dyke ahead of S2, three breakdowns | 25 | $1.77M | -60k | -16k | +199k | +213k | +206k | +131k |
| 103 | no disruption | 28 | $2.28M | -264k | -64k | +91k | +103k | +107k | +26k |

| Over the disrupted shifts (6) | Net value vs plan kept | Better in | With stockpiled ore at 90% | Copper (t) | Fuel (L) | Tonnes moved | Waste moved (t) | High grade to its stockpile (t) | Hours in the grade window (of 8) | Hours over the As limit |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline plan, kept | +0k | 0 of 6 | +0k | +0.0 | +0 | +0 | +0 | 2,060 | 4.5 | 1.2 |
| heuristic re-plan | +57k | 3 of 6 | +60k | +3.2 | -112 | +271 | -903 | 2,708 | 4.5 | 1.0 |
| nearest free shovel | -28k | 2 of 6 | -42k | +2.3 | -133 | +477 | +4,389 | 2,443 | 3.8 | 1.0 |
| MIP + robust blend | +107k | 5 of 6 | +94k | +16.6 | -502 | -719 | +228 | 9,186 | 6.3 | 0.5 |
| MIP + mean-only blend | +109k | 5 of 6 | +91k | +19.1 | -492 | -752 | +228 | 8,715 | 6.0 | 0.5 |
| MIP, proportional reclaim | +78k | 5 of 6 | +82k | +7.7 | -427 | -754 | +228 | 6,984 | 3.7 | 0.3 |
| MIP rates by need-based dispatch | +75k | 5 of 6 | +56k | +16.1 | -372 | -492 | +723 | 8,376 | 6.0 | 0.5 |

Against the strongest baselines: the MIP with the robust blend beats the heuristic re-plan by +50k a shift on average (better in 3 of 6) and nearest-free-shovel dispatch by +135k (better in 5 of 6). On the undisturbed shifts it changes the plan kept by +93k (better in 3 of 3).
Blend assay deviation (mean |hourly mill feed − 0.58 %Cu|, tolerance 0.1): MIP + robust blend 0.067, MIP + mean-only blend 0.073, MIP, proportional reclaim 0.101, baseline plan, kept 0.094.
The twin's paired prediction of the MIP plan against the plan kept, next to what the generator then did: +144k vs +101k, +213k vs +195k, +155k vs +92k, +113k vs +157k, +56k vs +53k, +115k vs +97k, +60k vs -62k, +160k vs +199k, +126k vs +91k.

## Dispatch solve time (blueprint bar: under 10 s for 200 vehicles)

| Shovels | Trucks | Formulation | Variables | Constraints | Solve (median of 3) | Worst | Optimality gap |
|---|---|---|---|---|---|---|---|
| 6 | 28 | trucks counted per current shovel | 65 | 131 | 0.02 s | 0.02 s | 0.18% |
| 12 | 100 | trucks counted per current shovel | 197 | 257 | 0.06 s | 0.07 s | 0.00% |
| 20 | 200 | trucks counted per current shovel | 489 | 429 | 0.09 s | 0.09 s | 0.26% |
| 20 | 200 | one group per truck | 4,089 | 609 | 0.33 s | 0.39 s | 0.45% |

SCIP through OR-Tools on the machine in docs/performance.md, the shovels' inputs replicated from a real mine's with their travel times perturbed. Trucks on the same shovel are interchangeable, so counting them is exact; the per-truck formulation is the same problem with 200 times the integer variables, shown for what it costs. Evaluation run time 81 s.

