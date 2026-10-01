/* Who Is Still Offline? The real county map from the project's own explorer data: each county lights up by the share of households
   with no internet subscription. Then the case study's point: income matters more than rurality (26.8% offline earning $10-20k vs 3.4%
   at $75k+; nonmetro 14.0% vs metro 8.0%). */
scene({
  slug: "digital-divide", aspect: 1.74, seconds: 6, bg: ["#0a1018", "#03060a"],
  async init() {
    const [D, topo] = await Promise.all([fetch("../digital-divide/explorer/map_data.json").then((r) => r.json()), fetch("../digital-divide/explorer/vendor/counties-albers-10m.json").then((r) => r.json())]);
    const path = d3.geoPath();
    const counties = topojson.feature(topo, topo.objects.counties).features.filter((f) => D[f.id]).map((f) => ({ p2d: new Path2D(path(f)), cx: path.centroid(f)[0], v: D[f.id][2] }));
    return { counties, nation: new Path2D(path(topojson.feature(topo, topo.objects.nation))), states: new Path2D(path(topojson.mesh(topo, topo.objects.states, (a, b) => a !== b))) };
  },
  draw(g, u, W, H, S, { seg, ease, hex, mix, txt, rr, clamp }) {
    const HOT = "#ff8a3d", ink = "#e8f0f8", s = Math.min((W * 0.64) / 975, (H * 0.84) / 610), ox = W * 0.03, oy = H * 0.1;
    const col = (v) => { const t = clamp((v - 3) / 22, 0, 1); return mix("#16324a", t < 0.5 ? "#3b8fd0" : HOT, t < 0.5 ? t * 2 : (t - 0.5) * 2); };
    g.save(); g.translate(ox, oy); g.scale(s, s);
    g.fillStyle = "#0f1a26"; g.fill(S.nation);
    S.counties.forEach((c) => { const k = ease.out3(seg(u, 0.05 + (c.cx / 975) * 0.32, 0.17 + (c.cx / 975) * 0.32)); if (k > 0) { g.fillStyle = mix("#0f1a26", col(c.v), k); g.fill(c.p2d); } });
    g.lineWidth = 0.9 / s; g.strokeStyle = "rgba(3,6,10,0.85)"; g.stroke(S.states);
    g.restore();
    txt(g, "HOUSEHOLDS WITH NO INTERNET, BY COUNTY", ox, H * 0.075, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    const rx = W * 0.72, rw = W * 0.24, k1 = ease.out5(seg(u, 0.2, 0.45));
    txt(g, "UNITED STATES", rx, H * 0.14, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, (8.9 * k1).toFixed(1) + "%", rx, H * 0.27, { size: H * 0.12, color: "#fff", spacing: -3 });
    txt(g, "OFFLINE", rx, H * 0.315, { size: H * 0.024, color: HOT, spacing: 2.5, alpha: k1 });
    [["Earning $10–20k", 26.8, HOT], ["Earning $75k+", 3.4, "#3b8fd0"], ["Nonmetro", 14.0, "#ffb06b"], ["Metro", 8.0, "#7fb8e6"]].forEach(([name, v, c], i) => {
      const y = H * 0.43 + i * H * 0.12, t = ease.out5(seg(u, 0.52 + i * 0.05, 0.7 + i * 0.05));
      txt(g, name, rx, y + H * 0.03, { size: H * 0.03, color: hex(ink, 0.85), weight: 400, alpha: Math.max(t, 0.25) });
      txt(g, v.toFixed(1) + "%", rx + rw, y + H * 0.03, { size: H * 0.03, color: c, align: "right", alpha: t });
      g.fillStyle = hex(ink, 0.07); rr(g, rx, y + H * 0.048, rw, H * 0.014, 7); g.fill();
      g.fillStyle = c; rr(g, rx, y + H * 0.048, Math.max(0.001, rw * (v / 28) * t), H * 0.014, 7); g.fill();
    });
  },
});
