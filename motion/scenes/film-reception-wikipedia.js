/* Do critics' scores predict film audiences and box office? 607 Wikipedia film articles joined to IMDb's official ratings. Left: mean IMDb rating x 10 (middle half as a band) by Rotten Tomatoes bin, rising from 45 to 74.
   Right: Rotten Tomatoes and IMDb rank correlation 0.74; IMDb x 10 is 9.3 points above Metacritic; budget alone explains 57% of box-office variation (log scale); the Rotten Tomatoes score adds 2.5 points. */
const MEAN = [44.8, 53.5, 57.9, 59.0, 60.3, 63.8, 66.3, 66.8, 69.9, 74.3], P25 = [38.5, 50.0, 54.0, 55.0, 57.0, 60.0, 62.0, 64.0, 66.0, 72.0], P75 = [51.5, 57.8, 63.0, 63.0, 65.0, 67.0, 71.0, 72.5, 74.0, 78.0];
scene({
  slug: "film-reception-wikipedia", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#46c28a";
    const x0 = W * 0.09, x1 = W * 0.54, y0 = H * 0.2, y1 = H * 0.78, N = MEAN.length, X = (i) => x0 + (x1 - x0) * (i + 0.5) / N, Y = (v) => y1 - (y1 - y0) * v / 100;
    txt(g, "IMDB RATING x 10, BY ROTTEN TOMATOES SCORE", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [0, 25, 50, 75, 100].forEach((v) => { line(g, x0 - H * 0.01, Y(v), x1, Y(v), hex(ink, 0.07), 1); txt(g, String(v), x0 - H * 0.02, Y(v) + H * 0.007, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    [0, 25, 50, 75, 100].forEach((v) => txt(g, String(v), x0 + (x1 - x0) * v / 100, y1 + H * 0.05, { size: H * 0.02, color: hex(ink, 0.4), align: "center" }));
    const p = ease.out5(seg(u, 0.05, 0.6)) * (N - 1), k = Math.floor(p), f = p - k;
    const pts = (arr) => { const o = []; for (let i = 0; i <= k; i++) o.push([X(i), Y(arr[i])]); if (k < N - 1) o.push([lerp(X(k), X(k + 1), f), Y(lerp(arr[k], arr[k + 1], f))]); return o; };
    const hi = pts(P75), lo = pts(P25).reverse();
    g.beginPath(); hi.forEach((q, i) => (i ? g.lineTo(q[0], q[1]) : g.moveTo(q[0], q[1]))); lo.forEach((q) => g.lineTo(q[0], q[1])); g.closePath(); g.fillStyle = hex(BL, 0.22); g.fill();
    const m = pts(MEAN); g.beginPath(); m.forEach((q, i) => (i ? g.lineTo(q[0], q[1]) : g.moveTo(q[0], q[1]))); g.strokeStyle = BL; g.lineWidth = H * 0.005; g.lineJoin = "round"; g.stroke();
    m.forEach((q) => dot(g, q[0], q[1], H * 0.007, BL));
    const tl = ease.out5(seg(u, 0.55, 0.7)); txt(g, MEAN[N - 1].toFixed(0), X(N - 1) - H * 0.02, Y(MEAN[N - 1]) - H * 0.03, { size: H * 0.024, color: ORG, align: "right", alpha: tl });
    const rx = W * 0.64, rw = W * 0.29; txt(g, "CRITICS, AUDIENCES, BOX OFFICE", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Rank corr., RT with IMDb", "0.74", BL], ["IMDb above Metacritic (points)", "9.3", GR], ["Gross explained by budget", "57%", ink], ["Added by the RT score (points)", "2.5", ORG]].forEach(([nm, v, c], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1); txt(g, nm, rx, y, { size: H * 0.021, color: hex(ink, 0.8), weight: 400, alpha: t }); txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.04, color: c, align: "right", alpha: t });
    });
  },
});
