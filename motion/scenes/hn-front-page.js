/* What Makes a Hacker News Story Reach 100 Points? 703,300 stories from 27 sampled months. Left: the share of all points held by the most-voted stories (log scale), the top 1% holding 30%.
   Right: 5.0% of stories reach 100+ points; a model that knows only the past reaches AUC 0.63 on later months, and 0.99 if it is allowed the comment count, which is known only afterwards. */
const FX = [0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 50.0, 75.0, 100.0], FY = [6.86, 12.74, 19.94, 30.26, 44.37, 67.62, 83.0, 90.62, 93.22, 96.29, 98.71, 100.0], TOP1 = 30;
scene({
  slug: "hn-front-page", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#46c28a";
    const x0 = W * 0.09, x1 = W * 0.54, y0 = H * 0.2, y1 = H * 0.78, N = FX.length, X = (f) => x0 + (x1 - x0) * (Math.log10(f) + 1) / 3, Y = (v) => y1 - (y1 - y0) * v / 100;
    txt(g, "SHARE OF ALL POINTS HELD, MOST-VOTED FIRST", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [0, 25, 50, 75, 100].forEach((v) => { line(g, x0 - H * 0.01, Y(v), x1, Y(v), hex(ink, v === 0 ? 0.3 : 0.07), 1); txt(g, v + "%", x0 - H * 0.02, Y(v) + H * 0.007, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    [[0.1, "0.1%"], [1, "1%"], [10, "10%"], [100, "100%"]].forEach(([f, l]) => txt(g, l, X(f), y1 + H * 0.05, { size: H * 0.02, color: hex(ink, 0.4), align: "center" }));
    txt(g, "stories (share of all, log scale)", (x0 + x1) / 2, y1 + H * 0.1, { size: H * 0.02, color: hex(ink, 0.4), align: "center" });
    const p = ease.out5(seg(u, 0.05, 0.55)) * (N - 1), k = Math.floor(p), fr = p - k;
    g.beginPath(); g.moveTo(X(FX[0]), Y(FY[0])); for (let i = 1; i <= k; i++) g.lineTo(X(FX[i]), Y(FY[i]));
    if (k < N - 1) g.lineTo(lerp(X(FX[k]), X(FX[k + 1]), fr), lerp(Y(FY[k]), Y(FY[k + 1]), fr));
    g.strokeStyle = BL; g.lineWidth = H * 0.006; g.lineJoin = "round"; g.stroke();
    const tl = ease.out5(seg(u, 0.5, 0.65)); dot(g, X(1), Y(TOP1), H * 0.012 * tl, ORG);
    txt(g, "top 1% hold " + TOP1 + "%", X(1) + H * 0.03, Y(TOP1) + H * 0.045, { size: H * 0.022, color: ORG, alpha: tl });
    const rx = W * 0.64, rw = W * 0.29; txt(g, "100+ POINTS, GUESSED EARLY", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Stories reaching 100+", "5.0%", BL], ["Points held by the top 1%", "30%", ORG], ["AUC at submission, past only", "0.63", GR], ["AUC with the comment count", "0.99", ORG]].forEach(([nm, v, c], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1); txt(g, nm, rx, y, { size: H * 0.021, color: hex(ink, 0.8), weight: 400, alpha: t }); txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.04, color: c, align: "right", alpha: t });
    });
  },
});
