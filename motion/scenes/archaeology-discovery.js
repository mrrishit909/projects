/* Two Surveys See It Faintly. Where Do You Dig? Left: false candidate areas per valley, 12 valleys (LiDAR and crop index fused 1.2; LiDAR alone 9.8; Crop index alone 0).
   Right: Masonry covered, fused vs LiDAR 55.7% vs 67.3%; Enclosure rectangle recovered 11 of 12; Enclosure vs field reading, after the trench 73% vs 11%; Walls drawn by inference 2.1 of 4. Every figure is on the project page. */
scene({
  slug: "archaeology-discovery", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "FALSE CANDIDATE AREAS PER VALLEY, 12 VALLEYS",
    bars: [["LiDAR and crop index fused", 1.2, "1.2"], ["LiDAR alone", 9.8, "9.8"], ["Crop index alone", 0.0, "0", "#8a8f98"]],
    stats: [["Masonry covered, fused vs LiDAR", "55.7% vs 67.3%", "#4a95f0"], ["Enclosure rectangle recovered", "11 of 12", "#4a95f0"], ["Enclosure vs field reading, after the trench", "73% vs 11%", "#4a95f0"], ["Walls drawn by inference", "2.1 of 4", "#8a8f98"]],
  }),
});
