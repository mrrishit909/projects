/* Can a Building Cut Its Power Bill Without Anyone Feeling Warmer? Left: a week's energy cost in a heat wave (Planned $3,563; Fixed schedule $5,236).
   Right: Peak demand 361 vs 519 kW; Energy used 28,615 vs 30,238 kWh; Minutes outside comfort band 0. Every figure is on the project page. */
scene({
  slug: "building-energy-optimizer", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "A WEEK'S ENERGY COST IN A HEAT WAVE",
    bars: [["Planned", 3563, "$3,563"], ["Fixed schedule", 5236, "$5,236"]],
    stats: [["Peak demand", "361 vs 519 kW", "#4a95f0"], ["Energy used", "28,615 vs 30,238 kWh", "#4a95f0"], ["Minutes outside comfort band", "0"]],
  }),
});
