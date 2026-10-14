/* The Invisible Machine That Powers Everything. Left: California (CISO) day-ahead test error, MAPE % (EIA's own forecast 6.5; independent model 3.3;
   Texas ERCOT, where the independent model loses: EIA 2.23, model 4.12). Right: 80% interval coverage 82.9% (CISO), midday net-load minimum
   3,362 MW (2021) to 253 MW (2024), EIA CISO day-ahead bias -6.36% by 2025, 40,776 hourly slots per series. Every figure is on the project page. */
scene({
  slug: "pulse-energy-grid", aspect: 1.72, seconds: 6, bg: ["#0b0d14", "#030307"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "DAY-AHEAD TEST ERROR, MAPE %",
    bars: [["CISO, EIA's own forecast", 6.5, "6.5%", "#ff8a3d"], ["CISO, independent model", 3.3, "3.3%", "#4a95f0"], ["ERCOT, independent model", 4.12, "4.12%", "#8a8f98"]],
    stats: [["80% interval coverage, CISO", "82.9%", "#4a95f0"], ["Midday net load, 2021 to 2024", "3,362 to 253 MW", "#ff8a3d"], ["EIA CISO forecast bias, 2025", "-6.36%", "#8a8f98"], ["Hourly slots per series", "40,776", "#8a8f98"]],
  }),
});
