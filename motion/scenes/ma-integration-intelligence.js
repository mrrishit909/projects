/* Will the Synergies Pay for the Premium? Left: value of the synergies with a fast erp cutover (The plan as written $397M; Model, expected value $268M; Simulation truth $282M).
   Right: Chance of covering the premium 51%; Revenue that can leave on a change of control 37%; Revenue from shared customers 48%; Change-of-control clauses found 14 of 16. Every figure is on the project page. */
scene({
  slug: "ma-integration-intelligence", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "VALUE OF THE SYNERGIES WITH A FAST ERP CUTOVER",
    bars: [["The plan as written", 397, "$397M"], ["Model, expected value", 268, "$268M", "#4a95f0"], ["Simulation truth", 282, "$282M", "#8a8f98"]],
    stats: [["Chance of covering the premium", "51%", "#ff8a3d"], ["Revenue that can leave on a change of control", "37%", "#ff8a3d"], ["Revenue from shared customers", "48%", "#4a95f0"], ["Change-of-control clauses found", "14 of 16", "#8a8f98"]],
  }),
});
