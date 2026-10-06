/* What Is a 12% Price Rise Really Worth? Left: 12-month revenue gain from a 12% price rise, $m (Spreadsheet 8.02; Calibrated agents 1.85; True world 1.92).
   Right: Seeded scenarios 10,000; Churn in the month of a 12% rise: agents vs truth +145% vs +110%; True outcomes inside the 80% interval 58%; Time per scenario 2.3 ms. Every figure is on the project page. */
scene({
  slug: "enterprise-simulation-lab", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "12-MONTH REVENUE GAIN FROM A 12% PRICE RISE, $M",
    bars: [["Spreadsheet", 8.02, "8.02"], ["Calibrated agents", 1.85, "1.85", "#4a95f0"], ["True world", 1.92, "1.92", "#8a8f98"]],
    stats: [["Seeded scenarios", "10,000", "#4a95f0"], ["Churn in the month of a 12% rise: agents vs truth", "+145% vs +110%", "#ff8a3d"], ["True outcomes inside the 80% interval", "58%", "#ff8a3d"], ["Time per scenario", "2.3 ms", "#8a8f98"]],
  }),
});
