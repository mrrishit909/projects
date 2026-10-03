/* Who Gets a Credit Card? Share of 690 applications approved: 78.7% when column A9 is t, 7.0% when it is f, 44.5% overall.
   Right: cross-validated accuracy of the one-line rule "approve if A9 = t", 85.5%, against the best of five models, a random forest, 87.4%; always refusing scores 55.5%;
   the forest's gain over the rule is +1.9 points, with a 95% interval of -0.2 to +3.9. */
scene({
  slug: "credit-approvals", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#8f918d";
    const x0 = W * 0.2, x1 = W * 0.58, mx = 100;
    txt(g, "SHARE OF APPLICATIONS APPROVED", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["A9 = t", 78.7, ORG], ["A9 = f", 7.0, BL], ["All 690", 44.5, GR]].forEach(([n, v, c], i) => {
      const y = H * 0.27 + i * H * 0.22, t = ease.out3(seg(u, 0.06 + i * 0.1, 0.28 + i * 0.1));
      txt(g, n, x0 - W * 0.012, y + H * 0.05, { size: H * 0.03, color: hex(ink, 0.85), weight: 400, align: "right" });
      g.fillStyle = hex(ink, 0.07); rr(g, x0, y, x1 - x0, H * 0.08, 7); g.fill();
      g.fillStyle = c; rr(g, x0, y, Math.max(0.001, (x1 - x0) * v / mx * t), H * 0.08, 7); g.fill();
      txt(g, (v * t).toFixed(1) + "%", x0 + (x1 - x0) * v / mx * t + W * 0.01, y + H * 0.054, { size: H * 0.034, color: "#fff", alpha: Math.min(1, t * 2) });
    });
    const rx = W * 0.67, rw = W * 0.28, k = ease.inOut(seg(u, 0.5, 0.76));
    txt(g, "CROSS-VALIDATED ACCURACY", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, (85.5 + (87.4 - 85.5) * k).toFixed(1) + "%", rx, H * 0.29, { size: H * 0.11, color: k > 0.5 ? BL : ORG, spacing: -3 });
    txt(g, k < 0.5 ? "approve if A9 = t" : "best of five models", rx, H * 0.345, { size: H * 0.026, color: hex(ink, 0.7), weight: 400 });
    [["Always refusing", "55.5%", GR], ["Gain over the rule", "+1.9 pts", BL], ["95% interval of the gain", "−0.2 to +3.9", ORG]].forEach(([n, v, c], i) => {
      const y = H * 0.54 + i * H * 0.14, t = ease.out5(seg(u, 0.64 + i * 0.07, 0.82 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12), 1);
      txt(g, n, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.038, color: c, align: "right", alpha: t });
    });
  },
});
