/* Which Two Fixes Cut Off the Route to the Database? Left: risk left after 2 fixes, all critical data (Chosen by route 60%; Public + known-exploited 92%; Most severe first 100%).
   Right: By route, after 4 fixes 29%; By route, after 8 fixes 0%; By severity, after 8 fixes 100%; Orders database, 2 fixes 85.1 to 0. Every figure is on the project page. */
scene({
  slug: "attack-path-platform", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "RISK LEFT AFTER 2 FIXES, ALL CRITICAL DATA",
    bars: [["Chosen by route", 60, "60%"], ["Public + known-exploited", 92, "92%"], ["Most severe first", 100, "100%"]],
    stats: [["By route, after 4 fixes", "29%", "#4a95f0"], ["By route, after 8 fixes", "0%", "#4a95f0"], ["By severity, after 8 fixes", "100%", "#ff8a3d"], ["Orders database, 2 fixes", "85.1 to 0", "#4a95f0"]],
  }),
});
