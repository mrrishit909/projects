/* Titanic: The Missing-Data Problem. Every passenger is a dot, grouped by class. Ages are missing far more in 3rd class (29% vs
   6-12%), the blanks are filled in, and the real finding lands: passengers with no recorded age survived less (27.8% vs 40.8%). */
scene({
  slug: "titanic-survival", aspect: 1.736, seconds: 6, bg: ["#0a1220", "#03060c"],
  init(W, H, { rng }) {
    const r = rng(15), groups = [["1ST", 0.24, 0.09], ["2ND", 0.21, 0.09], ["3RD", 0.55, 0.29]], dots = [];
    groups.forEach(([name, share, miss], gi) => { const n = Math.round(share * 891); for (let i = 0; i < n; i++) dots.push({ g: gi, i, n, missing: r() < miss, lived: r() < [0.62, 0.47, 0.24][gi], at: r() }); });
    return { dots, groups };
  },
  draw(g, u, W, H, S, { TAU, lerp, seg, ease, hex, txt, line, dot, rr, wrap01 }) {
    const ICE = "#9fd0ff", CREAM = "#ffe7b0", GREY = "#6c7f99", AMB = "#ffb454", ink = "#e9f1fc";
    const gx = W * 0.05, gw = W * 0.9, top = H * 0.17, colW = [0.24, 0.21, 0.55], gap = W * 0.012; let off = 0; const xs = colW.map((c) => { const x = gx + off; off += c * (gw - 2 * gap) + gap; return [x, c * (gw - 2 * gap)]; });
    const bob = Math.sin(u * TAU * 2) * 3;
    // a little ship above the grid
    g.save(); g.translate(W * 0.9, H * 0.095 + bob); g.fillStyle = hex(ink, 0.7); g.beginPath(); g.moveTo(-42, 4); g.lineTo(46, 4); g.lineTo(36, 18); g.lineTo(-30, 18); g.closePath(); g.fill(); g.fillRect(-26, -8, 52, 12); [-14, 0, 14].forEach((x) => g.fillRect(x - 3, -22, 6, 15)); g.restore();
    txt(g, "EVERY DOT IS A PASSENGER", gx, H * 0.09, { size: H * 0.026, color: hex(ink, 0.5), spacing: 2.5 });
    const showMiss = ease.out3(seg(u, 0.22, 0.34)), fill = ease.out3(seg(u, 0.4, 0.54)), surv = ease.out3(seg(u, 0.6, 0.76));
    S.dots.forEach((d) => {
      const [x0, w] = xs[d.g], cols = Math.max(4, Math.floor(w / (H * 0.0265))), step = w / cols, x = x0 + (d.i % cols + 0.5) * step, y = top + H * 0.06 + (Math.floor(d.i / cols) + 0.5) * step;
      const pop = ease.back(seg(u, 0.03 + d.at * 0.14, 0.12 + d.at * 0.14)); if (pop <= 0) return; const r = step * 0.34 * pop;
      let col = hex(ink, 0.55), ring = false;
      if (d.missing && showMiss > 0 && fill < 1) { ring = true; col = AMB; }
      if (surv > 0) col = d.lived ? `rgba(255,231,176,${0.35 + 0.65 * surv})` : `rgba(108,127,153,${1 - 0.5 * surv})`;
      if (d.missing && fill > 0 && surv === 0) col = ICE;
      if (ring) { g.strokeStyle = col; g.lineWidth = 2; g.globalAlpha *= 1; g.beginPath(); g.arc(x, y, r * (1 + 0.15 * Math.sin(u * 30 + d.at * 9)), 0, TAU); g.stroke(); }
      else dot(g, x, y, r, col, d.lived && surv > 0.8 ? hex(CREAM, 0.5) : null);
    });
    xs.forEach(([x0, w], gi) => txt(g, S.groups[gi][0] + " CLASS", x0, top + H * 0.02, { size: H * 0.024, color: hex(ink, 0.6), spacing: 2 }));
    // callouts
    const c1 = seg(u, 0.26, 0.36) * (1 - seg(u, 0.4, 0.46)), c2 = seg(u, 0.44, 0.54) * (1 - seg(u, 0.58, 0.64)), c3 = seg(u, 0.78, 0.9);
    txt(g, "3RD CLASS: AGE BLANK FOR 29%", xs[2][0], H * 0.82, { size: H * 0.03, color: AMB, spacing: 1.5, alpha: c1 }); txt(g, "FILLED IN FROM WHAT WE KNOW", xs[2][0], H * 0.82, { size: H * 0.03, color: ICE, spacing: 1.5, alpha: c2 });
    if (c3 > 0) { txt(g, "SURVIVED", gx, H * 0.84, { size: H * 0.024, color: hex(ink, 0.5 * c3), spacing: 2.5 }); txt(g, "AGE RECORDED", gx, H * 0.92, { size: H * 0.032, color: CREAM, alpha: c3 }); txt(g, "40.8%", gx + W * 0.2, H * 0.92, { size: H * 0.048, color: "#fff", alpha: c3 }); txt(g, "NO AGE", gx + W * 0.4, H * 0.92, { size: H * 0.032, color: AMB, alpha: c3 }); txt(g, "27.8%", gx + W * 0.5, H * 0.92, { size: H * 0.048, color: "#fff", alpha: c3 }); }
  },
});
