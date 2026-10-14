/* Where to Keep It, and How to Move It. Left: synthetic annual network cost, M USD (legacy 588.0, optimized 563.6, 8 of 14 sites open; a 4.15% saving of
   24.4 M that is a property of invented costs). Right: inbound haul 686 to 576 mi, outbound 244 to 204 mi, 41 of 41 browser parity vectors,
   500 Monte Carlo draws. Census anchors, SYNTHETIC costs. Every figure is on the project page. */
scene({
  slug: "supply-chain-orchestra", aspect: 1.72, seconds: 6, bg: ["#0f0a12", "#050307"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "SYNTHETIC ANNUAL COST, M USD",
    bars: [["Legacy footprint", 588.0, "588.0", "#ff8a3d"], ["Optimized, 8 of 14 sites open", 563.6, "563.6", "#4a95f0"]],
    stats: [["Saving, a property of the costs", "4.15%", "#4a95f0"], ["Inbound haul, miles", "686 to 576", "#ff8a3d"], ["Browser parity vectors", "41 of 41", "#8a8f98"], ["Disruption draws", "500", "#8a8f98"]],
  }),
});
