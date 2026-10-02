/* Hospital Data Warehouse. Each row is one hospital across seven years of releases; Type 2 history splits a row into versions when its
   ownership changes (colour). Right: 859 recorded versions, 431 real moves that stuck, 45 Rural Emergency Hospitals. Rows are illustrative. */
scene({
  slug: "hospital-warehouse", aspect: 1.72, seconds: 6, bg: ["#0b1418", "#03070a"],
  init(W, H, { rng }) { const r = rng(21), rows = []; for (let i = 0; i < 11; i++) { const cuts = r() < 0.7 ? [0.2 + r() * 0.6] : []; if (r() < 0.3) cuts.push(0.85); rows.push({ cuts, c0: Math.floor(r() * 3) }); } return { rows }; },
  draw(g, u, W, H, S, { seg, ease, hex, txt, rr, line }) {
    const ink = "#eaf4f6", C = ["#5c9dff", "#ff8a4c", "#46d39a"], x0 = W * 0.06, x1 = W * 0.52;
    txt(g, "ONE ROW PER HOSPITAL · SEVEN YEARS OF RELEASES", x0, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    const kx = ease.inOut(seg(u, 0.05, 0.55));
    S.rows.forEach((r, i) => {
      const y = H * 0.19 + i * H * 0.062, edges = [0, ...r.cuts, 1];
      for (let j = 0; j < edges.length - 1; j++) {
        const a = edges[j], b = Math.min(edges[j + 1], kx); if (b <= a) continue;
        g.fillStyle = C[(r.c0 + j) % 3]; rr(g, x0 + (x1 - x0) * a + (j ? 3 : 0), y, (x1 - x0) * (b - a) - (j ? 3 : 0), H * 0.04, 6); g.fill();
      }
    });
    line(g, x0 + (x1 - x0) * kx, H * 0.17, x0 + (x1 - x0) * kx, H * 0.88, hex(ink, 0.4), 1.5);
    [["non-profit", C[0]], ["for-profit", C[1]], ["government", C[2]]].forEach(([n, c], i) => { g.fillStyle = c; rr(g, x0 + i * W * 0.12, H * 0.91, 12, 12, 3); g.fill(); txt(g, n, x0 + i * W * 0.12 + 20, H * 0.925, { size: H * 0.024, color: hex(ink, 0.7), weight: 400 }); });
    const rx = W * 0.6;
    [["OWNERSHIP VERSIONS RECORDED", 859, "#fff"], ["REAL MOVES THAT STUCK", 431, C[1]], ["RURAL EMERGENCY HOSPITALS", 45, C[2]]].forEach(([n, v, c], i) => {
      const y = H * 0.14 + i * H * 0.26, t = ease.out5(seg(u, 0.25 + i * 0.12, 0.5 + i * 0.12));
      txt(g, n, rx, y, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
      txt(g, String(Math.round(v * t)), rx, y + H * 0.13, { size: H * 0.11, color: c, spacing: -3 });
    });
  },
});
