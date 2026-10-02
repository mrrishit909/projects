/* What Goes With Longer Lives. 2,992 county dots settle into an income-vs-life-expectancy cloud (a stylised cloud, not the data points),
   a fitted line draws through it; right: the model's years per standard deviation: income +1.24, smoking -0.68, and the trap,
   "excessive drinking" +0.63, which marks wealthier counties rather than adding years. */
scene({
  slug: "county-health-r", aspect: 1.72, seconds: 6, bg: ["#0c1712", "#030806"],
  init(W, H, { rng, gauss }) {
    const r = rng(7), pts = [];
    for (let i = 0; i < 900; i++) { const x = r(), y = 0.25 + 0.5 * x + gauss(r) * 0.09; pts.push({ x, y, sx: r(), sy: r(), d: r() * 0.25 }); }
    return { pts };
  },
  draw(g, u, W, H, S, { seg, ease, lerp, hex, txt, line, rr, dot }) {
    const ink = "#eaf6ef", GRN = "#46d39a", RED = "#ff6b6b", AMB = "#ffc35a", x0 = W * 0.06, x1 = W * 0.52, y0 = H * 0.2, y1 = H * 0.86;
    txt(g, "2,992 COUNTIES: INCOME AND LIFE EXPECTANCY", x0, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    S.pts.forEach((p) => {
      const t = ease.inOut(seg(u, 0.04 + p.d, 0.3 + p.d)), x = lerp(x0 + p.sx * (x1 - x0), x0 + p.x * (x1 - x0), t), y = lerp(y0 + p.sy * (y1 - y0), y1 - (y1 - y0) * p.y, t);
      dot(g, x, y, 1.8, hex(GRN, 0.25 + 0.4 * t));
    });
    const kl = ease.inOut(seg(u, 0.5, 0.68));
    line(g, x0, y1 - (y1 - y0) * 0.25, lerp(x0, x1, kl), y1 - (y1 - y0) * (0.25 + 0.5 * kl), "#fff", 2.5);
    txt(g, "household income →", x1, y1 + H * 0.05, { size: H * 0.022, color: hex(ink, 0.45), align: "right" });
    const rx = W * 0.6, mid = W * 0.78, sc = W * 0.11;
    txt(g, "YEARS OF LIFE PER STANDARD DEVIATION", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    line(g, mid, H * 0.2, mid, H * 0.78, hex(ink, 0.2), 1);
    [["Income", 1.24, GRN], ["Smoking", -0.68, RED], ["Excessive drinking", 0.63, AMB]].forEach(([n, v, c], i) => {
      const y = H * 0.24 + i * H * 0.18, t = ease.out5(seg(u, 0.35 + i * 0.08, 0.6 + i * 0.08)), w = sc * Math.abs(v) * t;
      txt(g, n, rx, y, { size: H * 0.03, color: hex(ink, 0.85), weight: 400 });
      g.fillStyle = c; rr(g, v < 0 ? mid - w : mid, y + H * 0.025, Math.max(0.001, w), H * 0.045, 7); g.fill();
      txt(g, (v > 0 ? "+" : "−") + Math.abs(v * t).toFixed(2), v < 0 ? mid - w - 8 : mid + w + 8, y + H * 0.06, { size: H * 0.032, color: c, align: v < 0 ? "right" : "left", alpha: t });
    });
    txt(g, "a marker of wealth, not a habit that adds years", rx, H * 0.86, { size: H * 0.026, color: AMB, weight: 400, alpha: seg(u, 0.72, 0.84) });
  },
});
