/* Which Material Makes the Lightest Part That Is Just as Stiff, and What Does It Cost the Planet? Left: carbon for a beam of equal stiffness, kgCO2e (carbon steel 2.55, aluminium 6061 6.53).
   Right: mass 1.34 kg steel vs 0.80 kg aluminium; CFRP 0.45 kg and 11.3 kgCO2e; spruce 0.33 kg and 0.13 kgCO2e. Every figure is on the project page. */
scene({
  slug: "alchemia-material-library", aspect: 1.72, seconds: 6, bg: ["#2a1a10", "#0E1114"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "CARBON FOR AN EQUAL-STIFFNESS BEAM, KGCO2E",
    bars: [["Carbon steel 1020", 2.55, "2.55", "#8796A5"], ["Aluminium 6061", 6.53, "6.53", "#FF9A3D"]],
    stats: [["Mass, steel to aluminium", "1.34 to 0.80 kg", "#EFEDE5"], ["CFRP beam", "0.45 kg, 11.3 kgCO2e", "#315D8C"], ["Spruce beam", "0.33 kg, 0.13 kgCO2e", "#B86E3C"], ["Materials in the library", "44", "#FF9A3D"]],
  }),
});
