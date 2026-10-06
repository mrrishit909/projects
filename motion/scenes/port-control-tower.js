/* A Ship Is Four Hours Late. Whose Berth Does She Take? Left: minutes late beyond departure windows, 18 days (Berths and cranes planned together 48; First come, first served 324; Perfect knowledge of arrivals 27).
   Right: Arrival error vs distance over speed 8 vs 23 min; Planned rehandles vs discharge order 0 vs 2,079; Gate wait with appointments 1.7 vs 113 min; Crane use 81% vs 69%. Every figure is on the project page. */
scene({
  slug: "port-control-tower", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "MINUTES LATE BEYOND DEPARTURE WINDOWS, 18 DAYS",
    bars: [["Berths and cranes planned together", 48, "48"], ["First come, first served", 324, "324"], ["Perfect knowledge of arrivals", 27, "27", "#8a8f98"]],
    stats: [["Arrival error vs distance over speed", "8 vs 23 min", "#4a95f0"], ["Planned rehandles vs discharge order", "0 vs 2,079", "#4a95f0"], ["Gate wait with appointments", "1.7 vs 113 min", "#4a95f0"], ["Crane use", "81% vs 69%", "#4a95f0"]],
  }),
});
