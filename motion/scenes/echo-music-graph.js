/* Can a Fingerprint Find the Sample? Left: fingerprint recall by query, % (Clean 10 s excerpt 47; Remixes 63; Noise 10 dB 16; Sped up 3% 0).
   Right: Precision, clean 87%; Real samples in the top 10 of the queue 8; Unlisted samples found 17 of 36; Recordings 1,471. Every figure is on the project page. */
scene({
  slug: "echo-music-graph", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "FINGERPRINT RECALL BY QUERY, %",
    bars: [["Clean 10 s excerpt", 47, "47", "#4a95f0"], ["Remixes", 63, "63", "#4a95f0"], ["Noise 10 dB", 16, "16", "#ff8a3d"], ["Sped up 3%", 0, "0", "#ff8a3d"]],
    stats: [["Precision, clean", "87%", "#4a95f0"], ["Real samples in the top 10 of the queue", "8", "#8a8f98"], ["Unlisted samples found", "17 of 36", "#8a8f98"], ["Recordings", "1,471", "#8a8f98"]],
  }),
});
