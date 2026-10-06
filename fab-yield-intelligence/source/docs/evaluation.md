# Evaluation

Three held-out fabs (seeds 101, 102, 103), 448 lots each, 14 excursions each across all five steps. Models are trained on lots 0-335 exactly as the service trains them and scored on lots 336-447; drift and root cause are scored on every excursion against the generator's truth. `python -m fab.evaluate` reproduces this file.

## Wafer-map pattern classifier

| Fab | Macro-F1 | Baseline (nearest centroid, radial profile) | Sent for review | Recall by pattern |
|---|---|---|---|---|
| 101 | 0.864 | 0.542 | 0.1% | none 0.997, scratch 0.739, cluster 0.872 |
| 102 | 0.925 | 0.666 | 0.1% | none 0.998, edge-ring 1.0, scratch 0.793, cluster 0.846 |
| 103 | 0.937 | 0.689 | 0.1% | none 1.0, edge-ring 0.903, donut 1.0, scratch 0.833, cluster 0.812 |

Macro-F1 over the patterns present in the test weeks; a wafer sent for review counts as a miss. Recall per pattern swings with how many examples of it the six training weeks happened to contain: a pattern seen in one short excursion is learned poorly, and a pattern never seen is sent for review rather than called normal (the novelty rule). Scratches and clusters come from handling and particles, not chambers.

**Trained on one fab, applied to all eight weeks of another** (seed + 1000), where every pattern occurs many times:

| Trained on | edge-ring | center | donut | random-high | scratch | cluster | Normal wafers wrongly flagged |
|---|---|---|---|---|---|---|---|
| 101 | 74% (68) | 88% (153) | 98% (242) | 93% (333) | 82% (113) | 87% (199) | 0.77% |
| 102 | 100% (32) | 96% (152) | 100% (26) | 98% (350) | 80% (103) | 85% (188) | 0.64% |
| 103 | 97% (78) | 98% (200) | 94% (170) | 100% (398) | 70% (108) | 89% (215) | 0.62% |

Recall per pattern, wafers in brackets. A pattern the training fab rarely saw is the weak spot; the cure is labels, not a bigger model.

## Yield before test

| Fab | MAE, all test wafers (pp) | Baseline: product's trailing 20-lot mean | MAE, excursion wafers | Baseline |
|---|---|---|---|---|
| 101 | 0.81 | 0.82 | None (0 wafers) | None |
| 102 | 0.88 | 1.18 | 2.5 (36 wafers) | 11.49 |
| 103 | 0.92 | 1.25 | 2.3 (81 wafers) | 9.77 |

The blueprint's bar is 2.5 percentage points. Most of the remaining error is incoming-material variation no sensor sees, and scratches and particle clusters, which no process sensor predicts.

## Drift detection on the chamber sensors

| Fab | Rule | Detected / detectable excursions | Median delay (lots) | False alarms per 1,000 runs |
|---|---|---|---|---|
| 101 | Bayesian online change-point | 14 / 14 | 1.0 | 0.12 |
| 101 | Shewhart 3-sigma | 13 / 14 | 1.0 | 3.73 |
| 102 | Bayesian online change-point | 14 / 14 | 2.0 | 0.04 |
| 102 | Shewhart 3-sigma | 13 / 14 | 1.0 | 3.25 |
| 103 | Bayesian online change-point | 14 / 14 | 2.5 | 0.0 |
| 103 | Shewhart 3-sigma | 13 / 14 | 1.0 | 3.8 |

An excursion is detectable when its chamber ran at least five wafers more than 3 sigma off its qualified baseline; some excursions never were (the tool processed no lots while it lasted, or the drift stayed small). The two rules catch about the same excursions about as fast; the change-point detector does it with a small fraction of the false alarms, which is what makes an alert worth reading across 27 chambers.

## Root cause ranking

| Fab | Excursions ranked | Full: top-1 | Full: top-3 | Commonality + change-point: top-3 | Commonality only: top-3 |
|---|---|---|---|---|---|
| 101 | 13 | 92% | 100% | 100% | 92% |
| 102 | 13 | 100% | 100% | 100% | 100% |
| 103 | 14 | 100% | 100% | 100% | 100% |
| **all** | 40 | 98% | 100% | 100% | 98% |

The blueprint's bar is top-3 recall above 85% on injected faults. An excursion is ranked when the classifier called its pattern on at least five wafers from the faulty chamber; the window is eight lots either side of the first. Commonality alone is confused when two excursions overlap or a pattern has two possible steps (random-high comes from deposition or implant); the change-point on the chamber's own sensor is what separates them.

