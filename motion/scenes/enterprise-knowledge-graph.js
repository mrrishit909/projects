/* Who Can Know What, and Since When? Left: retrieval recall@10 on three held-out corpora (BM25 alone 0.33–0.36; BM25 + LSA + graph
   0.59–0.62; BM25 + graph 0.69–0.71). Right: Permission leaks in 34,563 probes 0; Entity resolution B³ F1 0.977–0.981 vs 0.72–0.73;
   Citation coverage 100%; Owner today vs latest mention no better. Every figure is on the project page. */
scene({
  slug: "enterprise-knowledge-graph", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "RETRIEVAL RECALL@10, THREE HELD-OUT CORPORA",
    bars: [["BM25 alone", 0.36, "0.33–0.36", "#ff8a3d"], ["BM25 + LSA + graph", 0.62, "0.59–0.62", "#8a8f98"], ["BM25 + graph", 0.71, "0.69–0.71"]],
    stats: [["Permission leaks in 34,563 probes", "0", "#4a95f0"], ["Entity resolution B³ F1", "0.977–0.981 vs 0.72–0.73", "#4a95f0"], ["Citation coverage", "100%", "#4a95f0"], ["Owner today vs latest mention", "no better", "#ff8a3d"]],
  }),
});
