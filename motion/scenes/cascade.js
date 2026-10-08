/* What Does Zooming From Wafer to Atom Actually Look Like? Left: dies good vs defective (Good 60; Defective 4).
   Right: Draw calls, cells station 12; Scale stations, wafer to lattice 7; Hottest cell 101 C; Wafer yield 93.8%. Every figure is on the project page. */
scene({
  slug: "cascade", aspect: 1.72, seconds: 6, bg: ["#12101e", "#08090B"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "DIES, GOOD VS DEFECTIVE",
    bars: [["Good", 60, "60", "#5EF1D2"], ["Defective", 4, "4", "#FF46A2"]],
    stats: [["Draw calls, cells station", "12", "#7457FF"], ["Scale stations", "7", "#5EF1D2"], ["Hottest cell", "101 C", "#D98042"], ["Wafer yield", "93.8%", "#8a8f98"]],
  }),
});
