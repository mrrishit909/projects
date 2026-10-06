/* Where Should the Trucks Go When the Ore Runs Thin? Left: hours of the mill feed inside the plant's grade window, per 8-hour re-planned
   shift on held-out mines (MIP plan with proportional reclaim 3.7; with the blend MILP 6.3). Right: Engine failures caught ahead
   100 of 100 vs 64; Cycle-time MAPE 4.29–4.93% vs 9.82–12.0%; Dispatch solve, 200 trucks 0.09 s; Against a re-plan heuristic +$50k,
   3 of 6 shifts. Every figure is on the project page. */
scene({
  slug: "mine-ore-optimizer", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "HOURS OF MILL FEED IN THE GRADE WINDOW, OF 8",
    bars: [["Proportional reclaim", 3.7, "3.7", "#8a8f98"], ["Blend MILP", 6.3, "6.3"]],
    stats: [["Engine failures caught ahead", "100 of 100 vs 64", "#4a95f0"], ["Cycle-time MAPE", "4.29–4.93% vs 9.82–12.0%", "#4a95f0"], ["Dispatch solve, 200 trucks", "0.09 s", "#4a95f0"], ["Against a re-plan heuristic", "+$50k, 3 of 6 shifts", "#ff8a3d"]],
  }),
});
