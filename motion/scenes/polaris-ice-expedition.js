/* Which Way Across the Strait When the Ice Is Thin and a Storm Is Coming? Left: thinnest ice on the route, cm (direct 26, safe ice 54; the rover needs 30.6).
   Right: hours inside the storm leaving at hour 20 (direct 25.7, safe 0); distance 190 vs 210 km; support access 42% vs 81%. Every figure is on the project page. */
scene({
  slug: "polaris-ice-expedition", aspect: 1.72, seconds: 6, bg: ["#0B5466", "#07121B"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "THINNEST ICE ON THE ROUTE, CM",
    bars: [["Direct route", 26, "26", "#9F8BEA"], ["Safe-ice route", 54, "54", "#78E6B5"]],
    stats: [["Hours in the storm, direct", "25.7 h", "#9F8BEA"], ["Hours in the storm, safe ice", "0 h", "#78E6B5"], ["Distance, direct to safe", "190 to 210 km", "#D9F5F6"], ["Support access", "42% to 81%", "#7CC7D9"]],
  }),
});
