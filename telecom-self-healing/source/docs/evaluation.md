# Evaluation

Three held-out metros (seeds 101, 102, 103), each with its own topology (about 43 sites, 258 cells, 65 links), traffic and faults: four weeks with 24 faults in the first three and a dense fourth week of 18 (three of each kind: microwave backhaul degradation, fibre degradation, rain fade over two or three links, site power outage, handover misconfiguration, sleeping cell). Models are trained on the first three weeks exactly as the service trains them and scored on the fourth; correlation and root cause run over all four weeks interval by interval; capacity incidents are played forward after the history. Everything is scored against the generator's truth. `python -m noc.evaluate` reproduces this file.

## Alarm correlation

| Metro | Raw alarms | Incidents | Ratio | Alarms caused by faults | Topology: incidents holding them | Ratio on fault alarms | De-duplication: groups holding them | Ratio | By site: groups holding them | Ratio |
|---|---|---|---|---|---|---|---|---|---|---|
| 101 | 8,562 | 1,195 | 7.2:1 | 6,233 | 79 | **79:1** | 1208 | 5.2:1 | 120 | 51.9:1 |
| 102 | 5,172 | 1,096 | 4.7:1 | 3,602 | 79 | **46:1** | 963 | 3.7:1 | 100 | 36.0:1 |
| 103 | 4,721 | 897 | 5.3:1 | 3,689 | 77 | **48:1** | 899 | 4.1:1 | 104 | 35.5:1 |

| Metro | Purity: topology | De-duplication (groups over all alarms, purity) | By site (groups, purity) | Faults split over more than one incident |
|---|---|---|---|---|
| 101 | 99% | 2,339, 100% | 1,069, 97% | 9% |
| 102 | 99% | 1,991, 100% | 1,008, 97% | 2% |
| 103 | 100% | 1,724, 100% | 857, 98% | 5% |

Purity: the share of alarms whose cause is the main cause of the group they were put in (a noise alarm's cause is its own element and type). The blueprint's bar is a reduction above 20:1. On the alarms faults cause, topology correlation is past it on every metro. De-duplication barely compresses a storm, because every cell flaps on its own. Grouping by site compresses storms well too, but a storm behind a hub spans several sites, it puts unrelated noise together (lower purity) and it does not say which element is at fault. Over all alarms no method reaches 20:1 here: 22–30% of the raw alarms are noise with no fault behind them (VSWR, board temperature, sync, evening congestion on busy cells), mostly one-offs that no correlation can compress, and topology correlation keeps each one as its own incident.

## Root cause

| Metro | Faults ranked | Full: top-1 | Full: top-3 | Topology only: top-3 | Most alarms (baseline): top-3 | Learned ranker (other metros' tickets): top-3 |
|---|---|---|---|---|---|---|
| 101 | 46 | 98% | 100% | 98% | 46% | 100% |
| 102 | 45 | 91% | 98% | 93% | 42% | 100% |
| 103 | 44 | 98% | 100% | 98% | 50% | 100% |
| **all** | 135 | 96% | **99%** | 96% | 46% | 100% (top-1 96%) |

| Fault kind | Faults | Full: top-1 | Full: top-3 | Most alarms: top-3 |
|---|---|---|---|---|
| backhaul degradation | 21 | 100% | 100% | 14% |
| fibre degradation | 21 | 100% | 100% | 19% |
| handover misconfig | 21 | 100% | 100% | 90% |
| rain fade | 52 | 90% | 98% | 31% |
| site power outage | 20 | 95% | 100% | 100% |

The blueprint's bar is top-3 precision above 90%; here it is measured as the share of faults whose true element is among the top three of the incident that holds most of the fault's alarms. A fault is ranked when it caused at least three alarms. The most-alarmed element is usually a cell that flaps, not the link or router behind it. Topology alone ties a link with the router at its near end (both explain the same cells); the element's own alarms, telemetry and configuration changes break the tie. The learned ranker is logistic regression on the same six features, trained on the other two metros' incidents: the stand-in for asking whether learning the propagation (the blueprint's temporal graph network) would beat the hand-set weights.

## Anomaly detection (fourth week, per cell and interval)

| Metro | Detector | Precision | Recall | F1 | False flags per 1,000 healthy cell-intervals |
|---|---|---|---|---|---|
| 101 | model (two in a row) | 0.999 | 0.936 | 0.967 | 0.01 |
| 101 | model, one interval | 0.918 | 1.000 | 0.957 | 1.38 |
| 101 | largest single-feature z (two in a row) | 0.994 | 0.936 | 0.964 | 0.09 |
| 101 | static thresholds | 1.000 | 0.765 | 0.867 | 0.00 |
| 101 | static thresholds (two in a row) | 1.000 | 0.703 | 0.825 | 0.00 |
| 102 | model (two in a row) | 1.000 | 0.939 | 0.968 | 0.00 |
| 102 | model, one interval | 0.879 | 1.000 | 0.936 | 1.59 |
| 102 | largest single-feature z (two in a row) | 0.994 | 0.939 | 0.966 | 0.07 |
| 102 | static thresholds | 1.000 | 0.854 | 0.921 | 0.00 |
| 102 | static thresholds (two in a row) | 1.000 | 0.782 | 0.877 | 0.00 |
| 103 | model (two in a row) | 0.999 | 0.932 | 0.964 | 0.02 |
| 103 | model, one interval | 0.902 | 1.000 | 0.948 | 1.60 |
| 103 | largest single-feature z (two in a row) | 0.994 | 0.932 | 0.962 | 0.09 |
| 103 | static thresholds | 1.000 | 0.795 | 0.886 | 0.00 |
| 103 | static thresholds (two in a row) | 1.000 | 0.728 | 0.842 | 0.00 |

A cell-interval is impaired when a fault cost it at least 0.25% packet loss, throughput through a link the fault had squeezed, three points of handover success, its traffic (a sleeping cell) or its service. The service acts on the model's two-in-a-row flag.

**Faults detected in the fourth week, by kind** (any impaired cell flagged while the fault lasted; delay in intervals from the fault's start):

| Fault kind | Faults | Model (two in a row) | Median delay | Static thresholds | Median delay |
|---|---|---|---|---|---|
| backhaul degradation | 9 | 9 | 1 | 9 | 1 |
| fibre degradation | 9 | 8 | 1 | 4 | 0 |
| handover misconfig | 9 | 9 | 1 | 9 | 0 |
| rain fade | 20 | 20 | 1 | 17 | 1 |
| site power outage | 9 | 9 | 5 | 9 | 4 |
| sleeping cell | 9 | 9 | 1 | 0 | – |

Static thresholds are the vendor alarms' own thresholds. They catch what is loud and miss what is silent: a sleeping cell carries no traffic and raises no alarm, and a fibre degradation below the loss threshold leaks packets quietly. The model's normal range is per cell, per day type and per quarter hour.

## Traffic forecast (24 hours ahead, fourth week)

| Metro | Cell WAPE | Seasonal naive (same slot last week) | Link busy-hour peak WAPE | Seasonal naive |
|---|---|---|---|---|
| 101 | 0.079 | 0.105 | 0.024 | 0.021 |
| 102 | 0.080 | 0.106 | 0.027 | 0.022 |
| 103 | 0.080 | 0.106 | 0.022 | 0.023 |

Forecasts from every six hours of the fourth week, scored on cells with no fault nearby. Per cell, the profile beats last week's value because it averages out one week's noise; at the link's busy-hour peak, where dozens of cells add up and the noise cancels, the two are close, and the twin works at that level.

## Capacity incidents: plan on the forecast, then see what happened

| Metro | Incidents | Plans proposed | Doing nothing was enough | No plan inside the envelope | Plans that stayed inside the envelope (real traffic) | Twin's peak vs real peak on the links the plan touches (points) |
|---|---|---|---|---|---|---|
| 101 | 8 | 4 | 2 | 2 | 4 of 4 | 1.4 mean, 2.1 max |
| 102 | 8 | 7 | 0 | 1 | 7 of 7 | 2.0 mean, 3.9 max |
| 103 | 8 | 6 | 1 | 1 | 6 of 6 | 1.9 mean, 3.1 max |

**Over the following day, on the links each option touches** (all metros, incidents where a plan was proposed):

| Option | Intervals over the envelope (80%) | Intervals congested (over 100%) | Impaired cell-intervals | Moves a protected site |
|---|---|---|---|---|
| Do nothing | 625 | 349 | 21,048 | 0 of 17 |
| The optimiser's plan | 0 | 0 | 9,792 | 0 of 17 |
| Reroute everything possible (naive) | 5 | 0 | 5,760 | 2 of 17 |

Each incident degrades one microwave link that has sites with a standby path behind it, on a weekday or weekend afternoon; the service decides an hour in, from the last two hours of counters and the link's measured capacity. The plan is the optimiser's choice on the forecast; the generator then re-runs the same day (same traffic, same noise) under each option. Impaired cell-intervals include the packet loss on the degraded link itself, which rerouting only removes for the sites it moves. "Reroute everything" ignores the envelope, which is why it is not allowed to be proposed. The plan moves the fewest sites that fix capacity, so the sites it leaves behind keep the degraded link's packet loss until the link is repaired; that is the difference in impaired cell-intervals against rerouting everything.

