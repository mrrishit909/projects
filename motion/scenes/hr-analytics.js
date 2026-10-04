/* Who Leaves the Federal Workforce, and When? OPM's separations per 100 federal employees, 2016 to 2025: 9.7 to 12.7 a year until 2024, then 17.8 in 2025 (quits blue, retirements orange, the rest grey).
   Right: permanent staff quit at 12.8 per 100 in their first year of service and retire at 27.8 per 100 after 40 years; across 83 agency-waves, agencies whose staff say they might leave lose more people to quits the next year (r = 0.48), but only r = 0.26 when agencies are weighted by headcount. */
const QT = [3.68, 3.84, 3.84, 4.05, 3.36, 4.95, 4.96, 4.0, 3.54, 7.47], RT = [3.0, 3.07, 3.22, 3.14, 2.94, 3.45, 3.05, 2.57, 2.67, 6.86], TOT = [11.18, 10.9, 11.28, 11.56, 10.41, 12.4, 12.7, 10.59, 9.67, 17.85], YRS = [2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025];
scene({
  slug: "hr-analytics", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#8a8f98";
    const x0 = W * 0.09, x1 = W * 0.54, y0 = H * 0.2, y1 = H * 0.78, N = YRS.length, MAX = 20, Y = (v) => y1 - (y1 - y0) * v / MAX, bw = (x1 - x0) / N;
    txt(g, "SEPARATIONS PER 100 EMPLOYEES", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [0, 5, 10, 15, 20].forEach((v) => { line(g, x0 - H * 0.01, Y(v), x1, Y(v), hex(ink, v ? 0.07 : 0.3), 1); txt(g, String(v), x0 - H * 0.02, Y(v) + H * 0.007, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    YRS.forEach((y, i) => {
      const t = ease.out5(seg(u, 0.04 + i * 0.045, 0.3 + i * 0.045)), bx = x0 + i * bw + bw * 0.16, w = bw * 0.68;
      const hq = (Y(0) - Y(QT[i])) * t, hr = (Y(0) - Y(RT[i])) * t, ht = (Y(0) - Y(TOT[i])) * t;
      rr(g, bx, Y(0) - ht, w, ht, 2); g.fillStyle = hex(GR, 0.55); g.fill();
      rr(g, bx, Y(0) - hq - hr, w, hq + hr, 2); g.fillStyle = ORG; g.fill();
      rr(g, bx, Y(0) - hq, w, hq, 2); g.fillStyle = BL; g.fill();
      txt(g, i % 3 === 0 || i === N - 1 ? String(y) : "", bx + w / 2, y1 + H * 0.05, { size: H * 0.02, color: hex(ink, 0.4), align: "center" });
      if (i === N - 1) txt(g, "17.8", bx + w / 2, Y(0) - ht - H * 0.015, { size: H * 0.026, color: ink, align: "center", alpha: t });
    });
    const rx = W * 0.64, rw = W * 0.29; txt(g, "WHO LEAVES", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Quits per 100, first year of service", "12.8", BL], ["Retirements per 100, 40+ years", "27.8", ORG], ["Separations per 100 in 2025", "17.8", ink], ["Intent-to-leave vs quits, r (weighted)", "0.48 (0.26)", GR]].forEach(([nm, v, c], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1); txt(g, nm, rx, y, { size: H * 0.021, color: hex(ink, 0.8), weight: 400, alpha: t }); txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.04, color: c, align: "right", alpha: t });
    });
  },
});
