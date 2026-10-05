/* One Battery Is Warming, Debris Is Coming, and Nothing Is Sent Without Two People Left: slow battery drifts caught, 108 injected (Against the orbit-phase normal 108 of 108; Fixed red limit 36 of 108; Isolation Forest 0 of 108).
   Right: Time to alarm 2–3 h vs 10–13 h; False alarms, 36 clean records 0; Priority-weighted data vs first come +9.6%; Approvals before uplink 2 people. Every figure is on the project page. */
scene({
  slug: "satellite-fleet-ops", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "SLOW BATTERY DRIFTS CAUGHT, 108 INJECTED",
    bars: [["Against the orbit-phase normal", 108, "108 of 108"], ["Fixed red limit", 36, "36 of 108"], ["Isolation Forest", 0, "0 of 108", "#8a8f98"]],
    stats: [["Time to alarm", "2–3 h vs 10–13 h", "#4a95f0"], ["False alarms, 36 clean records", "0", "#4a95f0"], ["Priority-weighted data vs first come", "+9.6%", "#4a95f0"], ["Approvals before uplink", "2 people", "#8a8f98"]],
  }),
});
