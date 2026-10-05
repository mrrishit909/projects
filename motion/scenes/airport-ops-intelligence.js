/* A Storm Is Closing a Runway. Who Misses Their Flight? Left: missed connections, the evening replayed (Scheduled gates + hold departures 203; Scheduled gates 229; First free gate on arrival 239; New gates + a locked gate 266).
   Right: Delay error, model vs board 4.2 vs 4.5 min; Aircraft waiting for a gate 6 to 28; Nine evenings, with holds 2,148 vs 2,796; Gate optimiser alone saved none. Every figure is on the project page. */
scene({
  slug: "airport-ops-intelligence", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "MISSED CONNECTIONS, THE EVENING REPLAYED",
    bars: [["Scheduled gates + hold departures", 203, "203"], ["Scheduled gates", 229, "229"], ["First free gate on arrival", 239, "239"], ["New gates + a locked gate", 266, "266", "#ff8a3d"]],
    stats: [["Delay error, model vs board", "4.2 vs 4.5 min", "#4a95f0"], ["Aircraft waiting for a gate", "6 to 28", "#ff8a3d"], ["Nine evenings, with holds", "2,148 vs 2,796", "#4a95f0"], ["Gate optimiser alone", "saved none", "#8a8f98"]],
  }),
});
