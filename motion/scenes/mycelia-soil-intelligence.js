/* What Happens to a Farm's Water When Its Soil Carbon Rises? Left: runoff in a 180 mm storm on Stone Close, mm (Today 40.2; After 10 years of the regenerative practice 22.5; Rain 180).
   Right: Average soil health now 42; with the regenerative practice 54; Carbon on Stone Close in 10 years, current 0.90%, scenario 1.36%. Every figure is on the project page. */
scene({
  slug: "mycelia-soil-intelligence", aspect: 1.72, seconds: 6, bg: ["#18140F", "#0b0906"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "STORM RUNOFF ON STONE CLOSE, MM",
    bars: [["Today", 40.2, "40.2", "#A35C3B"], ["After ten regenerative years", 22.5, "22.5", "#92A85E"]],
    stats: [["Average health now", "42", "#8a8f98"], ["Average health, regenerative", "54", "#E8C86A"], ["Carbon in 10 y, current", "0.90%", "#A35C3B"], ["Carbon in 10 y, scenario", "1.36%", "#92A85E"]],
  }),
});
