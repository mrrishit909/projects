# Evaluation

Three held-out companies (seeds 101, 102, 103), each with six subsidiaries' vendor masters, 240,000 invoice lines for the year (the inventory's size does not depend on the line count: the year's spend is fixed), 40,000 shipments, a year of utility bills and the larger suppliers' disclosures. The supplier matcher is trained on two earlier engagements (seeds 900 and 901, 13,998 candidate pairs); the category classifier on each company's own 6,000 analyst-labelled lines from last year (about 2% mislabelled, as people do). Everything is scored against the generator's truth, which the pipeline never reads. `python -m carbon.evaluate` reproduces this file.

## Supplier resolution

| Company | Vendor records | True suppliers | Matcher: precision / recall / F1 | Exact name (after case and punctuation) | Fuzzy name similarity alone | Pairs sent for review |
|---|---|---|---|---|---|---|
| 101 | 920 | 460 | 0.967 / 0.984 / **0.976** (459 suppliers) | 0.988 / 0.205 / **0.340** (790) | 0.943 / 0.904 / **0.923** (489) | 62 |
| 102 | 906 | 460 | 0.969 / 0.990 / **0.979** (458 suppliers) | 1.000 / 0.151 / **0.262** (805) | 0.944 / 0.902 / **0.922** (482) | 52 |
| 103 | 914 | 460 | 0.976 / 0.984 / **0.980** (461 suppliers) | 0.991 / 0.140 / **0.245** (819) | 0.942 / 0.839 / **0.887** (505) | 38 |

Pairwise scores over every pair of vendor records placed together. Blocking (character n-gram neighbours plus shared tax ids and domains) keeps 7,122 of 422,740 possible pairs and loses 0.1%, 0.1%, 0.0% of the true ones. Exact matching is precise but finds only a seventh to a fifth of the duplicates; fuzzy similarity alone finds most and also merges different companies with near-identical names. The matcher's weights say why it does better: a shared tax id or company domain and the same country carry as much as the name, and two different tax ids veto a merge. Weights: tfidf_cosine 10.13, token_jaccard -0.59, sequence_ratio 9.7, first_token_equal -0.03, tax_id 4.75, email_domain 4.09, same_country 4.23, same_subsidiary -1.28.

## Spend categories

| Company | Classifier: accuracy / spend-weighted / macro-F1 | Rules (keywords, then GL account) | Orphans after mapping: classifier | Rules | Classifier on suppliers new this year (spend-weighted) | Sent to the fallback |
|---|---|---|---|---|---|---|
| 101 | 0.983 / 0.985 / 0.987 | 0.910 / 0.913 / 0.923 | 0.63% of lines, 0.61% of spend | 1.94%, 1.95% | 0.974 | 1.6% |
| 102 | 0.986 / 0.988 / 0.988 | 0.913 / 0.914 / 0.923 | 0.49% of lines, 0.44% of spend | 1.93%, 1.94% | 0.986 | 1.9% |
| 103 | 0.978 / 0.980 / 0.983 | 0.905 / 0.911 / 0.921 | 0.59% of lines, 0.55% of spend | 1.92%, 1.89% | 0.941 | 2.8% |

Orphans are lines no category could be given to (the classifier abstained below 0.55 and neither a keyword nor the GL account answered); the blueprint's bar is under 1%. The descriptions come from a few hundred templates, a fifth of them shared between categories or uninformative, so these accuracies are an upper bound for real ledgers: the vendor's name and the account carry much of the signal, which is why lines from suppliers new this year (absent from the labels) score lower.

## Supplier disclosures

| Company | Disclosures | Figures read within 1%: parser | Naive (first number, assumed units) | Accepted as factors | Unit slips caught | Matched to the right supplier |
|---|---|---|---|---|---|---|
| 101 | 33 | 130 of 130 | 57 of 130 | 30 | 1 of 1 | 32 of 33 |
| 102 | 38 | 147 of 147 | 61 of 147 | 32 | 1 of 1 | 37 of 38 |
| 103 | 34 | 132 of 132 | 49 of 132 | 30 | 1 of 1 | 32 of 34 |

A disclosure is accepted when revenue, scope 1, scope 2 and scope 3 upstream are all found and the intensity is plausible; the rest go to review with the reason (about one in six omits its upstream emissions). The planted unit slip (revenue in thousands labelled millions) is read exactly as written and then refused by the plausibility check, which is the point: the parser reads, the validation judges.

## The inventory against the truth

Estimated tCO2e with the 95% Monte Carlo interval, against the generator's true emissions (true sector intensities, each supplier's own offset, true grid, fuel and freight factors). *With disclosures* replaces the sector factor for the accepted suppliers' main category.

| Company | Scope | True | Catalogue only | Error | 95% interval covers truth | With disclosures | Error | Covers |
|---|---|---|---|---|---|---|---|---|
| 101 | Total | 1,204,999 | 1,294,786 [1,152,260–1,469,265] | +7.5% | yes | 1,305,383 [1,182,408–1,466,757] | +8.3% | yes |
| 101 | Scope 1 | 15,714 | 15,714 [14,415–17,020] | +0.0% | yes | 15,714 [14,415–17,020] | +0.0% | yes |
| 101 | Scope 2 | 65,767 | 63,391 [59,008–68,125] | -3.6% | yes | 63,391 [59,008–68,125] | -3.6% | yes |
| 101 | S3 cat 1 purchased goods | 970,705 | 1,032,041 [897,762–1,202,242] | +6.3% | yes | 1,048,714 [930,948–1,205,107] | +8.0% | yes |
| 101 | S3 cat 2 capital goods | 61,556 | 84,171 [59,950–118,830] | +36.7% | yes | 78,094 [58,145–107,077] | +26.9% | yes |
| 101 | S3 cat 4 transport | 60,918 | 62,850 [43,837–86,436] | +3.2% | yes | 62,850 [43,837–86,436] | +3.2% | yes |
| 101 | S3 cat 6 travel | 30,339 | 36,619 [25,744–51,998] | +20.7% | yes | 36,619 [25,576–52,297] | +20.7% | yes |
| 102 | Total | 1,588,666 | 1,344,949 [1,192,357–1,542,002] | -15.3% | **no** | 1,500,332 [1,388,719–1,634,333] | -5.6% | yes |
| 102 | Scope 1 | 15,035 | 15,035 [13,861–16,287] | -0.0% | yes | 15,035 [13,861–16,287] | -0.0% | yes |
| 102 | Scope 2 | 70,145 | 69,113 [64,505–73,988] | -1.5% | yes | 69,113 [64,505–73,988] | -1.5% | yes |
| 102 | S3 cat 1 purchased goods | 1,300,032 | 1,066,213 [919,937–1,246,966] | -18.0% | **no** | 1,215,873 [1,110,395–1,338,440] | -6.5% | yes |
| 102 | S3 cat 2 capital goods | 97,774 | 86,948 [58,931–129,600] | -11.1% | yes | 92,672 [70,583–129,046] | -5.2% | yes |
| 102 | S3 cat 4 transport | 68,509 | 67,016 [46,469–94,280] | -2.2% | yes | 67,016 [46,469–94,280] | -2.2% | yes |
| 102 | S3 cat 6 travel | 37,172 | 40,624 [27,519–60,930] | +9.3% | yes | 40,624 [27,480–61,990] | +9.3% | yes |
| 103 | Total | 1,137,201 | 1,265,842 [1,114,716–1,431,692] | +11.3% | yes | 1,230,224 [1,121,353–1,358,928] | +8.2% | yes |
| 103 | Scope 1 | 14,903 | 14,903 [13,762–16,230] | -0.0% | yes | 14,903 [13,762–16,230] | -0.0% | yes |
| 103 | Scope 2 | 56,718 | 56,181 [52,300–60,314] | -0.9% | yes | 56,181 [52,300–60,314] | -0.9% | yes |
| 103 | S3 cat 1 purchased goods | 887,701 | 1,010,657 [866,281–1,170,492] | +13.9% | yes | 962,879 [865,022–1,087,559] | +8.5% | yes |
| 103 | S3 cat 2 capital goods | 99,187 | 90,882 [59,470–137,226] | -8.4% | yes | 103,042 [75,348–148,696] | +3.9% | yes |
| 103 | S3 cat 4 transport | 55,507 | 58,457 [42,038–80,049] | +5.3% | yes | 58,457 [42,038–80,049] | +5.3% | yes |
| 103 | S3 cat 6 travel | 23,185 | 34,761 [22,997–53,262] | +49.9% | yes | 34,761 [22,647–52,503] | +49.9% | yes |

**Calibration across every bucket** (total, scopes, scope 3 categories and the ten spend categories, three companies):

| Factors | Buckets | Inside the 95% interval | Inside the 90% interval | Mean absolute error, spend categories | Spend on supplier-specific factors |
|---|---|---|---|---|---|
| catalogue | 54 | 47 (87%) | 39 (72%) | 17.0% | 0.0% |
| with disclosures | 54 | 50 (93%) | 47 (87%) | 13.8% | 17.2% |

The big errors are the catalogue's: when a sector average is itself 15% or more off, it moves a whole category, and no amount of good mapping fixes that. With the catalogue alone the 95% intervals hold the truth in 87% of buckets, so they are somewhat too narrow; with the accepted disclosures, 93%. Supplier-specific factors replace the sector average only for the suppliers who disclosed in full (the spend share in the last column), so the rest of the error stays where it was.

## Reproducibility and lineage

| Company | Activity lines | Same version twice: identical hash | 2025.1 vs 2024.2: different hash | Calculation time (in memory) |
|---|---|---|---|---|
| 101 | 280,411 | yes | yes | 1.15 s |
| 102 | 280,430 | yes | yes | 1.15 s |
| 103 | 280,435 | yes | yes | 1.13 s |

In the service the same hash is recomputed from the stored activities and from the stored lineage rows (`POST /v1/calculations/{id}:reproduce`); the tests check that a frozen version cannot be edited in the database and that every line carrying CO2e has its source, mapping and factor.

## Which suppliers to engage

Share of the generator's true supplier emissions within reach of the top 20 suppliers: their own, plus the part of every other supplier's footprint they sell to it (a mill whose steel goes into our component makers' parts). The network is what the disclosures reveal: each discloser's principal suppliers.

| Company | By spend (baseline) | By estimated emissions | By emissions + network centrality | Ranked by true emissions + network (oracle) | Network edges seen |
|---|---|---|---|---|---|
| 101 | 28.9% | 45.9% | 46.4% | 47.0% | 38 |
| 102 | 30.7% | 50.4% | 49.9% | 53.2% | 29 |
| 103 | 33.3% | 44.0% | 44.0% | 46.6% | 30 |

Ranking by estimated emissions instead of spend is the large step (+17.0, +19.7, +10.7 points). Adding the network centrality changes the result by +0.5, -0.5, +0.0 points: no better overall, because only the disclosing suppliers reveal who they buy from, and a mill that sells to many component makers is usually already near the top on its own emissions.

