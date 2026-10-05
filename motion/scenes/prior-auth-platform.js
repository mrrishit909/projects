/* Can Software Carry a Prior Authorization From Order to Appeal? Left: policy passage search, top hit right (This build 66.1%; Baseline 20.9%).
   Right: Approval score (AUC) 0.907 vs 0.663; Denial reason, unseen wording 65.2% vs 16.7%; MRI request, rules met 3 of 4. Every figure is on the project page. */
scene({
  slug: "prior-auth-platform", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "POLICY PASSAGE SEARCH, TOP HIT RIGHT",
    bars: [["This build", 66.1, "66.1%"], ["Baseline", 20.9, "20.9%"]],
    stats: [["Approval score (AUC)", "0.907 vs 0.663", "#4a95f0"], ["Denial reason, unseen wording", "65.2% vs 16.7%", "#4a95f0"], ["MRI request, rules met", "3 of 4"]],
  }),
});
