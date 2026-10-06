# Evaluation

Three held-out worlds (seeds 101, 102, 103): other weather, other storms, other vessels. In each, six vessels sail a year; the fuel models are fitted as the service fits them; then 12 ordinary voyages, 8 storm voyages and 6 congestion voyages per world are planned with the forecast at departure and sailed through the realised weather, each against its baselines sailed through the same realised weather. `python -m voyage.evaluate` reproduces this file.

## Fuel model (performance-model)

| World | Vessel | Noon reports scored | MAPE | Sea-trial curve MAPE | Bias | Fouling now, estimated | Fouling now, true | Cleaned during the year |
|---|---|---|---|---|---|---|---|---|
| 101 | V01 | 41 | 3.1% | 9.7% | +0.3% | 17.8% | 18.7% | no |
| 101 | V02 | 42 | 2.7% | 11.2% | -0.1% | 16.8% | 17.6% | no |
| 101 | V03 | 43 | 2.5% | 9.5% | -0.3% | 13.9% | 14.9% | no |
| 101 | V04 | 42 | 3.4% | 7.7% | +0.2% | 4.6% | 3.7% | yes |
| 101 | V05 | 41 | 2.0% | 5.8% | +0.0% | 14.7% | 13.2% | no |
| 101 | V06 | 36 | 3.0% | 9.1% | -1.7% | 9.2% | 9.1% | no |
| 102 | V01 | 40 | 3.0% | 12.3% | -0.6% | 14.8% | 18.4% | no |
| 102 | V02 | 41 | 3.5% | 8.8% | -1.1% | 6.4% | 10.7% | no |
| 102 | V03 | 41 | 2.8% | 10.6% | +1.9% | 14.3% | 17.0% | no |
| 102 | V04 | 44 | 2.5% | 8.4% | -0.1% | 4.3% | 4.0% | yes |
| 102 | V05 | 41 | 2.0% | 9.3% | +0.1% | 2.7% | 2.4% | yes |
| 102 | V06 | 39 | 2.7% | 6.1% | -0.2% | 4.3% | 4.5% | yes |
| 103 | V01 | 45 | 3.0% | 9.5% | +1.0% | 20.1% | 18.5% | no |
| 103 | V02 | 45 | 3.0% | 10.8% | +0.7% | 2.8% | 2.4% | yes |
| 103 | V03 | 38 | 2.7% | 8.3% | -0.7% | 11.3% | 13.3% | no |
| 103 | V04 | 48 | 2.8% | 9.8% | -1.6% | 11.9% | 14.6% | no |
| 103 | V05 | 44 | 2.6% | 17.0% | -0.9% | 20.0% | 19.3% | no |
| 103 | V06 | 47 | 2.5% | 3.5% | +0.9% | 7.4% | 6.2% | yes |

Daily fuel on the last 60 days of noon reports (fitted on the ten months before): MAPE 2.0-3.5% across the 18 vessels (blueprint bar: 7%), against 3.5-17.0% for the yard's sea-trial curve, which knows nothing of weather, load or fouling. Hull fouling (extra fuel at service speed against the same hull clean): off by 0.9 points at the median and 4.3 at worst; the no-fouling baseline is off by the whole true value (2.4-19.3%).

## Ordinary voyages: savings against baselines sailed through the same weather

36 voyages between New York, Norfolk or Halifax and Rotterdam, Antwerp, Le Havre or Hamburg, either way, with a berth window (36 hours, closing at a schedule speed of 13.5-16 kn), hire of $18,000-35,000 a day, fuel at $560-700 a tonne and carbon at $80 a tonne on half the voyage's CO2 (the EU ETS share for a voyage into or out of the EU). Cost = fuel and carbon (including auxiliary fuel waiting at anchor) + hire until berthing + late penalty.

| Plan (all sailed through the realised weather) | Fuel incl. waiting | CO2 | Voyage cost | Late voyages | Cost saved by the optimiser |
|---|---|---|---|---|---|
| Baseline: shortest sea route at service speed, then wait for the berth | 23,124 t | 72,008 t | $25.01M | 0 of 36 | 12.7% |
| Baseline: shortest route at the constant speed the forecast says lands mid-window | 18,387 t | 57,258 t | $22.21M | 0 of 36 | 1.7% |
| Optimised route, service speed | 23,222 t | 72,313 t | $25.09M | 0 of 36 | 12.9% |
| Shortest route, optimised speed | 17,611 t | 54,842 t | $21.87M | 1 of 36 | 0.1% |
| Optimised route and speed (the plan) | 17,496 t | 54,484 t | $21.84M | 1 of 36 |  |

Against the weather-normalised baseline the plan saves 24.3% of fuel and CO2 and 12.7% of voyage cost (per voyage 1.8 to 27.6%); almost all of it is speed: sailing at service speed and waiting for the berth is expensive. Against the careful constant-speed master it saves 1.7% of cost in total, and per voyage it ranges from -5.6 to +6.8% (it was dearer on 9 of 36). Weather routing alone, at service speed, costs 0.34% more on average (per voyage -3.40 to +0.88%): in ordinary weather the route the forecast prefers is no better in the weather that really comes, and routing earns its keep in storms (below). Heavy weather (hours in seas above 6 m): 124 for the plan, 119 for the baseline (the plan is slower, so longer at sea).

## ETA uncertainty and voyage fuel

| ETA from the departure forecast | Realised arrival at or before it |
|---|---|
| Ensemble P50 (24 members + the fuel model's own error) | 39% (ideal 50%) |
| Ensemble P90 | 89% (ideal 90%) |
| Baseline: deterministic forecast | 39% |
| Baseline: deterministic forecast + 6 h | 89% |

Over 36 voyages; the P90 sits a median 4.9 h after the P50, and the P50 missed the realised arrival by a median 1.4 h. The P90 is calibrated; the P50 is a little early. Said plainly: on ordinary voyages a fixed six-hour margin on the deterministic forecast covered as often (89%); what the ensemble adds is a band whose width follows the weather (from 1.4 to 17.7 h here) and the members' storms beyond the forecast horizon, which the deterministic forecast cannot have. Voyage fuel (the plan's P50 against the fuel burned): MAPE 1.3%, worst 5.6%.

**Route solve time** (time-dependent A* over the 0.5-degree grid, 7,283 ocean nodes, 16 courses each): median 1.7 s, worst 3.0 s over 132 solves (blueprint bar: 30 s), one process.

## Storm voyages: replanning when the forecast sees the storm

24 voyages. A storm (27-32 m/s winds, seas to 9-13 m) forms 56-68 hours after departure, after the departure forecast's horizon, and crosses the planned track about four days out. At day two the new forecast shows it; the alternatives are planned from the ship's position with that forecast and sailed through the realised weather (the first two days are the same for all three).

| Plan | Fuel incl. waiting | Voyage cost | Late voyages | Hours in seas above 6 m | Worst sea met |
|---|---|---|---|---|---|
| Baseline: shortest route at service speed, no replanning | 15,529 t | $17.03M | 0 of 24 | 333 | 7.6 m median, 10.7 m worst |
| Departure plan kept | 11,615 t | $15.15M | 12 of 24 | 581 | 10.3 m median, 13.5 m worst |
| Re-speeded on the same route | 11,989 t | $15.18M | 4 of 24 | 417 | 8.6 m median, 11.0 m worst |
| Re-routed and re-speeded | 11,939 t | $15.20M | 3 of 24 | 101 | 6.2 m median, 7.8 m worst |

Re-routing and re-speeding against keeping the plan: hours in seas above 6 m from 581 to 101, late voyages from 12 to 3, for 0.4% more cost in total (per voyage -5.9 to +6.3%, positive is cheaper). In money it is about even; what re-routing buys is the sea the ship does not meet.

## Congestion voyages: just-in-time arrival

18 voyages. At day two the destination announces it cannot berth until 18-40 hours after the window closes (its estimate is off by a median 2.3 h). Late penalties do not apply to waiting the port causes.

| Plan | Fuel incl. waiting | CO2 | Hours at anchor | Voyage cost |
|---|---|---|---|---|
| Departure plan kept, wait at anchor | 9,475 t | 29,505 t | 683 | $12.58M |
| Re-speeded to the announced berth | 8,026 t | 24,994 t | 112 | $11.51M |

Just in time saves 15.3% of fuel and CO2 on these voyages; hire is the same either way because the berth, not the ship, sets the end of the voyage.

## Bunker plan

For each ordinary voyage, bunkers for it and the next two legs (back and out again), with American ports at $610-680 and European at $555-620 a tonne, $6,000 a delivery, a 250 t minimum stem, the tank's capacity and a reserve of the leg's P90-over-P50 plus three days. The MILP against topping up at every call for the next leg: 1,276,001 USD saved over 36 plans (0.7% median, 0.0-15.6%; never worse, by construction), median solve 4 ms.

Run time per world: 557 s, 563 s, 518 s (in parallel).
