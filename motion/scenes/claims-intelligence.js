/* Who Is Really Behind This Insurance Claim? Left: fraud caught in the top 2% of claims (Graph + claim facts 54.6%; Claim facts only 36.6%; Red-flag checklist 16.8%).
   Right: Hit rate, graph 47.7%; Hit rate, claim facts only 32.0%; Hit rate, checklist 14.7%; Planted fraud rings 25. Every figure is on the project page. */
scene({
  slug: "claims-intelligence", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "FRAUD CAUGHT IN THE TOP 2% OF CLAIMS",
    bars: [["Graph + claim facts", 54.6, "54.6%"], ["Claim facts only", 36.6, "36.6%"], ["Red-flag checklist", 16.8, "16.8%"]],
    stats: [["Hit rate, graph", "47.7%", "#4a95f0"], ["Hit rate, claim facts only", "32.0%", "#ff8a3d"], ["Hit rate, checklist", "14.7%", "#ff8a3d"], ["Planted fraud rings", "25"]],
  }),
});
