/* Can Boosted Trees Beat a 28-Day Average? WRMSSE-style error of four forecasts of Walmart unit sales (3,000 M5 series) at five origins, d_1801 to d_1913 (lower is better): last day 1.168, last week 1.090, 28-day average 0.852, boosted trees 0.821 (means of the five origins).
   Right: boosted 0.821, average 0.852, boosted lower at 5 of 5 origins, but on RMSE 2.86 against 2.79. */
const SER = {"naive": [1.1942, 1.2235, 1.1142, 1.1981, 1.1113], "seasonal_naive_7": [1.1659, 1.0945, 1.0613, 1.0848, 1.0437], "moving_avg_28": [0.8705, 0.8791, 0.8562, 0.8277, 0.8255], "hgb": [0.815, 0.8641, 0.8276, 0.8005, 0.7967]};
scene({
  slug: "m5-demand-spark", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#46c28a", GY = "#8a8f98";
    const x0 = W * 0.09, x1 = W * 0.5, y0 = H * 0.2, y1 = H * 0.78, N = 5, X = (i) => x0 + (x1 - x0) * i / (N - 1), Y = (v) => y1 - (y1 - y0) * (v - 0.7) / 0.6;
    txt(g, "ERROR OF FOUR FORECASTS, 5 ORIGINS", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [0.8, 1.0, 1.2].forEach((v) => { line(g, x0 - H * 0.01, Y(v), x1 + W * 0.03, Y(v), hex(ink, 0.08), 1); txt(g, v.toFixed(1), x0 - H * 0.02, Y(v) + H * 0.007, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    ["d_1801", "d_1913"].forEach((s, k) => txt(g, s, X(k * 4), y1 + H * 0.05, { size: H * 0.02, color: hex(ink, 0.4), align: "center" }));
    const p = ease.out5(seg(u, 0.05, 0.6)) * (N - 1), k = Math.floor(p), fr = p - k;
    [["naive", GY, 0.35], ["seasonal_naive_7", GY, 0.6], ["moving_avg_28", ORG, 1], ["hgb", BL, 1]].forEach(([m, c, a]) => {
      const v = SER[m]; g.beginPath(); g.moveTo(X(0), Y(v[0]));
      for (let i = 1; i <= k; i++) g.lineTo(X(i), Y(v[i]));
      if (k < N - 1) g.lineTo(X(k) + (X(k + 1) - X(k)) * fr, Y(v[k] + (v[k + 1] - v[k]) * fr));
      g.strokeStyle = hex(c, a); g.lineWidth = H * (m === "hgb" ? 0.007 : 0.005); g.lineJoin = "round"; g.stroke();
    });
    const tl = ease.out5(seg(u, 0.55, 0.7));
    txt(g, "28-day average", X(4) + W * 0.015, Y(SER.moving_avg_28[4]) - H * 0.035, { size: H * 0.019, color: ORG, alpha: tl });
    txt(g, "boosted trees", X(4) + W * 0.015, Y(SER.hgb[4]) + H * 0.045, { size: H * 0.019, color: BL, alpha: tl });
    const rx = W * 0.66, rw = W * 0.28; txt(g, "SCALED, WEIGHTED ERROR", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Boosted trees", "0.821", BL], ["28-day average", "0.852", ORG], ["Boosted ahead at origins", "5 of 5", GR], ["RMSE, boosted vs average", "2.86 vs 2.79", ink]].forEach(([nm, v, c], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1); txt(g, nm, rx, y, { size: H * 0.021, color: hex(ink, 0.8), weight: 400, alpha: t }); txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.04, color: c, align: "right", alpha: t });
    });
  },
});
