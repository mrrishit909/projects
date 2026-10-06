# Evaluation

Three held-out estates (seeds 101, 102, 103), each six accounts on three clouds with 56 days of history and 91 days after it. Every estate is analysed exactly as the service analyses one (utilisation, units and billing as a cloud API reports them); the days after the history and the generator's truth (true demand, the bill with and without each change) only score. `python -m finops.evaluate` reproduces this file.

## Workload forecast (four weeks ahead, per resource)

| Estate | Series | WAPE | Baseline: seasonal naive (last week again) | True p99 under the forecast's 90% path p99 |
|---|---|---|---|---|
| 101 | 146 | 0.078 | 0.122 | 90.4% |
| 102 | 144 | 0.076 | 0.113 | 91.0% |
| 103 | 149 | 0.079 | 0.127 | 90.6% |

CPU demand of every machine, database and node pool alive for the whole history (the batch training pool excluded: its jobs are random by construction). The last column is the calibration the rightsizer relies on: it sizes to the 90th percentile of the forecast's p99 across sample paths, so about 90% is the target.

## Rightsizing under the SLO, scored on the four weeks after

A recommendation is a false positive when, on the four weeks after the history, the resource at its new size would have broken the SLO by the generator's true demand: hours above 90% CPU more than 1% of running hours beyond what its current size shows, memory above 100% in any hour, a terminated machine or deleted volume that was needed, or a node-pool floor that adds more than 1% hot hours.

| Estate | Recommendations | False positives | FP rate | $/month | Baseline: 14-day average rule | Its FPs | Its FP rate | Its $/month (of which safe) |
|---|---|---|---|---|---|---|---|---|
| 101 | 93 | 0 | 0.0% | $25,758 | 138 | 69 | 50.0% | $44,689 ($14,296) |
| 102 | 85 | 0 | 0.0% | $21,999 | 134 | 67 | 50.0% | $36,762 ($14,527) |
| 103 | 89 | 0 | 0.0% | $23,213 | 148 | 77 | 52.0% | $44,954 ($13,012) |
| **all** | 267 | 0 | 0.0% | | 420 | 213 | 50.7% | |

The blueprint's bar is a false-positive rate under 10%. The baseline's false positives by what the generator knows the workload to be: oversized 71, bursty 50, weekly 26, monthly 25, membound 23, growing 18 (oversized machines too: the rule shrinks them until the *average* is 40%, which puts the daily peak over the line; weekly = a volume attached for a Sunday restore test). The rightsizer finds more safe savings than the rule's safe part because it can go two sizes down where the forecast allows. Review tasks (too little history, CPU pinned at 100%): 1, 3, 3.

Applied after change-risk gating (risk above 0.25 goes to review):

| Estate | Changes applied | False positives | $/month |
|---|---|---|---|
| 101 | 80 | 0 | $20,713 |
| 102 | 82 | 0 | $20,691 |
| 103 | 86 | 0 | $21,861 |

## Change-risk scoring

Trained on each estate's own history (features four weeks before the end of the history for every one- and two-size resize, labelled by the observed four weeks that followed), scored on every one- and two-size resize at the end of the history against the true four weeks after.

| Estate | Training rows (positives) | Scored | AUC | Baseline: headroom alone | Baseline: environment and kind rule | Brier | Mean predicted vs observed |
|---|---|---|---|---|---|---|---|
| 101 | 250 (162) | 247 | 0.987 | 0.963 | 0.607 | 0.0363 | 0.657 vs 0.672 |
| 102 | 247 (165) | 247 | 0.993 | 0.983 | 0.643 | 0.0265 | 0.692 vs 0.696 |
| 103 | 257 (166) | 255 | 0.972 | 0.955 | 0.608 | 0.0351 | 0.666 vs 0.659 |

Most of what the model knows is the forecast headroom at the new size, which the rightsizer already uses; the other features (burstiness, growth, backtest error, environment, kind) add a little. A change board's rule of thumb (production databases risky, dev safe) barely ranks better than chance here.

## Commitment portfolio, regret on the thirteen weeks after

The portfolio (one-year compute savings plans per cloud in $1/h blocks, database reservations per type) is chosen on twenty forecast scenarios of usage after the gated changes; then the changes are applied and the real thirteen weeks run, including machines the teams launch and retire. Regret is the cost over those weeks minus the cost of the best portfolio chosen with hindsight on the same weeks.

| Estate | No commitments | Hindsight best | Optimised: regret | Unused fees | Baseline (last month's minimum): regret | Unused fees |
|---|---|---|---|---|---|---|
| 101 | $373,897 | $282,910 | $1,483 (0.5%) | $549 | $9,289 (3.3%) | $11,859 |
| 102 | $335,374 | $253,530 | $3,003 (1.2%) | $230 | $14,033 (5.5%) | $15,978 |
| 103 | $362,246 | $273,729 | $2,436 (0.9%) | $513 | $7,901 (2.9%) | $10,487 |

Most of the value is committing at all (about a quarter off). The baseline's regret is the sequencing mistake: it commits to last month's usage before the rightsizing, and pays for commitments the smaller estate no longer uses. Thirteen weeks is the start of a one-year term; churn and growth over the rest of it are not scored.

## Savings verification, against the generator's truth

The gated changes and the optimised portfolio take effect on day 57; 28 days later each method estimates what the changes saved over those days. The truth is the generator's bill for the same days re-run without the changes (same demand, same commitments, same churn).

| Estate | Changes | True savings | Counterfactual re-pricing | Error | List price | Error | Difference-in-differences | Error | Before / after | Error |
|---|---|---|---|---|---|---|---|---|---|---|
| 101 | 80 | $19,667 | $19,522 | 0.7% | $18,809 | 4.4% | $14,507 | 26.2% | $26,947 | 37.0% |
| 102 | 82 | $20,467 | $20,161 | 1.5% | $18,660 | 8.8% | $31,989 | 56.3% | $26,969 | 31.8% |
| 103 | 86 | $20,372 | $20,199 | 0.9% | $19,925 | 2.2% | $15,205 | 25.4% | $27,045 | 32.8% |

The blueprint's bar is an attribution error under 5%. The counterfactual puts the old configurations' hourly on-demand cost back into each pricing pool and bills the pool again through the commitments in force, so a dollar above a savings plan saves a dollar and a dollar inside an under-used one saves nothing. What it cannot observe it has to model: the node-pool autoscaler (the service's model does not know the real one removes nodes one an hour), demand hidden while a pool ran at 100%, and a terminated machine's hours after it was gone (taken from its schedule before); its residual error was not broken down by source. This is the best case: the verifier prices with the same catalogue and allocation rule the generator bills by, where a real bill adds credits, private discounts and amortisation. Before/after counts the new commitments' discount as rightsizing; difference-in-differences scales each resource's cost before by how much the untouched resources' cost moved, which prices savings at their average discounted rate (the margin above a fixed commitment is paid at full price) and carries their own usage changes, so it misses in either direction; the list price ignores commitments.

