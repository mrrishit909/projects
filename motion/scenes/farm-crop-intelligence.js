/* Which Patch of the Field Is Sick, and Where Should a Quarter Less Water Go? Left: yield under a 25% water cut, the season replayed (Water budgets by field 1,176 t; Every field cut by a quarter 1,136 t; Fixed schedule, no cut 1,204 t).
   Right: Disease patch found 11 of 12; Healthy ground flagged 0; Yield error vs crop average 1.5% vs 2.1%; Margin kept vs flat cut +2.4%. Every figure is on the project page. */
scene({
  slug: "farm-crop-intelligence", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "YIELD UNDER A 25% WATER CUT, THE SEASON REPLAYED",
    bars: [["Water budgets by field", 1176, "1,176 t"], ["Every field cut by a quarter", 1136, "1,136 t"], ["Fixed schedule, no cut", 1204, "1,204 t", "#8a8f98"]],
    stats: [["Disease patch found", "11 of 12", "#4a95f0"], ["Healthy ground flagged", "0", "#4a95f0"], ["Yield error vs crop average", "1.5% vs 2.1%", "#4a95f0"], ["Margin kept vs flat cut", "+2.4%", "#4a95f0"]],
  }),
});
