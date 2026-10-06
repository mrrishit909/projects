/* When Should the Strawberries Go on Sale? Left: units thrown out in a heatwave week at one store, on the truth (The chain's ordering rule 348; Plan, last week's forecast 111; Plan, heatwave forecast 123).
   Right: Gross margin: plan vs chain rule $6,442 vs $5,471; Demand error: censored vs same weekday 7.3% vs 28.0%; Warm strawberries spoiling before the date 79%; Markdown: optimiser vs flat 30% $282 vs $288. Every figure is on the project page. */
scene({
  slug: "grocery-perishables-optimizer", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "UNITS THROWN OUT IN A HEATWAVE WEEK AT ONE STORE, ON THE TRUTH",
    bars: [["The chain's ordering rule", 348, "348"], ["Plan, last week's forecast", 111, "111", "#4a95f0"], ["Plan, heatwave forecast", 123, "123", "#8a8f98"]],
    stats: [["Gross margin: plan vs chain rule", "$6,442 vs $5,471", "#4a95f0"], ["Demand error: censored vs same weekday", "7.3% vs 28.0%", "#8a8f98"], ["Warm strawberries spoiling before the date", "79%", "#ff8a3d"], ["Markdown: optimiser vs flat 30%", "$282 vs $288", "#ff8a3d"]],
  }),
});
