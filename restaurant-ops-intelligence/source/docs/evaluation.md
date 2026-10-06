# Evaluation

Three held-out chains (seeds 101, 102, 103), 50 stores each, 56 days of history run the chain's usual way (par prep and par orders). Models are fitted exactly as the service fits them on days 0-41 and scored on days 42-55 against what the generator knows and the service never sees: true demand, including what stockouts hid; true elasticities; which lots spoiled; the injected shrinkage. The planners then run days 56-69 from the same stock with the same customers, weather and spoilage draws. The prep and order quantiles (0.9 and 0.95) were chosen on a tuning chain (seed 11) that neither this file nor the demo uses. `python -m resto.evaluate` reproduces this file.

## Demand forecast (15-minute, hierarchical)

Lunch rush (11:00-14:00) of the two held-out weeks, against true demand. The forecast uses the weather service's day-ahead forecast, not the rain that fell. Baseline: seasonal naive (the same slot last week, from sales) with empirical 90% error quantiles from the training weeks.

| Chain | Level | WAPE | Baseline WAPE | 90% interval coverage | Baseline coverage | Interval width | Baseline width |
|---|---|---|---|---|---|---|---|
| 101 | item x store x 15 min (mean 2.5) | 0.508 | 0.700 | 96.0% (PIT 89.9%) | 93.7% | 5.0 | 5.8 |
| 101 | item x store x lunch rush (mean 30) | 0.171 | 0.245 | 91.1% | 92.7% | 20.6 | 33.0 |
| 101 | store x day | 0.078 | 0.118 | 87.4% | 86.6% | | |
| 101 | chain lunch rush | 0.016 | 0.029 | | | | |
| 102 | item x store x 15 min (mean 2.6) | 0.502 | 0.695 | 96.0% (PIT 89.7%) | 94.1% | 5.0 | 5.9 |
| 102 | item x store x lunch rush (mean 31) | 0.166 | 0.248 | 91.0% | 91.7% | 20.4 | 32.3 |
| 102 | store x day | 0.076 | 0.109 | 86.0% | 85.6% | | |
| 102 | chain lunch rush | 0.022 | 0.022 | | | | |
| 103 | item x store x 15 min (mean 2.8) | 0.485 | 0.670 | 95.9% (PIT 89.9%) | 93.5% | 5.3 | 6.2 |
| 103 | item x store x lunch rush (mean 33) | 0.162 | 0.245 | 91.2% | 91.8% | 21.7 | 36.4 |
| 103 | store x day | 0.074 | 0.120 | 87.9% | 87.3% | | |
| 103 | chain lunch rush | 0.014 | 0.043 | | | | |

The blueprint's band is 85-95% item interval coverage. At 15 minutes an item sells about three units in a store, and a 90% interval on whole numbers covers more than 90% because its ends are whole numbers; the calibration that matters there is the randomised PIT (Czado, Gneiting and Held, 2009), shown in brackets. Summed to the lunch rush, where prep plans are made, the literal interval lands in the band. Most of the remaining error at 15 minutes is Poisson noise no model removes.

| Chain | Lunch slots in rain (item x store) | WAPE | Baseline | PIT coverage | Promotion item-days | WAPE | Baseline |
|---|---|---|---|---|---|---|---|
| 101 | 4,200 | 0.534 | 0.766 | 89.6% | 300 | 0.204 | 0.339 |
| 102 | 2,160 | 0.520 | 0.741 | 88.5% | 0 | – | – |
| 103 | 1,920 | 0.665 | 0.966 | 90.6% | 440 | 0.134 | 0.373 |

Fitting takes 3.7 s, 3.1 s, 3.7 s (six weeks, 50 stores). A refresh (every store, item and 15-minute slot for two days, with intervals, from the fitted model) takes 245 ms (p95 267 ms), 245 ms (p95 257 ms), 246 ms (p95 255 ms) in the model alone; the blueprint's bar is p95 under 2 minutes. Through the API, with the reads and writes, see docs/performance.md.

## Promotion elasticity

| Chain | Items promoted in the history | MAE of elasticity, those items | Baseline: one pooled elasticity | Baseline: no promotion effect | Items never promoted (fall back to pooled) |
|---|---|---|---|---|---|
| 101 | 8 | 0.05 | 0.44 | 1.85 | chicken_bowl, beef_burrito, burger, fries |
| 102 | 8 | 0.12 | 0.55 | 2.52 | chicken_bowl, chicken_tacos, fries, quesadilla |
| 103 | 8 | 0.08 | 0.57 | 1.88 | beef_burrito, salmon_bowl, garden_salad, chicken_salad |

Elasticities run from 1.0 to 3.2 in the generator. Each promoted item is estimated from its own promotion (one discount level, 20-30 stores for 4-7 days) shrunk toward the pooled value; an item the history never promoted gets the pooled value, and its error is whatever that is.

## Ingredient consumption

Counted usage over the two held-out weeks, per store and ingredient, predicted from the sales those weeks at recipe.

| Chain | Recipes x learned ratio (2 weeks) | Recipes alone | Last week's usage | Daily: ratio | Daily: recipes | Daily: last week |
|---|---|---|---|---|---|---|
| 101 | 0.65% | 1.88% | 3.09% | 3.6% | 4.3% | 13.2% |
| 102 | 0.68% | 1.89% | 2.21% | 3.6% | 4.4% | 12.0% |
| 103 | 0.72% | 1.81% | 2.47% | 3.6% | 4.4% | 13.3% |

WAPE. The learned ratio absorbs what recipes miss (avocados yield less flesh than the spec everywhere; spillage; the over-portioning stores); daily error is dominated by the closing count's own error.

## Spoilage hazard

| Chain | Test | Lot-days | Spoiled | AUC | AUC, age only | AUC, printed date | Log loss | Base rate | Spoilage caught in the riskiest 5% | Age only |
|---|---|---|---|---|---|---|---|---|---|---|
| 101 | held-out weeks | 6,969 | 36 | 0.846 | 0.8 | 0.575 | 0.0274 | 0.0324 | 39% | 42% |
| 101 | another chain, 8 weeks | 28,138 | 142 | 0.846 | 0.809 | 0.605 | 0.0261 | 0.0317 | 46% | 38% |
| 102 | held-out weeks | 7,028 | 37 | 0.868 | 0.827 | 0.654 | 0.0265 | 0.0329 | 51% | 51% |
| 102 | another chain, 8 weeks | 28,250 | 166 | 0.844 | 0.802 | 0.624 | 0.0291 | 0.036 | 49% | 37% |
| 103 | held-out weeks | 6,906 | 32 | 0.878 | 0.875 | 0.664 | 0.0232 | 0.0295 | 44% | 47% |
| 103 | another chain, 8 weeks | 28,107 | 138 | 0.846 | 0.807 | 0.613 | 0.0258 | 0.031 | 43% | 40% |

On lot-days in a warm walk-in (above 5.5 °C) of the other chain: 101: 735 lot-days, 28 spoiled (3.8%), model said 2.9%; 102: 1149 lot-days, 36 spoiled (3.1%), model said 2.5%; 103: 877 lot-days, 26 spoiled (3.0%), model said 3.7%. The printed date flags almost nothing because lots are used or spoil before it; the hazard's advantage over age alone is the temperature, and warm walk-ins are rare, so on most lot-days the two rank alike.

## Shrinkage detection

Six chains (seeds 101, 102, 103, 104, 105, 106), 300 stores, 24 with injected shrinkage (two thefts of one or two ingredients at 6-12% of usage, two over-portioning stores at 8-16% on proteins, cheese and guacamole per chain), 55 days of counts.

| | Shrinkage stores found | Stores flagged that had none | Theft store-ingredient pairs found | Pairs flagged in all |
|---|---|---|---|---|
| Usage against the chain's normal, z > 4 | 24 of 24 (class right for 24) | 0 of 276 | 15 of 15 | 85 |
| Baseline: variance above 4% | 24 of 24 | 276 of 276 | 15 of 15 | 371 |

The threshold flags every store, because the chain's avocados yield less flesh than the recipe assumes (about 9% more avocado used everywhere): a chain-wide yield problem looks like shrinkage at every store to a fixed rule, and like the normal to a comparison with the chain.

## Planning: 14 days on each policy

Days 56-69 from the same stock with the same customers, weather and spoilage draws. Waste is prep thrown away at the end of its hold plus spoiled and expired lots, as a share of purchases; stockouts are demand lost because an item was 86'd (the generator's truth: the POS never sees it).

| Chain | Policy | Waste | Waste $ | of which prep | Stockout rate | Lost revenue | Purchases | Backup spend |
|---|---|---|---|---|---|---|---|---|
| 101 | usual practice | 12.5% | $187,768 | $171,085 | 3.33% | $205,784 | $1,499,582 | $0 |
| 101 | system, unattended (lines over $250 at par) | 9.0% | $130,970 | $121,829 | 1.97% | $124,072 | $1,456,259 | $4,007 |
| 101 | system, every line approved | 8.8% | $125,638 | $120,509 | 1.86% | $116,494 | $1,433,876 | $6,446 |
| 101 | system, printed dates instead of the hazard | 8.8% | $125,487 | $120,515 | 1.88% | $117,700 | $1,433,048 | $6,170 |
| 102 | usual practice | 12.0% | $193,163 | $173,588 | 2.60% | $170,782 | $1,605,258 | $0 |
| 102 | system, unattended (lines over $250 at par) | 9.1% | $142,484 | $130,418 | 1.73% | $115,842 | $1,561,963 | $4,652 |
| 102 | system, every line approved | 9.0% | $138,030 | $129,241 | 1.58% | $105,426 | $1,541,164 | $7,703 |
| 102 | system, printed dates instead of the hazard | 8.9% | $137,505 | $129,163 | 1.61% | $107,876 | $1,539,597 | $7,270 |
| 103 | usual practice | 11.8% | $195,846 | $174,992 | 3.37% | $229,212 | $1,666,849 | $0 |
| 103 | system, unattended (lines over $250 at par) | 9.0% | $146,870 | $132,314 | 2.09% | $143,664 | $1,626,871 | $3,333 |
| 103 | system, every line approved | 8.7% | $139,135 | $130,966 | 1.95% | $134,259 | $1,598,881 | $9,490 |
| 103 | system, printed dates instead of the hazard | 8.7% | $138,870 | $131,006 | 1.98% | $136,902 | $1,597,912 | $9,614 |
| **all** | | | | | | | | |
| | usual practice | 12.1% | $576,777 | $519,665 | 3.10% | $605,778 | $4,771,688 | $0 |
| | system, unattended (lines over $250 at par) | 9.0% | $420,325 | $384,561 | 1.93% | $383,578 | $4,645,094 | $11,992 |
| | system, every line approved | 8.8% | $402,804 | $380,716 | 1.80% | $356,180 | $4,573,921 | $23,639 |
| | system, printed dates instead of the hazard | 8.8% | $401,862 | $380,684 | 1.82% | $362,478 | $4,570,557 | $23,053 |

Most of the waste avoided is prep ($135,104 of $156,452 unattended): the usual par is the same weekday of the last two weeks plus 15%, so it carries two weeks of noise and none of the weather, events or promotions, while the forecast's 90th percentile carries the day's own risk and the dinner prep is updated from lunch. Unattended, the lines that would move more than $250 from par go at par, which gives back a little of each gain. The hazard model does not earn its place in ordering here: with printed dates instead, the planner wasted $401,862 against $402,804 (every line approved) and ran out on 1.82% against 1.80%. Lots here turn over in two or three days, so few live long enough for their risk to change an order; its use is the waste-risk list.

## The demo's disruption on each chain

A late produce truck (Harbor and Uptown, one day) and a lunch rainstorm (Uptown and Midtown, 11:00-15:00), both on day 56, then three days. The plan made before the notices ran unattended after them; the re-plan knew both on the night before.

| Chain | Plan | Waste $ | Stockout rate (3 days) | Day 1 stockout rate | Lost revenue | Backup premium |
|---|---|---|---|---|---|---|
| 101 | usual practice | $47,273 | 9.9% | 27.5% | $134,022 | $0 |
| 101 | system, plan before the notices | $36,747 | 8.8% | 26.0% | $119,514 | $76 |
| 101 | system, re-planned | $28,690 | 1.4% | 2.1% | $18,811 | $2,749 |
| 102 | usual practice | $51,279 | 9.8% | 25.6% | $138,308 | $0 |
| 102 | system, plan before the notices | $42,163 | 8.7% | 25.1% | $122,770 | $79 |
| 102 | system, re-planned | $33,218 | 1.6% | 2.0% | $22,856 | $2,689 |
| 103 | usual practice | $47,131 | 12.1% | 31.2% | $175,244 | $0 |
| 103 | system, plan before the notices | $42,123 | 10.3% | 28.9% | $150,542 | $260 |
| 103 | system, re-planned | $31,664 | 1.8% | 2.3% | $26,824 | $3,417 |

The plan made before the notices does barely better than usual practice on day one: without produce, guacamole, pico and lettuce run out at the 20 stores and with them most of the menu, and only the backup order the re-plan places prevents that.

