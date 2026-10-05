/* What Is Happening in the Reserve at Night? Left: gunshot alerts raised (Threshold set for the field 47; Simple way 3,750).
   Right: Real ones among them 16 vs 35; Night-vehicle pattern found 12 of 12; False clusters 0; Risk patrolled 90% vs 75%. Every figure is on the project page. */
scene({
  slug: "wildlife-conservation-network", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "GUNSHOT ALERTS RAISED",
    bars: [["Threshold set for the field", 47, "47"], ["Simple way", 3750, "3,750"]],
    stats: [["Real ones among them", "16 vs 35"], ["Night-vehicle pattern found", "12 of 12", "#4a95f0"], ["False clusters", "0", "#4a95f0"], ["Risk patrolled", "90% vs 75%", "#4a95f0"]],
  }),
});
