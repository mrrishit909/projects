/* How Did a Dinosaur Line End Up as a Sparrow? Left: species lost in the big five, % (End-Permian 96; End-Triassic 80; K-Pg 76).
   Right: Lineages ending at the K-Pg 11; Steps from a sparrow to the first cells 24; Cited lineages 56; Published sources 48. Every figure is on the project page. */
scene({
  slug: "genesis-evolution-explorer", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "SPECIES LOST IN THE BIG FIVE, %",
    bars: [["End-Permian", 96, "96", "#ff8a3d"], ["End-Triassic", 80, "80", "#4a95f0"], ["K-Pg", 76, "76", "#ff8a3d"]],
    stats: [["Lineages ending at the K-Pg", "11", "#ff8a3d"], ["Steps from a sparrow to the first cells", "24", "#4a95f0"], ["Cited lineages", "56", "#8a8f98"], ["Published sources", "48", "#8a8f98"]],
  }),
});
