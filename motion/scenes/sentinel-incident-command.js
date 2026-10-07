/* Which Agent Should Read the Evidence? Left: tokens read per tier, one run (Raw telemetry in the window 148,392; Endpoint investigator, sonnet 13,013; Synthesizer, opus 2,829; Escalated subproblem, opus 894).
   Right: Cost per run $0.59; Claims unsupported by evidence 1 of 9; Escalations 1 of 8 agents; Alerts kept of 1,996 events 29. Every figure is on the project page. */
scene({
  slug: "sentinel-incident-command", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "TOKENS READ PER TIER, ONE RUN",
    bars: [["Raw telemetry in the window", 148392, "148,392", "#8a8f98"], ["Endpoint investigator, sonnet", 13013, "13,013", "#4a95f0"], ["Synthesizer, opus", 2829, "2,829", "#ff8a3d"], ["Escalated subproblem, opus", 894, "894", "#ff8a3d"]],
    stats: [["Cost per run", "$0.59", "#ff8a3d"], ["Claims unsupported by evidence", "1 of 9", "#ff8a3d"], ["Escalations", "1 of 8 agents", "#8a8f98"], ["Alerts kept of 1,996 events", "29", "#8a8f98"]],
  }),
});
