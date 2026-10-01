/* Who Will Buy Again? Each row is a customer's purchase history (dot size = spend). A time cursor reads the past;
   customers who stop buying go quiet ("churned"); the models then forecast the unseen six months and rank customers by value. */
scene({
  slug: "customer-clv", aspect: 1.736, seconds: 6, bg: ["#170d16", "#07040a"],
  init(W, H, { rng }) {
    const r = rng(14), custs = [];
    for (let i = 0; i < 9; i++) {
      const dies = r() < 0.4 ? 0.12 + r() * 0.3 : 1, ev = [];
      let t = 0.02 + r() * 0.08; const gap = 0.05 + r() * 0.08;
      while (t < 0.6) { if (t < dies * 0.6 || dies === 1) ev.push({ t, s: 0.4 + r() * 0.6 }); t += gap * (0.6 + r() * 0.9); }
      const future = []; if (dies === 1) { let f = 0.62 + r() * 0.05; while (f < 0.96) { future.push({ t: f, s: 0.4 + r() * 0.6 }); f += gap * (0.8 + r()); } }
      custs.push({ ev, future, dies, value: dies === 1 ? 0.35 + future.length * 0.1 + r() * 0.1 : 0.05 + r() * 0.1 });
    }
    custs.forEach((c, i) => (c.rank = custs.map((d) => d.value).sort((a, b) => b - a).indexOf(c.value)));
    return { custs };
  },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, dot, rr }) {
    const PINK = "#ff5fb2", ink = "#f8e9f3", x0 = W * 0.08, x1 = W * 0.7, top = H * 0.16, rowH = H * 0.082, boundary = 0.6;
    const X = (t) => x0 + t * (x1 - x0) / 0.98, cur = lerp(0.02, boundary, ease.inOut(seg(u, 0.1, 0.46)));
    txt(g, "6 MONTHS SEEN", X(0.02), top - H * 0.05, { size: H * 0.026, color: hex(ink, 0.45), spacing: 2.5 });
    txt(g, "UNSEEN 6 MONTHS", X(boundary + 0.02), top - H * 0.05, { size: H * 0.026, color: hex(PINK, 0.8), spacing: 2.5 });
    // unseen region, hatched
    const fh = rowH * S.custs.length; g.save(); g.beginPath(); g.rect(X(boundary), top - rowH * 0.5, x1 - X(boundary) + 10, fh + rowH * 0.2); g.clip();
    g.fillStyle = hex(PINK, 0.05); g.fillRect(X(boundary), top - rowH, x1, fh + rowH * 2);
    for (let k = -40; k < 60; k++) line(g, X(boundary) + k * 16, top + fh, X(boundary) + k * 16 + 90, top - rowH, hex(PINK, 0.07), 1.5); g.restore();
    line(g, X(boundary), top - rowH * 0.6, X(boundary), top + fh, hex(PINK, 0.7), 2, [5, 6]);
    S.custs.forEach((c, i) => {
      const y = top + i * rowH + rowH * 0.3; line(g, x0, y, x1, y, hex(ink, 0.07));
      c.ev.forEach((e) => { const k = ease.back(seg(cur, e.t, e.t + 0.03)); if (k > 0) dot(g, X(e.t), y, H * 0.011 + H * 0.016 * e.s * k, hex(ink, 0.92), hex(PINK, 0.4)); });
      const last = c.ev.length ? c.ev[c.ev.length - 1].t : 0, gone = c.dies < 1 && cur > last + 0.06;
      if (gone) { const k = seg(cur, last + 0.06, last + 0.12); line(g, X(last) + 20, y, X(last) + 20 + (X(boundary) - X(last) - 24) * k, y, hex(ink, 0.2), 2, [3, 6]); if (k > 0.9) { txt(g, "×", X(boundary) - 14, y + 8, { size: H * 0.04, color: hex("#ff6b6b", 0.9), align: "center" }); } }
      c.future.forEach((e, j) => { const k = ease.back(seg(u, 0.5 + j * 0.02, 0.56 + j * 0.02)); if (k <= 0) return; g.strokeStyle = hex(PINK, 0.95); g.lineWidth = 2.5; g.setLineDash([]); g.beginPath(); g.arc(X(e.t), y, (H * 0.011 + H * 0.016 * e.s) * k, 0, 6.3); g.stroke(); });
      // predicted value, ranked
      const bt = ease.out5(seg(u, 0.66 + c.rank * 0.02, 0.8 + c.rank * 0.02)), bx = W * 0.75, bw = W * 0.2 * c.value * 1.4 * bt;
      g.fillStyle = hex(ink, 0.06); rr(g, bx, y - H * 0.012, W * 0.2, H * 0.024, H * 0.012); g.fill();
      g.fillStyle = hex(PINK, 0.95); rr(g, bx, y - H * 0.012, Math.max(0.001, Math.min(W * 0.2, bw)), H * 0.024, H * 0.012); g.fill();
    });
    g.save(); g.fillStyle = hex(PINK, 0.9); g.fillRect(X(cur), top - rowH * 0.6, 3, fh + rowH * 0.5); g.restore();
    txt(g, "PREDICTED VALUE", W * 0.75, top - H * 0.05, { size: H * 0.026, color: hex(ink, 0.45), spacing: 2.5 });
  },
});
