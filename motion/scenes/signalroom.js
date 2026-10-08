/* Where Does Gross Revenue Actually Go? Left: Dec 2024, the catalogue's peak month (Gross $864,035; Net $654,255;
   Margin $401,260). Right: 80% of a year's net revenue takes 70 of 112 products 62.5%; July 2025-to-2026 comp is
   down 13.2% because a promo ran the year before, not the year after; retail's December-to-February swing is 3.1x;
   8 real scroll scenes ship on the site. Every figure is on the project page. */
scene({
  slug: "signalroom", aspect: 1.72, seconds: 6, bg: ["#101923", "#0a121a"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "DEC 2024, REAL RECONCILIATION",
    bars: [["Gross revenue", 864035, "$864,035", "#D58A58"], ["Net revenue", 654255, "$654,255", "#308B89"], ["Margin", 401260, "$401,260", "#E8C46A"]],
    stats: [["80% of net needs this many SKUs", "70 of 112", "#D58A58"], ["Jul comp, no promo ran", "-13.2%", "#308B89"], ["Dec-to-Feb seasonality swing", "3.1x", "#8a8f98"], ["Real scroll scenes", "7", "#8a8f98"]],
  }),
});
