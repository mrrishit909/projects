/* How Far Can Simple Methods Read Reviews? Amazon Digital_Music reviews, random 80/20 split. Left: for four models, accuracy (blue) and the share of negative reviews caught (orange): always positive 93% / 0%, VADER with negation 93% / 47%, naive Bayes 95% / 46%, TF-IDF + logistic 97% / 65%.
   Right: "always positive" is 93% right, the logistic model 97%, it catches 65% of the negative reviews, and 10% of the random test reviews have an exact twin in training. */
const NAMES = ["always positive", "VADER + negation", "naive Bayes", "TF-IDF + logistic"], ACC = [0.9263, 0.9309, 0.951, 0.967], REC = [0.0, 0.4683, 0.4567, 0.6523];
scene({
  slug: "review-sentiment", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#46c28a";
    const x0 = W * 0.22, x1 = W * 0.54, y0 = H * 0.25, rowH = H * 0.16, bh = H * 0.045;
    txt(g, "ACCURACY AND NEGATIVE REVIEWS CAUGHT", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [0, 0.5, 1].forEach((v) => { const x = x0 + (x1 - x0) * v; line(g, x, y0 - H * 0.04, x, y0 + rowH * 4 - H * 0.04, hex(ink, 0.08), 1); txt(g, Math.round(100 * v) + "%", x, y0 + rowH * 4 - H * 0.005, { size: H * 0.02, color: hex(ink, 0.4), align: "center" }); });
    NAMES.forEach((nm, i) => {
      const y = y0 + i * rowH, t = ease.out5(seg(u, 0.05 + i * 0.07, 0.4 + i * 0.07)), t2 = ease.out5(seg(u, 0.12 + i * 0.07, 0.48 + i * 0.07));
      txt(g, nm, x0 - H * 0.025, y + H * 0.045, { size: H * 0.022, color: hex(ink, 0.8), align: "right" });
      rr(g, x0, y, Math.max((x1 - x0) * ACC[i] * t, 0.1), bh, H * 0.004); g.fillStyle = BL; g.fill();
      rr(g, x0, y + bh * 1.25, Math.max((x1 - x0) * REC[i] * t2, 0.1), bh, H * 0.004); g.fillStyle = ORG; g.fill();
      txt(g, (100 * ACC[i] * t).toFixed(0) + "%", x0 + (x1 - x0) * ACC[i] * t + H * 0.012, y + bh * 0.8, { size: H * 0.019, color: BL, alpha: t });
      txt(g, (100 * REC[i] * t2).toFixed(0) + "%", x0 + (x1 - x0) * REC[i] * t2 + H * 0.012, y + bh * 2.05, { size: H * 0.019, color: ORG, alpha: t2 });
    });
    const rx = W * 0.64, rw = W * 0.29; txt(g, "WHAT THE SCORE HIDES", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["'Always positive' is right", "93%", ink], ["TF-IDF + logistic is right", "97%", BL], ["Negative reviews it catches", "65%", ORG], ["Test reviews with a twin in train", "10%", GR]].forEach(([nm, v, c], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1); txt(g, nm, rx, y, { size: H * 0.021, color: hex(ink, 0.8), weight: 400, alpha: t }); txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.04, color: c, align: "right", alpha: t });
    });
  },
});
