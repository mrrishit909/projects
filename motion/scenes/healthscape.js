/* Health Has an Address. Left: CDC PLACES 2023 fair-or-poor-health estimates by county status (2,956 estimated, 187 not in this release, 1 suppressed).
   Right: median 21.3% (range 11.0 to 42.7%), 13.8 M adults in the counties not in the release, 146 counties hold half of all adults, rank movers 303.
   Every figure is on the project page. */
scene({
  slug: "healthscape", aspect: 1.72, seconds: 6, bg: ["#0b0714", "#030207"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "COUNTIES BY STATUS, 3,144 IN ALL",
    bars: [["Estimated (2023)", 2956, "2,956", "#A47CF6"], ["Not in this release: KY, PA", 187, "187", "#8a8f98"], ["Suppressed: Loving, TX", 8, "1", "#ff8a3d"]],
    stats: [["Median fair or poor health", "21.3%", "#A47CF6"], ["Adults in the missing counties", "13.8 M", "#8a8f98"], ["Counties holding half of adults", "146", "#A47CF6"], ["Counties that change rank most", "303", "#8a8f98"]],
  }),
});
