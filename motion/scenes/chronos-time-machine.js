/* Can a Map of History Show What It Doesn't Know? Left: land area of illustrative outlines vs published, million km² (Rome 117 CE, our outline 4.9; Rome 117 CE, published 5.0; Han 100 CE, our outline 4.1; Han 100 CE, published 6.5).
   Right: Citations behind the facts 507; Published city figures 201; Outlines within ±50% of published 24 of 27; Years on one timeline 12,000. Every figure is on the project page. */
scene({
  slug: "chronos-time-machine", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "LAND AREA OF ILLUSTRATIVE OUTLINES VS PUBLISHED, MILLION KM²",
    bars: [["Rome 117 CE, our outline", 4.9, "4.9", "#4a95f0"], ["Rome 117 CE, published", 5.0, "5.0", "#8a8f98"], ["Han 100 CE, our outline", 4.1, "4.1", "#4a95f0"], ["Han 100 CE, published", 6.5, "6.5", "#ff8a3d"]],
    stats: [["Citations behind the facts", "507", "#8a8f98"], ["Published city figures", "201", "#8a8f98"], ["Outlines within ±50% of published", "24 of 27", "#4a95f0"], ["Years on one timeline", "12,000", "#8a8f98"]],
  }),
});
