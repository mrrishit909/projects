/* Where Do the Next 157 Trees Go to Cool the Hottest Blocks the Most? Left: share of walkway cells that feel 36 C or hotter, July 15:00 in 2050 (no planting 60.7, starter plan 44.8).
   Right: canopy 5.7 to 16.0 percent; stormwater 889 to 2,284 m3 a year; plan cost $107,912; hottest block 70.7 percent hot. Every figure is on the project page. */
scene({
  slug: "arbor-urban-canopy", aspect: 1.72, seconds: 6, bg: ["#285C3D", "#161B16"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "HOT WALKWAY CELLS IN 2050, PERCENT",
    bars: [["No planting", 60.7, "60.7", "#E98270"], ["Starter plan, 157 trees", 44.8, "44.8", "#7EB35A"]],
    stats: [["Canopy cover", "5.7 to 16.0%", "#7EB35A"], ["Stormwater held", "889 to 2,284 m3/yr", "#ADDCE2"], ["Plan cost", "$107,912", "#D5B557"], ["Hottest block, now", "70.7% hot", "#E98270"]],
  }),
});
