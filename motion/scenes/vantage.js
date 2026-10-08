/* What Happens When the Camera Loop Only Fires Twice? Left: lateral g by section (Turn-in 2.80; Apex 2.07; Exit 0.95; High-speed 0.00).
   Right: Draw calls, full scene 10; Lap sections tracked 8; Top speed, finish 310 kph; Track radius, apex 38 m. Every figure is on the project page. */
scene({
  slug: "vantage", aspect: 1.72, seconds: 6, bg: ["#120709", "#07090A"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "LATERAL G BY SECTION",
    bars: [["Turn-in", 2.8, "2.80", "#FF2B2B"], ["Apex", 2.07, "2.07", "#FF2B2B"], ["Exit", 0.95, "0.95", "#B6FF3B"], ["High-speed", 0, "0.00", "#7E878A"]],
    stats: [["Draw calls, full scene", "10", "#B6FF3B"], ["Lap sections tracked", "8", "#F3F3EF"], ["Top speed, finish", "310 kph", "#267BFF"], ["Track radius, apex", "38 m", "#8a8f98"]],
  }),
});
