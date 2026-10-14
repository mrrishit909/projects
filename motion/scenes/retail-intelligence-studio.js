/* The Hidden Patterns Behind Every Purchase. Left: the hero pair, baskets holding a Jumbo Bag Red Retrospot (4,013), a Jumbo Bag Pink Polkadot (2,245)
   and both (1,428 against 228 expected by chance). Right: lift 6.3, best forecast WAPE 29.3% against seasonal-naive 45.2%, CLV holdout error -1.4%,
   Champions 68.6% of revenue. Every figure is on the project page. */
scene({
  slug: "retail-intelligence-studio", aspect: 1.72, seconds: 6, bg: ["#12060b", "#050203"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "BASKETS, ONE PAIR OF BAGS",
    bars: [["Red Retrospot bag", 4013, "4,013", "#FF2F7A"], ["Pink Polkadot bag", 2245, "2,245", "#FF4C25"], ["Both (chance: 228)", 1428, "1,428", "#FFE9E2"]],
    stats: [["Lift over chance", "6.3x", "#FFE9E2"], ["Forecast WAPE vs naive", "29.3 vs 45.2%", "#8fa2ff"], ["CLV holdout error", "-1.4%", "#8fa2ff"], ["Champions, share of revenue", "68.6%", "#FF2F7A"]],
  }),
});
