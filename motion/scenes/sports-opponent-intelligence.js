/* What Does the Opponent Run When the Clock Runs Down? Left: plays named from tracking alone, three leagues (Rules on the geometry 92.4%; Always the commonest play 35.7%).
   Right: Late-clock pick-and-roll, Prairie 37% (33–41%); Hidden share inside the 95% band 93.1%; Lineup error vs raw plus-minus 0.09–0.13 vs 0.14–0.18; Game score error, either way 8.1 pts. Every figure is on the project page. */
scene({
  slug: "sports-opponent-intelligence", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "PLAYS NAMED FROM TRACKING ALONE, THREE LEAGUES",
    bars: [["Rules on the geometry", 92.4, "92.4%"], ["Always the commonest play", 35.7, "35.7%"]],
    stats: [["Late-clock pick-and-roll, Prairie", "37% (33–41%)", "#4a95f0"], ["Hidden share inside the 95% band", "93.1%", "#4a95f0"], ["Lineup error vs raw plus-minus", "0.09–0.13 vs 0.14–0.18", "#4a95f0"], ["Game score error, either way", "8.1 pts", "#8a8f98"]],
  }),
});
