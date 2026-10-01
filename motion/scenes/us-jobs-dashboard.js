/* Where America's Jobs Grew: the real map, drawn from the dashboard's own geometry and data. States fill west to east, coloured by
   job growth 2024-25; the leaders are outlined and ranked on the right. Every number here is computed from dashboard/data.json. */
scene({
  slug: "us-jobs-dashboard", aspect: 1.74, seconds: 6, bg: ["#08121a", "#03070b"],
  async init(W, H, { mix }) {
    const [data, topo] = await Promise.all([fetch("../us-jobs-dashboard/dashboard/data.json").then((r) => r.json()), fetch("../us-jobs-dashboard/dashboard/vendor/counties-albers-10m.json").then((r) => r.json())]);
    const path = d3.geoPath(), feats = topojson.feature(topo, topo.objects.states).features.filter((f) => data.states[f.id]);
    const growth = (id) => data.states[id].data.total["2025"][0] / data.states[id].data.total["2024"][0] - 1;
    const states = feats.map((f) => { const c = path.centroid(f); return { id: f.id, name: data.states[f.id].name, p2d: new Path2D(path(f)), cx: c[0], cy: c[1], g: growth(f.id) }; });
    const ranked = states.slice().sort((a, b) => b.g - a.g);
    const us = data.us.total, jobs = us["2025"][0], jobsPrev = us["2024"][0], wage = us["2025"][1], wagePrev = us["2024"][1];
    return { states, ranked, jobs, jobsGrowth: jobs / jobsPrev - 1, wageGrowth: wage / wagePrev - 1, border: new Path2D(path(topojson.mesh(topo, topo.objects.states, (a, b) => a !== b))) };
  },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, mix, txt, line, dot, rr, fmt, clamp }) {
    const TEAL = "#35d6c6", RED = "#ff6a55", ink = "#e6f2f5", s = Math.min((W * 0.64) / 975, (H * 0.84) / 610), ox = W * 0.03, oy = H * 0.1;
    const color = (v) => { const t = clamp(v / 0.018, -1, 1); return t >= 0 ? mix("#1d2a38", TEAL, Math.pow(t, 0.8)) : mix("#1d2a38", RED, Math.pow(-t / 1.35, 0.8)); };
    g.save(); g.translate(ox, oy); g.scale(s, s);
    S.states.forEach((st) => { const k = ease.out3(seg(u, 0.06 + (st.cx / 975) * 0.3, 0.2 + (st.cx / 975) * 0.3)); g.fillStyle = mix("#141c27", color(st.g), k); g.fill(st.p2d); });
    g.lineWidth = 1 / s * 1.1; g.strokeStyle = "rgba(4,10,16,0.9)"; g.stroke(S.border);
    const top3 = S.ranked.slice(0, 3), hl = ease.out3(seg(u, 0.5, 0.62));
    top3.forEach((st) => { g.save(); g.globalAlpha *= hl; g.lineWidth = 2.6 / s; g.strokeStyle = "#fff"; g.stroke(st.p2d); g.restore(); });
    g.restore();
    txt(g, "JOB GROWTH, 2024–25", ox, H * 0.075, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    // right: headline + leaders
    const rx = W * 0.72, rw = W * 0.23, k1 = ease.out5(seg(u, 0.2, 0.5));
    txt(g, "JOBS IN 2025", rx, H * 0.14, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, (S.jobs / 1e6 * k1).toFixed(2) + "M", rx, H * 0.255, { size: H * 0.115, color: "#fff", spacing: -3 });
    txt(g, "+" + (S.jobsGrowth * 100).toFixed(1) + "% on 2024", rx, H * 0.31, { size: H * 0.03, color: TEAL, alpha: k1 }); txt(g, "wages +" + (S.wageGrowth * 100).toFixed(1) + "%", rx + W * 0.13, H * 0.31, { size: H * 0.03, color: hex(ink, 0.6), weight: 400, alpha: k1 });
    txt(g, "FASTEST GROWING", rx, H * 0.43, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    S.ranked.slice(0, 5).forEach((st, i) => {
      const y = H * 0.48 + i * H * 0.098, t = ease.out5(seg(u, 0.5 + i * 0.05, 0.68 + i * 0.05));
      txt(g, st.name, rx, y + H * 0.03, { size: H * 0.03, color: hex(ink, 0.85 * Math.max(t, 0.001)), weight: 400 }); txt(g, "+" + (st.g * 100).toFixed(1) + "%", rx + rw, y + H * 0.03, { size: H * 0.03, color: TEAL, align: "right", alpha: t });
      g.fillStyle = hex(ink, 0.07); rr(g, rx, y + H * 0.045, rw, H * 0.013, 7); g.fill(); g.fillStyle = TEAL; rr(g, rx, y + H * 0.045, Math.max(0.001, rw * (st.g / S.ranked[0].g) * t), H * 0.013, 7); g.fill();
    });
  },
});
