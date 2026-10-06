/* Can Two Million Invoices Become a Carbon Number You Can Audit? Left: true supplier emissions within reach of the top 20
   suppliers (Ranked by spend 38.7%; Ranked by emissions + network 50.5%). Right: Lineage coverage 100%; Reproduced from the
   stored data: hash for hash; Scenario on 10.2 million lines 39.6-41.5 s; Network centrality over emissions alone: no better.
   Every figure is on the project page. */
scene({
  slug: "scope3-carbon-accounting", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "TRUE SUPPLIER EMISSIONS IN REACH OF THE TOP 20",
    bars: [["Ranked by spend", 38.7, "38.7%", "#8a8f98"], ["Ranked by emissions + network", 50.5, "50.5%"]],
    stats: [["Lineage coverage", "100%", "#4a95f0"], ["Reproduced from the stored data", "hash for hash", "#4a95f0"], ["Scenario on 10.2 million lines", "39.6-41.5 s", "#4a95f0"], ["Network centrality over emissions alone", "no better", "#ff8a3d"]],
  }),
});
