/* What Does It Cost to Keep the Lines Within Their Limits? Left: overload minutes after a line trip, on the true weather (Network-blind, no battery 480; The 12:00 plan 30; Perfect knowledge of the weather 0).
   Right: Solar at noon vs forecast 38%; Corridor loading after the trip 241%; Renewables used: plan vs perfect 84% vs 91%; Buses in the network 118. Every figure is on the project page. */
scene({
  slug: "renewable-grid-twin", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "OVERLOAD MINUTES AFTER A LINE TRIP, ON THE TRUE WEATHER",
    bars: [["Network-blind, no battery", 480, "480"], ["The 12:00 plan", 30, "30", "#4a95f0"], ["Perfect knowledge of the weather", 0, "0", "#8a8f98"]],
    stats: [["Solar at noon vs forecast", "38%", "#ff8a3d"], ["Corridor loading after the trip", "241%", "#ff8a3d"], ["Renewables used: plan vs perfect", "84% vs 91%", "#4a95f0"], ["Buses in the network", "118", "#8a8f98"]],
  }),
});
