/* How Fairly Do Votes Become Seats in India? The Gallagher index of disproportionality (points) for the 16 Lok Sabha elections 1962 to 2024, from 5.4 (2004) to 22.0 (1984), orange where it is 15 or more.
   Right: Congress won 77% of the seats on 48% of the votes in 1984, the BJP 52% on 31% in 2014, and 52% of all contested seats were won with under half of the valid votes. */
const G = [21.4, 11.0, 18.6, 10.9, 19.9, 22.0, 8.4, 7.8, 8.1, 6.8, 9.2, 5.4, 8.2, 17.6, 15.1, 6.7], YR = [1962, 1967, 1971, 1977, 1980, 1984, 1989, 1991, 1996, 1998, 1999, 2004, 2009, 2014, 2019, 2024];
scene({
  slug: "india-elections", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#46c28a";
    const x0 = W * 0.09, x1 = W * 0.54, y0 = H * 0.2, y1 = H * 0.78, N = G.length, bw = (x1 - x0) / N, Y = (v) => y1 - (y1 - y0) * v / 25;
    txt(g, "GALLAGHER INDEX: SEATS AGAINST VOTES (POINTS)", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [0, 5, 10, 15, 20].forEach((v) => { line(g, x0 - H * 0.01, Y(v), x1, Y(v), hex(ink, v === 0 ? 0.3 : 0.07), 1); txt(g, String(v), x0 - H * 0.02, Y(v) + H * 0.007, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    G.forEach((v, i) => {
      const t = ease.out5(seg(u, 0.04 + i * 0.03, 0.3 + i * 0.03)), h = (y1 - Y(v)) * t, bx = x0 + i * bw + bw * 0.14;
      rr(g, bx, y1 - h, bw * 0.72, Math.max(h, 0.1), 3); g.fillStyle = v >= 15 ? ORG : BL; g.fill();
      if (i % 2 === 0 || i === N - 1) txt(g, "'" + String(YR[i]).slice(2), bx + bw * 0.36, y1 + H * 0.05, { size: H * 0.019, color: hex(ink, 0.4), align: "center" });
    });
    const t1 = ease.out5(seg(u, 0.5, 0.65)); txt(g, "22.0", x0 + 5 * bw + bw * 0.5, Y(22.0) - H * 0.02, { size: H * 0.021, color: ORG, align: "center", alpha: t1 }); txt(g, "5.4", x0 + 11 * bw + bw * 0.5, Y(5.4) - H * 0.02, { size: H * 0.021, color: BL, align: "center", alpha: t1 });
    const rx = W * 0.64, rw = W * 0.29; txt(g, "VOTES INTO SEATS", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["1984 Congress: seats on 48% of votes", "77%", BL], ["2014 BJP: seats on 31% of votes", "52%", ORG], ["Seats won with under half the votes", "52%", ink], ["Lowest gap (2004), Gallagher index", "5.4", GR]].forEach(([nm, v, c], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1); txt(g, nm, rx, y, { size: H * 0.021, color: hex(ink, 0.8), weight: 400, alpha: t }); txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.04, color: c, align: "right", alpha: t });
    });
  },
});
