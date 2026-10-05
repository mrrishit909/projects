/* The Lead Is Out for Three Days. Now What? Left: cost of an 85-scene shoot (Solved schedule, 17 days $1.33M; Story order, 19 days $1.64M).
   Right: Lead out 3 days: re-plan 12 s; Scenes moved 35 of 85; Cost after the re-plan $1.37M; Exteriors on rain days 0. Every figure is on the project page. */
scene({
  slug: "film-production-planner", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "COST OF AN 85-SCENE SHOOT",
    bars: [["Solved schedule, 17 days", 1.33, "$1.33M"], ["Story order, 19 days", 1.64, "$1.64M"]],
    stats: [["Lead out 3 days: re-plan", "12 s", "#4a95f0"], ["Scenes moved", "35 of 85", "#4a95f0"], ["Cost after the re-plan", "$1.37M"], ["Exteriors on rain days", "0"]],
  }),
});
