/* How Many Cycles Does This Engine Have Left? Left: remaining life of one worn engine, cycles (Fleet Weibull, population curve 4,567; Trend on its own telemetry, P50 68; What really happened 43).
   Right: Hangar night chosen day +1, fails day +13; RUL band coverage, eight fleets ≈40%; Anomaly lead over fault codes no earlier; Flights simulated 23,008. Every figure is on the project page. */
scene({
  slug: "aircraft-health-ops", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "REMAINING LIFE OF ONE WORN ENGINE, CYCLES",
    bars: [["Fleet Weibull, population curve", 4567, "4,567"], ["Trend on its own telemetry, P50", 68, "68", "#4a95f0"], ["What really happened", 43, "43", "#8a8f98"]],
    stats: [["Hangar night chosen", "day +1, fails day +13", "#8a8f98"], ["RUL band coverage, eight fleets", "≈40%", "#ff8a3d"], ["Anomaly lead over fault codes", "no earlier", "#ff8a3d"], ["Flights simulated", "23,008", "#4a95f0"]],
  }),
});
