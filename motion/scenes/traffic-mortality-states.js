/* What Makes Some States Deadlier to Drive In? FARS 2024 deaths per 100 million vehicle-miles (FHWA VM-2) for the 50 states and DC against the rural share of each state's miles: the points scatter (9% of the spread is explained by the rural-urban mix).
   Right: how much of the 2024 spread between states each guide predicts (R-squared): last year's rate 0.82, a regression fitted on 2023 0.15, the rural-urban mix of miles 0.08, the national average 0.0. */
const PTS = [[0.0, 1.328], [0.0456, 0.585], [0.0675, 0.843], [0.103, 1.002], [0.1041, 0.679], [0.1643, 1.258], [0.1785, 0.958], [0.1876, 1.189], [0.1982, 1.013], [0.2051, 1.467], [0.2115, 0.911], [0.2391, 1.129], [0.2628, 1.744], [0.2681, 1.349], [0.2737, 1.268], [0.2779, 1.206], [0.2821, 0.766], [0.2933, 1.251], [0.2963, 0.997], [0.3014, 1.036], [0.3052, 1.148], [0.3115, 1.102], [0.3666, 1.184], [0.3757, 1.517], [0.3762, 1.673], [0.3773, 1.365], [0.3854, 0.943], [0.3894, 1.236], [0.3977, 0.96], [0.4005, 0.806], [0.4005, 1.32], [0.4091, 1.439], [0.4277, 1.272], [0.4481, 1.167], [0.4666, 1.532], [0.4682, 1.07], [0.4916, 1.388], [0.52, 0.86], [0.5238, 1.438], [0.5323, 1.146], [0.5679, 1.187], [0.5689, 1.487], [0.587, 1.053], [0.5871, 1.812], [0.5923, 1.428], [0.6608, 1.167], [0.6765, 0.897], [0.6961, 1.397], [0.7068, 1.486], [0.7253, 0.819], [0.7337, 1.101]], GUIDES = [["last year's rate", 0.82], ["regression on 2023", 0.15], ["rural-urban mix of miles", 0.08], ["national average only", 0.0]];
scene({
  slug: "traffic-mortality-states", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#46c28a";
    const x0 = W * 0.09, x1 = W * 0.52, y0 = H * 0.2, y1 = H * 0.78, X = (s) => x0 + (x1 - x0) * s / 0.8, Y = (r) => y1 - (y1 - y0) * (r - 0.4) / 1.6;
    txt(g, "DEATHS PER 100 MILLION MILES AGAINST RURAL MILES", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [0.4, 0.8, 1.2, 1.6, 2.0].forEach((v) => { line(g, x0 - H * 0.01, Y(v), x1, Y(v), hex(ink, 0.07), 1); txt(g, v.toFixed(1), x0 - H * 0.02, Y(v) + H * 0.007, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    [0, 0.2, 0.4, 0.6, 0.8].forEach((s) => txt(g, Math.round(s * 100) + "%", X(s), y1 + H * 0.05, { size: H * 0.02, color: hex(ink, 0.4), align: "center" }));
    txt(g, "share of the state's miles on rural roads", (x0 + x1) / 2, y1 + H * 0.1, { size: H * 0.02, color: hex(ink, 0.4), align: "center" });
    PTS.forEach((p, i) => { const t = ease.out5(seg(u, 0.04 + i * 0.006, 0.16 + i * 0.006)); dot(g, X(p[0]), Y(p[1]), H * 0.0095 * t, BL); });
    const tl = ease.out5(seg(u, 0.42, 0.55)); line(g, X(0), Y(1.05), X(0.75), Y(1.32), hex(ORG, tl), 2.5);
    txt(g, "the line explains 9%", X(0.36), Y(0.5), { size: H * 0.022, color: ORG, alpha: tl });
    const rx = W * 0.62, rw = W * 0.31; txt(g, "SHARE OF THE 2024 SPREAD PREDICTED", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    GUIDES.forEach(([nm, v], i) => {
      const y = H * 0.27 + i * H * 0.17, t = ease.out5(seg(u, 0.55 + i * 0.07, 0.75 + i * 0.07)), c = i === 0 ? GR : i === 1 ? BL : i === 2 ? ORG : "#8a8f98";
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t }); if (t > 0.01 && v > 0) { rr(g, rx, y + H * 0.02, rw * v * t, H * 0.045, 4); g.fillStyle = c; g.fill(); }
      txt(g, v.toFixed(2).replace(/^0/, ""), rx + Math.max(rw * v * t, 0) + H * 0.014, y + H * 0.055, { size: H * 0.034, color: ink, alpha: t });
    });
  },
});
