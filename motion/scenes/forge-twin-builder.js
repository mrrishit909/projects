/* Would a Second CNC Machine Pay Off? Left: throughput, parts per hour, thirty simulated shifts (Production line 60.8; Expansion: second CNC 71.8; Raw-material release rate 72).
   Right: Gain, 95% interval +11.0 (9.4 to 12.6); Added capex $240,000; Vibration alarm before the trip 22.3 min median; Telemetry WebSockets held 2,000. Every figure is on the project page. */
scene({
  slug: "forge-twin-builder", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "THROUGHPUT, PARTS PER HOUR, THIRTY SIMULATED SHIFTS",
    bars: [["Production line", 60.8, "60.8", "#8a8f98"], ["Expansion: second CNC", 71.8, "71.8", "#4a95f0"], ["Raw-material release rate", 72, "72", "#ff8a3d"]],
    stats: [["Gain, 95% interval", "+11.0 (9.4 to 12.6)", "#4a95f0"], ["Added capex", "$240,000", "#8a8f98"], ["Vibration alarm before the trip", "22.3 min median", "#ff8a3d"], ["Telemetry WebSockets held", "2,000", "#8a8f98"]],
  }),
});
