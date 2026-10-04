/* How accurately can a used car's price be predicted? Median asking price by age ($ thousand) for the 8 most listed brands, Craigslist US, April to May 2021 (Toyota highlighted: $31,790 at one year, $9,800 at ten).
   Right: 426,880 listings become 188,938 cars; a median 15% miss; R-squared 0.84 on random listings but 0.79 with folds by car and one listing per car; the 90% range runs 40% below to 66% above the guess. */
const CURVES = {"ford": [45.5, 41.0, 36.0, 30.0, 26.0, 23.0, 21.6, 14.9, 13.8, 11.9, 11.0, 9.0, 8.0, 8.9, 7.0, 7.0, 6.5, 6.5, 5.5, 5.9, 5.4], "chevrolet": [38.6, 38.0, 33.0, 25.0, 24.0, 19.0, 20.0, 13.5, 12.3, 10.0, 10.0, 8.0, 7.5, 8.5, 8.6, 6.0, 6.0, 6.0, 5.9, 5.5, 5.0], "toyota": [41.9, 31.8, 30.6, 24.9, 22.0, 20.4, 17.0, 15.0, 13.9, 11.0, 9.8, 8.0, 7.0, 8.0, 6.8, 6.5, 5.5, 5.7, 5.0, 5.0, 5.0], "honda": [null, 27.0, 25.0, 22.8, 19.6, 17.5, 15.0, 14.0, 12.0, 10.0, 9.0, 7.8, 6.8, 6.5, 5.8, 5.0, 4.5, 3.9, 3.7, 3.2, 3.0], "nissan": [null, 23.5, 20.8, 19.0, 17.0, 14.0, 10.9, 10.0, 8.6, 7.5, 7.0, 6.9, 6.0, 5.5, 5.0, 5.0, 4.6, 4.2, 3.8, 3.3, 3.7], "jeep": [51.5, 40.0, 27.0, 29.0, 25.0, 17.8, 19.5, 17.0, 21.5, 14.0, 12.8, 10.2, 9.3, 10.0, 6.9, 6.0, 6.0, 5.0, 5.4, 4.8, 5.9], "gmc": [66.5, 49.6, 44.4, 35.9, 32.0, 32.0, 29.0, 21.7, 18.8, 14.0, 14.0, 10.0, 11.0, 10.9, 11.0, 8.0, 8.0, 6.5, 6.0, 5.0, 6.5], "ram": [66.0, 46.6, 41.2, 37.5, 33.0, 30.7, 29.5, 25.0, 22.9, 24.9, 18.5, 16.0, 14.0, 15.0, 15.0, 16.0, 11.0, 8.9, 7.7, 6.5, 7.0]}, HL = "toyota";
scene({
  slug: "car-prices", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#46c28a";
    const x0 = W * 0.09, x1 = W * 0.54, y0 = H * 0.2, y1 = H * 0.78, X = (a) => x0 + (x1 - x0) * a / 20, Y = (v) => y1 - (y1 - y0) * v / 70;
    txt(g, "MEDIAN ASKING PRICE BY AGE, $ THOUSAND", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [0, 20, 40, 60].forEach((v) => { line(g, x0 - H * 0.01, Y(v), x1, Y(v), hex(ink, v === 0 ? 0.25 : 0.07), 1); txt(g, String(v), x0 - H * 0.02, Y(v) + H * 0.007, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    [0, 5, 10, 15, 20].forEach((a) => txt(g, String(a), X(a), y1 + H * 0.05, { size: H * 0.02, color: hex(ink, 0.4), align: "center" }));
    txt(g, "years of age", (x0 + x1) / 2, y1 + H * 0.1, { size: H * 0.019, color: hex(ink, 0.4), align: "center" });
    const p = ease.out5(seg(u, 0.05, 0.6)) * 20, k = Math.floor(p);
    Object.entries(CURVES).forEach(([b, v]) => {
      const hi = b === HL; g.beginPath(); let started = false;
      for (let a = 0; a <= k; a++) { if (v[a] === null) continue; if (!started) { g.moveTo(X(a), Y(v[a])); started = true; } else g.lineTo(X(a), Y(v[a])); }
      g.strokeStyle = hi ? BL : hex(ink, 0.28); g.lineWidth = H * (hi ? 0.006 : 0.003); g.lineJoin = "round"; g.stroke();
    });
    const tl = ease.out5(seg(u, 0.55, 0.7)), vt = CURVES[HL]; dot(g, X(10), Y(vt[10]), H * 0.011 * tl, ORG); txt(g, "Toyota at 10 years: $" + vt[10].toFixed(1) + "k", X(10) + H * 0.03, Y(vt[10]) - H * 0.03, { size: H * 0.021, color: ORG, align: "left", alpha: tl });
    const rx = W * 0.64, rw = W * 0.29; txt(g, "PREDICTING THE PRICE", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Listings, then distinct cars", "427k to 189k", ink], ["Typical miss, boosting", "15%", BL], ["R\u00b2 random listings, by car", "0.84, 0.79", ORG], ["90% range around the guess", "-40% to +66%", GR]].forEach(([nm, v, c], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1); txt(g, nm, rx, y, { size: H * 0.021, color: hex(ink, 0.8), weight: 400, alpha: t }); txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.04, color: c, align: "right", alpha: t });
    });
  },
});
