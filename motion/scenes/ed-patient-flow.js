/* How Bad Will the Waiting Room Get? Left: peak waiting room in the surge, 30 runs (Baseline, wards slow 49.5; Six surge beds, four nurses, discharge push 35.5).
   Right: Door to bed, median 137 → 81 min; Admission AUC vs triage alone 0.78 vs 0.73; Length-of-stay model vs median no better; Approval before any action director, not proposer. Every figure is on the project page. */
scene({
  slug: "ed-patient-flow", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "PEAK WAITING ROOM IN THE SURGE, 30 RUNS",
    bars: [["Baseline, wards slow", 49.5, "49.5"], ["Six surge beds, four nurses, discharge push", 35.5, "35.5", "#8a8f98"]],
    stats: [["Door to bed, median", "137 → 81 min", "#4a95f0"], ["Admission AUC vs triage alone", "0.78 vs 0.73", "#4a95f0"], ["Length-of-stay model vs median", "no better", "#ff8a3d"], ["Approval before any action", "director, not proposer", "#8a8f98"]],
  }),
});
