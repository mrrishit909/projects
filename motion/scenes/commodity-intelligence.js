/* Is Copper in Surplus Right Now? Left: balance nowcast error, kt a week, 32 periods (Last official figure 15.8; Regression on the same signals 4.9; Kalman nowcast 2.8).
   Right: Truth inside the 80% band 84–91%; Outages caught by the shipping detector 24 of 32; Price direction, 12 weeks out 34–53%; Cargoes simulated 5,281. Every figure is on the project page. */
scene({
  slug: "commodity-intelligence", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "BALANCE NOWCAST ERROR, KT A WEEK, 32 PERIODS",
    bars: [["Last official figure", 15.8, "15.8"], ["Regression on the same signals", 4.9, "4.9"], ["Kalman nowcast", 2.8, "2.8", "#8a8f98"]],
    stats: [["Truth inside the 80% band", "84–91%", "#4a95f0"], ["Outages caught by the shipping detector", "24 of 32", "#4a95f0"], ["Price direction, 12 weeks out", "34–53%", "#ff8a3d"], ["Cargoes simulated", "5,281", "#8a8f98"]],
  }),
});
