/* What Did the Rightsizing Really Save? Left: savings of the demo's pull request over 27 days by two methods against the simulation's
   truth (Before / after $25,084; Counterfactual re-pricing $17,466; Simulation truth $17,698). Right: Rightsizing false positives 0 of 267
   vs 213 of 420; Verified savings error 0.7–1.5%; Commitment regret, 13 weeks 0.5–1.2% vs 2.9–5.5%; Change-risk AUC vs headroom alone
   0.972–0.993 vs 0.955–0.983. Every figure is on the project page. */
scene({
  slug: "cloud-finops-optimizer", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "WHAT THE PULL REQUEST SAVED IN 27 DAYS",
    bars: [["Before / after estimate", 25084, "$25,084", "#ff8a3d"], ["Counterfactual re-pricing", 17466, "$17,466"], ["Simulation truth", 17698, "$17,698", "#8a8f98"]],
    stats: [["Rightsizing false positives", "0 of 267 vs 213 of 420", "#4a95f0"], ["Verified savings error", "0.7–1.5%", "#4a95f0"], ["Commitment regret, 13 weeks", "0.5–1.2% vs 2.9–5.5%", "#4a95f0"], ["Change-risk AUC vs headroom alone", "0.972–0.993 vs 0.955–0.983", "#ff8a3d"]],
  }),
});
