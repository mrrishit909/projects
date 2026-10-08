/* What Does It Look Like to Bring a Star Online? Left: confinement percent by stage (Vacuum 0; Confinement 55; Heating 92; Output 95).
   Right: Draw calls, full scene 4; Core temp at heating 150 MK; Field coils instanced 16; Instability dip, mid-sequence 75%. Every figure is on the project page. */
scene({
  slug: "aurelia", aspect: 1.72, seconds: 6, bg: ["#071626", "#020408"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "CONFINEMENT % BY STAGE",
    bars: [["Vacuum", 0, "0", "#2870FF"], ["Confinement", 55, "55", "#19E6FF"], ["Heating", 92, "92", "#19E6FF"], ["Output", 95, "95", "#A55CFF"]],
    stats: [["Draw calls, full scene", "4", "#19E6FF"], ["Core temp at heating", "150 MK", "#FF2BB5"], ["Field coils instanced", "16", "#A55CFF"], ["Instability dip", "75%", "#8a8f98"]],
  }),
});
