/* How Many Hours Does This Bearing Have Left? Left: error in hours left, final 300 hours (This build 23 h; Simple approach 181 h).
   Right: Warning before failure 773 vs 535 h; Cost of the repair plan $13,788; Simple plan $40,067; Running to failure $111,631. Every figure is on the project page. */
scene({
  slug: "predictive-maintenance-rul", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "ERROR IN HOURS LEFT, FINAL 300 HOURS",
    bars: [["This build", 23, "23 h"], ["Simple approach", 181, "181 h"]],
    stats: [["Warning before failure", "773 vs 535 h", "#4a95f0"], ["Cost of the repair plan", "$13,788", "#4a95f0"], ["Simple plan", "$40,067", "#ff8a3d"], ["Running to failure", "$111,631", "#ff8a3d"]],
  }),
});
