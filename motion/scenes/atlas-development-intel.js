/* Who Challenges the Pro Forma? Left: irr, as submitted vs committee-adjusted, % (Mixed-use, as submitted 9.5; Mixed-use, adjusted 7.6; Multifamily, adjusted 7.1; Bonus program, adjusted 7.0).
   Right: Cost per run $0.65; Assumptions flagged 3 of 7; Escalations 1 of 10; Parcels in the city 1,900. Every figure is on the project page. */
scene({
  slug: "atlas-development-intel", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "IRR, AS SUBMITTED VS COMMITTEE-ADJUSTED, %",
    bars: [["Mixed-use, as submitted", 9.49, "9.5", "#8a8f98"], ["Mixed-use, adjusted", 7.65, "7.6", "#ff8a3d"], ["Multifamily, adjusted", 7.11, "7.1", "#4a95f0"], ["Bonus program, adjusted", 6.96, "7.0", "#4a95f0"]],
    stats: [["Cost per run", "$0.65", "#ff8a3d"], ["Assumptions flagged", "3 of 7", "#ff8a3d"], ["Escalations", "1 of 10", "#8a8f98"], ["Parcels in the city", "1,900", "#8a8f98"]],
  }),
});
