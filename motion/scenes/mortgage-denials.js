/* Who Gets Denied a Mortgage? Applications drop through the model and split into approved and denied. The leakage trap fakes
   0.975 AUC (struck through); the honest model, tested on the following year, scores 0.80. Both numbers are the case study's. */
scene({
  slug: "mortgage-denials", aspect: 1.74, seconds: 6, bg: ["#0e1218", "#04060a"],
  init(W, H, { rng }) { const r = rng(12); return { apps: Array.from({ length: 56 }, (_, i) => ({ off: i / 56, x: (r() - 0.5) * 2, deny: r() < 0.22 })) }; },
  draw(g, u, W, H, S, { TAU, lerp, seg, ease, hex, txt, line, dot, rr, wrap01 }) {
    const OK = "#46d08b", NO = "#ff6259", ink = "#e9eff7", cx = W * 0.3, gateY = H * 0.46, top = H * 0.06, bot = H * 0.94;
    // gate: the model
    const pulse = 0.5 + 0.5 * Math.sin(u * TAU * 6);
    g.strokeStyle = hex(ink, 0.35); g.lineWidth = 2; g.beginPath(); g.arc(cx, gateY, H * 0.075, 0, TAU); g.stroke();
    g.fillStyle = hex(ink, 0.06 + 0.05 * pulse); g.beginPath(); g.arc(cx, gateY, H * 0.075, 0, TAU); g.fill();
    txt(g, "MODEL", cx, gateY + H * 0.011, { size: H * 0.024, color: hex(ink, 0.8), align: "center", spacing: 2 });
    // chutes
    const dx = cx - W * 0.16, ax = cx + W * 0.16;
    line(g, dx, gateY + H * 0.14, dx, bot, hex(NO, 0.25), 2); line(g, ax, gateY + H * 0.14, ax, bot, hex(OK, 0.25), 2);
    txt(g, "DENIED", dx, bot + H * 0.03, { size: H * 0.024, color: NO, align: "center", spacing: 2.5 }); txt(g, "APPROVED", ax, bot + H * 0.03, { size: H * 0.024, color: OK, align: "center", spacing: 2.5 });
    let nd = 0, na = 0;
    S.apps.forEach((a) => {
      const c = u * 1.4 + a.off, p = wrap01(c), flow = seg(u, 0.04, 0.12);
      if (flow <= 0 || p > 0.97) return; const t1 = seg(p, 0, 0.45), t2 = seg(p, 0.45, 1);
      let x, y, col;
      if (t2 <= 0) { x = cx + a.x * W * 0.07 * (1 - t1 * 0.85); y = lerp(top, gateY, ease.in3(t1) * 0.6 + 0.4 * t1); col = ink; }
      else { const tx = a.deny ? dx : ax; x = lerp(cx, tx, ease.out3(Math.min(1, t2 * 2.2))) + a.x * W * 0.01; y = lerp(gateY, bot - 8, ease.in3(t2) * 0.7 + 0.3 * t2); col = a.deny ? NO : OK; }
      g.save(); g.globalAlpha *= flow; dot(g, x, y, H * 0.0095, col, t2 > 0 ? col : null); g.restore();
      if (Math.floor(c) >= 0 && p < 0.5) { /* counters tallied below from cycle count */ }
    });
    // the two AUCs
    const rx = W * 0.62, rw = W * 0.33, leakT = ease.out3(seg(u, 0.3, 0.5)), strike = ease.out5(seg(u, 0.52, 0.6)), honest = ease.out5(seg(u, 0.6, 0.78));
    txt(g, "LEAKY MODEL", rx, H * 0.2, { size: H * 0.024, color: hex(NO, 0.9 * leakT), spacing: 2.5 });
    const shake = (u > 0.4 && u < 0.52) ? Math.sin(u * 900) * 3 : 0;
    txt(g, (0.975 * leakT).toFixed(3), rx + shake, H * 0.36, { size: H * 0.13, color: NO, spacing: -3, alpha: leakT * (1 - 0.55 * strike) });
    line(g, rx, H * 0.315, rx + rw * strike * 0.95, H * 0.315, "#fff", 4);
    txt(g, "AUC · looks too good", rx, H * 0.415, { size: H * 0.028, color: hex(ink, 0.5 * leakT), weight: 400 });
    txt(g, "HONEST MODEL", rx, H * 0.58, { size: H * 0.024, color: hex(OK, 0.9 * honest), spacing: 2.5 });
    txt(g, (0.802 * honest).toFixed(2), rx, H * 0.74, { size: H * 0.15, color: OK, spacing: -4, alpha: honest });
    txt(g, "AUC · tested on the next year", rx, H * 0.805, { size: H * 0.028, color: hex(ink, 0.5 * honest), weight: 400 });
    g.fillStyle = hex(ink, 0.08); rr(g, rx, H * 0.86, rw, H * 0.016, 8); g.fill(); g.fillStyle = OK; rr(g, rx, H * 0.86, Math.max(0.001, rw * 0.802 * honest), H * 0.016, 8); g.fill();
  },
});
