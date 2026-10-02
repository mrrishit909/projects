/* College Scorecard Warehouse. The for-profit boom and bust traced through the warehouse's own figures: 510,852 undergraduates (1996),
   2,186,060 at the 2010 peak, 1,068,635 in 2020, 1,124,457 in 2024. Right: debt as a share of a year's pay ten years on (0.38 / 0.45 / 0.61). */
scene({
  slug: "college-scorecard-warehouse", aspect: 1.72, seconds: 6, bg: ["#101421", "#04050a"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, path, dot, fmt, pointOn }) {
    const ink = "#eef1fb", FP = "#ff8a4c", x0 = W * 0.06, x1 = W * 0.53, y0 = H * 0.22, y1 = H * 0.84;
    const pts = [[1996, 510852], [2010, 2186060], [2020, 1068635], [2024, 1124457]].map(([y, v]) => [x0 + (x1 - x0) * (y - 1996) / 28, y1 - (y1 - y0) * v / 2300000, y, v]);
    txt(g, "UNDERGRADUATES AT FOR-PROFIT COLLEGES", x0, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    line(g, x0, y1, x1, y1, hex(ink, 0.2), 1);
    const k = ease.inOut(seg(u, 0.06, 0.6)), p = pts.map((q) => [q[0], q[1]]);
    g.save(); g.globalAlpha *= 0.18; g.fillStyle = FP; g.beginPath(); g.moveTo(x0, y1);
    const head = pointOn(p, k); const n = Math.floor(k * 3);
    for (let i = 0; i <= n; i++) g.lineTo(p[i][0], p[i][1]); g.lineTo(head[0], head[1]); g.lineTo(head[0], y1); g.fill(); g.restore();
    path(g, p, k, FP, 3, FP);
    pts.forEach(([x, y, yr, v], i) => {
      const t = ease.out3(seg(u, 0.06 + i * 0.18, 0.14 + i * 0.18)); if (t <= 0) return;
      dot(g, x, y, 5, "#fff");
      txt(g, fmt(v), x + (i === 3 ? 4 : i === 2 ? -4 : 6), i === 2 ? y + H * 0.06 : y - 12, { size: H * 0.028, color: "#fff", align: i === 3 ? "right" : i === 2 ? "right" : i ? "center" : "left", alpha: t });
      txt(g, String(yr), x, y1 + H * 0.045, { size: H * 0.024, color: hex(ink, 0.5), align: "center", alpha: t });
    });
    const rx = W * 0.62, rw = W * 0.32;
    txt(g, "DEBT ÷ A YEAR'S PAY, 10 YEARS ON", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Public", 0.38, "#6aa6ff"], ["Nonprofit", 0.45, "#a98bff"], ["For-profit", 0.61, FP]].forEach(([nm, v, c], i) => {
      const y = H * 0.22 + i * H * 0.2, t = ease.out5(seg(u, 0.5 + i * 0.07, 0.75 + i * 0.07));
      txt(g, nm, rx, y + H * 0.03, { size: H * 0.032, color: hex(ink, 0.85), weight: 400 });
      txt(g, (v * t).toFixed(2), rx + rw, y + H * 0.03, { size: H * 0.05, color: c, align: "right" });
      g.fillStyle = hex(ink, 0.07); rr(g, rx, y + H * 0.065, rw, H * 0.02, 10); g.fill();
      g.fillStyle = c; rr(g, rx, y + H * 0.065, Math.max(0.001, rw * v / 0.7 * t), H * 0.02, 10); g.fill();
    });
  },
});
