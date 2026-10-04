/* Where Does Walmart's Revenue Actually Come From? Monthly revenue of 10 Walmart stores by category, February 2011 to April 2016 (complete months), the real
   series from the case study: foods (blue) from $1.16M to $2.31M a month, household (orange), hobbies (green). Right: $191.6M in total; foods are 58% of it; Saturday
   runs 21% above an average day; foods sell 33% more on a SNAP day in Wisconsin; the top 10% of items earn 43% of revenue. */
const S_ = {"foods": [1.162, 1.212, 1.167, 1.145, 1.223, 1.344, 1.36, 1.335, 1.46, 1.33, 1.481, 1.49, 1.514, 1.663, 1.593, 1.705, 1.78, 1.776, 1.778, 1.697, 1.585, 1.546, 1.696, 1.681, 1.611, 1.786, 1.599, 1.677, 1.764, 1.812, 1.836, 1.8, 1.816, 1.666, 1.715, 1.718, 1.646, 1.868, 1.857, 1.867, 1.833, 1.878, 1.914, 1.844, 1.958, 1.874, 1.846, 1.914, 1.764, 1.912, 1.875, 1.95, 1.883, 2.009, 2.032, 1.973, 2.163, 1.936, 1.984, 2.17, 2.143, 2.258, 2.31], "household": [0.552, 0.608, 0.609, 0.598, 0.598, 0.646, 0.642, 0.649, 0.683, 0.621, 0.618, 0.649, 0.714, 0.752, 0.697, 0.701, 0.787, 0.796, 0.874, 0.901, 0.85, 0.812, 0.824, 0.787, 0.84, 0.933, 0.873, 0.908, 0.91, 0.929, 0.985, 0.941, 0.937, 0.88, 0.845, 0.841, 0.883, 0.993, 0.914, 0.932, 0.937, 0.98, 1.029, 0.961, 0.997, 0.944, 0.897, 0.943, 0.961, 1.098, 1.054, 1.133, 1.081, 1.162, 1.233, 1.119, 1.157, 1.089, 1.095, 1.132, 1.174, 1.202, 1.234], "hobbies": [0.211, 0.233, 0.251, 0.26, 0.25, 0.262, 0.239, 0.227, 0.241, 0.213, 0.241, 0.236, 0.243, 0.271, 0.263, 0.272, 0.29, 0.316, 0.311, 0.308, 0.313, 0.304, 0.339, 0.337, 0.347, 0.382, 0.359, 0.367, 0.381, 0.38, 0.389, 0.358, 0.375, 0.356, 0.365, 0.368, 0.325, 0.361, 0.35, 0.362, 0.37, 0.371, 0.382, 0.369, 0.398, 0.389, 0.406, 0.432, 0.438, 0.505, 0.487, 0.517, 0.48, 0.5, 0.51, 0.477, 0.521, 0.502, 0.527, 0.515, 0.505, 0.517, 0.523]};
scene({
  slug: "m5-sales-sql", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, path, dot }) {
    const ink = "#f3efec", BL = "#4a95f0", ORG = "#ff8a3d", GRN = "#3aa876";
    const x0 = W * 0.07, x1 = W * 0.58, y0 = H * 0.2, y1 = H * 0.8, N = S_.foods.length;
    const X = (i) => x0 + i / (N - 1) * (x1 - x0), Y = (v) => y1 - v / 2.6 * (y1 - y0);
    txt(g, "REVENUE A MONTH, $ MILLIONS", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [0, 1, 2].forEach((v) => { line(g, x0, Y(v), x1, Y(v), hex(ink, 0.08), 1); txt(g, String(v), x0 - H * 0.015, Y(v) + H * 0.008, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    [["2012", 11], ["2013", 23], ["2014", 35], ["2015", 47]].forEach(([s, i]) => txt(g, s, X(i), y1 + H * 0.05, { size: H * 0.021, color: hex(ink, 0.45), align: "center" }));
    const k = ease.inOut(seg(u, 0.05, 0.62));
    [["foods", BL], ["household", ORG], ["hobbies", GRN]].forEach(([c, col]) => path(g, S_[c].map((v, i) => [X(i), Y(v)]), k, col, 2.6, hex(col, 0.5)));
    const rx = W * 0.67, rw = W * 0.28, m = ease.inOut(seg(u, 0.1, 0.66));
    txt(g, "REVENUE, 5.3 YEARS, 10 STORES", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, "$" + (191.6 * m).toFixed(1) + "M", rx, H * 0.29, { size: H * 0.13, color: "#fff", spacing: -3 });
    txt(g, "foods 58%, household 30%, hobbies 12%", rx, H * 0.345, { size: H * 0.025, color: hex(ink, 0.7), weight: 400, alpha: seg(m, 0.3, 0.6) });
    [["Saturday vs an average day", "+21%", BL], ["Foods on a SNAP day, Wisconsin", "+33%", GRN], ["Revenue from the top 10% of items", "43%", ink]].forEach(([n, v, c], i) => {
      const y = H * 0.54 + i * H * 0.14, t = ease.out5(seg(u, 0.64 + i * 0.07, 0.82 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12), 1);
      txt(g, n, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.038, color: c, align: "right", alpha: t });
    });
  },
});
