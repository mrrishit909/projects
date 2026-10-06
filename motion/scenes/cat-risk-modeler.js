/* How Much Could One Hurricane Season Cost? Left: average annual loss on the demo coast, $m (Burn cost, forty observed storms $9.6M; The model, 50,000 landfalls $9.2M; Simulation truth $8.9M).
   Right: 250-year PML: model vs truth $227M vs $231M; Category 4 stress: model vs truth $299M vs $440M; Cat 4 landfalls, fitted vs true 1 in 12 vs 1 in 50; Simulated years 144,118. Every figure is on the project page. */
scene({
  slug: "cat-risk-modeler", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "AVERAGE ANNUAL LOSS ON THE DEMO COAST, $M",
    bars: [["Burn cost, forty observed storms", 9.6, "$9.6M"], ["The model, 50,000 landfalls", 9.2, "$9.2M", "#4a95f0"], ["Simulation truth", 8.9, "$8.9M", "#8a8f98"]],
    stats: [["250-year PML: model vs truth", "$227M vs $231M", "#4a95f0"], ["Category 4 stress: model vs truth", "$299M vs $440M", "#ff8a3d"], ["Cat 4 landfalls, fitted vs true", "1 in 12 vs 1 in 50", "#ff8a3d"], ["Simulated years", "144,118", "#8a8f98"]],
  }),
});
