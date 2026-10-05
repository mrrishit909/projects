/* Can an LLM Review a 52-Page Contract? Left: 74 clauses of one contract, by risk (High 21; Medium 11; Low 42).
   Right: Pages 52; Time 32 s; Cost $0.18; Replies failing validation 0. Every figure is on the project page. */
scene({
  slug: "contract-rfp-automator", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "74 CLAUSES OF ONE CONTRACT, BY RISK",
    bars: [["High", 21, "21", "#ff8a3d"], ["Medium", 11, "11", "#8a8f98"], ["Low", 42, "42", "#4a95f0"]],
    stats: [["Pages", "52"], ["Time", "32 s", "#4a95f0"], ["Cost", "$0.18", "#4a95f0"], ["Replies failing validation", "0"]],
  }),
});
