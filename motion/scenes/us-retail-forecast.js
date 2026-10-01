/* US Retail Sales Forecast: a seasonal series; five methods are tested on months they hadn't seen; the best (ETS + SARIMA average)
   carries on into the next 12 months with an honest, widening range. MAPE figures are the case study's. */
scene({
  slug: "us-retail-forecast", aspect: 1.74, seconds: 6, bg: ["#0a1219", "#03070b"],
  init(W, H, { rng, gauss }) {
    const r = rng(33), N = 60, F = 12, season = (m) => 0.05 * Math.sin((m % 12) / 12 * Math.PI * 2 - 1.9) + 0.045 * Math.exp(-(((m % 12) - 11) ** 2) / 1.2), hist = [];
    for (let m = 0; m < N; m++) hist.push(100 * (1 + 0.0035 * m) * (1 + season(m)) * (1 + gauss(r) * 0.004));
    const test0 = N - 24, mk = (bias, wob, seed) => { const rr2 = rng(seed); return Array.from({ length: 24 }, (_, i) => hist[test0 + i] * (1 + bias + gauss(rr2) * wob)); };
    const methods = [["ETS + SARIMA", mk(0.002, 0.007, 1), "#35d6c6", 1.81], ["SARIMA", mk(0.009, 0.008, 2), "#7aa7ff", 1.96], ["Holt-Winters", mk(-0.004, 0.009, 3), "#a98bff", 1.98], ["Seasonal naive", mk(-0.032, 0.011, 4), "#ff9f6b", 3.33], ["Last year × growth", mk(0.02, 0.012, 5), "#ff6fa0", 3.39]];
    const fut = Array.from({ length: F }, (_, i) => 100 * (1 + 0.0035 * (N + i)) * (1 + season(N + i)) * 1.002);
    return { N, F, hist, methods, fut, test0 };
  },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, dot, rr, path }) {
    const TEAL = "#35d6c6", ink = "#e5f1f7", px = W * 0.05, pw = W * 0.62, py = H * 0.12, ph = H * 0.72, tot = S.N + S.F, lo = 90, hi = 168;
    const X = (m) => px + (m / (tot - 1)) * pw, Y = (v) => py + (1 - (v - lo) / (hi - lo)) * ph;
    txt(g, "MONTHLY RETAIL SALES", px, H * 0.075, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    for (let i = 0; i <= 3; i++) line(g, px, py + (ph * i) / 3, px + pw, py + (ph * i) / 3, hex(ink, 0.06));
    const hp = ease.inOut(seg(u, 0.04, 0.4)), pts = S.hist.map((v, m) => [X(m), Y(v)]); path(g, pts, hp, "#fff", 2.6, hex("#ffffff", 0.35));
    // held-out months
    const tb = ease.out3(seg(u, 0.38, 0.5)); g.fillStyle = hex(TEAL, 0.07 * tb); g.fillRect(X(S.test0), py - H * 0.02, (X(S.N - 1) - X(S.test0)) * 1, ph + H * 0.04); txt(g, "TEST MONTHS", X(S.test0) + 8, py - H * 0.035, { size: H * 0.02, color: hex(TEAL, 0.9 * tb), spacing: 1.8 });
    const mp = ease.inOut(seg(u, 0.42, 0.6)), lose = ease.smooth(seg(u, 0.62, 0.72));
    S.methods.forEach(([name, vals, col], i) => path(g, vals.map((v, j) => [X(S.test0 + j), Y(v)]), mp, col, i === 0 ? 3.2 : 2, i === 0 ? hex(col, 0.7) : null) , g.globalAlpha);
    // the future fan
    const fp = ease.inOut(seg(u, 0.7, 0.88)), fpts = S.fut.map((v, j) => [X(S.N + j), Y(v)]);
    if (fp > 0) {
      const n = Math.max(1, Math.floor(fp * (S.F - 1)) + 1); g.fillStyle = hex(TEAL, 0.17); g.beginPath();
      for (let j = 0; j < n; j++) { const spread = 0.012 + j * 0.0045; g[j ? "lineTo" : "moveTo"](fpts[j][0], Y(S.fut[j] * (1 + spread))); }
      for (let j = n - 1; j >= 0; j--) { const spread = 0.012 + j * 0.0045; g.lineTo(fpts[j][0], Y(S.fut[j] * (1 - spread))); } g.closePath(); g.fill();
      path(g, [[X(S.N - 1), Y(S.methods[0][1][23])], ...fpts], fp, TEAL, 3.4, hex(TEAL, 0.8));
    }
    txt(g, "NEXT 12 MONTHS", px + pw, py + ph + H * 0.075, { size: H * 0.02, color: hex(TEAL, 0.95 * fp), spacing: 1.8, align: "right" });
    txt(g, "+4.9%", px + pw, py + ph + H * 0.015, { size: H * 0.06, color: "#fff", alpha: fp, align: "right" });
    // MAPE panel
    const rx = W * 0.73, rw = W * 0.2, bt = ease.out5(seg(u, 0.5, 0.74));
    txt(g, "AVERAGE ERROR (MAPE)", rx, H * 0.14, { size: H * 0.022, color: hex(ink, 0.5), spacing: 2 });
    S.methods.forEach(([name, , col, v], i) => {
      const y = H * 0.2 + i * H * 0.14, best = i === 0;
      txt(g, name, rx, y + H * 0.025, { size: H * 0.029, color: hex(ink, 0.85), weight: best ? 500 : 400 }); txt(g, v.toFixed(2) + "%", rx + rw, y + H * 0.025, { size: H * 0.03, color: col, align: "right", alpha: bt });
      g.fillStyle = hex(ink, 0.07); rr(g, rx, y + H * 0.045, rw, H * 0.016, 8); g.fill(); g.fillStyle = col; rr(g, rx, y + H * 0.045, Math.max(0.001, rw * (v / 3.6) * bt), H * 0.016, 8); g.fill();
    });
  },
});
