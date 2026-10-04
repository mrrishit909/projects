/* Which Items Do Shoppers Click, Cart and Buy Next? Retailrocket shop events (2015, 1,761,675 sessions), test = the last 28 days. Left: blended recall@20 (0.1 clicks, 0.3 carts, 0.6 orders) of five session recommenders: Most popular 3.0%, Popular in category 30.3%, Co-visits 3.4%, Seen items 74.5%, Seen + co-visits 76.7%.
   Right: 72% of the items bought next were already in the session; showing them back scores 83% recall for orders, co-visits that never repeat 1%; 2.6% of views become carts; training on later sessions lifts the co-visit blend +42%. */
const NAMES = ["Most popular", "Popular in category", "Co-visits", "Seen items", "Seen + co-visits"], VALS = [0.0305, 0.3027, 0.0335, 0.7448, 0.7673], COLS = ["GR0", "GR1", "BL", "GR", "ORG"];
scene({
  slug: "session-recommender", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#46c28a", GY = "#9a9a96", C = { GR0: "#7d7d7a", GR1: "#5f5f5c", BL, GR, ORG };
    const x0 = W * 0.27, x1 = W * 0.55, y0 = H * 0.24, dy = H * 0.125;
    txt(g, "BLENDED RECALL@20 OF FIVE RECOMMENDERS", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [0, 0.5, 1].forEach((v) => { line(g, x0 + (x1 - x0) * v, y0 - H * 0.03, x0 + (x1 - x0) * v, y0 + dy * 4.6, hex(ink, 0.08), 1); txt(g, Math.round(v * 100) + "%", x0 + (x1 - x0) * v, y0 + dy * 4.6 + H * 0.045, { size: H * 0.019, color: hex(ink, 0.4), align: "center" }); });
    NAMES.forEach((nm, i) => {
      const y = y0 + i * dy, t = ease.out5(seg(u, 0.05 + i * 0.07, 0.5 + i * 0.07)), w = (x1 - x0) * VALS[i] * t;
      txt(g, nm, x0 - H * 0.02, y + H * 0.027, { size: H * 0.022, color: hex(ink, 0.8), align: "right" });
      rr(g, x0, y, Math.max(w, 1), H * 0.05, 4); g.fillStyle = C[COLS[i]]; g.fill();
      txt(g, (VALS[i] * 100).toFixed(VALS[i] < 0.1 ? 1 : 0) + "%", x0 + w + H * 0.015, y + H * 0.035, { size: H * 0.024, color: ink, alpha: t });
    });
    const rx = W * 0.64, rw = W * 0.29; txt(g, "WHAT THE LOGS SAY", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Order answers already seen", "72%", "BL"], ["Seen items vs co-visits, orders", "83% / 1%", "ORG"], ["Views that become carts", "2.6%", "ink"], ["Co-visit gain from later sessions", "+42%", "GR"]].forEach(([nm, v, c], i) => {
      const col = { BL, ORG, GR, ink }[c] || ink, y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1); txt(g, nm, rx, y, { size: H * 0.021, color: hex(ink, 0.8), weight: 400, alpha: t }); txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.04, color: col, align: "right", alpha: t });
    });
  },
});
