/* Did Guest Stars Lift The Office's Ratings? Mean IMDb rating of The Office's guest-star episodes (blue) and the other episodes (orange) by season, 1 to 9: the two lines run together. Season-adjusted difference +0.005 stars (95% bootstrap interval -0.13 to +0.14, permutation p = 0.96, 188 episodes);
   seasons 8-9 average 7.53 against 8.35 for seasons 2-5; Netflix's median movie runs 108 minutes for the 1990s and 94 for the 2020s. */
const GUEST = [7.775, 8.277, 8.507, 8.4, 8.336, 8.108, 7.964, 7.371, 7.689], OTHER = [7.7, 8.256, 8.287, 8.4, 8.333, 7.971, 8.3, 7.41, 7.64];
scene({
  slug: "netflix-office", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#46c28a";
    const x0 = W * 0.09, x1 = W * 0.54, y0 = H * 0.2, y1 = H * 0.78, N = 9, X = (i) => x0 + (x1 - x0) * i / (N - 1), Y = (v) => y1 - (y1 - y0) * (v - 7.2) / 1.5;
    txt(g, "IMDB RATING BY SEASON, THE OFFICE", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [7.5, 8, 8.5].forEach((v) => { line(g, x0 - H * 0.01, Y(v), x1, Y(v), hex(ink, 0.07), 1); txt(g, v.toFixed(1), x0 - H * 0.02, Y(v) + H * 0.007, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    for (let i = 0; i < N; i++) txt(g, String(i + 1), X(i), y1 + H * 0.05, { size: H * 0.02, color: hex(ink, 0.4), align: "center" });
    txt(g, "season", (x0 + x1) / 2, y1 + H * 0.1, { size: H * 0.02, color: hex(ink, 0.4), align: "center" });
    const path = (arr, t, col, w, dash) => { const p = t * (N - 1), k = Math.floor(p), fr = p - k; g.beginPath(); g.moveTo(X(0), Y(arr[0])); for (let i = 1; i <= k; i++) g.lineTo(X(i), Y(arr[i])); if (k < N - 1) g.lineTo(X(k) + (X(k + 1) - X(k)) * fr, Y(lerp(arr[k], arr[k + 1], fr))); g.strokeStyle = col; g.lineWidth = w; g.lineJoin = "round"; g.setLineDash(dash || []); g.stroke(); g.setLineDash([]); };
    const t1 = ease.out5(seg(u, 0.04, 0.4)), t2 = ease.out5(seg(u, 0.25, 0.6));
    path(OTHER, t2, ORG, H * 0.006, [H * 0.014, H * 0.01]); path(GUEST, t1, BL, H * 0.007);
    const lt = ease.out5(seg(u, 0.5, 0.65)); dot(g, x1 + H * 0.0, Y(GUEST[8]), H * 0.01 * lt, BL); txt(g, "guest-star episodes", x0 + W * 0.01, y0 - H * 0.025, { size: H * 0.021, color: BL, alpha: lt }); txt(g, "other episodes", x0 + W * 0.2, y0 - H * 0.025, { size: H * 0.021, color: ORG, alpha: lt });
    const rx = W * 0.64, rw = W * 0.29; txt(g, "DID THE GUESTS HELP?", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Gap within a season, stars", "+0.005", BL], ["95% interval", "-0.13 to +0.14", ink], ["Seasons 8-9 vs 2-5, stars", "-0.8", ORG], ["Netflix movie, 1990s to 2020s", "108 to 94 min", GR]].forEach(([nm, v, c], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1); txt(g, nm, rx, y, { size: H * 0.021, color: hex(ink, 0.8), weight: 400, alpha: t }); txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.04, color: c, align: "right", alpha: t });
    });
  },
});
