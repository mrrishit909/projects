/* Is Chicago's Crime Drop Real? A forecast band from 2015-2023 history, then reality falling out of the bottom of it; on the right the
   case study's gaps vs expected, Jan 2024 - Aug 2026: robbery -44%, weapons -26%, motor vehicle theft -25%, homicide -23%, burglary +49%. */
scene({
  slug: "chicago-crime-r", aspect: 1.72, seconds: 6, bg: ["#120d1a", "#050308"],
  init(W, H, { rng }) {
    const r = rng(11), hist = [], fut = [];
    for (let i = 0; i <= 40; i++) hist.push(0.5 + 0.08 * Math.sin(i / 3.1) + (r() - 0.5) * 0.06);
    for (let i = 0; i <= 24; i++) fut.push(0.5 - i * 0.012 + (r() - 0.5) * 0.05);
    return { hist, fut };
  },
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, path }) {
    const ink = "#f1ecf7", BAND = "#7d6cff", RED = "#ff5c7a", GRN = "#35d39a", x0 = W * 0.05, x1 = W * 0.5, y0 = H * 0.22, y1 = H * 0.86;
    const X = (i, n, a, b) => a + (b - a) * (i / n), Y = (v) => y1 - (y1 - y0) * v, xm = x0 + (x1 - x0) * 0.62;
    txt(g, "REPORTED CRIME VS ITS OWN FORECAST", x0, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    const kh = ease.inOut(seg(u, 0.04, 0.3));
    path(g, S.hist.map((v, i) => [X(i, 40, x0, xm), Y(v)]), kh, hex(ink, 0.75), 2.5);
    const kb = ease.out3(seg(u, 0.28, 0.42));
    g.save(); g.globalAlpha *= kb * 0.35; g.fillStyle = BAND; g.beginPath();
    for (let i = 0; i <= 24; i++) g.lineTo(X(i, 24, xm, x1), Y(0.5 + 0.13 * Math.sqrt(i / 24)));
    for (let i = 24; i >= 0; i--) g.lineTo(X(i, 24, xm, x1), Y(0.5 - 0.13 * Math.sqrt(i / 24)));
    g.fill(); g.restore();
    line(g, xm, y0, xm, y1, hex(ink, 0.15), 1, [4, 6]);
    txt(g, "forecast", xm + 8, Y(0.68), { size: H * 0.024, color: BAND, alpha: kb });
    path(g, S.fut.map((v, i) => [X(i, 24, xm, x1), Y(v)]), ease.inOut(seg(u, 0.4, 0.62)), RED, 3, RED);
    const rx = W * 0.58, rw = W * 0.36, mid = rx + rw * 0.47;
    txt(g, "JAN 2024 – AUG 2026, VS EXPECTED", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    line(g, mid, H * 0.18, mid, H * 0.9, hex(ink, 0.2), 1);
    [["Robbery", -44], ["Weapons violation", -26], ["Motor vehicle theft", -25], ["Homicide", -23], ["Burglary", 49]].forEach(([n, v], i) => {
      const y = H * 0.22 + i * H * 0.135, t = ease.out5(seg(u, 0.45 + i * 0.05, 0.68 + i * 0.05)), w = (rw * 0.45) * (Math.abs(v) / 50) * t, c = v < 0 ? GRN : RED;
      txt(g, n, rx, y, { size: H * 0.03, color: hex(ink, 0.85), weight: 400 });
      g.fillStyle = c; rr(g, v < 0 ? mid - w : mid, y + H * 0.02, Math.max(0.001, w), H * 0.04, 6); g.fill();
      txt(g, (v > 0 ? "+" : "−") + Math.abs(Math.round(v * t)) + "%", v < 0 ? mid - w - 8 : mid + w + 8, y + H * 0.052, { size: H * 0.03, color: c, align: v < 0 ? "right" : "left", alpha: t });
    });
  },
});
