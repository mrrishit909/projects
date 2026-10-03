/* Do Women's Matches Have More Goals? Goals per match at each World Cup draw in as two lines (men's blue, women's orange; the per-tournament
   means on the case-study chart). Right: the same Mann-Whitney test run on more and more tournaments: p = 0.004 through 2019, 0.023
   through 2023, 0.083 through 2026 (orange when below 0.05), and the overall gap, +0.27 goals (95% interval -0.01 to +0.57). */
scene({
  slug: "soccer-goals-test", aspect: 1.72, seconds: 6, bg: ["#0d1510", "#040605"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, dot, path }) {
    const ink = "#eef4ee", ORG = "#ff8a3d", BL = "#4a95f0";
    const men = [[2002, 2.52], [2006, 2.30], [2010, 2.27], [2014, 2.67], [2018, 2.64], [2022, 2.69], [2026, 2.96]];
    const women = [[2003, 3.34], [2007, 3.47], [2011, 2.69], [2015, 2.81], [2019, 2.81], [2023, 2.56]];
    const x0 = W * 0.07, x1 = W * 0.55, y0 = H * 0.22, y1 = H * 0.8;
    const X = (yr) => x0 + (yr - 2002) / 24 * (x1 - x0), Y = (v) => y1 - (v - 2.0) / 1.7 * (y1 - y0);
    txt(g, "GOALS PER MATCH, EACH WORLD CUP", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [2.0, 2.5, 3.0, 3.5].forEach((v) => { line(g, x0, Y(v), x1, Y(v), hex(ink, 0.08), 1); txt(g, v.toFixed(1), x0 - H * 0.02, Y(v) + H * 0.008, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    [2002, 2010, 2018, 2026].forEach((yr) => txt(g, String(yr), X(yr), y1 + H * 0.05, { size: H * 0.021, color: hex(ink, 0.45), align: "center" }));
    const k = ease.inOut(seg(u, 0.06, 0.46));
    [[men, BL], [women, ORG]].forEach(([d, c]) => { const pts = d.map(([yr, v]) => [X(yr), Y(v)]); path(g, pts, k, c, 3, hex(c, 0.5));
      pts.forEach((p, i) => { if (k * (pts.length - 1) >= i) dot(g, p[0], p[1], 4.5, c); }); });
    txt(g, "women", X(2007) - W * 0.005, Y(3.47) - H * 0.035, { size: H * 0.024, color: ORG, weight: 500, alpha: seg(u, 0.14, 0.24), align: "center" });
    txt(g, "men", X(2026) - W * 0.005, Y(2.96) - H * 0.035, { size: H * 0.024, color: BL, weight: 500, alpha: seg(u, 0.4, 0.5), align: "center" });
    const rx = W * 0.64, rw = W * 0.31;
    txt(g, "WOMEN'S > MEN'S?  p-VALUE", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Matches through 2019", 0.004], ["Matches through 2023", 0.023], ["Matches through 2026", 0.083]].forEach(([n, p], i) => {
      const y = H * 0.25 + i * H * 0.15, t = ease.out5(seg(u, 0.42 + i * 0.1, 0.62 + i * 0.1)), c = p < 0.05 ? ORG : hex(ink, 0.55);
      txt(g, n, rx, y, { size: H * 0.028, color: hex(ink, 0.85), weight: 400, alpha: Math.min(1, t * 3) });
      txt(g, (p * t).toFixed(3), rx + rw, y + H * 0.005, { size: H * 0.05, color: c, align: "right", alpha: Math.min(1, t * 3) });
      g.fillStyle = hex(ink, 0.07); g.fillRect(rx, y + H * 0.035, rw, H * 0.012);
      g.fillStyle = c; g.fillRect(rx, y + H * 0.035, rw * Math.min(1, p / 0.1) * t, H * 0.012);
      line(g, rx + rw * 0.5, y + H * 0.028, rx + rw * 0.5, y + H * 0.054, hex(ink, 0.5 * t), 1);
    });
    txt(g, "0.05", rx + rw * 0.5, H * 0.715, { size: H * 0.02, color: hex(ink, 0.45), align: "center", alpha: seg(u, 0.5, 0.6) });
    const k2 = ease.out5(seg(u, 0.72, 0.88));
    txt(g, "+" + (0.27 * k2).toFixed(2), rx, H * 0.82, { size: H * 0.09, color: "#fff", spacing: -3, alpha: Math.min(1, k2 * 4) });
    txt(g, "goals per match, women minus men", rx, H * 0.875, { size: H * 0.026, color: hex(ink, 0.75), weight: 400, alpha: k2 });
    txt(g, "95% interval -0.01 to +0.57", rx, H * 0.92, { size: H * 0.024, color: hex(ink, 0.5), weight: 400, alpha: k2 });
  },
});
