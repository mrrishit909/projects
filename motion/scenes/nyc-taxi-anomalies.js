/* Can Simple Detectors Find NYC's Unusual Taxi Days? A seasonal z-score on hourly NYC taxi pickups, scored against 48 labelled days of 2023 to August 2026. Left: F1 (blue) and false-alarm days a week (orange) as the z threshold moves from 1 to 14:
   at z = 3 the detector finds 96% of the days but cries wolf 3.0 days a week (F1 0.14); at z = 8, one alarm day a week set on 2022, 0.4 a week and F1 0.44;
   a rolling z that ignores the weekly cycle scores 0.02; the 22 Feb 2026 blizzard has only 4 unlabelled days scoring higher. */
const TH = [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 3.75, 4.0, 4.25, 4.5, 4.75, 5.0, 5.25, 5.5, 5.75, 6.0, 6.25, 6.5, 6.75, 7.0, 7.25, 7.5, 7.75, 8.0, 8.25, 8.5, 8.75, 9.0, 9.25, 9.5, 9.75, 10.0, 10.25, 10.5, 10.75, 11.0, 11.25, 11.5, 11.75, 12.0, 12.25, 12.5, 12.75, 13.0, 13.25, 13.5, 13.75, 14.0], F1 = [0.071, 0.074, 0.079, 0.086, 0.095, 0.106, 0.116, 0.127, 0.14, 0.154, 0.171, 0.181, 0.196, 0.217, 0.239, 0.26, 0.279, 0.296, 0.317, 0.32, 0.331, 0.362, 0.387, 0.388, 0.397, 0.413, 0.421, 0.432, 0.443, 0.446, 0.444, 0.475, 0.482, 0.49, 0.485, 0.493, 0.514, 0.515, 0.506, 0.515, 0.505, 0.515, 0.505, 0.5, 0.5, 0.467, 0.472, 0.472, 0.455, 0.442, 0.442, 0.452, 0.458], FA = [6.67, 6.4, 5.99, 5.48, 4.89, 4.31, 3.82, 3.45, 3.02, 2.63, 2.32, 2.05, 1.81, 1.59, 1.4, 1.21, 1.1, 0.98, 0.85, 0.78, 0.72, 0.62, 0.55, 0.5, 0.48, 0.44, 0.41, 0.39, 0.37, 0.32, 0.31, 0.26, 0.25, 0.24, 0.23, 0.22, 0.19, 0.18, 0.17, 0.16, 0.16, 0.15, 0.14, 0.13, 0.12, 0.12, 0.1, 0.1, 0.1, 0.1, 0.1, 0.09, 0.08], I3 = 8, I8 = 28;
scene({
  slug: "nyc-taxi-anomalies", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#46c28a";
    const x0 = W * 0.09, x1 = W * 0.54, y0 = H * 0.2, y1 = H * 0.78, N = TH.length, X = (i) => x0 + (x1 - x0) * i / (N - 1), YF = (v) => y1 - (y1 - y0) * v / 0.6, YA = (v) => y1 - (y1 - y0) * v / 6.5;
    txt(g, "SEASONAL Z-SCORE: THRESHOLD VS RESULT", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [0, 0.2, 0.4, 0.6].forEach((v) => { line(g, x0 - H * 0.01, YF(v), x1, YF(v), hex(ink, 0.07), 1); txt(g, v.toFixed(1), x0 - H * 0.02, YF(v) + H * 0.007, { size: H * 0.02, color: hex(BL, 0.7), align: "right" }); });
    [2, 4, 6].forEach((v) => txt(g, String(v), x1 + H * 0.02, YA(v) + H * 0.007, { size: H * 0.02, color: hex(ORG, 0.7), align: "left" }));
    [1, 3, 5, 8, 11, 14].forEach((z) => txt(g, "z" + z, X(TH.indexOf(z)), y1 + H * 0.05, { size: H * 0.02, color: hex(ink, 0.4), align: "center" }));
    const p = ease.out5(seg(u, 0.05, 0.6)) * (N - 1), k = Math.floor(p);
    [[F1, YF, BL], [FA, YA, ORG]].forEach(([A, Y, c]) => { g.beginPath(); g.moveTo(X(0), Y(A[0])); for (let i = 1; i <= k; i++) g.lineTo(X(i), Y(A[i])); g.strokeStyle = c; g.lineWidth = H * 0.005; g.lineJoin = "round"; g.stroke(); });
    const t3 = ease.out5(seg(u, 0.4, 0.55)), t8 = ease.out5(seg(u, 0.6, 0.75));
    line(g, X(I3), y0, X(I3), y1, hex(ink, 0.35 * t3), 1); dot(g, X(I3), YA(FA[I3]), H * 0.011 * t3, ORG); txt(g, "z = 3: " + FA[I3].toFixed(1) + " a week", X(I3) + H * 0.02, YA(FA[I3]) - H * 0.015, { size: H * 0.021, color: ORG, align: "left", alpha: t3 });
    line(g, X(I8), y0, X(I8), y1, hex(GR, 0.5 * t8), 1); dot(g, X(I8), YF(F1[I8]), H * 0.011 * t8, GR); txt(g, "z = 8: F1 " + F1[I8].toFixed(2), X(I8) - H * 0.02, YF(F1[I8]) - H * 0.025, { size: H * 0.021, color: GR, align: "right", alpha: t8 });
    const rx = W * 0.64, rw = W * 0.29; txt(g, "FINDING THE LABELLED DAYS", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["False-alarm days a week, z = 3", "3.0", ORG], ["With z = 8 (set on 2022)", "0.4", BL], ["F1 on labelled days, 3 to 8", "0.14 to 0.44", GR], ["Rolling z, no weekly cycle: F1", "0.02", ink]].forEach(([nm, v, c], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1); txt(g, nm, rx, y, { size: H * 0.021, color: hex(ink, 0.8), weight: 400, alpha: t }); txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.04, color: c, align: "right", alpha: t });
    });
  },
});
