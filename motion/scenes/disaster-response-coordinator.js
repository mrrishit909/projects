/* Who Gets Cut Off, and Who Gets Help First? Left: severe emergencies reached, of 35 at peak (All units assigned together 18; Nearest unit, call order 14).
   Right: Minutes to a severe call 6.0 vs 7.9; Weighted wait 19.5% lower; Severe left waiting 416 vs 558; Response units 24. Every figure is on the project page. */
scene({
  slug: "disaster-response-coordinator", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "SEVERE EMERGENCIES REACHED, OF 35 AT PEAK",
    bars: [["All units assigned together", 18, "18"], ["Nearest unit, call order", 14, "14"]],
    stats: [["Minutes to a severe call", "6.0 vs 7.9", "#4a95f0"], ["Weighted wait", "19.5% lower", "#4a95f0"], ["Severe left waiting", "416 vs 558", "#4a95f0"], ["Response units", "24"]],
  }),
});
