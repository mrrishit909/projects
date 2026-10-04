/* Who Are the Influencers in a Twitter Network? A 2012 crawl of 81,306 Twitter accounts and 1,768,135 follows (SNAP). Left: each of the ten most-followed accounts (1 to 10) and where it ranks by PageRank (blue) and by betweenness (orange), on a log scale:
   the most followed account is first by PageRank and 10,848th by betweenness. Right: the 100 most followed and the 100 highest by PageRank share 60 accounts, followers and betweenness 33, PageRank and betweenness 30;
   betweenness against itself on another 60 pivot accounts 43. */
const PR = [1, 5, 21, 3, 30, 39, 32, 6, 44, 4], BT = [10848, 15, 54, 1, 267, 99, 384, 19, 4, 43], N = 81306;
scene({
  slug: "twitter-network", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#8a8f98";
    const x0 = W * 0.1, x1 = W * 0.5, y0 = H * 0.2, y1 = H * 0.8, Y = (r) => y0 + (y1 - y0) * Math.log10(r) / Math.log10(N), X = (i) => x0 + (x1 - x0) * (i + 0.5) / 10;
    txt(g, "THE 10 MOST FOLLOWED, RANKED TWO OTHER WAYS", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [[1, "1"], [10, "10"], [100, "100"], [1000, "1,000"], [10000, "10,000"]].forEach(([r, s]) => { line(g, x0 - H * 0.01, Y(r), x1, Y(r), hex(ink, 0.07), 1); txt(g, s, x0 - H * 0.02, Y(r) + H * 0.007, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    for (let i = 0; i < 10; i++) txt(g, String(i + 1), X(i), y1 + H * 0.05, { size: H * 0.02, color: hex(ink, 0.4), align: "center" });
    txt(g, "rank by followers", (x0 + x1) / 2, y1 + H * 0.1, { size: H * 0.02, color: hex(ink, 0.4), align: "center" });
    for (let i = 0; i < 10; i++) {
      const a = ease.out5(seg(u, 0.04 + i * 0.03, 0.14 + i * 0.03)), b = ease.out5(seg(u, 0.3 + i * 0.03, 0.5 + i * 0.03)), yb = Y(PR[i]), yo = lerp(yb, Y(BT[i]), b);
      line(g, X(i), yb, X(i), yo, hex(ink, 0.25 * a), 1.5); dot(g, X(i), yb, H * 0.011 * a, BL); dot(g, X(i), yo, H * 0.011 * ease.out5(seg(u, 0.28 + i * 0.03, 0.33 + i * 0.03)), ORG);
    }
    const tl = ease.out5(seg(u, 0.55, 0.7)); txt(g, "most followed: betweenness rank " + BT[0].toLocaleString("en-US"), X(0) + H * 0.03, Y(BT[0]) - H * 0.025, { size: H * 0.021, color: ORG, alpha: tl });
    txt(g, "PageRank", x1 - H * 0.2, y1 - H * 0.09, { size: H * 0.021, color: BL, alpha: ease.out5(seg(u, 0.2, 0.3)) }); txt(g, "betweenness", x1 - H * 0.2, y1 - H * 0.05, { size: H * 0.021, color: ORG, alpha: ease.out5(seg(u, 0.4, 0.5)) });
    const rx = W * 0.6, rw = W * 0.33; txt(g, "SHARED BY TWO TOP-100 LISTS", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Followers, PageRank", 60, BL], ["Followers, betweenness", 33, ORG], ["PageRank, betweenness", 30, ORG], ["Betweenness, other pivots", 43, GR]].forEach(([nm, v, c], i) => {
      const y = H * 0.27 + i * H * 0.17, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t }); if (t > 0.01) { rr(g, rx, y + H * 0.02, rw * v / 100 * t, H * 0.045, 4); g.fillStyle = c; g.fill(); }
      txt(g, String(Math.round(v * t)), rx + rw * v / 100 * t + H * 0.014, y + H * 0.055, { size: H * 0.034, color: ink, alpha: t });
    });
  },
});
