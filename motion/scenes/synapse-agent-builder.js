/* Is the Cheaper Model Good Enough to Ship? Left: end-to-end pass rate on 64 labeled e-mails, % (v1, Atlas Large 89.1%; v2, Nova Pro: release gate blocks it 82.8%).
   Right: v2 cost per 1,000 runs $0.48 vs $1.65; v2 classification accuracy 92.2% vs 90.6%; CRM timeout, then retry 2.50 s + 250 ms; Draft cache: wrong order quoted 24 replies. Every figure is on the project page. */
scene({
  slug: "synapse-agent-builder", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "END-TO-END PASS RATE ON 64 LABELED E-MAILS, %",
    bars: [["v1, Atlas Large", 89.1, "89.1%", "#4a95f0"], ["v2, Nova Pro: release gate blocks it", 82.8, "82.8%", "#ff8a3d"]],
    stats: [["v2 cost per 1,000 runs", "$0.48 vs $1.65", "#8a8f98"], ["v2 classification accuracy", "92.2% vs 90.6%", "#8a8f98"], ["CRM timeout, then retry", "2.50 s + 250 ms", "#ff8a3d"], ["Draft cache: wrong order quoted", "24 replies", "#ff8a3d"]],
  }),
});
