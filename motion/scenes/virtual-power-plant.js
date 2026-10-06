/* How Much Can 10,000 Homes Really Give the Grid at 6 p.m.? Left: flexible mw on a heat-wave evening (Nameplate in the registry 41.9; Bid: 25th percentile of what it can hold 13.1; Industry performance-factor bid 6.4).
   Right: Credited by the market, of delivered 27.8 of 38.7 MWh; Stale battery reserves found 68 of 68; F4 if devices had reverted 1.25 MW over; Market baseline short of the truth 28%. Every figure is on the project page. */
scene({
  slug: "virtual-power-plant", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "FLEXIBLE MW ON A HEAT-WAVE EVENING",
    bars: [["Nameplate in the registry", 41.9, "41.9"], ["Bid: 25th percentile of what it can hold", 13.1, "13.1", "#4a95f0"], ["Industry performance-factor bid", 6.4, "6.4"]],
    stats: [["Credited by the market, of delivered", "27.8 of 38.7 MWh", "#ff8a3d"], ["Stale battery reserves found", "68 of 68", "#8a8f98"], ["F4 if devices had reverted", "1.25 MW over", "#ff8a3d"], ["Market baseline short of the truth", "28%", "#4a95f0"]],
  }),
});
