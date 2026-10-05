/* How Private Can Useful Synthetic Data Be? Left: auc of a model trained on each table (Synthetic, no DP 0.880; Synthetic, ε = 8 0.870; Synthetic, ε = 1 0.845; The real rows 0.929).
   Right: Census rows 32,561; JS distance, no DP 0.046; JS distance, ε = 1 0.228. Every figure is on the project page. */
scene({
  slug: "synthetic-data-generator", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "AUC OF A MODEL TRAINED ON EACH TABLE",
    bars: [["Synthetic, no DP", 0.88, "0.880"], ["Synthetic, ε = 8", 0.87, "0.870", "#4a95f0"], ["Synthetic, ε = 1", 0.845, "0.845", "#4a95f0"], ["The real rows", 0.929, "0.929", "#8a8f98"]],
    stats: [["Census rows", "32,561"], ["JS distance, no DP", "0.046", "#4a95f0"], ["JS distance, ε = 1", "0.228", "#ff8a3d"]],
  }),
});
