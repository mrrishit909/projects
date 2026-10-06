/* Is This Invention New, and Where Has Nobody Filed? Left: ndcg@10 on 450 held-out inventions, judged by hidden concepts (LSA alone 0.591; BM25 keywords 0.699; Element re-ranking + citations 0.786).
   Right: Patents in the invented field 4,000; Recall@50 of near-anticipations 0.462; Paraphrase cost to nDCG@10 0.896 → 0.786; White-space pairs naming the planted gap 12 of 12. Every figure is on the project page. */
scene({
  slug: "patent-landscape-engine", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "NDCG@10 ON 450 HELD-OUT INVENTIONS, JUDGED BY HIDDEN CONCEPTS",
    bars: [["LSA alone", 0.591, "0.591"], ["BM25 keywords", 0.699, "0.699", "#4a95f0"], ["Element re-ranking + citations", 0.786, "0.786", "#8a8f98"]],
    stats: [["Patents in the invented field", "4,000", "#4a95f0"], ["Recall@50 of near-anticipations", "0.462", "#ff8a3d"], ["Paraphrase cost to nDCG@10", "0.896 → 0.786", "#ff8a3d"], ["White-space pairs naming the planted gap", "12 of 12", "#8a8f98"]],
  }),
});
