/* What Has Nobody Tested Yet? Left: top 5 proposals that were real hidden effects (This build 72%; Count the connections 68%; Random untested pair 4%).
   Right: Generated papers 4,000; Test fields 10. Every figure is on the project page. */
scene({
  slug: "literature-discovery-engine", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "TOP 5 PROPOSALS THAT WERE REAL HIDDEN EFFECTS",
    bars: [["This build", 72, "72%"], ["Count the connections", 68, "68%"], ["Random untested pair", 4, "4%", "#8a8f98"]],
    stats: [["Generated papers", "4,000"], ["Test fields", "10"]],
  }),
});
