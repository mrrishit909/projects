/* How Far Ahead Does Today's Weather Beat the Calendar? Skill of forecasts of the daily high at twelve US airport stations against a calendar (seasonal cycle and trend), 2011 to 2025, models fitted only on the 20 years before each test year.
   Left: damped persistence (one grey line per station, the mean in blue) falls from 42% tomorrow to 7% in three days and 1% in fourteen; repeating today (orange, the mean) is below the calendar from day two (-24% at two days).
   Right: the same numbers, and tomorrow's rain probability, 4.5% better than the seasonal one. */
const STN = [[0.3316, 0.0687, 0.0215, 0.013, 0.0102, 0.0073, 0.0028, 0.0017, 0.0025, 0.0021, 0.0015, 0.0014, 0.0027, 0.0029], [0.4268, 0.1397, 0.0681, 0.0417, 0.0293, 0.0173, 0.0136, 0.0103, 0.0063, 0.005, 0.0035, 0.0034, 0.0044, 0.004], [0.4584, 0.1721, 0.0768, 0.0453, 0.0319, 0.0227, 0.0146, 0.0073, 0.0043, 0.0049, 0.0051, 0.0052, 0.0044, 0.0034], [0.5773, 0.256, 0.1074, 0.05, 0.0259, 0.0151, 0.0118, 0.0104, 0.0103, 0.0098, 0.0086, 0.0071, 0.0055, 0.0055], [0.3524, 0.0997, 0.036, 0.0226, 0.0203, 0.0164, 0.0113, 0.0092, 0.0071, 0.0065, 0.0089, 0.0114, 0.0088, 0.008], [0.4291, 0.1422, 0.0604, 0.0291, 0.0166, 0.0144, 0.0124, 0.0075, 0.0042, 0.0027, 0.0026, 0.0027, 0.0031, 0.004], [0.2874, 0.0397, 0.0113, 0.008, 0.0048, 0.003, 0.0013, 0.001, 0.0018, 0.0014, 0.0013, 0.0011, 0.0011, 0.0016], [0.4797, 0.2067, 0.1218, 0.0735, 0.0458, 0.0313, 0.0217, 0.014, 0.0089, 0.0066, 0.0035, 0.0022, 0.0026, 0.0013], [0.529, 0.2099, 0.0876, 0.0441, 0.0266, 0.0181, 0.0167, 0.0162, 0.0153, 0.0164, 0.014, 0.0119, 0.012, 0.015], [0.4153, 0.1278, 0.0491, 0.0204, 0.0127, 0.0108, 0.0084, 0.0055, 0.0027, 0.0035, 0.005, 0.0058, 0.0054, 0.0044], [0.3356, 0.1912, 0.1285, 0.1011, 0.0804, 0.0628, 0.0635, 0.0557, 0.0512, 0.0434, 0.0346, 0.0379, 0.0475, 0.0425], [0.4442, 0.1516, 0.0585, 0.0335, 0.0184, 0.0104, 0.0073, 0.0065, 0.0063, 0.0059, 0.0046, 0.0032, 0.0029, 0.0035]], DM = [0.4223, 0.1504, 0.0689, 0.0402, 0.0269, 0.0191, 0.0154, 0.0121, 0.0101, 0.009, 0.0078, 0.0078, 0.0084, 0.008], PM = [0.2934, -0.2422, -0.4982, -0.6257, -0.7048, -0.7628, -0.8062, -0.8473, -0.8796, -0.9049, -0.931, -0.9526, -0.9711, -0.9963];
scene({
  slug: "weather-forecast-skill", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#8a8f98";
    const x0 = W * 0.09, x1 = W * 0.54, y0 = H * 0.2, y1 = H * 0.78, N = 14, X = (h) => x0 + (x1 - x0) * (h - 1) / (N - 1), Y = (v) => y1 - (y1 - y0) * (v + 1.1) / 1.7;
    txt(g, "SKILL AGAINST THE CALENDAR, DAILY HIGH", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [-1, -0.5, 0, 0.5].forEach((v) => { line(g, x0 - H * 0.01, Y(v), x1, Y(v), hex(ink, v ? 0.07 : 0.35), 1); txt(g, Math.round(v * 100) + "%", x0 - H * 0.02, Y(v) + H * 0.007, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    [1, 2, 3, 5, 7, 10, 14].forEach((h) => txt(g, String(h), X(h), y1 + H * 0.05, { size: H * 0.02, color: hex(ink, 0.4), align: "center" }));
    txt(g, "days ahead", (x0 + x1) / 2, y1 + H * 0.1, { size: H * 0.02, color: hex(ink, 0.4), align: "center" });
    const path = (arr, t, col, w, dash) => { const p = t * (N - 1), k = Math.floor(p), fr = p - k; g.beginPath(); g.moveTo(X(1), Y(arr[0])); for (let i = 1; i <= k; i++) g.lineTo(X(i + 1), Y(arr[i])); if (k < N - 1) g.lineTo(X(k + 1) + (X(k + 2) - X(k + 1)) * fr, Y(lerp(arr[k], arr[k + 1], fr))); g.strokeStyle = col; g.lineWidth = w; g.lineJoin = "round"; g.setLineDash(dash || []); g.stroke(); g.setLineDash([]); };
    const t1 = ease.out5(seg(u, 0.04, 0.3)), t2 = ease.out5(seg(u, 0.3, 0.55)), t3 = ease.out5(seg(u, 0.5, 0.75));
    STN.forEach((a) => path(a, t1, hex(ink, 0.22), H * 0.0025)); path(PM, t2, ORG, H * 0.006, [H * 0.014, H * 0.01]); path(DM, t3, BL, H * 0.007);
    const rx = W * 0.64, rw = W * 0.29; txt(g, "AGAINST THE CALENDAR", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Damped, tomorrow", "42%", BL], ["Damped, in 3 days", "7%", BL], ["Repeat today, in 2 days", "-24%", ORG], ["Rain tomorrow", "4.5%", GR]].forEach(([nm, v, c], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1); txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t }); txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.04, color: c, align: "right", alpha: t });
    });
  },
});
