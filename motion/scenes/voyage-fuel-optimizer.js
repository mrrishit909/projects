/* Through the Storm, or Around It? Left: the demo voyage's cost from New York to Rotterdam, by the simulation truth (Shortest route at
   service speed $715,187; Re-routed and re-speeded $557,965). Right: Daily fuel error vs sea-trial curve 2.0–3.5% vs 3.5–17.0%; Hours in
   seas above 6 m, storm voyages 101 vs 581; Arrival at or before the P90 89%; Weather routing alone, ordinary weather 0.34% dearer.
   Every figure is on the project page. */
scene({
  slug: "voyage-fuel-optimizer", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "VOYAGE COST, NEW YORK TO ROTTERDAM",
    bars: [["Shortest route at service speed", 715187, "$715,187", "#8a8f98"], ["Re-routed and re-speeded", 557965, "$557,965"]],
    stats: [["Daily fuel error vs sea-trial curve", "2.0–3.5% vs 3.5–17.0%", "#4a95f0"], ["Hours in seas above 6 m, storm voyages", "101 vs 581", "#4a95f0"], ["Arrival at or before the P90", "89%", "#4a95f0"], ["Weather routing alone, ordinary weather", "0.34% dearer", "#ff8a3d"]],
  }),
});
