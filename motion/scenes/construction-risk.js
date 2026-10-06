/* When Does the Building Really Finish? Left: finish forecast, mean error in days, 24 outcomes (Re-plan at planned durations 80; Monte Carlo, site status only 17; Monte Carlo, told the disruptions 14).
   Right: Truth inside the band 71–75%; One notice and three wet weeks +53 days; Change order: requested vs simulated 30 vs 47 days; Activities simulated 600. Every figure is on the project page. */
scene({
  slug: "construction-risk", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "FINISH FORECAST, MEAN ERROR IN DAYS, 24 OUTCOMES",
    bars: [["Re-plan at planned durations", 80, "80"], ["Monte Carlo, site status only", 17, "17"], ["Monte Carlo, told the disruptions", 14, "14", "#8a8f98"]],
    stats: [["Truth inside the band", "71–75%", "#ff8a3d"], ["One notice and three wet weeks", "+53 days", "#4a95f0"], ["Change order: requested vs simulated", "30 vs 47 days", "#4a95f0"], ["Activities simulated", "600", "#8a8f98"]],
  }),
});
