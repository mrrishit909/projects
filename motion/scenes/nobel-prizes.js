/* Who Wins the Nobel Prize? Science prizes by decade, each bar split into prizes won by one laureate, shared by two, shared by three
   (the stacked chart on the case-study page; counts from results/team_size.csv). The lone laureate falls from 81.5% in the 1900s to
   10.0% in the 2010s. Right: mean laureates per science prize 1.22 to 2.57, women 6.8% of people honoured, 1,026 prizes since 1901. */
scene({
  slug: "nobel-prizes", aspect: 1.72, seconds: 6, bg: ["#16120a", "#050403"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line }) {
    const ink = "#f6f1e6", GOLD = "#e8b84a", BL = "#3987e5", GR = "#8f8f8a";
    const D = [[22, 4, 1], [20, 2, 0], [21, 6, 0], [17, 9, 1], [15, 3, 3], [12, 12, 6], [13, 7, 10], [8, 9, 13], [7, 10, 13], [9, 12, 9], [2, 7, 21], [3, 7, 20], [1, 6, 11]];
    const x0 = W * 0.05, x1 = W * 0.58, y0 = H * 0.2, y1 = H * 0.8, bw = (x1 - x0) / D.length;
    txt(g, "SCIENCE PRIZES: ONE LAUREATE, TWO OR THREE", x0, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    D.forEach((d, i) => {
      const t = ease.out3(seg(u, 0.06 + i * 0.03, 0.2 + i * 0.03)), tot = d[0] + d[1] + d[2];
      let y = y1;
      [[d[0], BL], [d[1], GR], [d[2], GOLD]].forEach(([n, c]) => { const h = (y1 - y0) * (n / tot) * t; g.fillStyle = c; g.fillRect(x0 + i * bw + bw * 0.1, y - h, bw * 0.8, h); y -= h; });
    });
    line(g, x0, y1 + 1, x1, y1 + 1, hex(ink, 0.25), 1);
    [[0, "1900s"], [6, "1960s"], [12, "2020–25"]].forEach(([i, s]) => txt(g, s, x0 + i * bw + bw * 0.5, y1 + H * 0.05, { size: H * 0.022, color: hex(ink, 0.5), align: "center" }));
    [["one laureate", BL], ["two", GR], ["three", GOLD]].forEach(([s, c], i) => { const lx = x0 + i * W * 0.17; g.fillStyle = c; g.fillRect(lx, H * 0.905, H * 0.022, H * 0.022); txt(g, s, lx + H * 0.035, H * 0.925, { size: H * 0.024, color: hex(ink, 0.7), weight: 400 }); });
    const rx = W * 0.67, k = ease.out5(seg(u, 0.5, 0.76));
    txt(g, "WON ALONE, 1900s TO 2010s", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, (81.5 + (10.0 - 81.5) * k).toFixed(1) + "%", rx, H * 0.29, { size: H * 0.11, color: "#fff", spacing: -3 });
    txt(g, "of physics, chemistry and medicine prizes", rx, H * 0.35, { size: H * 0.026, color: hex(ink, 0.7), weight: 400, alpha: k });
    [["Laureates per prize, 1900s to 2010s", "1.22 → 2.57", GOLD], ["Women among people honoured", "6.8%", BL], ["Prizes, 1901–2025", "1,026", ink]].forEach(([n, v, c], i) => {
      const y = H * 0.55 + i * H * 0.13, t = ease.out5(seg(u, 0.62 + i * 0.06, 0.8 + i * 0.06));
      line(g, rx, y - H * 0.05, rx + W * 0.28, y - H * 0.05, hex(ink, 0.12), 1);
      txt(g, n, rx, y, { size: H * 0.026, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + W * 0.28, y + H * 0.045, { size: H * 0.036, color: c, align: "right", alpha: t });
    });
  },
});
