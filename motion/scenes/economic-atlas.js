/* Economic Atlas. Left: a Vogel seed head, a schematic of the atlas's seed-head encoding (grain positions are illustrative, not data;
   the real grains are one million people each). Counter: 217 countries. Right: figures on the project page. Income per person 1,067 (Burundi)
   to 139,593 (Singapore) international dollars in 2025, a 131-fold range; absolute-convergence slope since 1990 of -0.37 pp per year per log unit
   (95% CI -0.59 to -0.15); China and India hold 38.8% of the 1990 population weight. */
scene({
  slug: "economic-atlas", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, _S, { seg, ease, hex, txt, line, dot, fmt, TAU }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0";
    const cx = W * 0.3, cy = H * 0.54, R = H * 0.36, N = 420, GA = Math.PI * (3 - Math.sqrt(5));
    txt(g, "ONE GRAIN, ONE MILLION PEOPLE", W * 0.06, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, "SCHEMATIC", W * 0.54, H * 0.12, { size: H * 0.02, color: hex(ink, 0.4), spacing: 2, align: "right" });
    const turn = u * TAU * 0.25;
    for (let i = 1; i <= N; i++) {
      const f = i / N, r = Math.sqrt(f) * R, a = i * GA + turn * (1 - f * 0.6);
      if (r < H * 0.09) continue;                           // keep the counter legible
      const t = ease.out3(seg(u, 0.02 + f * 0.4, 0.2 + f * 0.4));
      if (t <= 0) continue;
      const warm = 1 - f;                                   // richer toward the core
      dot(g, cx + Math.cos(a) * r, cy + Math.sin(a) * r, H * (0.004 + 0.0075 * f) * t, warm > 0.6 ? hex(ORG, 0.9) : hex(BL, 0.35 + 0.5 * warm));
    }
    const n = Math.round(217 * ease.out3(seg(u, 0.08, 0.5)));
    txt(g, fmt(n), cx, cy + H * 0.015, { size: H * 0.058, color: ink, align: "center", weight: 500 });
    txt(g, "COUNTRIES", cx, cy + H * 0.07, { size: H * 0.022, color: hex(ink, 0.55), align: "center", spacing: 2 });
    const rx = W * 0.64, rw = W * 0.31;
    txt(g, "WHAT THE DATA SHOWS", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Richest to poorest, 2025", "131-fold", ORG], ["Catch-up slope since 1990", "-0.37 pp/yr", BL], ["China and India, 1990 weight", "38.8%", ORG]].forEach(([nm, v, c], i) => {
      const y = H * 0.3 + i * H * 0.2, t = ease.out5(seg(u, 0.45 + i * 0.08, 0.65 + i * 0.08));
      line(g, rx, y - H * 0.06, rx + rw, y - H * 0.06, hex(ink, 0.12), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + rw, y + H * 0.07, { size: H * 0.05, color: c, align: "right", alpha: t });
    });
  },
});
