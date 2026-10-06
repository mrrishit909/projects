/* Which 20 Sites Will Actually Enrol This Trial? Left: evaluable patients after 12 simulated months (Top sites by history 48;
   MILP portfolio 88; Forecast for the MILP portfolio 111). Right: Truly eligible patients found 98–100%; Evaluable patients,
   12 portfolios 1,286 vs 1,012; Criteria translated, unseen wording 9.0%, 0 wrong; Portfolio inside its 80% interval 7 of 12.
   Every figure is on the project page. */
scene({
  slug: "trial-site-optimizer", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "EVALUABLE PATIENTS AFTER 12 SIMULATED MONTHS",
    bars: [["Top sites by history", 48, "48", "#8a8f98"], ["MILP portfolio", 88, "88"], ["Forecast for the MILP portfolio", 111, "111", "#ff8a3d"]],
    stats: [["Truly eligible patients found", "98–100%", "#4a95f0"], ["Evaluable patients, 12 portfolios", "1,286 vs 1,012", "#4a95f0"], ["Criteria translated, unseen wording", "9.0%, 0 wrong", "#ff8a3d"], ["Portfolio inside its 80% interval", "7 of 12", "#ff8a3d"]],
  }),
});
