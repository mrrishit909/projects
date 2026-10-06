/* Which Chamber Is Ringing the Edge? Left: good dies recovered on the 11 exposed lots (Recipe offset −3.71 °C 3,886; Route around ETCH-03/B 5,238).
   Right: Drift flagged before the first bad wafer 4 lots; Root cause in the top three 40 of 40; False drift alarms per 1,000 runs 0–0.12 vs 3.3–3.8;
   Change-point vs 3-sigma, speed no faster. Every figure is on the project page. */
scene({
  slug: "fab-yield-intelligence", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "GOOD DIES RECOVERED ON 11 EXPOSED LOTS",
    bars: [["Recipe offset −3.71 °C", 3886, "3,886", "#8a8f98"], ["Route around ETCH-03/B", 5238, "5,238"]],
    stats: [["Drift flagged before the first bad wafer", "4 lots", "#4a95f0"], ["Root cause in the top three", "40 of 40", "#4a95f0"], ["False drift alarms per 1,000 runs", "0–0.12 vs 3.3–3.8", "#4a95f0"], ["Change-point vs 3-sigma, speed", "no faster", "#ff8a3d"]],
  }),
});
