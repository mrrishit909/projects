/* SF 311 Intake Requirements. Where intake fails, from the case study: of closed cases, 70,526 duplicates, 26,359 wrong agency,
   19,044 unable to locate, 11,972 out of scope, 8,385 insufficient info: 136,286 cases (16.3%) a better front door could prevent.
   Then the eight requirements tick in. */
scene({
  slug: "sf311-requirements", aspect: 1.72, seconds: 6, bg: ["#0d141b", "#04070a"],
  draw(g, u, W, H, S, { seg, ease, hex, mix, txt, rr, fmt }) {
    const ink = "#ecf3f8", RED = "#ff6b5a", GRN = "#46d39a", x0 = W * 0.05, w = W * 0.47;
    txt(g, "CLOSED CASES A BETTER FRONT DOOR COULD PREVENT", x0, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2 });
    [["Duplicate", 70526], ["Wrong agency", 26359], ["Unable to locate", 19044], ["Out of scope", 11972], ["Insufficient info", 8385]].forEach(([n, v], i) => {
      const y = H * 0.18 + i * H * 0.12, t = ease.out5(seg(u, 0.05 + i * 0.06, 0.3 + i * 0.06));
      txt(g, n, x0, y + H * 0.03, { size: H * 0.03, color: hex(ink, 0.85), weight: 400 });
      txt(g, fmt(Math.round(v * t)), x0 + w, y + H * 0.03, { size: H * 0.03, color: mix(RED, "#ffb35a", i / 4), align: "right" });
      g.fillStyle = mix(RED, "#ffb35a", i / 4); rr(g, x0, y + H * 0.05, Math.max(0.001, w * v / 70526 * t), H * 0.022, 8); g.fill();
    });
    const rx = W * 0.6, k = ease.out5(seg(u, 0.3, 0.55));
    txt(g, Math.round(136286 * k).toLocaleString("en-US"), rx, H * 0.24, { size: H * 0.11, color: "#fff", spacing: -3 });
    txt(g, "cases, 16.3% of a year's closures", rx, H * 0.31, { size: H * 0.028, color: hex(ink, 0.7), weight: 400, alpha: k });
    ["Warn about an open case nearby", "Attend parking within the hour", "Route to the right agency first", "Replace “General Request”", "A/B test the guided form", "…and three more, each with acceptance criteria"].forEach((s, i) => {
      const t = seg(u, 0.55 + i * 0.045, 0.6 + i * 0.045), y = H * 0.44 + i * H * 0.075;
      txt(g, i < 5 ? "REQ-0" + (i + 1) : "", rx, y, { size: H * 0.022, color: GRN, mono: true, alpha: t });
      txt(g, s, rx + (i < 5 ? W * 0.07 : 0), y, { size: H * 0.027, color: i < 5 ? ink : hex(ink, 0.55), weight: 400, alpha: t });
    });
  },
});
