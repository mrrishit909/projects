/* Decision Universe. Mean NPV and P(loss) under three decisions over the same 20,000 seeded worlds, the NSW benchmark and the naive gap. Every figure is on the project page. */
scene({
  slug: "decision-universe", aspect: 1.72, seconds: 6, bg: ["#0c0618", "#030107"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "20,000 SEEDED FUTURES, THREE DECISIONS",
    bars: [["Build now, mean NPV", 11.1, "11.1 M", "#FFFFFF"], ["Phased, mean NPV", 13.4, "13.4 M", "#B48CFF"], ["Delay one year, mean NPV", 10.2, "10.2 M", "#690DE2"]],
    stats: [["P(loss), build now", "38%", "#FFFFFF"], ["Randomised benchmark", "1,794 USD", "#B48CFF"], ["Naive gap vs benchmark", "-16,999 USD", "#B48CFF"], ["Instruments matching reference", "10 of 10", "#FFFFFF"]],
  }),
});
