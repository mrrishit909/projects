/* Does Any Recommender Beat 'Most Popular'? Hit rate in the top 10 on MovieLens 1M ({6,040} users, one rating hidden each): most popular 3.5%, item neighbours 6.6%, PureSVD 8.9% when the user's last rating is hidden (solid), and 6.8%, 15.4%, 23.4%
   when a random rating is hidden (faded). Right: PureSVD is 2.5x the popularity baseline, and a random hold-out would flatter it to 23.4%. */
const HITS = [[3.5, 6.8], [6.6, 15.4], [8.9, 23.4]];
scene({
  slug: "movie-recommender", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#9a9a96", COL = [GR, BL, ORG], NM = ["most popular", "item neighbours", "PureSVD"];
    const x0 = W * 0.09, x1 = W * 0.57, y0 = H * 0.2, y1 = H * 0.76, gw = (x1 - x0) / 3, Y = (v) => y1 - v / 26 * (y1 - y0);
    txt(g, "HIT RATE IN THE TOP 10 (%), TWO WAYS OF HIDING A RATING", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [0, 10, 20].forEach((v) => { line(g, x0, Y(v), x1, Y(v), hex(ink, v ? 0.08 : 0.3), 1); txt(g, String(v), x0 - H * 0.015, Y(v) + H * 0.008, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    let cur = 1;
    HITS.forEach((pair, i) => pair.forEach((v, j) => {
      const k = i * 2 + j, t = ease.out5(seg(u, 0.06 + k * 0.07, 0.2 + k * 0.07)), h = (y1 - Y(v)) * t, bw = gw * 0.34, bx = x0 + gw * i + gw * 0.12 + j * (bw + gw * 0.04);
      rr(g, bx, y1 - h, bw, Math.max(h, 0.1), 4); g.fillStyle = COL[i]; g.globalAlpha = j ? 0.5 : 1; g.fill(); g.globalAlpha = 1;
      txt(g, v.toFixed(1), bx + bw / 2, y1 - h - H * 0.016, { size: H * 0.022, color: ink, align: "center", alpha: t });
      if (i === 2 && j === 0 && t > 0) cur = lerp(1, 2.5, t);
    }));
    NM.forEach((s, i) => txt(g, s, x0 + gw * i + gw * 0.5, y1 + H * 0.055, { size: H * 0.021, color: hex(ink, 0.55), align: "center" }));
    txt(g, "solid: last rating hidden   faded: a random rating hidden", x0, y1 + H * 0.115, { size: H * 0.02, color: hex(ink, 0.4) });
    const rx = W * 0.65, rw = W * 0.28;
    txt(g, "PURESVD VS MOST POPULAR", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, cur.toFixed(1) + "\u00d7", rx, H * 0.29, { size: H * 0.12, color: seg(u, 0.06, 0.62) >= 1 ? ORG : BL, spacing: -3 });
    txt(g, "the hit rate, last rating hidden", rx, H * 0.345, { size: H * 0.026, color: hex(ink, 0.7), weight: 400 });
    [["Most popular, last rating hidden", "3.5%", GR], ["PureSVD, last rating hidden", "8.9%", ORG], ["PureSVD, a random rating hidden", "23.4%", ink]].forEach(([nm, v, c], i) => {
      const y = H * 0.54 + i * H * 0.14, t = ease.out5(seg(u, 0.66 + i * 0.07, 0.84 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.038, color: c, align: "right", alpha: t });
    });
  },
});
