/* Retail Pipeline in dbt: the model lineage. A run sweeps source -> staging -> intermediate -> marts, each model lights up as it
   builds and earns a green tick when its tests pass. Mart names are the real ones from the case study. */
scene({
  slug: "retail-dbt", aspect: 1.614, seconds: 6, bg: ["#170d0a", "#070403"],
  init() {
    const nodes = [
      { id: "src", label: "raw invoices csv", x: 0.1, y: 0.5, layer: 0, w: 0.17 }, { id: "stg", label: "staging", x: 0.29, y: 0.5, layer: 1, w: 0.17 },
      { id: "seed", label: "seed: stock codes", x: 0.29, y: 0.2, layer: 1, w: 0.17 }, { id: "int", label: "intermediate", x: 0.49, y: 0.5, layer: 2, w: 0.17 },
      { id: "fct", label: "fct_sales", x: 0.82, y: 0.12, layer: 3, w: 0.24 }, { id: "cust", label: "dim_customers", x: 0.82, y: 0.31, layer: 3, w: 0.24 }, { id: "prod", label: "dim_products", x: 0.82, y: 0.5, layer: 3, w: 0.24 },
      { id: "rev", label: "mart_monthly_revenue", x: 0.82, y: 0.69, layer: 3, w: 0.24 }, { id: "coh", label: "mart_cohort_retention", x: 0.82, y: 0.88, layer: 3, w: 0.24 },
    ];
    const edges = [["src", "stg"], ["stg", "int"], ["seed", "int"], ["int", "fct"], ["int", "cust"], ["int", "prod"], ["int", "rev"], ["int", "coh"]];
    return { nodes, edges };
  },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, mix, txt, line, dot, rr, path, fmt }) {
    const OR = "#ff694a", GRN = "#4fe08f", ink = "#f7e8e2", byId = Object.fromEntries(S.nodes.map((n) => [n.id, n]));
    const nh = H * 0.075, nwOf = (n) => W * n.w, pos = (n) => [W * n.x - nwOf(n) / 2, H * 0.1 + n.y * H * 0.78 - nh / 2];
    const run = (n) => 0.12 + n.layer * 0.17 + (n.y * 0.04);     // when this model builds
    S.edges.forEach(([a, b]) => {
      const A = byId[a], B = byId[b], pa = pos(A), pb = pos(B), x1 = pa[0] + nwOf(A), y1 = pa[1] + nh / 2, x2 = pb[0], y2 = pb[1] + nh / 2, mx = (x1 + x2) / 2;
      const pts = Array.from({ length: 21 }, (_, i) => { const t = i / 20, s = t * t * (3 - 2 * t); return [lerp(x1, x2, t), lerp(y1, y2, s)]; });
      path(g, pts, 1, hex(ink, 0.14), 2); const p = ease.inOut(seg(u, run(A) + 0.04, run(B))); path(g, pts, p, OR, 2.5, hex(OR, 0.7));
      if (p > 0 && p < 1) { const q = pts[Math.min(20, Math.floor(p * 20))]; dot(g, q[0], q[1], 4.5, "#fff", OR); }
    });
    S.nodes.forEach((n) => {
      const [x, y] = pos(n), nw = nwOf(n), t0 = run(n), appear = ease.out3(seg(u, t0 - 0.1, t0 - 0.02)), building = seg(u, t0, t0 + 0.04) * (1 - seg(u, t0 + 0.08, t0 + 0.12)), done = ease.back(seg(u, t0 + 0.1, t0 + 0.16));
      g.save(); g.globalAlpha *= appear; const mart = n.layer === 3;
      g.fillStyle = mart ? hex(OR, 0.16 + 0.1 * building) : hex(ink, 0.07 + 0.08 * building); rr(g, x, y, nw, nh, 10); g.fill();
      g.strokeStyle = building > 0 ? "#fff" : mart ? hex(OR, 0.75) : hex(ink, 0.3); g.lineWidth = building > 0 ? 2.5 : 1.5; rr(g, x, y, nw, nh, 10); g.stroke();
      txt(g, n.label, x + nw / 2, y + nh / 2 + H * 0.0095, { size: H * 0.0245, color: mart ? "#ffd9cf" : hex(ink, 0.85), align: "center", mono: true, weight: 400 });
      if (done > 0) { dot(g, x + nw - 4, y + 4, H * 0.019 * done, GRN); g.strokeStyle = "#04140a"; g.lineWidth = 2.5; g.lineCap = "round"; g.beginPath(); g.moveTo(x + nw - 4 - 5.5 * done, y + 4); g.lineTo(x + nw - 4 - 1.5 * done, y + 4 + 4.5 * done); g.lineTo(x + nw - 4 + 6 * done, y + 4 - 5 * done); g.stroke(); }
      g.restore();
    });
    const rows = 1067371 * ease.out5(seg(u, 0.08, 0.5)); txt(g, fmt(Math.round(rows)) + " INVOICE LINES", W * 0.04, H * 0.965, { size: H * 0.025, color: hex(ink, 0.5), spacing: 2.5, mono: false });
    const ok = seg(u, 0.78, 0.9); txt(g, "ALL TESTS PASS", W * 0.96, H * 0.965, { size: H * 0.025, color: GRN, spacing: 2.5, align: "right", alpha: ok });
  },
});
