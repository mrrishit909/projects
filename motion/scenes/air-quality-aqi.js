/* When Does the Air Turn Unhealthy? Bad air-quality days (AQI above 100) by month, 2015 to 2025, in the 609 counties monitored all eleven years: ozone (orange), PM2.5 (blue), other (grey).
   Right: 1.6% of county-days are above 100; the 50 counties with the most bad days hold half of them (50.7%); the worst day, 29 June 2023, had 113 counties above 150;
   counties reporting six or more sites have 7.3% bad days against 0.7% for one site. */
const OZ = [96, 154, 215, 1014, 2574, 5314, 5209, 4582, 2522, 975, 33, 23], PM = [1224, 521, 256, 162, 286, 1277, 1675, 3129, 2235, 629, 1076, 1286], OT = [97, 150, 237, 265, 204, 184, 145, 130, 181, 294, 161, 137];
scene({
  slug: "air-quality-aqi", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#8f918d";
    const x0 = W * 0.1, x1 = W * 0.58, y0 = H * 0.2, y1 = H * 0.8, bw = (x1 - x0) / 12, Y = (v) => y1 - v / 8000 * (y1 - y0);
    txt(g, "BAD DAYS BY MONTH, 2015–2025", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [0, 2000, 4000, 6000, 8000].forEach((v) => { line(g, x0, Y(v), x1, Y(v), hex(ink, v ? 0.08 : 0.3), 1); txt(g, v ? v / 1000 + "k" : "0", x0 - H * 0.015, Y(v) + H * 0.008, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    "JFMAMJJASOND".split("").forEach((l, i) => txt(g, l, x0 + bw * (i + 0.5), y1 + H * 0.055, { size: H * 0.024, color: hex(ink, 0.5), align: "center" }));
    for (let i = 0; i < 12; i++) {
      const t = ease.out3(seg(u, 0.05 + i * 0.03, 0.3 + i * 0.03)); let base = 0;
      [[OZ[i], ORG], [PM[i], BL], [OT[i], GR]].forEach(([v, c]) => { const h = Y(base) - Y(base + v * t); g.fillStyle = c; g.fillRect(x0 + bw * i + bw * 0.14, Y(base + v * t), bw * 0.72, h); base += v * t; });
    }
    const rx = W * 0.67, rw = W * 0.28, k = ease.out3(seg(u, 0.4, 0.7));
    txt(g, "COUNTY-DAYS ABOVE 100", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, (1.6 * k).toFixed(1) + "%", rx, H * 0.29, { size: H * 0.13, color: ORG, spacing: -3 });
    txt(g, "of all county-days", rx, H * 0.345, { size: H * 0.026, color: hex(ink, 0.7), weight: 400 });
    [["50 counties hold half of them", "50 of 609", BL], ["Worst day, 29 Jun 2023", "113 counties", ORG], ["Bad days, 6+ sites vs 1", "7.3% vs 0.7%", ink]].forEach(([nm, v, c], i) => {
      const y = H * 0.54 + i * H * 0.14, t = ease.out5(seg(u, 0.64 + i * 0.07, 0.82 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.038, color: c, align: "right", alpha: t });
    });
  },
});
