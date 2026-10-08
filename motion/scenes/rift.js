/* What Does a Six-Second Rupture Do to 36 Buildings? Left: risk crossing 50% by elapsed seconds (T+0 0; T+3 6; T+5 14; T+7 22; T+9 27).
   Right: Draw calls, street view 20; Infrastructure lines failed by T+10 6 of 14; Wave speed 3.5 km/s; Rupture duration 7 s. Every figure is on the project page. */
scene({
  slug: "rift", aspect: 1.72, seconds: 6, bg: ["#1C1714", "#0A0908"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "BUILDINGS OVER 50% RISK, BY T+",
    bars: [["T+3s", 6, "6", "#F2C94C"], ["T+5s", 14, "14", "#FF4A18"], ["T+7s", 22, "22", "#FF4A18"], ["T+9s", 27, "27", "#8E1C12"]],
    stats: [["Draw calls, street view", "20", "#F2C94C"], ["Infra lines failed by T+10s", "6 / 14", "#8E1C12"], ["Wave speed", "3.5 km/s", "#8a8f98"], ["Rupture duration", "7 s", "#8a8f98"]],
  }),
});
