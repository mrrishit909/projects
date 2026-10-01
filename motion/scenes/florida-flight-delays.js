/* Florida Flight Delays: a Power BI-style report page. The headline numbers are the real ones (635,459 flights, 75.5% on time,
   1.8% cancelled); the hour-by-hour columns run from 92% on time at 6 a.m. down to 63% at 8 p.m., as in the case study. */
scene({
  slug: "florida-flight-delays", aspect: 1.614, seconds: 6, bg: ["#16140a", "#070603"],
  init() {
    const hours = [], pts = [92, 90, 88, 86, 84, 82, 80, 78, 76, 74, 72, 70, 68, 66, 63, 64, 65, 66]; // 6 a.m. .. 11 p.m.
    for (let i = 0; i < pts.length; i++) hours.push({ h: 6 + i, v: pts[i] });
    return { hours };
  },
  draw(g, u, W, H, S, { TAU, lerp, seg, ease, hex, txt, line, dot, rr, fmt }) {
    const Y = "#f2c811", ink = "#f4efd9", M = W * 0.05;
    txt(g, "FLORIDA DEPARTURES", M, H * 0.085, { size: H * 0.028, color: hex(ink, 0.55), spacing: 3 });
    [["SCHEDULED FLIGHTS", () => fmt(635459 * ease.out5(seg(u, 0.1, 0.4)))], ["ON-TIME ARRIVALS", () => (75.5 * ease.out5(seg(u, 0.14, 0.44))).toFixed(1) + "%"], ["CANCELLATION RATE", () => (1.8 * ease.out5(seg(u, 0.18, 0.48))).toFixed(1) + "%"]].forEach(([label, val], i) => {
      const cw = (W - 2 * M - 2 * 16) / 3, x = M + i * (cw + 16), k = ease.out5(seg(u, 0.04 + i * 0.04, 0.16 + i * 0.04)), y = H * 0.13 + (1 - k) * 24;
      g.save(); g.globalAlpha *= k; g.fillStyle = hex(ink, 0.06); rr(g, x, y, cw, H * 0.19, 14); g.fill(); g.fillStyle = Y; g.fillRect(x, y + H * 0.04, 4, H * 0.11);
      txt(g, label, x + 22, y + H * 0.06, { size: H * 0.023, color: hex(ink, 0.55), spacing: 2 }); txt(g, val(), x + 22, y + H * 0.147, { size: H * 0.066, color: "#fff", spacing: -1.5 }); g.restore();
    });
    // by-hour columns
    const cx = M, cy = H * 0.9, cw = W * 0.6, chh = H * 0.42, n = S.hours.length, bw = cw / n * 0.7;
    txt(g, "ON TIME, BY HOUR OF DEPARTURE", cx, H * 0.4, { size: H * 0.023, color: hex(ink, 0.55), spacing: 2 });
    S.hours.forEach((d, i) => {
      const k = ease.out5(seg(u, 0.3 + i * 0.012, 0.5 + i * 0.012)), x = cx + (i / n) * cw, hh = (d.v / 100) * H * 0.43 * k, hi = d.h === 6 || d.h === 20;
      g.fillStyle = hi ? Y : hex(Y, 0.4); rr(g, x, cy - hh, bw, hh, 4); g.fill();
      if (i % 3 === 0) txt(g, ((d.h + 11) % 12 + 1) + (d.h < 12 ? "a" : "p"), x + bw / 2, cy + H * 0.035, { size: H * 0.021, color: hex(ink, 0.4), align: "center", weight: 400 });
      if (hi && k > 0.9) txt(g, d.v + "%", x + bw / 2, cy - hh - H * 0.015, { size: H * 0.03, color: Y, align: "center" });
    });
    line(g, cx, cy, cx + cw, cy, hex(ink, 0.25));
    // donut
    const dx = W * 0.8, dy = H * 0.66, R = H * 0.15, t = ease.out5(seg(u, 0.4, 0.7));
    g.lineWidth = H * 0.04; g.strokeStyle = hex(ink, 0.1); g.beginPath(); g.arc(dx, dy, R, 0, TAU); g.stroke();
    g.strokeStyle = Y; g.lineCap = "round"; g.beginPath(); g.arc(dx, dy, R, -Math.PI / 2, -Math.PI / 2 + TAU * 0.755 * t); g.stroke(); g.lineCap = "butt";
    txt(g, (75.5 * t).toFixed(1) + "%", dx, dy + H * 0.016, { size: H * 0.058, color: "#fff", align: "center", spacing: -1 }); txt(g, "ON TIME", dx, dy + H * 0.065, { size: H * 0.021, color: hex(ink, 0.5), align: "center", spacing: 2 });
  },
});
