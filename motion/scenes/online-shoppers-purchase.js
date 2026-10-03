/* Who Buys Online? Purchase rates in 12,330 shopping sessions: new visitors 24.9% against returning 13.9%, and sessions with a positive PageValues 56.3% against 3.9% when it is zero.
   Right: the gradient-boosting model's AUC in cross-validation, 0.93 with PageValues and 0.78 without it; its top tenth of sessions captures 50.3% of buyers, then 26.8%;
   on a time split (train February to September, test October to December) it scores 0.66 without PageValues. */
scene({
  slug: "online-shoppers-purchase", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#8f918d";
    const x0 = W * 0.27, x1 = W * 0.58, mx = 60;
    txt(g, "SHARE OF SESSIONS ENDING IN A PURCHASE", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["New visitors", 24.9, ORG], ["Returning visitors", 13.9, BL], ["PageValues above 0", 56.3, ORG], ["PageValues = 0", 3.9, BL]].forEach(([n, v, c], i) => {
      const y = H * 0.24 + i * H * 0.15 + (i >= 2 ? H * 0.05 : 0), t = ease.out3(seg(u, 0.06 + i * 0.08, 0.26 + i * 0.08));
      txt(g, n, x0 - W * 0.012, y + H * 0.045, { size: H * 0.027, color: hex(ink, 0.85), weight: 400, align: "right" });
      g.fillStyle = hex(ink, 0.07); rr(g, x0, y, x1 - x0, H * 0.07, 7); g.fill();
      g.fillStyle = c; rr(g, x0, y, Math.max(0.001, (x1 - x0) * v / mx * t), H * 0.07, 7); g.fill();
      txt(g, (v * t).toFixed(1) + "%", x0 + (x1 - x0) * v / mx * t + W * 0.01, y + H * 0.047, { size: H * 0.032, color: "#fff", alpha: Math.min(1, t * 2) });
    });
    const rx = W * 0.67, rw = W * 0.28, k = ease.inOut(seg(u, 0.5, 0.76));
    txt(g, "MODEL SCORE (AUC)", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, (0.93 + (0.78 - 0.93) * k).toFixed(2), rx, H * 0.29, { size: H * 0.13, color: k > 0.5 ? ORG : "#fff", spacing: -3 });
    txt(g, k < 0.5 ? "with PageValues" : "without PageValues", rx, H * 0.345, { size: H * 0.026, color: hex(ink, 0.7), weight: 400 });
    [["Buyers captured by the top tenth", "50.3% → 26.8%", BL], ["Time-split score without it", "0.66", ORG], ["Sessions in the data", "12,330", ink]].forEach(([n, v, c], i) => {
      const y = H * 0.54 + i * H * 0.14, t = ease.out5(seg(u, 0.64 + i * 0.07, 0.82 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12), 1);
      txt(g, n, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.038, color: c, align: "right", alpha: t });
    });
  },
});
