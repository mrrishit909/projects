/* Where Should 183 Tonnes of Surplus Food Go? Left: trucks needed to collect the surplus (Planned rounds 65; One trip per seller 172).
   Right: Kilometres 1,624 vs 3,444; Unsafe lots offered 16 vs 772; Forecast error 26.7% vs 33.3%. Every figure is on the project page. */
scene({
  slug: "food-waste-exchange", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "TRUCKS NEEDED TO COLLECT THE SURPLUS",
    bars: [["Planned rounds", 65, "65"], ["One trip per seller", 172, "172"]],
    stats: [["Kilometres", "1,624 vs 3,444", "#4a95f0"], ["Unsafe lots offered", "16 vs 772", "#4a95f0"], ["Forecast error", "26.7% vs 33.3%", "#4a95f0"]],
  }),
});
