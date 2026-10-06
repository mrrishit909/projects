/* Which Burn Actually Makes the Satellite Safe? Left: avoidance burns re-screened, cm/s (Cheapest, 4 orbits early: rejected 2.84; Option A, 0.5 orbit early 7.65; Option B, 0.25 orbit early 16.26).
   Right: Closest approach, rocket body 41 m; Probability of collision 3.0 × 10⁻⁴; Candidates rejected 8 of 10; Objects propagated live 18,050. Every figure is on the project page. */
scene({
  slug: "orbital-space-traffic", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "AVOIDANCE BURNS RE-SCREENED, CM/S",
    bars: [["Cheapest, 4 orbits early: rejected", 2.84, "2.84", "#ff8a3d"], ["Option A, 0.5 orbit early", 7.65, "7.65", "#4a95f0"], ["Option B, 0.25 orbit early", 16.26, "16.26", "#4a95f0"]],
    stats: [["Closest approach, rocket body", "41 m", "#ff8a3d"], ["Probability of collision", "3.0 × 10⁻⁴", "#ff8a3d"], ["Candidates rejected", "8 of 10", "#8a8f98"], ["Objects propagated live", "18,050", "#8a8f98"]],
  }),
});
