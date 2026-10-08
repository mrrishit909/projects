/* What Does a Lens Change Actually Cost a Camera Move? Left: field of view by lens (24mm 74deg; 35mm 56deg; 50mm 42deg; 85mm 26deg).
   Right: Draw calls, full scene 8; Shots in the sequence 5; Defocus at shot 2 0.06mm; Timeline length 30s. Every figure is on the project page. */
scene({
  slug: "phantom", aspect: 1.72, seconds: 6, bg: ["#140f0a", "#050505"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "FIELD OF VIEW BY LENS, DEGREES",
    bars: [["24mm", 74, "74", "#DA923D"], ["35mm", 56, "56", "#DA923D"], ["50mm", 42, "42", "#B9B8B3"], ["85mm", 26, "26", "#A31F28"]],
    stats: [["Draw calls, full scene", "8", "#DA923D"], ["Shots in the sequence", "5", "#B9B8B3"], ["Defocus at shot 2", "0.06 mm", "#A31F28"], ["Timeline length", "30 s", "#8a8f98"]],
  }),
});
