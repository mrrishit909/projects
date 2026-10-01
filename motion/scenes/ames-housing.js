/* Ames House Prices: sale price against living area. Five bad sales drag the fit; flag them, drop them, the line snaps true,
   and the typical error settles as a band around it (about 6%, from the case study). */
scene({
  slug: "ames-housing", aspect: 1.747, seconds: 6, bg: ["#171310", "#080706"],
  init(W, H, { rng, gauss }) {
    const r = rng(11), pts = [];
    for (let i = 0; i < 120; i++) {
      let x = 0.42 + gauss(r) * 0.19; while (x < 0.06 || x > 0.8) x = 0.42 + gauss(r) * 0.19;
      pts.push({ x, y: 0.1 + 0.8 * x + gauss(r) * 0.07, at: 0.04 + r() * 0.3 });
    }
    const bad = [[0.92, 0.2], [0.97, 0.3], [0.88, 0.17], [0.95, 0.25], [0.9, 0.22]].map(([x, y], i) => ({ x, y, at: 0.34 + i * 0.012, bad: true }));
    return { pts, bad };
  },
  draw(g, u, W, H, S, { clamp, lerp, seg, ease, hex, txt, line, dot, rr, path }) {
    const A = "#f2b84b", ink = "#f4ece0", pad = { l: W * 0.1, r: W * 0.06, t: H * 0.14, b: H * 0.17 };
    const pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;
    const X = (x) => pad.l + x * pw, Y = (y) => pad.t + (1 - y) * ph;
    // axes + faint grid
    for (let i = 0; i <= 4; i++) { line(g, pad.l, Y(i / 4), W - pad.r, Y(i / 4), hex(ink, 0.07)); line(g, X(i / 4), pad.t, X(i / 4), pad.t + ph, hex(ink, 0.05)); }
    line(g, pad.l, pad.t + ph, W - pad.r, pad.t + ph, hex(ink, 0.35)); line(g, pad.l, pad.t, pad.l, pad.t + ph, hex(ink, 0.35));
    txt(g, "LIVING AREA", W - pad.r, H - pad.b * 0.4, { size: H * 0.024, color: hex(ink, 0.5), align: "right", spacing: 2 });
    txt(g, "SALE PRICE", pad.l, pad.t * 0.62, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2 });
    const drop = ease.inOut(seg(u, 0.5, 0.64)), fade = 1 - drop;
    // the fit: first dragged flat by the five bad sales, then it rotates steeper once they're gone
    const slope = lerp(0.52, 0.8, drop), icpt = lerp(0.22, 0.1, drop);
    const fy = (x) => icpt + slope * x;
    S.pts.forEach((p) => {
      const t = ease.back(seg(u, p.at, p.at + 0.07)); if (t <= 0) return;
      dot(g, X(p.x), Y(p.y), H * 0.0125 * t, hex(A, 0.88), hex(A, 0.35));
    });
    S.bad.forEach((p) => {
      const t = ease.back(seg(u, p.at, p.at + 0.06)); if (t <= 0) return;
      const pulse = 1 + 0.25 * Math.sin(u * 60 + p.x * 9) * seg(u, 0.4, 0.5) * fade;
      g.save(); g.globalAlpha *= fade;
      dot(g, X(p.x), Y(p.y), H * 0.0165 * t * pulse, "#ff5a4f", "#ff5a4f");
      if (seg(u, 0.42, 0.5) > 0) { const k = ease.out3(seg(u, 0.42, 0.5)), s = H * 0.026 * k; line(g, X(p.x) - s, Y(p.y) - s, X(p.x) + s, Y(p.y) + s, "#fff", 2); line(g, X(p.x) - s, Y(p.y) + s, X(p.x) + s, Y(p.y) - s, "#fff", 2); }
      g.restore();
    });
    const lt = ease.out5(seg(u, 0.36, 0.5));
    if (lt > 0) {
      // ± typical error band, drawn once the line has settled
      const bt = ease.out3(seg(u, 0.7, 0.84));
      if (bt > 0) {
        const x0 = 0.03, x1 = 0.97, e = 0.09 * bt;
        g.save(); g.fillStyle = hex(A, 0.14 * bt); g.beginPath();
        g.moveTo(X(x0), Y(fy(x0) * (1 + e))); g.lineTo(X(x1), Y(fy(x1) * (1 + e))); g.lineTo(X(x1), Y(fy(x1) * (1 - e))); g.lineTo(X(x0), Y(fy(x0) * (1 - e))); g.closePath(); g.fill(); g.restore();
      }
      path(g, [[X(0.03), Y(fy(0.03))], [X(0.97), Y(fy(0.97))]], lt, "#fff", 3, hex("#ffffff", 0.6));
    }
    // a house settles on the line: tiny price tag with the error
    const ht = ease.back(seg(u, 0.78, 0.88));
    if (ht > 0) {
      const hx = X(0.56), hy = Y(fy(0.56)) - H * 0.17, s = H * 0.05 * ht;
      g.save(); g.globalAlpha *= ht; g.fillStyle = "#171310"; rr(g, hx - s * 1.6, hy - s * 1.5, s * 6.2, s * 3.2, s * 0.5); g.fill(); g.restore();
      line(g, hx, hy + s * 1.7, hx, Y(fy(0.56)) - 6, hex("#fff", 0.5 * ht), 1.5, [4, 5]);
      g.save(); g.translate(hx - s * 0.2, hy - s * 0.2); g.fillStyle = "#fff"; g.beginPath(); g.moveTo(-s, 0); g.lineTo(0, -s * 0.9); g.lineTo(s, 0); g.lineTo(s * 0.8, 0); g.lineTo(s * 0.8, s * 0.8); g.lineTo(-s * 0.8, s * 0.8); g.lineTo(-s * 0.8, 0); g.closePath(); g.fill();
      g.fillStyle = "#171310"; g.fillRect(-s * 0.18, s * 0.2, s * 0.36, s * 0.6); g.restore();
      txt(g, "± 6%", hx + s * 1.1, hy + s * 0.55, { size: H * 0.046, color: A, weight: 500, alpha: ht });
    }
  },
});
