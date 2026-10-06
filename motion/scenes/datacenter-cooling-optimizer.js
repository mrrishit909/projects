/* Where Can 240 kW of GPUs Go, and What Happens When a CRAC Fails? Left: racks over 27 °c after crac-1 stops, in the simulated hall (No action 24; Runbook: every unit to 16 °C 16; Read the sensors, re-plan, approve caps 0).
   Right: Model said / hall reached, unit stopped 25.7 vs 36.4 °C; GPU power capped to recover 77 kW; Cooling energy saved by warmer set-points 22%; Model error on ordinary days 0.22 °C. Every figure is on the project page. */
scene({
  slug: "datacenter-cooling-optimizer", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "RACKS OVER 27 °C AFTER CRAC-1 STOPS, IN THE SIMULATED HALL",
    bars: [["No action", 24, "24"], ["Runbook: every unit to 16 °C", 16, "16", "#4a95f0"], ["Read the sensors, re-plan, approve caps", 0, "0", "#8a8f98"]],
    stats: [["Model said / hall reached, unit stopped", "25.7 vs 36.4 °C", "#ff8a3d"], ["GPU power capped to recover", "77 kW", "#ff8a3d"], ["Cooling energy saved by warmer set-points", "22%", "#8a8f98"], ["Model error on ordinary days", "0.22 °C", "#4a95f0"]],
  }),
});
