/* Which 96 Compounds Go on the Next Plate? Left: actives found per plate, three libraries (Upper confidence + diversity 73; Exploitation, best-predicted 83; Random plate 8).
   Right: Affinity error vs nearest neighbours 0.62 vs 0.85; Inside the 90% band, after rescaling 83–91%; Model error after the plate 0.629 vs 0.606 random; Molecules handled by RDKit 10,000. Every figure is on the project page. */
scene({
  slug: "drug-discovery-workspace", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "ACTIVES FOUND PER PLATE, THREE LIBRARIES",
    bars: [["Upper confidence + diversity", 73, "73"], ["Exploitation, best-predicted", 83, "83"], ["Random plate", 8, "8", "#8a8f98"]],
    stats: [["Affinity error vs nearest neighbours", "0.62 vs 0.85", "#4a95f0"], ["Inside the 90% band, after rescaling", "83–91%", "#4a95f0"], ["Model error after the plate", "0.629 vs 0.606 random", "#ff8a3d"], ["Molecules handled by RDKit", "10,000", "#8a8f98"]],
  }),
});
