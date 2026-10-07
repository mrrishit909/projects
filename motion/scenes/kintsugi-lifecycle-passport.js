/* What If a Repair Were the Most Valuable Part of the Product? Left: resale estimate of the hero kettle, USD (before the gold-seam lid repair 67, after 91).
   Right: grade C to B; repairability 7 to 8.3; share of its 1,392 g recovered 86.6 percent; repair 3.6 h, $150. Every figure is on the project page. */
scene({
  slug: "kintsugi-lifecycle-passport", aspect: 1.72, seconds: 6, bg: ["#1a1712", "#12110f"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "RESALE ESTIMATE, USD",
    bars: [["Lid chipped, grade C", 67, "$67", "#8E241F"], ["Gold-seam repair, grade B", 91, "$91", "#D9AA45"]],
    stats: [["Repairability index", "7 to 8.3", "#D9AA45"], ["Repair time and cost", "3.6 h, $150", "#EEE7D5"], ["Recovered at end of life", "86.6%", "#D9AA45"], ["Kettle mass", "1,392 g", "#EEE7D5"]],
  }),
});
