/* Can Better Signal Timing Empty a Stadium Faster? Left: delay per vehicle, stadium evening (Proposed timing 158 s; Today 388 s).
   Right: Bus delay 66 vs 192 s; Junctions blocked 0 vs 1,225; Pedestrian wait 11.2 vs 13.3 s; Stops (worse) 13,192 vs 11,445. Every figure is on the project page. */
scene({
  slug: "traffic-signal-twin", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "DELAY PER VEHICLE, STADIUM EVENING",
    bars: [["Proposed timing", 158, "158 s"], ["Today", 388, "388 s"]],
    stats: [["Bus delay", "66 vs 192 s", "#4a95f0"], ["Junctions blocked", "0 vs 1,225", "#4a95f0"], ["Pedestrian wait", "11.2 vs 13.3 s", "#4a95f0"], ["Stops (worse)", "13,192 vs 11,445", "#ff8a3d"]],
  }),
});
