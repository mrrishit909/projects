/* Can Ships Tell You About a Slump Before the Statistics Do? Left: nowcast error, index points (Last published value 3.94; Factor-model bridge 2.35; Boosted trees 1.41).
   Right: Slump flagged before the official figure 77 days; Ningbo median dwell at the outage 6.4 vs 1.6 days; True voyages rebuilt 98.6%; Voyages on the map 45,758. Every figure is on the project page. */
scene({
  slug: "pulse-economic-activity", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "NOWCAST ERROR, INDEX POINTS",
    bars: [["Last published value", 3.94, "3.94", "#8a8f98"], ["Factor-model bridge", 2.35, "2.35", "#4a95f0"], ["Boosted trees", 1.41, "1.41", "#4a95f0"]],
    stats: [["Slump flagged before the official figure", "77 days", "#ff8a3d"], ["Ningbo median dwell at the outage", "6.4 vs 1.6 days", "#ff8a3d"], ["True voyages rebuilt", "98.6%", "#8a8f98"], ["Voyages on the map", "45,758", "#8a8f98"]],
  }),
});
