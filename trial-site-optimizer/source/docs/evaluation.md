# Evaluation

Three held-out research networks (seeds 201, 202, 203), 120 sites each with their investigators, five years of site history and the sites' tokenised patient records; four protocols each (nsclc_post_platinum, nsclc_second_line, melanoma_io_refractory, breast_her2). The models are trained on each network's history exactly as the service trains them; then the generator runs every protocol at every site, and that is the truth everything below is scored against. `python -m trials.evaluate` reproduces this file.

## Criteria translation (protocol text to the DSL)

| Wording | Protocols | Criteria | Translated exactly | Sent to review | Confidently wrong | Keyword baseline: exact |
|---|---|---|---|---|---|---|
| the wording the grammar was written against | 240 | 3,660 | 3,575 (97.7%) | 85 (2.3%) | 0 | 1,537 (42.0%) |
| wording written separately, never shown to the grammar | 240 | 3,660 | 330 (9.0%) | 3,330 (91.0%) | 0 | 964 (26.3%) |

Exact means every rule of the criterion equals the generator's structured truth (field, operator, value, unit, window, classes). The grammar's rule is to account for every word of a criterion or send it to review, so a translation it proposes is one a reviewer can accept: of the 3,575 and 330 it proposed, 0 were wrong, so the blueprint's acceptance bar (above 95% after review) is met by every proposal. Coverage is the honest limit: on wording it was written against it translates 97% and sends the deliberately hard phrasings ("advanced" without a stage, a conditional threshold, "half a year") to review; on wording it never saw it translates only the few phrases that happen to coincide, and the reviewer writes the rest. The keyword baseline guesses instead of abstaining and is confidently wrong on 1,745 and 1,376 criteria.

## Temporal eligibility engine

| Network | Protocol | Criterion values decided | Correct when decided | Same rules without time: correct | Truly eligible | Found (eligible or needs screening) | Same rules without time: found | Expected eligible vs truly eligible |
|---|---|---|---|---|---|---|---|---|
| 201 | nsclc_post_platinum | 71.5% | 99.81% | 94.63% | 351 | 347 (99%) | 0 (0%) | 321.6 vs 351 |
| 201 | nsclc_second_line | 66.5% | 99.69% | 95.68% | 268 | 266 (99%) | 0 (0%) | 260.4 vs 268 |
| 201 | melanoma_io_refractory | 69.4% | 99.76% | 95.08% | 506 | 505 (100%) | 0 (0%) | 464.8 vs 506 |
| 201 | breast_her2 | 62.6% | 99.72% | 94.47% | 130 | 130 (100%) | 0 (0%) | 129.9 vs 130 |
| 202 | nsclc_post_platinum | 74.8% | 99.72% | 94.74% | 290 | 284 (98%) | 0 (0%) | 321.7 vs 290 |
| 202 | nsclc_second_line | 69.1% | 99.65% | 95.73% | 282 | 281 (100%) | 0 (0%) | 291.9 vs 282 |
| 202 | melanoma_io_refractory | 72.6% | 99.68% | 95.13% | 630 | 628 (100%) | 0 (0%) | 626.8 vs 630 |
| 202 | breast_her2 | 64.6% | 99.66% | 94.53% | 189 | 188 (99%) | 61 (32%) | 189.5 vs 189 |
| 203 | nsclc_post_platinum | 72.5% | 99.77% | 94.65% | 323 | 317 (98%) | 0 (0%) | 316.6 vs 323 |
| 203 | nsclc_second_line | 67.1% | 99.67% | 95.68% | 295 | 292 (99%) | 0 (0%) | 297.3 vs 295 |
| 203 | melanoma_io_refractory | 69.0% | 99.79% | 95.04% | 608 | 606 (100%) | 0 (0%) | 606.5 vs 608 |
| 203 | breast_her2 | 62.6% | 99.71% | 94.44% | 201 | 201 (100%) | 54 (27%) | 213.4 vs 201 |

A criterion value is undecided when the record cannot answer it today: no lab inside the protocol's window, no recent ECOG, a biomarker never tested. Those patients are "potentially eligible, needs screening", and the site pool counts each of them by the chance its open criteria pass (the pass rate among patients whose record does answer). Decided values are wrong when the world moved since the measurement (a lab drifting inside its window, an ECOG that got worse) or the record is incomplete (a regimen given at another hospital). Without time, every "within 28 days" exclusion becomes "ever" and every stale lab counts: most truly eligible patients are lost.

## Site enrolment (12 months)

| Network | Protocol | Actual enrolled, 120 sites | Model total | Naive total | Model MAE per site | Naive MAE | Rank correlation, model | Naive | Inside the 80% interval, all sites | Sites expected to enrol 3+ |
|---|---|---|---|---|---|---|---|---|---|---|
| 201 | nsclc_post_platinum | 428 | 374.8 | 985.9 | 1.95 | 5.18 | 0.741 | 0.481 | 91% | 96% (45) |
| 201 | nsclc_second_line | 319 | 313.9 | 985.9 | 1.73 | 5.67 | 0.625 | 0.482 | 86% | 76% (38) |
| 201 | melanoma_io_refractory | 422 | 456.2 | 985.9 | 1.78 | 5.68 | 0.754 | 0.324 | 92% | 91% (53) |
| 201 | breast_her2 | 165 | 159.9 | 985.9 | 1.06 | 6.97 | 0.662 | 0.324 | 91% | 79% (14) |
| 202 | nsclc_post_platinum | 386 | 451.9 | 1241.2 | 2.19 | 7.28 | 0.617 | 0.405 | 89% | 87% (53) |
| 202 | nsclc_second_line | 450 | 417.4 | 1241.2 | 1.96 | 6.93 | 0.736 | 0.488 | 90% | 90% (51) |
| 202 | melanoma_io_refractory | 538 | 647.2 | 1241.2 | 1.94 | 6.35 | 0.821 | 0.396 | 88% | 84% (63) |
| 202 | breast_her2 | 211 | 255.0 | 1241.2 | 1.24 | 8.63 | 0.661 | 0.199 | 91% | 83% (29) |
| 203 | nsclc_post_platinum | 386 | 431.1 | 1115.0 | 2.12 | 6.41 | 0.543 | 0.396 | 92% | 86% (50) |
| 203 | nsclc_second_line | 358 | 397.8 | 1115.0 | 2.15 | 6.59 | 0.57 | 0.372 | 92% | 89% (47) |
| 203 | melanoma_io_refractory | 618 | 630.6 | 1115.0 | 1.99 | 5.56 | 0.813 | 0.392 | 91% | 89% (64) |
| 203 | breast_her2 | 244 | 288.9 | 1115.0 | 1.46 | 7.36 | 0.661 | 0.356 | 92% | 91% (35) |

The model: a negative-binomial rate per eligible patient-month (site type, competing trials, the lead investigator's trials in the indication; studies that filled their slots treated as censored) with each site's own history as a gamma frailty, times the months a Weibull activation model expects the site to be open (each site's contracting history shrunk toward its type). The naive baseline is the site's historical average enrolment per study: it knows nothing about this protocol's pool, so its totals are several times too high and its ranking weaker. Calibration: the 80% intervals held the actual count at 86%-92% of sites, and at 76%-96% of the sites expected to enrol three or more. Most sites expect one or two patients, where an interval of whole numbers covers more than its nominal 80%, so the all-sites figure overstates the width. The bound this slice holds itself to is 70-90% on the busier sites: 8 of 12 protocols are inside it, 4 above (intervals a little too wide), 0 below.

## Dropout risk

| Network | Enrollees scored | Observed dropout | Mean predicted | AUC | Brier | Base-rate Brier |
|---|---|---|---|---|---|---|
| 201 | 1334 | 22.2% | 23.0% | 0.645 | 0.1646 | 0.1729 |
| 202 | 1585 | 23.7% | 23.6% | 0.622 | 0.1729 | 0.1806 |
| 203 | 1606 | 23.2% | 23.2% | 0.619 | 0.1733 | 0.1783 |

Logistic regression on the enrollee's ECOG, age band, distance band, prior lines, comorbidities and the site's past retention, trained on the history's enrollees. It ranks moderately (the generator's dropout has a site effect and plenty of chance) and improves the Brier score over the base rate only a little; it is used to turn expected enrolment into expected evaluable patients.

## Portfolio: 20 sites under a budget

Budget per protocol: 1.3 x 20 x the mean site's expected cost (activation plus per-patient fees at the model's expected enrolment); at most 6 sites per region, at least 3 academic, no site whose lead investigator has an open GCP finding. Every plan is scored by the evaluable patients the generator's run of the protocol actually gives its sites in 12 months.

| Network | Protocol | Budget | MILP: actual evaluable | Top-20 by history: sites, actual | Greedy by value per dollar: actual | Hindsight best (MILP on the actual results) | MILP total inside its 80% interval |
|---|---|---|---|---|---|---|---|
| 201 | nsclc_post_platinum | $2,240,000 | 159 (predicted 86-124) | 17, 87 | 151 | 185 | no |
| 201 | nsclc_second_line | $2,080,000 | 132 (predicted 77-113) | 17, 71 | 124 | 156 | no |
| 201 | melanoma_io_refractory | $2,500,000 | 115 (predicted 98-133) | 17, 88 | 114 | 156 | yes |
| 201 | breast_her2 | $1,680,000 | 64 (predicted 41-68) | 16, 48 | 65 | 91 | yes |
| 202 | nsclc_post_platinum | $2,550,000 | 116 (predicted 97-136) | 14, 86 | 102 | 157 | yes |
| 202 | nsclc_second_line | $2,460,000 | 138 (predicted 93-131) | 13, 102 | 115 | 170 | no |
| 202 | melanoma_io_refractory | $3,100,000 | 115 (predicted 138-171) | 18, 88 | 116 | 153 | no |
| 202 | breast_her2 | $1,990,000 | 63 (predicted 63-93) | 16, 56 | 65 | 94 | yes |
| 203 | nsclc_post_platinum | $2,370,000 | 94 (predicted 89-126) | 16, 90 | 100 | 157 | yes |
| 203 | nsclc_second_line | $2,280,000 | 98 (predicted 87-122) | 18, 109 | 98 | 155 | yes |
| 203 | melanoma_io_refractory | $2,920,000 | 127 (predicted 122-160) | 18, 118 | 140 | 182 | yes |
| 203 | breast_her2 | $1,990,000 | 65 (predicted 67-99) | 18, 69 | 78 | 119 | no |
| **all** | | | **1286** | **1012** | **1268** | 1775 | 7 of 12 |

Across the twelve protocols the MILP's portfolios enrolled 1.27x the evaluable patients of the top-20-by-history baseline under the same budget, and 1.01x a greedy pick on the same predictions; the hindsight best (the same MILP given the actual results) got 1775. The gain over the baseline is the prediction: knowing this protocol's pool at each site. On the same predictions the MILP is no better than a greedy pick by value per dollar; what it adds is that its plans keep the region and academic rules and the full 20 sites, which the greedy pick does not check. Its portfolio totals landed inside their own 80% interval 7 times in 12: chosen sites are the ones whose predictions were high, so misses on the high side are expected (the optimiser's curse), and a shared error in the pool estimate moves every site at once.

## Optimisation time for 1,000 candidate sites

1,000 candidate sites with 4,974 historical studies: fitting the enrolment and dropout models 1.47 s, scoring every site with 2,000 predictive draws 1.11 s, the MILP 0.08 s (optimal, 20 sites). End to end 2.66 s against the blueprint's bar of 2 minutes. One process on the machine in docs/performance.md.

