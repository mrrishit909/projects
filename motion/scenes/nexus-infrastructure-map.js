/* What Breaks When One Cable Is Cut? Left: yearly degraded traffic saved, tbps-h per $m (72-hour generator fuel, $9M 277; Marseille second feed, $3M 224; Jeddah–Mumbai cable, $240M 103; Bude second feed, $5M 12).
   Right: Unserved after Bude goes dark 145 Tbps; West Africa cables after the cut 87–88%; Paired years per remedy 1,000; Submarine cables 31. Every figure is on the project page. */
scene({
  slug: "nexus-infrastructure-map", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "YEARLY DEGRADED TRAFFIC SAVED, TBPS-H PER $M",
    bars: [["72-hour generator fuel, $9M", 277, "277", "#4a95f0"], ["Marseille second feed, $3M", 224, "224", "#4a95f0"], ["Jeddah–Mumbai cable, $240M", 103, "103", "#8a8f98"], ["Bude second feed, $5M", 12, "12", "#ff8a3d"]],
    stats: [["Unserved after Bude goes dark", "145 Tbps", "#ff8a3d"], ["West Africa cables after the cut", "87–88%", "#ff8a3d"], ["Paired years per remedy", "1,000", "#8a8f98"], ["Submarine cables", "31", "#8a8f98"]],
  }),
});
