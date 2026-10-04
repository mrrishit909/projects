/* Can a Bar's Liquor Sales Next Month Be Predicted? Left: the typical error (WAPE, log scale) of "same as last month" (gray) and of a random forest trained without the COVID months (orange), by month, 2019 to 2025; last month's error peaks at 571% in April 2020.
   Right: 2022 to 2025 the forest's error is 18.3% against 20.7% for last month (12% lower), only 1% lower if it trained through COVID; 0.21% of forecasts are for places that never file again. */
const NAIVE = [27.0, 15.1, 23.3, 24.7, 17.2, 16.7, 15.1, 15.0, 20.2, 17.0, 17.8, 20.3, 24.9, 18.6, 89.2, 571.0, 72.4, 39.0, 55.3, 26.0, 21.8, 22.5, 29.3, 20.5, 21.1, 22.9, 38.0, 16.1, 16.9, 19.6, 15.0, 21.9, 16.3, 19.3, 23.8, 19.6, 28.7, 17.4, 24.3, 18.1, 16.3, 19.4, 16.5, 18.6, 15.5, 16.6, 24.7, 24.0, 27.7, 14.8, 21.2, 18.8, 15.6, 17.1, 15.7, 18.4, 18.0, 18.3, 20.7, 24.0, 39.4, 20.9, 21.5, 22.3, 17.9, 20.4, 20.8, 17.9, 19.9, 21.4, 20.7, 22.6, 33.8, 18.3, 23.5, 22.8, 19.4, 24.8, 16.5, 16.8, 22.9, 21.0, 20.3, 22.2], FOREST = [15.6, 14.7, 19.7, 15.7, 16.0, 14.5, 13.4, 15.2, 17.0, 17.2, 16.8, 17.2, 16.0, 19.3, 91.0, 559.2, 78.5, 47.6, 56.0, 30.4, 26.5, 27.0, 24.0, 24.2, 26.1, 23.2, 43.8, 44.8, 33.8, 25.7, 27.9, 20.7, 22.3, 26.9, 20.7, 25.1, 20.8, 21.5, 24.7, 22.6, 16.8, 17.0, 17.3, 16.4, 18.2, 17.7, 18.9, 21.7, 17.9, 15.4, 17.8, 16.3, 15.2, 16.1, 16.2, 16.1, 17.4, 17.9, 17.3, 20.4, 22.2, 19.1, 18.8, 17.9, 17.0, 16.6, 19.1, 17.7, 17.9, 20.0, 18.4, 19.7, 19.0, 17.1, 19.5, 17.5, 19.1, 17.1, 16.5, 17.0, 18.3, 19.6, 16.3, 18.7], PEAK = 15;
scene({
  slug: "texas-bar-sales", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#46c28a", GY = "#a8abb3";
    const x0 = W * 0.09, x1 = W * 0.54, y0 = H * 0.2, y1 = H * 0.78, N = NAIVE.length, X = (i) => x0 + (x1 - x0) * i / (N - 1), Y = (v) => y1 - (y1 - y0) * (Math.log10(Math.max(v, 10)) - 1) / 2.0;
    txt(g, "ERROR OF THE NEXT-MONTH FORECAST, LOG SCALE", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    g.fillStyle = hex(ORG, 0.08); g.fillRect(X(14), y0, X(35) - X(14), y1 - y0);
    [10, 30, 100, 300, 1000].forEach((v) => { line(g, x0 - H * 0.01, Y(v), x1, Y(v), hex(ink, v === 100 ? 0.25 : 0.07), 1); txt(g, v + "%", x0 - H * 0.02, Y(v) + H * 0.007, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    [2019, 2021, 2023, 2025].forEach((y) => txt(g, String(y), X((y - 2019) * 12), y1 + H * 0.05, { size: H * 0.02, color: hex(ink, 0.4), align: "center" }));
    const p = ease.out5(seg(u, 0.05, 0.6)) * (N - 1), k = Math.floor(p);
    [[NAIVE, GY, 0.004], [FOREST, ORG, 0.005]].forEach(([S_, col, w]) => {
      g.beginPath(); g.moveTo(X(0), Y(S_[0])); for (let i = 1; i <= k; i++) g.lineTo(X(i), Y(S_[i])); g.strokeStyle = col; g.lineWidth = H * w; g.lineJoin = "round"; g.stroke();
    });
    const tl = ease.out5(seg(u, 0.55, 0.7)); dot(g, X(PEAK), Y(NAIVE[PEAK]), H * 0.011 * tl, GY); txt(g, "April 2020: " + NAIVE[PEAK].toFixed(0) + "%", X(PEAK) + H * 0.03, Y(NAIVE[PEAK]) + H * 0.01, { size: H * 0.021, color: GY, align: "left", alpha: tl });
    txt(g, "last month", x1, Y(NAIVE[N - 1]) - H * 0.07, { size: H * 0.02, color: GY, align: "right", alpha: tl }); txt(g, "forest, no COVID in training", x1, Y(FOREST[N - 1]) + H * 0.07, { size: H * 0.02, color: ORG, align: "right", alpha: tl });
    const rx = W * 0.64, rw = W * 0.29; txt(g, "2022 TO 2025", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Last month's typical error", "20.7%", GY], ["Forest, COVID left out", "18.3%", ORG], ["Forest, trained through COVID", "20.5%", ink], ["Forecasts for places that close", "0.21%", GR]].forEach(([nm, v, c], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1); txt(g, nm, rx, y, { size: H * 0.021, color: hex(ink, 0.8), weight: 400, alpha: t }); txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.04, color: c, align: "right", alpha: t });
    });
  },
});
