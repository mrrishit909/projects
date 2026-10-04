/* Did Super Bowl Ad Prices Outrun the Audience? Games II to LVIII (1968 to 2024), 57 games. Left, on a log scale and indexed to 1968 = 100: average viewers (blue, 39.1 to 120.3 million, 3.1x) and the average price of a 30-second ad in 2025 dollars (orange, $0.50M to $7.2M, 14.2x).
   Right: the same ratios, the real price of a thousand viewers ($13 in 1968, $60 in 2024) and the audience's trend from 2010 to 2024 (−0.3% a year, interval -1.2% to 0.6%). */
const VW = [100.0, 106.5, 113.2, 117.7, 144.8, 136.3, 132.2, 143.3, 147.5, 158.6, 201.8, 191.1, 194.9, 174.6, 217.9, 209.0, 198.4, 218.6, 236.6, 222.9, 204.9, 208.6, 188.8, 203.2, 203.5, 232.6, 230.1, 213.2, 240.5, 224.6, 230.1, 214.0, 226.2, 215.6, 221.9, 226.6, 229.6, 220.0, 232.0, 238.2, 249.1, 252.4, 272.2, 283.8, 284.6, 277.8, 286.8, 292.5, 285.9, 284.6, 264.5, 251.7, 259.0, 243.4, 253.5, 291.9, 307.4], PR = [100.0, 95.7, 128.5, 114.3, 131.4, 126.6, 134.0, 126.9, 123.4, 131.6, 158.8, 162.7, 171.9, 193.0, 214.5, 256.3, 226.2, 311.5, 320.3, 337.0, 348.1, 347.5, 342.1, 374.9, 386.6, 375.5, 387.5, 481.7, 441.5, 477.1, 505.5, 613.0, 778.3, 793.0, 780.6, 763.3, 777.9, 784.3, 791.5, 734.2, 800.4, 892.5, 819.5, 836.6, 957.0, 1031.5, 1101.3, 1153.3, 1276.4, 1406.0, 1330.7, 1298.1, 1331.6, 1295.4, 1417.5, 1466.2, 1424.2];
scene({
  slug: "super-bowl-ads", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#8a8f98";
    const x0 = W * 0.09, x1 = W * 0.54, y0 = H * 0.2, y1 = H * 0.78, N = VW.length, X = (i) => x0 + (x1 - x0) * i / (N - 1), Y = (v) => y1 - (y1 - y0) * Math.log(v / 100) / Math.log(1600 / 100);
    txt(g, "AUDIENCE AND REAL AD PRICE, 1968 = 100", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [[100, "100"], [300, "300"], [1000, "1,000"]].forEach(([v, l]) => { line(g, x0 - H * 0.01, Y(v), x1, Y(v), hex(ink, v === 100 ? 0.35 : 0.07), 1); txt(g, l, x0 - H * 0.02, Y(v) + H * 0.007, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    [1970, 1990, 2010].forEach((yr) => txt(g, String(yr), X(yr - 1968), y1 + H * 0.05, { size: H * 0.02, color: hex(ink, 0.4), align: "center" }));
    txt(g, "log scale", (x0 + x1) / 2, y1 + H * 0.1, { size: H * 0.02, color: hex(ink, 0.4), align: "center" });
    const path = (arr, t, col, w) => { const p = t * (N - 1), k = Math.floor(p), fr = p - k; g.beginPath(); g.moveTo(X(0), Y(arr[0])); for (let i = 1; i <= k; i++) g.lineTo(X(i), Y(arr[i])); if (k < N - 1) g.lineTo(X(k) + (X(k + 1) - X(k)) * fr, Y(lerp(arr[k], arr[k + 1], fr))); g.strokeStyle = col; g.lineWidth = w; g.lineJoin = "round"; g.stroke(); };
    const t1 = ease.out5(seg(u, 0.04, 0.32)), t2 = ease.out5(seg(u, 0.3, 0.6)), tl = ease.out5(seg(u, 0.6, 0.72));
    path(VW, t1, BL, H * 0.007); path(PR, t2, ORG, H * 0.007);
    txt(g, "3.1x", x1 + H * 0.015, Y(VW[N - 1]) + H * 0.008, { size: H * 0.03, color: BL, alpha: tl }); txt(g, "14.2x", x1 + H * 0.015, Y(PR[N - 1]) + H * 0.008, { size: H * 0.03, color: ORG, alpha: tl });
    const rx = W * 0.68, rw = W * 0.26; txt(g, "1968 TO 2024", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Audience", "3.1x", BL], ["Real price of an ad", "14.2x", ORG], ["Per 1,000 viewers", "$13 to $60", ORG], ["Audience since 2010, a year", "−0.3%", BL]].forEach(([nm, v, c], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1); txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t }); txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.04, color: c, align: "right", alpha: t });
    });
  },
});
