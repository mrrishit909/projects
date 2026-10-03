/* What Wins an IPL Match? Average first-innings total, season by season (2008 to 2026; the bars on the case-study chart): flat around
   160-170 until the Impact Player rule in 2023, then 183 to 196. Right: the break-even total for the side batting first moves from 170 to
   195, the toss winner wins 51.6% (a coin flip), powerplay runs per over go from 7.8 (2022) to 10.1 (2026). */
scene({
  slug: "ipl-cricket", aspect: 1.72, seconds: 6, bg: ["#0d1119", "#040508"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line }) {
    const ink = "#eef1f7", ORG = "#ff8a3d", BL = "#4a95f0";
    const A = [163.3, 150.3, 164.8, 155.6, 158.4, 156.6, 163.7, 167.8, 164.3, 166.4, 172.1, 168.5, 169.5, 159.3, 171.1, 183.0, 190.1, 192.3, 195.8];
    const x0 = W * 0.05, x1 = W * 0.58, y0 = H * 0.2, y1 = H * 0.8, bw = (x1 - x0) / A.length;
    const Y = (v) => y1 - (v - 140) / 65 * (y1 - y0);
    txt(g, "FIRST-INNINGS TOTAL, 2008 TO 2026", x0, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [150, 170, 190].forEach((v) => { line(g, x0, Y(v), x1, Y(v), hex(ink, 0.08), 1); txt(g, String(v), x0 - H * 0.015, Y(v) + H * 0.008, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    A.forEach((v, i) => { const t = ease.out3(seg(u, 0.05 + i * 0.022, 0.17 + i * 0.022)), h = (y1 - Y(v)) * t; g.fillStyle = i < 15 ? BL : ORG; g.fillRect(x0 + i * bw + bw * 0.12, y1 - h, bw * 0.76, h); });
    line(g, x0, y1 + 1, x1, y1 + 1, hex(ink, 0.25), 1);
    [[0, "2008"], [14, "2022"], [18, "2026"]].forEach(([i, s]) => txt(g, s, x0 + i * bw + bw * 0.5, y1 + H * 0.05, { size: H * 0.021, color: hex(ink, 0.5), align: "center" }));
    const m = ease.out3(seg(u, 0.5, 0.62)), mx = x0 + 15 * bw;
    line(g, mx, y0, mx, y1, hex(ink, 0.45 * m), 1, [4, 4]);
    txt(g, "Impact Player rule", mx - H * 0.012, y0 + H * 0.03, { size: H * 0.022, color: hex(ink, 0.7), align: "right", alpha: m });
    const rx = W * 0.67, rw = W * 0.28;
    txt(g, "SAFE TOTAL, BATTING FIRST", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    const k = ease.out5(seg(u, 0.5, 0.76));
    txt(g, Math.round(170 + 25 * k) + "", rx, H * 0.29, { size: H * 0.13, color: "#fff", spacing: -3 });
    txt(g, "runs for a coin flip, up from 170", rx, H * 0.345, { size: H * 0.026, color: hex(ink, 0.7), weight: 400, alpha: k });
    [["Toss winner wins", "51.6%", BL], ["Powerplay runs per over, 2022 to 2026", "7.8 → 10.1", ORG], ["Matches, ball by ball", "1,243", ink]].forEach(([n, v, c], i) => {
      const y = H * 0.54 + i * H * 0.14, t = ease.out5(seg(u, 0.62 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12), 1);
      txt(g, n, rx, y, { size: H * 0.025, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.038, color: c, align: "right", alpha: t });
    });
  },
});
