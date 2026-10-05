/* Can Software Match Every Payout to the Bank? Left: 38 payouts, four matching passes (By reference 21; By exact amount 11; Within tolerance 1; Across currencies 1; Sent to review 3).
   Right: Matched 34 of 38; Problems flagged 8 of 8; Still inside the 3-day window 1. Every figure is on the project page. */
scene({
  slug: "recon-engine", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "38 PAYOUTS, FOUR MATCHING PASSES",
    bars: [["By reference", 21, "21"], ["By exact amount", 11, "11", "#4a95f0"], ["Within tolerance", 1, "1", "#4a95f0"], ["Across currencies", 1, "1", "#4a95f0"], ["Sent to review", 3, "3"]],
    stats: [["Matched", "34 of 38", "#4a95f0"], ["Problems flagged", "8 of 8", "#4a95f0"], ["Still inside the 3-day window", "1"]],
  }),
});
