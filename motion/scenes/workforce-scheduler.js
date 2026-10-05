/* Who Works When? A Week's Schedule That Obeys Every Rule, and Survives Two Sick Calls Left: a week's labor cost, 61 people (Solver $29,121; First-fit $33,908).
   Right: Demand covered 99.9% vs 92.8%; Hours beyond demand 122.5 vs 400; Two sick calls: changed 3 of 45; Hours below contract (worse) 264 vs 128. Every figure is on the project page. */
scene({
  slug: "workforce-scheduler", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "A WEEK'S LABOR COST, 61 PEOPLE",
    bars: [["Solver", 29121, "$29,121"], ["First-fit", 33908, "$33,908"]],
    stats: [["Demand covered", "99.9% vs 92.8%", "#4a95f0"], ["Hours beyond demand", "122.5 vs 400", "#4a95f0"], ["Two sick calls: changed", "3 of 45", "#4a95f0"], ["Hours below contract (worse)", "264 vs 128", "#ff8a3d"]],
  }),
});
