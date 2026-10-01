/* Will My Flight Be Disrupted? Flights move between Florida airports coloured by their risk score; on the right, the night-before
   ranking sorts itself so the riskiest tenth rises to the top. */
scene({
  slug: "flight-delay-model", aspect: 1.838, seconds: 6, bg: ["#0a1320", "#03070d"],
  init(W, H, { rng }) {
    const ap = { JAX: [0.5, 0.1], TPA: [0.26, 0.46], MCO: [0.5, 0.42], PBI: [0.76, 0.66], RSW: [0.32, 0.74], FLL: [0.78, 0.8], MIA: [0.68, 0.92] };
    const names = Object.keys(ap), r = rng(31), flights = [];
    for (let i = 0; i < 16; i++) { let a = names[Math.floor(r() * names.length)], b; do b = names[Math.floor(r() * names.length)]; while (b === a); flights.push({ a, b, off: r(), risk: r(), bend: (r() - 0.5) * 0.18 }); }
    const rows = Array.from({ length: 12 }, (_, i) => ({ v: r(), start: i })); const order = rows.map((x, i) => i).sort((p, q) => rows[q].v - rows[p].v); rows.forEach((x, i) => (x.rank = order.indexOf(i)));
    return { ap, flights, rows };
  },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, mix, txt, line, dot, quad, wrap01, rr }) {
    const ink = "#e8f1ff", mapW = W * 0.6, mx = W * 0.04, my = H * 0.08, mh = H * 0.86, risk = (v) => mix("#3ddc97", v > 0.5 ? "#ff5d5d" : "#ffc24d", v > 0.5 ? (v - 0.5) * 2 : v * 2);
    const P = (n) => [mx + S.ap[n][0] * mapW * 0.9 + mapW * 0.05, my + S.ap[n][1] * mh];
    Object.keys(S.ap).forEach((n, i) => { const p = P(n), k = ease.back(seg(u, 0.04 + i * 0.02, 0.14 + i * 0.02)); g.strokeStyle = hex(ink, 0.2 * k); g.lineWidth = 1.5; g.beginPath(); g.arc(p[0], p[1], H * 0.03 * k, 0, 6.3); g.stroke(); dot(g, p[0], p[1], H * 0.009 * k, hex(ink, 0.9)); txt(g, n, p[0] + H * 0.045, p[1] + H * 0.01, { size: H * 0.027, color: hex(ink, 0.6 * k), spacing: 1.5 }); });
    S.flights.forEach((f) => {
      const a = P(f.a), b = P(f.b), c = [(a[0] + b[0]) / 2 + (b[1] - a[1]) * f.bend, (a[1] + b[1]) / 2 - (b[0] - a[0]) * f.bend];
      const p = wrap01(u * 2 + f.off), col = risk(f.risk), vis = Math.sin(p * Math.PI) * seg(u, 0.06, 0.16);
      g.save(); g.globalAlpha *= vis; g.strokeStyle = hex("#ffffff", 0.07); g.lineWidth = 1.5; g.beginPath(); for (let k = 0; k <= 16; k++) { const q = quad(a, c, b, k / 16); k ? g.lineTo(q[0], q[1]) : g.moveTo(q[0], q[1]); } g.stroke();
      const q = quad(a, c, b, p), q2 = quad(a, c, b, Math.min(1, p + 0.02)), ang = Math.atan2(q2[1] - q[1], q2[0] - q[0]);
      g.translate(q[0], q[1]); g.rotate(ang); g.fillStyle = col; g.shadowColor = col; g.shadowBlur = 14; g.beginPath(); g.moveTo(H * 0.02, 0); g.lineTo(-H * 0.013, H * 0.012); g.lineTo(-H * 0.006, 0); g.lineTo(-H * 0.013, -H * 0.012); g.closePath(); g.fill(); g.restore();
    });
    // ranking
    const rx = W * 0.68, rw = W * 0.27, top = H * 0.16, rowH = H * 0.064, sortT = ease.inOut(seg(u, 0.42, 0.72));
    txt(g, "RISK SCORE, NIGHT BEFORE", rx, H * 0.09, { size: H * 0.025, color: hex(ink, 0.5), spacing: 2.5 });
    S.rows.forEach((r) => {
      const k = ease.out3(seg(u, 0.14 + r.start * 0.02, 0.26 + r.start * 0.02)); if (k <= 0) return;
      const y = top + lerp(r.start, r.rank, sortT) * rowH, col = risk(r.v), hot = r.rank === 0 && sortT > 0.9;
      g.fillStyle = hex(ink, 0.06); rr(g, rx, y, rw, rowH * 0.7, rowH * 0.2); g.fill();
      g.fillStyle = col; rr(g, rx, y, Math.max(0.001, rw * (0.15 + 0.85 * r.v) * k), rowH * 0.7, rowH * 0.2); g.fill();
      if (hot) { g.strokeStyle = "#fff"; g.lineWidth = 2; rr(g, rx - 4, y - 4, rw + 8, rowH * 0.7 + 8, rowH * 0.25); g.stroke(); }
    });
    const lab = seg(u, 0.74, 0.86); txt(g, "TOP 10% · 64% DISRUPTED", rx, H * 0.95, { size: H * 0.027, color: "#ff8a80", spacing: 2, alpha: lab });
  },
});
