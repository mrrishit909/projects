/* FAA Aircraft Registry Database: every US-registered aircraft loaded into PostgreSQL. Records stream into a constraint-checked table,
   the counter reaches the real 317,166, and the registry's story appears: an old fleet (median single-engine airplane built in 1976). */
scene({
  slug: "faa-aircraft-db", aspect: 1.701, seconds: 6, bg: ["#0b111c", "#04060b"],
  init(W, H, { rng, gauss }) {
    const r = rng(29), planes = Array.from({ length: 16 }, (_, i) => ({ y: 0.12 + r() * 0.5, off: i / 16, s: 0.8 + r() * 0.5 }));
    // build-year histogram 1940..2025, peaking in the 1960s-70s with a median of 1976 (from the case study)
    const years = []; for (let y = 1940; y <= 2025; y += 5) years.push({ y, h: Math.exp(-((y - 1972) ** 2) / 260) * 0.85 + (y > 1995 ? 0.18 + 0.12 * Math.exp(-((y - 2008) ** 2) / 90) : 0) + 0.05 });
    return { planes, years };
  },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, dot, rr, wrap01, fmt }) {
    const BL = "#5fb3ff", ink = "#e6eefb", AMB = "#ffc35a";
    // database cylinder
    const cx = W * 0.27, cy = H * 0.5, rw = W * 0.12, rh = H * 0.05, ht = H * 0.3, fill = ease.out3(seg(u, 0.05, 0.6));
    g.fillStyle = hex(BL, 0.08); g.fillRect(cx - rw, cy - ht / 2, rw * 2, ht);
    g.fillStyle = hex(BL, 0.25); g.fillRect(cx - rw, cy + ht / 2 - ht * fill, rw * 2, ht * fill);
    [cy - ht / 2, cy - ht / 6, cy + ht / 6, cy + ht / 2].forEach((y, i) => { g.strokeStyle = hex(BL, i === 0 ? 0.9 : 0.4); g.lineWidth = 2; g.beginPath(); g.ellipse(cx, y, rw, rh, 0, i === 0 ? 0 : 0, i === 0 ? Math.PI * 2 : Math.PI); g.stroke(); });
    g.strokeStyle = hex(BL, 0.6); g.beginPath(); g.moveTo(cx - rw, cy - ht / 2); g.lineTo(cx - rw, cy + ht / 2); g.moveTo(cx + rw, cy - ht / 2); g.lineTo(cx + rw, cy + ht / 2); g.stroke();
    txt(g, "PostgreSQL", cx, cy + ht / 2 + H * 0.1, { size: H * 0.034, color: ink, align: "center", mono: true, weight: 400 });
    txt(g, fmt(Math.round(317166 * ease.out5(seg(u, 0.05, 0.62)))) + " AIRCRAFT", cx, cy + ht / 2 + H * 0.16, { size: H * 0.026, color: hex(ink, 0.6), align: "center", spacing: 2.5 });
    // aircraft flying in from the left as records
    S.planes.forEach((p) => {
      const t = wrap01(u * 2 + p.off), x = lerp(-W * 0.05, cx - rw * 0.6, ease.in3(t)), y = lerp(p.y * H, cy - ht / 2, ease.in3(t)), a = (1 - t) * seg(u, 0.03, 0.1) * (1 - seg(u, 0.62, 0.7));
      if (a <= 0) return; g.save(); g.globalAlpha *= a; g.translate(x, y); g.scale(p.s, p.s); g.fillStyle = "#fff";
      g.beginPath(); g.moveTo(16, 0); g.lineTo(-12, -3); g.lineTo(-12, 3); g.closePath(); g.fill(); g.fillRect(-2, -12, 5, 24); g.fillRect(-12, -6, 3, 12); g.restore();
    });
    // build years
    const hx = W * 0.5, hw = W * 0.45, hb = H * 0.8, hh = H * 0.5, n = S.years.length, bw = (hw / n) * 0.7;
    txt(g, "YEAR BUILT", hx, H * 0.2, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    S.years.forEach((d, i) => { const k = ease.out5(seg(u, 0.3 + i * 0.012, 0.5 + i * 0.012)); g.fillStyle = d.y >= 1960 && d.y < 1980 ? AMB : hex(BL, 0.55); rr(g, hx + (i / n) * hw, hb - d.h * hh * k, bw, d.h * hh * k, 3); g.fill(); if (d.y % 20 === 0) txt(g, String(d.y), hx + (i / n) * hw + bw / 2, hb + H * 0.04, { size: H * 0.022, color: hex(ink, 0.4), align: "center", weight: 400 }); });
    line(g, hx, hb, hx + hw, hb, hex(ink, 0.3));
    const m = ease.out3(seg(u, 0.62, 0.74)), mx = hx + ((1976 - 1940) / 5 / n) * hw + bw / 2;
    line(g, mx, hb, mx, hb - hh * 1.05 * m, "#fff", 2, [5, 5]);
    txt(g, "MEDIAN SINGLE-ENGINE: 1976", mx + 10, hb - hh * 1.02, { size: H * 0.027, color: "#fff", spacing: 1.5, alpha: m });
    txt(g, "17,734 ELECTRIC · DRONES IN THE TOP 15", hx, H * 0.95, { size: H * 0.025, color: AMB, spacing: 1.8, alpha: seg(u, 0.76, 0.88) });
  },
});
