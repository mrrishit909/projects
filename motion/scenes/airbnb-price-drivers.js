/* What Makes an Austin Airbnb Expensive? Out-of-sample R squared (folds made of hosts) as groups of columns are added to a model of the log price: size 0.51, type 0.52, place 0.58, host and reviews 0.61, amenities 0.63,
   then boosted trees 0.67. Right: size alone explains 0.51; the best model still misses by a median 21%; folds made of listings instead of hosts would have flattered it to 0.77. */
scene({
  slug: "airbnb-price-drivers", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0";
    const V = [0.51, 0.52, 0.58, 0.61, 0.63, 0.67], NM = [["size"], ["+ type"], ["+ place"], ["+ host,", "reviews"], ["+ amenities"], ["boosted", "trees"]];
    const x0 = W * 0.09, x1 = W * 0.57, y0 = H * 0.2, y1 = H * 0.76, bw = (x1 - x0) / V.length, Y = (v) => y1 - v / 0.8 * (y1 - y0);
    txt(g, "OUT-OF-SAMPLE R² AS COLUMNS ARE ADDED", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [0, 0.2, 0.4, 0.6, 0.8].forEach((v) => { line(g, x0, Y(v), x1, Y(v), hex(ink, v ? 0.08 : 0.3), 1); txt(g, v.toFixed(1), x0 - H * 0.015, Y(v) + H * 0.008, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    V.forEach((v, i) => {
      const t = ease.out5(seg(u, 0.06 + i * 0.075, 0.2 + i * 0.075)), h = (y1 - Y(v)) * t, bx = x0 + bw * i + bw * 0.14;
      rr(g, bx, y1 - h, bw * 0.72, Math.max(h, 0.1), 4); g.fillStyle = i === 5 ? ORG : BL; g.fill();
      txt(g, v.toFixed(2), bx + bw * 0.36, y1 - h - H * 0.016, { size: H * 0.024, color: ink, align: "center", alpha: t });
      NM[i].forEach((s, j) => txt(g, s, bx + bw * 0.36, y1 + H * 0.055 + j * H * 0.03, { size: H * 0.021, color: hex(ink, 0.55), align: "center" }));
    });
    const rx = W * 0.65, rw = W * 0.28; let cur = 0;
    V.forEach((v, i) => { const t = ease.out5(seg(u, 0.06 + i * 0.075, 0.2 + i * 0.075)); if (t > 0) cur = i === 0 ? v * t : lerp(V[i - 1], v, t); });
    txt(g, "R² OF THE LOG PRICE", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, cur.toFixed(2), rx, H * 0.29, { size: H * 0.12, color: u >= 0.575 ? ORG : BL, spacing: -3 });
    txt(g, u < 0.135 ? "size alone" : u >= 0.575 ? "boosted trees, the best model" : "columns added one group at a time", rx, H * 0.345, { size: H * 0.026, color: hex(ink, 0.7), weight: 400 });
    [["Size alone explains", "0.51", BL], ["Median miss of the best model", "21%", ORG], ["If folds were listings, not hosts", "0.77", ink]].forEach(([nm, v, c], i) => {
      const y = H * 0.54 + i * H * 0.14, t = ease.out5(seg(u, 0.64 + i * 0.07, 0.82 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.038, color: c, align: "right", alpha: t });
    });
  },
});
