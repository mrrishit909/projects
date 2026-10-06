/* How Long Is the Line at the Polling Place? Left: worst-hour wait at one polling place, minutes (Before the failure 97; Two check-in devices down 254; After the dispatch 58).
   Right: The plan's own view: places to standard 6 → 16; On the real day one fewer over 30; In line at close, after the plan 11–35% fewer; Voter records in the system none. Every figure is on the project page. */
scene({
  slug: "election-ops-planner", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "WORST-HOUR WAIT AT ONE POLLING PLACE, MINUTES",
    bars: [["Before the failure", 97, "97"], ["Two check-in devices down", 254, "254", "#ff8a3d"], ["After the dispatch", 58, "58", "#8a8f98"]],
    stats: [["The plan's own view: places to standard", "6 → 16", "#4a95f0"], ["On the real day", "one fewer over 30", "#ff8a3d"], ["In line at close, after the plan", "11–35% fewer", "#8a8f98"], ["Voter records in the system", "none", "#8a8f98"]],
  }),
});
