/* Can Four Measurements Name an Iris? Each dot is one of the 150 flowers in the case study (real data): its petal length, by species. Setosa's longest petal is 1.9 cm and the
   shortest versicolor petal is 3.0 cm; versicolor and virginica overlap between 4.5 and 5.1 cm, where 37 of the 100 flowers lie. Right: cross-validated accuracy of the petal-width rule,
   95.2%, against Fisher's discriminant (LDA) on all four measurements, 98.0%; its gain is 2.8 points with a 95% interval of -0.5 to +6.1; 7 of the 150 flowers are wrong most often. */
const P = [[1.4,0],[1.4,0],[1.3,0],[1.5,0],[1.4,0],[1.7,0],[1.4,0],[1.5,0],[1.4,0],[1.5,0],[1.5,0],[1.6,0],[1.4,0],[1.1,0],[1.2,0],[1.5,0],[1.3,0],[1.4,0],[1.7,0],[1.5,0],[1.7,0],[1.5,0],[1.0,0],[1.7,0],[1.9,0],[1.6,0],[1.6,0],[1.5,0],[1.4,0],[1.6,0],[1.6,0],[1.5,0],[1.5,0],[1.4,0],[1.5,0],[1.2,0],[1.3,0],[1.4,0],[1.3,0],[1.5,0],[1.3,0],[1.3,0],[1.3,0],[1.6,0],[1.9,0],[1.4,0],[1.6,0],[1.4,0],[1.5,0],[1.4,0],[4.7,1],[4.5,1],[4.9,1],[4.0,1],[4.6,1],[4.5,1],[4.7,1],[3.3,1],[4.6,1],[3.9,1],[3.5,1],[4.2,1],[4.0,1],[4.7,1],[3.6,1],[4.4,1],[4.5,1],[4.1,1],[4.5,1],[3.9,1],[4.8,1],[4.0,1],[4.9,1],[4.7,1],[4.3,1],[4.4,1],[4.8,1],[5.0,1],[4.5,1],[3.5,1],[3.8,1],[3.7,1],[3.9,1],[5.1,1],[4.5,1],[4.5,1],[4.7,1],[4.4,1],[4.1,1],[4.0,1],[4.4,1],[4.6,1],[4.0,1],[3.3,1],[4.2,1],[4.2,1],[4.2,1],[4.3,1],[3.0,1],[4.1,1],[6.0,2],[5.1,2],[5.9,2],[5.6,2],[5.8,2],[6.6,2],[4.5,2],[6.3,2],[5.8,2],[6.1,2],[5.1,2],[5.3,2],[5.5,2],[5.0,2],[5.1,2],[5.3,2],[5.5,2],[6.7,2],[6.9,2],[5.0,2],[5.7,2],[4.9,2],[6.7,2],[4.9,2],[5.7,2],[6.0,2],[4.8,2],[4.9,2],[5.6,2],[5.8,2],[6.1,2],[6.4,2],[5.6,2],[5.1,2],[5.6,2],[6.1,2],[5.6,2],[5.5,2],[4.8,2],[5.4,2],[5.6,2],[5.1,2],[5.1,2],[5.9,2],[5.7,2],[5.2,2],[5.0,2],[5.2,2],[5.4,2],[5.1,2]];
scene({
  slug: "iris-fisher", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, dot, rr }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GRN = "#3fbf8a", COL = [BL, ORG, GRN];
    const x0 = W * 0.19, x1 = W * 0.58, X = (v) => x0 + (v - 1) / 6 * (x1 - x0), Y = (c) => H * (0.27 + c * 0.23);
    txt(g, "PETAL LENGTH OF 150 FLOWERS (CM)", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [1, 3, 5, 7].forEach((v) => { line(g, X(v), H * 0.18, X(v), H * 0.8, hex(ink, 0.07), 1); txt(g, String(v), X(v), H * 0.86, { size: H * 0.024, color: hex(ink, 0.45), align: "center" }); });
    const b = ease.out3(seg(u, 0.42, 0.56));
    g.fillStyle = hex(ORG, 0.13 * b); g.fillRect(X(4.5), H * 0.38, X(5.1) - X(4.5), H * 0.42);
    txt(g, "37 of 100 flowers", X(4.8), H * 0.345, { size: H * 0.026, color: ORG, align: "center", alpha: b });
    ["setosa", "versicolor", "virginica"].forEach((nm, c) => {
      txt(g, nm, x0 - W * 0.015, Y(c) + H * 0.009, { size: H * 0.028, color: hex(ink, 0.85), weight: 400, align: "right" });
      const pts = P.filter((p) => p[1] === c), n = Math.floor(pts.length * ease.out3(seg(u, 0.04 + c * 0.08, 0.3 + c * 0.08)));
      for (let i = 0; i < n; i++) dot(g, X(pts[i][0]), Y(c) + ((i * 0.6180339887) % 1 - 0.5) * H * 0.13, 4, COL[c]);
    });
    const rx = W * 0.67, rw = W * 0.28, k = ease.inOut(seg(u, 0.5, 0.76));
    txt(g, "CROSS-VALIDATED ACCURACY", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, (95.2 + (98.0 - 95.2) * k).toFixed(1) + "%", rx, H * 0.29, { size: H * 0.11, color: k > 0.5 ? BL : ORG, spacing: -3 });
    txt(g, k < 0.5 ? "petal width alone" : "LDA, all four measurements", rx, H * 0.345, { size: H * 0.026, color: hex(ink, 0.7), weight: 400 });
    [["Gain of LDA over the rule", "+2.8 pts", BL], ["95% interval of the gain", "−0.5 to +6.1", ink], ["Flowers wrong most often", "7 of 150", ORG]].forEach(([n, v, c], i) => {
      const y = H * 0.54 + i * H * 0.14, t = ease.out5(seg(u, 0.64 + i * 0.07, 0.82 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12), 1);
      txt(g, n, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.038, color: c, align: "right", alpha: t });
    });
  },
});
