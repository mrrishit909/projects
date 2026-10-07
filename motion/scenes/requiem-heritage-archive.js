/* Can a Date Slider Build and Destroy a Building Honestly? Left: mean damage by year, % (1802: 1; 1996: 39; 2026: 51).
   Right: Parts standing in 2026 32; Parts lost 7; Risk before the $150,000 plan 1,656; after 1,370. Every figure is on the project page. */
scene({
  slug: "requiem-heritage-archive", aspect: 1.72, seconds: 6, bg: ["#171614", "#0a0a0a"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "MEAN DAMAGE, PERCENT",
    bars: [["1802, as built", 1, "1", "#E9DFC8"], ["1996, after the shelling", 39, "39", "#945D43"], ["2026, today", 51, "51", "#8A2424"]],
    stats: [["Parts standing, 2026", "32", "#E9DFC8"], ["Parts lost", "7", "#8A2424"], ["Risk before the plan", "1,656", "#8a8f98"], ["Risk after the plan", "1,370", "#E9DFC8"]],
  }),
});
