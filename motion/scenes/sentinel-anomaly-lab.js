/* Find the Signal Inside the Noise. Left: PCA detector on the test split, share of the 67 incidents caught and the false alerts a day (event recall 61%,
   alert precision 98%, 0.14 false alerts a day; point F1 0.47, point-adjusted 0.82). Right: median delay 107 s, robust z one-a-day line 0.97 on val and
   2.0 on test, point-adjust inflation up to 18.6x. Simulated CATS v2 data. Every figure is on the project page. */
scene({
  slug: "sentinel-anomaly-lab", aspect: 1.72, seconds: 6, bg: ["#0c0a14", "#040308"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "PCA DETECTOR, TEST SPLIT, SHARE %",
    bars: [["Alert precision", 98, "98%", "#4a95f0"], ["Incidents caught, 41 of 67", 61.2, "61%", "#ff8a3d"], ["Point F1, the flattering score is 0.82", 47, "0.47", "#8a8f98"]],
    stats: [["False alerts a day", "0.14", "#4a95f0"], ["Median detection delay", "107 s", "#ff8a3d"], ["Robust z, one a day: val, test", "0.97, 2.00", "#8a8f98"], ["Point-adjust inflation, up to", "18.6x", "#8a8f98"]],
  }),
});
