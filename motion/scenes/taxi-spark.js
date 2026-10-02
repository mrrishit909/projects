/* NYC Congestion Pricing in Spark. Trips as moving dots around a stylised Manhattan congestion zone; once pricing starts, fewer dots
   cross into it. Right: Jan-Jun 2025 vs 2024 from the case study: Uber/Lyft trips within the zone -7.4% vs +2.7% outside, yellow taxi
   +11.5% within vs +18.9% outside, and all 272,950,020 kept trips matched between Spark and DuckDB. */
scene({
  slug: "taxi-spark", aspect: 1.72, seconds: 6, bg: ["#0c1218", "#03060a"],
  init(W, H, { rng }) { const r = rng(41), t = []; for (let i = 0; i < 70; i++) t.push({ a: r(), b: r(), ph: r(), sp: 0.6 + r() * 0.8, inz: r() < 0.5 }); return { t }; },
  draw(g, u, W, H, S, { seg, ease, hex, txt, rr, lerp, wrap01, dot }) {
    const ink = "#eaf1f7", YEL = "#ffcc33", BL = "#5c9dff", zx = W * 0.15, zy = H * 0.3, zw = W * 0.22, zh = H * 0.45;
    txt(g, "TRIPS TOUCHING THE CONGESTION ZONE", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    const on = ease.out3(seg(u, 0.35, 0.45));
    g.fillStyle = hex("#ff6b5a", 0.08 + 0.1 * on); rr(g, zx, zy, zw, zh, 14); g.fill();
    g.strokeStyle = hex("#ff6b5a", 0.3 + 0.5 * on); g.lineWidth = 2; rr(g, zx, zy, zw, zh, 14); g.stroke();
    txt(g, on > 0.5 ? "toll on · Jan 2025" : "zone · below 60th St", zx + zw / 2, zy - H * 0.03, { size: H * 0.024, color: on > 0.5 ? "#ff8a7a" : hex(ink, 0.5), align: "center" });
    S.t.forEach((p, i) => {
      if (p.inz && on > 0.5 && i % 4 === 0) return;              // illustrative: some zone trips disappear once the toll starts
      const f = wrap01(p.ph + u * p.sp), inside = p.inz;
      const x = inside ? zx + 10 + f * (zw - 20) : W * 0.05 + f * W * 0.47, y = inside ? zy + 10 + p.b * (zh - 20) : (p.b < 0.5 ? H * 0.2 + p.b * H * 0.15 : H * 0.8 + (p.b - 0.5) * H * 0.12);
      if (!inside && x > zx - 6 && x < zx + zw + 6 && y > zy && y < zy + zh) return;
      dot(g, x, y, 3.2, i % 3 ? BL : YEL);
    });
    txt(g, "Uber/Lyft", W * 0.05, H * 0.95, { size: H * 0.024, color: BL }); txt(g, "yellow taxi", W * 0.14, H * 0.95, { size: H * 0.024, color: YEL });
    const rx = W * 0.6, cw = W * 0.11;
    txt(g, "TRIPS, JAN–JUN 2025 VS 2024", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, "within zone", rx + W * 0.13, H * 0.2, { size: H * 0.022, color: hex(ink, 0.5) }); txt(g, "outside", rx + W * 0.26, H * 0.2, { size: H * 0.022, color: hex(ink, 0.5) });
    [["Uber/Lyft", -7.4, 2.7, BL], ["Yellow taxi", 11.5, 18.9, YEL]].forEach(([n, a, b, c], i) => {
      const y = H * 0.3 + i * H * 0.12, t = ease.out5(seg(u, 0.45 + i * 0.07, 0.65 + i * 0.07)), f = (v) => (v > 0 ? "+" : "−") + Math.abs(v * t).toFixed(1) + "%";
      txt(g, n, rx, y, { size: H * 0.032, color: c, weight: 400 });
      txt(g, f(a), rx + W * 0.13, y, { size: H * 0.036, color: "#fff", alpha: t }); txt(g, f(b), rx + W * 0.26, y, { size: H * 0.036, color: hex(ink, 0.6), alpha: t });
    });
    const k = ease.out5(seg(u, 0.65, 0.85));
    txt(g, "fewer trips touching the zone, relative to elsewhere", rx, H * 0.58, { size: H * 0.027, color: hex(ink, 0.75), weight: 400, alpha: k });
    txt(g, Math.round(272950020 * k).toLocaleString("en-US"), rx, H * 0.77, { size: H * 0.07, color: "#fff", spacing: -2 });
    txt(g, "trips, Spark and DuckDB agree on every one", rx, H * 0.84, { size: H * 0.026, color: hex(ink, 0.6), weight: 400, alpha: k });
  },
});
