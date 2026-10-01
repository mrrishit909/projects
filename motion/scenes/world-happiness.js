/* World Happiness: countries by income and life satisfaction; the fitted curve says what circumstances predict, dots above it are
   happier than predicted. Then the change: 86 of 141 countries rose (the case study's count). */
scene({
  slug: "world-happiness", aspect: 1.614, seconds: 6, bg: ["#1a1208", "#080503"],
  init(W, H, { rng, gauss }) {
    const r = rng(19), pts = [];
    for (let i = 0; i < 141; i++) { const x = 0.04 + r() * 0.92, fit = 0.16 + 0.7 * Math.pow(x, 0.55), y = Math.min(0.97, Math.max(0.05, fit + gauss(r) * 0.075)); pts.push({ x, y, fit, up: i < 86, mag: 0.025 + r() * 0.06, at: r() }); }
    pts.sort((a, b) => a.at - b.at); const order = pts.map((p, i) => i).sort(() => r() - 0.5); pts.forEach((p, i) => (p.up = order[i] < 86));
    return { pts };
  },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, mix, txt, line, dot, rr, path }) {
    const SUN = "#ffcf5a", BLU = "#6aa8ff", ink = "#f8eddc", px = W * 0.06, py = H * 0.1, pw = W * 0.6, ph = H * 0.74, X = (x) => px + x * pw, Y = (y) => py + (1 - y) * ph;
    const sg = g.createRadialGradient(W * 0.9, H * 0.05, 0, W * 0.9, H * 0.05, W * 0.55); sg.addColorStop(0, "rgba(255,190,70,0.22)"); sg.addColorStop(1, "rgba(255,190,70,0)"); g.fillStyle = sg; g.fillRect(0, 0, W, H);
    line(g, px, py + ph, px + pw, py + ph, hex(ink, 0.3)); line(g, px, py, px, py + ph, hex(ink, 0.3));
    txt(g, "LIFE SATISFACTION", px, py - H * 0.025, { size: H * 0.023, color: hex(ink, 0.5), spacing: 2.5 }); txt(g, "INCOME →", px + pw, py + ph + H * 0.05, { size: H * 0.023, color: hex(ink, 0.5), spacing: 2.5, align: "right" });
    const fitT = ease.inOut(seg(u, 0.3, 0.46)), color = seg(u, 0.36, 0.5), move = ease.inOut(seg(u, 0.52, 0.76));
    const curve = Array.from({ length: 41 }, (_, i) => { const x = 0.04 + (i / 40) * 0.92; return [X(x), Y(0.16 + 0.7 * Math.pow(x, 0.55))]; });
    path(g, curve, fitT, hex(ink, 0.85), 3);
    S.pts.forEach((p) => {
      const k = ease.back(seg(u, 0.04 + p.at * 0.24, 0.12 + p.at * 0.24)); if (k <= 0) return;
      const above = p.y > p.fit, col = color > 0 ? mix("#f8eddc", above ? SUN : BLU, color) : "#f8eddc", dy = (p.up ? 1 : -1) * p.mag * move;
      if (move > 0 && move < 1.01) { const a = Y(p.y), b = Y(p.y + dy); line(g, X(p.x), a, X(p.x), b, hex(p.up ? SUN : BLU, 0.5), 2); }
      dot(g, X(p.x), Y(p.y + dy), H * 0.0098 * k, col, above && color > 0.5 ? hex(SUN, 0.45) : null);
    });
    // callouts
    const rx = W * 0.72, a = ease.out3(seg(u, 0.46, 0.58)), n = Math.round(86 * ease.out5(seg(u, 0.54, 0.76)));
    txt(g, "HAPPIER THAN", rx, H * 0.2, { size: H * 0.024, color: hex(SUN, 0.95 * a), spacing: 2.5 }); txt(g, "CIRCUMSTANCES PREDICT", rx, H * 0.2 + H * 0.04, { size: H * 0.024, color: hex(SUN, 0.95 * a), spacing: 2.5 });
    txt(g, "LESS HAPPY THAN", rx, H * 0.34, { size: H * 0.024, color: hex(BLU, 0.95 * a), spacing: 2.5 }); txt(g, "CIRCUMSTANCES PREDICT", rx, H * 0.34 + H * 0.04, { size: H * 0.024, color: hex(BLU, 0.95 * a), spacing: 2.5 });
    txt(g, String(n), rx, H * 0.7, { size: H * 0.19, color: "#fff", spacing: -6, alpha: move > 0 ? 1 : 0 }); txt(g, "OF 141 GOT HAPPIER", rx, H * 0.76, { size: H * 0.024, color: hex(ink, 0.6), spacing: 2, alpha: seg(u, 0.56, 0.7) });
    txt(g, "Latin America: +0.59", rx, H * 0.88, { size: H * 0.027, color: SUN, weight: 400, alpha: seg(u, 0.8, 0.9) });
  },
});
