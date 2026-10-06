/* Which Bins Overflow This Weekend? Left: a festival saturday: kilometres to collect what needs it (Fixed weekly schedule 202.3 km; Dynamic routes, risk policy 125 km).
   Right: Overflows left for Sunday 12 vs 4; Overflow list on the festival bins 41 caught, 13 missed; Toy classifier on easy frames 100%; Smart containers 500. Every figure is on the project page. */
scene({
  slug: "waste-recycling-ops", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "A FESTIVAL SATURDAY: KILOMETRES TO COLLECT WHAT NEEDS IT",
    bars: [["Fixed weekly schedule", 202.3, "202.3 km"], ["Dynamic routes, risk policy", 125, "125 km", "#8a8f98"]],
    stats: [["Overflows left for Sunday", "12 vs 4", "#8a8f98"], ["Overflow list on the festival bins", "41 caught, 13 missed", "#ff8a3d"], ["Toy classifier on easy frames", "100%", "#ff8a3d"], ["Smart containers", "500", "#4a95f0"]],
  }),
});
