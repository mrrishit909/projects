/* Can a Model Fitted to the Past See the Heat Coming? Left: miami 2080–2099, high scenario: extreme-heat days (1991–2020 level 31.8; Model projection 169; Generator's truth 296).
   Right: Heat truth outside the interval 111 of 336; Wildfire backtest skill −0.03; First interactive 277 ms; Global mean 2090, high +4.07 °C. Every figure is on the project page. */
scene({
  slug: "terra-climate-twin", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "MIAMI 2080–2099, HIGH SCENARIO: EXTREME-HEAT DAYS",
    bars: [["1991–2020 level", 31.8, "31.8", "#8a8f98"], ["Model projection", 169, "169", "#4a95f0"], ["Generator's truth", 296, "296", "#ff8a3d"]],
    stats: [["Heat truth outside the interval", "111 of 336", "#ff8a3d"], ["Wildfire backtest skill", "−0.03", "#ff8a3d"], ["First interactive", "277 ms", "#8a8f98"], ["Global mean 2090, high", "+4.07 °C", "#8a8f98"]],
  }),
});
