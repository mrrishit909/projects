/* How Wrong Are Election Polls? Poll errors land as dots around zero; the band is the polls' own stated margin of error, and the dots
   outside it turn red (29% in the case study; the dots are illustrative). Right: typical miss 7.0 points against 3.7 if only sampling
   mattered, and an error floor of 4.7 points no sample size removes. */
scene({
  slug: "poll-accuracy", aspect: 1.72, seconds: 6, bg: ["#120f18", "#050408"],
  init(W, H, { rng, gauss }) { const r = rng(29), d = []; for (let i = 0; i < 240; i++) { const e = gauss(r) * 7; d.push({ e, y: r(), t: r() * 0.4, out: Math.abs(e) > 7.6 }); } return { d }; },
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, dot }) {
    const ink = "#f2eef8", RED = "#ff5f6d", BL = "#7aa7ff", x0 = W * 0.05, x1 = W * 0.52, cx = (x0 + x1) / 2, X = (e) => cx + e * (x1 - x0) / 50;
    txt(g, "POLL ERROR, POINTS · BAND = STATED MARGIN", x0, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    const kb = ease.out3(seg(u, 0.05, 0.2));
    g.fillStyle = hex(BL, 0.12 * kb); g.fillRect(X(-7.6), H * 0.2, X(7.6) - X(-7.6), H * 0.62);
    line(g, cx, H * 0.2, cx, H * 0.82, hex(ink, 0.3), 1);
    S.d.forEach((p) => { const t = ease.out3(seg(u, 0.1 + p.t, 0.2 + p.t)); if (t <= 0) return; const red = p.out && seg(u, 0.55, 0.65) > 0;
      dot(g, X(p.e), H * 0.22 + p.y * H * 0.58, 3.5 * t, red ? RED : hex(BL, 0.85)); });
    [-20, -10, 0, 10, 20].forEach((v) => txt(g, (v > 0 ? "+" : "") + v, X(v), H * 0.88, { size: H * 0.022, color: hex(ink, 0.45), align: "center" }));
    const rx = W * 0.6, k = ease.out5(seg(u, 0.3, 0.55));
    txt(g, "TYPICAL MISS (RMSE)", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, (7.0 * k).toFixed(1), rx, H * 0.29, { size: H * 0.14, color: "#fff", spacing: -3 });
    txt(g, "points, vs 3.7 if only sampling", rx + W * 0.12, H * 0.28, { size: H * 0.028, color: hex(ink, 0.7), weight: 400, alpha: k });
    [["Outside their own margin of error", "29%", RED], ["Error floor no sample size removes", "4.7 pts", BL], ["General-election polls, 1998–2022", "17,226", ink]].forEach(([n, v, c], i) => {
      const y = H * 0.47 + i * H * 0.13, t = ease.out5(seg(u, 0.55 + i * 0.06, 0.72 + i * 0.06));
      line(g, rx, y - H * 0.05, rx + W * 0.34, y - H * 0.05, hex(ink, 0.12), 1);
      txt(g, n, rx, y, { size: H * 0.028, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + W * 0.34, y, { size: H * 0.034, color: c, align: "right", alpha: t });
    });
  },
});
