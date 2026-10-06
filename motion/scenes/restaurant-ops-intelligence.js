/* What Should 50 Kitchens Prep When the Truck Is Late and It Rains? Left: demand lost to stockouts over the demo's three disrupted
   days (Usual practice 13.0%; Plan before the notices 9.5%; Re-planned 1.9%). Right: Item lunch-rush interval coverage 91.0–91.2%;
   Waste, 14 days 9.0% vs 12.1%; Forecast refresh, 50 stores, p95 1.22 s; Hazard model in ordering no better.
   Every figure is on the project page. */
scene({
  slug: "restaurant-ops-intelligence", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "DEMAND LOST TO STOCKOUTS, 3 DISRUPTED DAYS",
    bars: [["Usual practice", 13.0, "13.0%", "#8a8f98"], ["Plan before the notices", 9.5, "9.5%", "#8a8f98"], ["Re-planned", 1.9, "1.9%"]],
    stats: [["Item lunch-rush interval coverage", "91.0–91.2%", "#4a95f0"], ["Waste, 14 days", "9.0% vs 12.1%", "#4a95f0"], ["Forecast refresh, 50 stores, p95", "1.22 s", "#4a95f0"], ["Hazard model in ordering", "no better", "#ff8a3d"]],
  }),
});
