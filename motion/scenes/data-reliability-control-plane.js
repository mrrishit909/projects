/* The Dashboard Is Wrong and No Job Failed. Where Did It Break? Left: true origin ranked first, 108 planted failures (This build 94%; Blame the loudest alert 31%).
   Right: Alerts that were real 97.6%; Affected table-days flagged 77.7% vs 5.9%; Tables and dashboards, one incident 10. Every figure is on the project page. */
scene({
  slug: "data-reliability-control-plane", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "TRUE ORIGIN RANKED FIRST, 108 PLANTED FAILURES",
    bars: [["This build", 94, "94%"], ["Blame the loudest alert", 31, "31%"]],
    stats: [["Alerts that were real", "97.6%", "#4a95f0"], ["Affected table-days flagged", "77.7% vs 5.9%", "#4a95f0"], ["Tables and dashboards, one incident", "10"]],
  }),
});
