/* Which Kitchens to Inspect First? Places are ranked by risk of failing; inspecting in that order finds failures sooner than
   the actual order (first half of the failures after 24.3 days instead of 29.4: about five days sooner, from the case study). */
scene({
  slug: "food-inspections", aspect: 1.701, seconds: 6, bg: ["#170e0e", "#070404"],
  init(W, H, { rng }) {
    const r = rng(17), rows = Array.from({ length: 10 }, (_, i) => ({ v: r(), start: i, bar: 0.4 + r() * 0.5 })); const ord = rows.map((_, i) => i).sort((a, b) => rows[b].v - rows[a].v); rows.forEach((x, i) => (x.rank = ord.indexOf(i)));
    return { rows };
  },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, mix, txt, line, dot, rr, path }) {
    const RED = "#ff5d5d", GRN = "#52d68a", ink = "#f6e9e7", lx = W * 0.05, lw = W * 0.4, top = H * 0.16, rowH = H * 0.079;
    txt(g, "RISK OF FAILING", lx, H * 0.09, { size: H * 0.026, color: hex(ink, 0.5), spacing: 2.5 });
    const sortT = ease.inOut(seg(u, 0.26, 0.52));
    S.rows.forEach((r) => {
      const k = ease.out3(seg(u, 0.06 + r.start * 0.02, 0.16 + r.start * 0.02)); if (k <= 0) return;
      const y = top + lerp(r.start, r.rank, sortT) * rowH, col = mix("#52d68a", "#ff5d5d", r.v);
      g.save(); g.globalAlpha *= k; g.fillStyle = hex(ink, 0.05); rr(g, lx, y, lw, rowH * 0.76, 10); g.fill();
      g.fillStyle = hex(ink, 0.18); rr(g, lx + 14, y + rowH * 0.22, lw * 0.28 * r.bar, rowH * 0.3, 5); g.fill();
      const bx = lx + lw * 0.4, bw = lw * 0.5; g.fillStyle = hex(ink, 0.08); rr(g, bx, y + rowH * 0.25, bw, rowH * 0.26, 5); g.fill(); g.fillStyle = col; rr(g, bx, y + rowH * 0.25, Math.max(0.001, bw * (0.12 + 0.88 * r.v)), rowH * 0.26, 5); g.fill();
      if (r.rank < 2 && sortT > 0.9) { g.strokeStyle = RED; g.lineWidth = 2; rr(g, lx - 3, y - 3, lw + 6, rowH * 0.76 + 6, 12); g.stroke(); }
      g.restore();
    });
    // cumulative failures found vs days
    const px = W * 0.56, pw = W * 0.38, py = H * 0.86, ph = H * 0.62;
    txt(g, "FAILURES FOUND, BY DAY", px, H * 0.09, { size: H * 0.026, color: hex(ink, 0.5), spacing: 2.5 });
    line(g, px, py, px + pw, py, hex(ink, 0.3)); line(g, px, py, px, py - ph, hex(ink, 0.3)); line(g, px, py - ph * 0.5, px + pw, py - ph * 0.5, hex(ink, 0.08), 1, [4, 5]);
    const curve = (f) => Array.from({ length: 41 }, (_, i) => { const x = i / 40; return [px + x * pw, py - f(x) * ph]; });
    const actual = curve((x) => x * 0.95 + 0.05 * Math.sin(x * 12) * 0.2 * 0), risk = curve((x) => 1 - Math.pow(1 - x, 1.75));
    const tA = ease.inOut(seg(u, 0.5, 0.74)), tR = ease.inOut(seg(u, 0.56, 0.8));
    path(g, actual, tA, hex(ink, 0.55), 3); path(g, risk, tR, GRN, 4, hex(GRN, 0.6));
    // the gap at the halfway mark
    const gap = ease.out3(seg(u, 0.78, 0.9));
    if (gap > 0) {
      const xa = px + pw * 0.5, ya = py - ph * 0.5, xr = px + pw * (1 - Math.pow(0.5, 1 / 1.75)), yR = py - ph * 0.5;
      line(g, xr, yR, lerp(xr, xa, gap), yR, "#fff", 2); line(g, xr, yR - 8, xr, yR + 8, "#fff", 2); line(g, lerp(xr, xa, gap), yR - 8, lerp(xr, xa, gap), yR + 8, "#fff", 2);
      txt(g, "≈ 5 days sooner", (xr + xa) / 2, yR - H * 0.04, { size: H * 0.034, color: "#fff", align: "center", alpha: gap });
    }
    txt(g, "RISK ORDER", px + pw * 0.62, py - ph * 0.9, { size: H * 0.024, color: GRN, spacing: 2, alpha: tR }); txt(g, "ACTUAL ORDER", px + pw * 0.62, py - ph * 0.32, { size: H * 0.024, color: hex(ink, 0.6), spacing: 2, alpha: tA });
  },
});
