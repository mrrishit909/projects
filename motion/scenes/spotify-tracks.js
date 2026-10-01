/* Spotify: What Makes a Hit? Tracks scatter by how they sound (colour = genre); the popularity histogram has a huge spike at zero,
   which shrinks once the duplicate/compilation copies are set aside; an equalizer keeps time underneath. */
scene({
  slug: "spotify-tracks", aspect: 1.838, seconds: 6, bg: ["#0b1411", "#040806"],
  init(W, H, { rng, gauss }) {
    const r = rng(23), cols = ["#35e08a", "#a77bff", "#ff7ab6", "#ffd05e", "#5ec8ff", "#ff8a4c"], cl = cols.map((c, i) => ({ c, x: 0.18 + r() * 0.64, y: 0.18 + r() * 0.64, s: 0.07 + r() * 0.06 })), pts = [];
    for (let i = 0; i < 520; i++) { const k = i % cl.length, c = cl[k]; pts.push({ x: Math.min(0.98, Math.max(0.02, c.x + gauss(r) * c.s)), y: Math.min(0.98, Math.max(0.02, c.y + gauss(r) * c.s)), c: c.c, at: r() }); }
    const bins = Array.from({ length: 24 }, (_, i) => (i === 0 ? 1 : 0.14 + 0.3 * Math.exp(-((i - 9) ** 2) / 50) + 0.08 * r()));
    return { pts, bins };
  },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, dot, rr }) {
    const GR = "#35e08a", ink = "#e6f4ee", sx = W * 0.05, sy = H * 0.1, sw = W * 0.5, sh = H * 0.62;
    line(g, sx, sy + sh, sx + sw, sy + sh, hex(ink, 0.3)); line(g, sx, sy, sx, sy + sh, hex(ink, 0.3));
    txt(g, "SOUND · 114 GENRES", sx, sy - H * 0.025, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    S.pts.forEach((p) => { const k = ease.out3(seg(u, 0.05 + p.at * 0.3, 0.14 + p.at * 0.3)); if (k > 0) { g.save(); g.globalAlpha *= 0.85; dot(g, sx + p.x * sw, sy + (1 - p.y) * sh, H * 0.0072 * k, p.c); g.restore(); } });
    // histogram
    const hx = W * 0.62, hw = W * 0.33, hb = sy + sh, hh = sh * 0.9, n = S.bins.length, bw = hw / n * 0.72, shrink = ease.inOut(seg(u, 0.56, 0.74));
    txt(g, "POPULARITY", hx, sy - H * 0.025, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    S.bins.forEach((v, i) => {
      const k = ease.out5(seg(u, 0.3 + i * 0.008, 0.46 + i * 0.008)), val = i === 0 ? lerp(v, 0.16, shrink) : v, x = hx + (i / n) * hw;
      g.fillStyle = i === 0 ? mixZero(shrink) : hex(GR, 0.7); rr(g, x, hb - val * hh * k, bw, val * hh * k, 3); g.fill();
    });
    function mixZero(s) { return `rgb(${Math.round(255 + (53 - 255) * s)},${Math.round(106 + (224 - 106) * s)},${Math.round(98 + (138 - 98) * s)})`; }
    line(g, hx, hb, hx + hw, hb, hex(ink, 0.3));
    const lab = seg(u, 0.34, 0.48), lab2 = seg(u, 0.76, 0.9);
    txt(g, "0", hx + bw / 2, hb + H * 0.04, { size: H * 0.026, color: hex(ink, 0.5), align: "center" }); txt(g, "100", hx + hw, hb + H * 0.04, { size: H * 0.026, color: hex(ink, 0.5), align: "right" });
    txt(g, "SO MANY ZEROS", hx + bw + 14, hb - hh * 0.95, { size: H * 0.027, color: "#ff6a62", spacing: 1.5, alpha: lab * (1 - shrink) }); txt(g, "…MOSTLY DUPLICATES", hx + bw + 14, hb - hh * 0.55, { size: H * 0.027, color: GR, spacing: 1.5, alpha: lab2 });
    // equalizer
    const ey = H * 0.97, bars = 46, ew = W * 0.9, bwid = ew / bars * 0.55;
    for (let i = 0; i < bars; i++) { const h = H * 0.12 * (0.15 + 0.85 * Math.abs(Math.sin(u * 6.2832 * 3 + i * 0.55) * Math.cos(u * 6.2832 * 2 + i * 0.21))); g.fillStyle = hex(GR, 0.22 + 0.5 * (h / (H * 0.12))); rr(g, W * 0.05 + (i / bars) * ew, ey - h, bwid, h, 2); g.fill(); }
  },
});
