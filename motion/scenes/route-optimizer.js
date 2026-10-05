/* Can 50 Deliveries Be Re-Planned While Driving? Left: route length by solver time limit, 50 stops (3 s (default) 193.5 km; 0.5 s 196.2 km; 30 s 193.5 km).
   Right: Stops delivered 50 of 50; On time 49 of 50; Re-plans of van 1 3; Customer texts 93. Every figure is on the project page. */
scene({
  slug: "route-optimizer", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "ROUTE LENGTH BY SOLVER TIME LIMIT, 50 STOPS",
    bars: [["3 s (default)", 193.5, "193.5 km"], ["0.5 s", 196.2, "196.2 km"], ["30 s", 193.5, "193.5 km", "#8a8f98"]],
    stats: [["Stops delivered", "50 of 50", "#4a95f0"], ["On time", "49 of 50", "#4a95f0"], ["Re-plans of van 1", "3"], ["Customer texts", "93"]],
  }),
});
