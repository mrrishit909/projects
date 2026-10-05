/* 100,000 Pipes, Roads and Drains, and Money to Fix One in Ten. Which Ones? Left: expected loss avoided with the same $150m (Optimized $203M; Best ratio first $193M; Worst condition first $55M).
   Right: Avoided per dollar, optimized 1.36; Per dollar, worst first 0.37; Against worst first 3.7x. Every figure is on the project page. */
scene({
  slug: "city-capital-planner", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "EXPECTED LOSS AVOIDED WITH THE SAME $150M",
    bars: [["Optimized", 203, "$203M"], ["Best ratio first", 193, "$193M"], ["Worst condition first", 55, "$55M"]],
    stats: [["Avoided per dollar, optimized", "1.36", "#4a95f0"], ["Per dollar, worst first", "0.37", "#ff8a3d"], ["Against worst first", "3.7x", "#4a95f0"]],
  }),
});
