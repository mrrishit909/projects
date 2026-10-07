/* Which Plan Gets the Passengers Home? Left: passengers misconnected by plan (Wait for gates, the reference 101; A, minimum total delay 128; C, least disruption 121; B, protect connections 17).
   Right: Cost per run $0.43; Misconnected, waiting to plan B 101 → 17; Escalations 1 of 7 agents; Solver nodes per option 8,001. Every figure is on the project page. */
scene({
  slug: "aether-airport-recovery", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "PASSENGERS MISCONNECTED BY PLAN",
    bars: [["Wait for gates, the reference", 101, "101", "#8a8f98"], ["A, minimum total delay", 128, "128", "#ff8a3d"], ["C, least disruption", 121, "121", "#8a8f98"], ["B, protect connections", 17, "17", "#4a95f0"]],
    stats: [["Cost per run", "$0.43", "#ff8a3d"], ["Misconnected, waiting to plan B", "101 → 17", "#4a95f0"], ["Escalations", "1 of 7 agents", "#8a8f98"], ["Solver nodes per option", "8,001", "#8a8f98"]],
  }),
});
