# Evaluation

Three held-out corpora (seeds 101, 102, 103): each a different invented company with its own people, owners, vendors and decisions, 2218, 2171, 2182 source objects as of 2026-10-05. Each is processed exactly as the service processes it: the extractor and the linker are trained on the corpus's annotated fifth (436, 387, 402 documents) and everything is scored against the generator's truth on the rest. `python -m ekg.evaluate` reproduces this file. No language model or external API is called anywhere.

## Extraction (free text, documents nobody annotated)

| Corpus | Assertions in the truth | Model precision | Model recall | Trigger-word baseline precision | Baseline recall |
|---|---|---|---|---|---|
| 101 | 502 | 1.0 | 0.992 | 0.831 | 0.853 |
| 102 | 482 | 0.957 | 0.971 | 0.799 | 0.882 |
| 103 | 567 | 0.979 | 0.988 | 0.839 | 0.864 |

An assertion counts when its relation, both arguments and its value (a reason, a price) match the truth; an argument matches when the detected mention overlaps the true one, so a missed mention is a missed assertion. Relations: who owns a service, a handover, a vendor selected, considered or rejected (with the reason), who decided, the reasons, a contract value, a team rename. The baseline fires on trigger words and is fooled by hedges, questions and "budget owner"; the logistic model reads the words between and around the two mentions. By relation, all corpora together (model: true positives / false positives / misses):

| Relation | Model TP / FP / FN | Baseline TP / FP / FN |
|---|---|---|
| CONSIDERED | 199 / 0 / 11 | 199 / 0 / 11 |
| CONTRACT_VALUE | 41 / 0 / 4 | 45 / 0 / 0 |
| DECIDED_BY | 23 / 0 / 0 | 23 / 23 / 0 |
| HANDOVER | 39 / 0 / 0 | 39 / 0 / 0 |
| OWNS | 985 / 33 / 3 | 794 / 218 / 194 |
| REASON | 69 / 0 / 0 | 69 / 0 / 0 |
| REJECTED | 101 / 0 / 3 | 101 / 0 / 3 |
| RENAMED | 10 / 0 / 0 | 10 / 0 / 0 |
| SELECTED | 59 / 0 / 4 | 63 / 47 / 0 |

The corpus is generated from templates with varied wording, so these numbers say the pipeline is wired correctly and the model handles hedges and negation that trigger words do not; they do not say how it would do on real prose (see the README).

## Entity resolution

| Corpus | Mentions | System B³ F1 (precision / recall) | + approved rename merges | String equality | Fuzzy match | System pairwise F1 |
|---|---|---|---|---|---|---|
| 101 | 3552 | 0.9792 (0.9985 / 0.9607) | 0.9866 (0.9985 / 0.9751) | 0.7238 (0.9914 / 0.57) | 0.8731 (0.9895 / 0.7812) | 0.9777 |
| 102 | 3487 | 0.9813 (0.9986 / 0.9646) | 0.9883 (0.9986 / 0.9781) | 0.7294 (0.9904 / 0.5773) | 0.8854 (0.9891 / 0.8014) | 0.9817 |
| 103 | 3679 | 0.9765 (0.9986 / 0.9553) | 0.9851 (0.9986 / 0.972) | 0.7281 (0.9875 / 0.5766) | 0.8694 (0.9851 / 0.778) | 0.9747 |

Mentions of people, teams, services and vendors in the documents nobody annotated, scored with B³ (every mention weighs the same, so a big entity cannot hide a small one's errors) and pairwise F1. The blueprint's bar is F1 above 0.95. String equality keeps "P. Raman", "@praman" and "priya.raman@…" apart and puts the two Daniel Kims together; the fuzzy match merges the two people who share an initial and a surname. The system abstains when two candidates score alike (two people with the same name and no context): 42, 34, 46 mentions. Rename merges are proposals from "X is now Y" statements (2 of 2, 2 of 2, 2 of 2 correct); the system never merges two named entities on its own, so the second column is after a person approves them.

## Who owns it, then and now

| Corpus | Rule | All service-months | Services that changed owner | Today | Today, changed services |
|---|---|---|---|---|---|
| 101 | system | 99.2% | 97.8% | 100.0% | 100.0% |
| 101 | latest mention | 98.7% | 96.4% | 100.0% | 100.0% |
| 101 | majority of mentions | 94.5% | 85.2% | 100.0% | 100.0% |
| 102 | system | 99.0% | 95.7% | 100.0% | 100.0% |
| 102 | latest mention | 97.8% | 90.8% | 100.0% | 100.0% |
| 102 | majority of mentions | 96.4% | 85.1% | 95.6% | 83.3% |
| 103 | system | 99.8% | 99.3% | 100.0% | 100.0% |
| 103 | latest mention | 98.3% | 92.7% | 100.0% | 100.0% |
| 103 | majority of mentions | 96.6% | 85.4% | 97.8% | 90.9% |

The owner of every service with any ownership evidence, on the 15th of every month and today, end to end from the extracted assertions (seed 101: 598 service-months, 45 services today, 16 of which changed owner). The system decodes the most likely ownership history (Viterbi over days, sources weighted by reliability, stated handovers as transitions). Today, on these corpora, the latest-mention rule is as right as the system: the latest thing said about most services is a ticket or a catalog revision. The difference is in the months around a handover, when the latest mention is a service page edited without its owner line or a chat line that still names the old team. (The demo corpus has a service where the stale page is the latest mention today; that is why the demo picks it.)

## Retrieval

| Corpus | Reader | Queries | BM25 recall@10 / MRR | LSA | BM25 + LSA | BM25 + LSA + graph | BM25 + graph (the default) |
|---|---|---|---|---|---|---|---|
| 101 | every container | 65 | 0.36 / 0.634 | 0.299 / 0.569 | 0.307 / 0.609 | 0.615 / 0.831 | 0.691 / 0.9 |
| 101 | an engineer | 55 | 0.441 / 0.693 | 0.352 / 0.521 | 0.362 / 0.578 | 0.678 / 0.847 | 0.702 / 0.931 |
| 102 | every container | 65 | 0.327 / 0.645 | 0.286 / 0.542 | 0.316 / 0.612 | 0.589 / 0.802 | 0.714 / 0.893 |
| 102 | an engineer | 55 | 0.392 / 0.649 | 0.339 / 0.562 | 0.361 / 0.633 | 0.681 / 0.863 | 0.732 / 0.913 |
| 103 | every container | 65 | 0.332 / 0.637 | 0.332 / 0.634 | 0.324 / 0.622 | 0.608 / 0.74 | 0.705 / 0.934 |
| 103 | an engineer | 55 | 0.393 / 0.638 | 0.363 / 0.616 | 0.374 / 0.596 | 0.674 / 0.787 | 0.729 / 0.963 |

By question kind (recall@10, all corpora, reader with every container):

| Question | BM25 | BM25 + graph |
|---|---|---|
| owner | 0.281–0.304 | 0.636–0.673 |
| why | 0.500–0.650 | 1.000 |
| alternatives | 0.269–0.321 | 0.574–0.626 |

Questions are generated from the truth with varied wording and aliases ("who maintains svc-ledger-api now", "why did we pick Northwind"); the relevant chunks are the ones that assert the current owner, the selection and its reasons, or the candidates and rejections. Recall@10 is the share of relevant chunks in the top ten (capped at ten), MRR the reciprocal rank of the first. Every statistic is computed inside the reader's view: BM25's document frequencies and the LSA basis come from the chunks that reader may read. LSA (TF-IDF, 96 dimensions, fitted per view) is no better than BM25 alone here and drags the fusion down; on the demo corpus 32 and 256 dimensions and a lower fusion weight did not change that, so the default fuses BM25 and the graph. Templated text gives a co-occurrence model little to learn that exact terms do not already carry; the graph earns its place because the chunks that answer a question often do not contain its words (the reasons for a decision sit in a sentence that never names the vendor).

## Answers

| Corpus | Reader | Owner today | Owner in a past month | Why a vendor was selected | Reasons correct | Unanswerable: abstained | Citation coverage |
|---|---|---|---|---|---|---|---|
| 101 | every container | 45 of 45 | 16 of 16 | 10 of 10 | 20 of 20 | 5 of 5 | 100% of 263 sentences |
| 101 | an engineer | 45 of 45 | 16 of 16 | 10 of 10 | 10 of 10 | 5 of 5 | 100% of 214 sentences |
| 102 | every container | 45 of 45 | 11 of 12 | 10 of 10 | 20 of 20 | 5 of 5 | 100% of 249 sentences |
| 102 | an engineer | 45 of 45 | 11 of 12 | 10 of 10 | 10 of 10 | 5 of 5 | 100% of 207 sentences |
| 103 | every container | 45 of 45 | 9 of 11 | 10 of 10 | 20 of 20 | 5 of 5 | 100% of 255 sentences |
| 103 | an engineer | 45 of 45 | 9 of 11 | 10 of 10 | 10 of 10 | 5 of 5 | 100% of 203 sentences |

Answers are composed only from the reader's facts. Citation coverage is measured by a separate verifier: a sentence counts when every fact it states is backed by a cited chunk the reader may read that names the fact's subject and object (or holds its value). The blueprint's bar is 100%. Unanswerable questions name services and vendors that do not exist; the answer must say it found nothing rather than guess. The engineer cannot read procurement, so the vendor questions they can ask are the ones announced in an engineering channel, and their answers carry the announced reason only.

## Permission leakage

| Corpus | Principals probed | Probes | Leaks | With the permission filter off | Non-interference checks failed |
|---|---|---|---|---|---|
| 101 | 28 | 10,986 | 0 | 880 of 956 leak | 0 of 240 |
| 102 | 29 | 11,704 | 0 | 876 of 962 leak | 0 of 240 |
| 103 | 29 | 11,873 | 0 | 904 of 970 leak | 0 of 240 |

Every principal with a distinct set of readable containers is probed through search, graph queries, answers, entities and provenance (answers 13,922, entity 1,865, graph 2,725, provenance 3,849, search 12,202 across the corpora): provenance and entity lookups on every fact and entity the principal cannot see, graph queries around every decision, questions and searches naming every vendor and every restricted literal (contract values, rejection reasons, codenames, names only restricted documents use), and searches by the title of every unreadable document. A probe leaks when its response carries an identifier of something the view cannot see, or a restricted literal the probe did not itself contain. The blueprint's bar is zero. Run with the permission filter off, the same probes leak most of the time, which is what shows the suite can see a leak. Non-interference compares the persona's search results and answers on the full index with those of an index built from only the objects they may read: identical, because every statistic is computed inside the view.

## Incremental sync

| Corpus | Changed objects (three days, one failing service) | Pipeline time in process |
|---|---|---|
| 101 | 13 | 0.05 s |
| 102 | 23 | 0.07 s |
| 103 | 15 | 0.06 s |

Normalising, detecting, linking and extracting the changed objects and rebuilding the index; the live figure through the API and the job queue is in docs/performance.md. The blueprint's bar is under five minutes.

