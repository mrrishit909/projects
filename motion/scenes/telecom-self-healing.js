/* Which Link Is Behind Four Hundred Alarms? Left: peak load on the degraded backhaul link L-S08-AGG-NE at the evening busy hour
   (twin forecast, doing nothing 113%; measured with the approved plan 61%). Right: Alarms into incidents 403 → 11; Root cause in
   the top three 99% vs 46%; Sleeping cells found 9 of 9 vs 0 of 9; Alarm reduction over all alarms 4.7–7.2:1. Every figure is on
   the project page. */
scene({
  slug: "telecom-self-healing", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "PEAK LOAD ON THE DEGRADED BACKHAUL, EVENING BUSY HOUR",
    bars: [["Do nothing (twin forecast)", 113, "113%", "#8a8f98"], ["With the approved reroute (measured)", 61, "61%"]],
    stats: [["Alarms into incidents", "403 → 11", "#4a95f0"], ["Root cause in the top three", "99% vs 46%", "#4a95f0"], ["Sleeping cells found", "9 of 9 vs 0 of 9", "#4a95f0"], ["Alarm reduction, all alarms", "4.7–7.2:1", "#ff8a3d"]],
  }),
});
