/* Did Fast-Food Stocks Beat the Market? Left: compound annual growth of each stock and SPY, 1 November 2016 to 2 October 2026 (statistics only, no prices): CMG 16.4%, SPY 15.7%, DRI 15.3%, YUM 10.5%, MCD 10.2%, SBUX 8.4%, QSR 8.0%, DPZ 7.2%, WEN -2.3%; the eight combined 11.9%.
   Right: eight combined 11.9% vs SPY 15.7% a year; mean correlation between pairs of the eight 0.69 from 20 February to 30 April 2020 (against 0.26 before); next-month spread of past 12-month winners minus losers -1.1% (95% interval -2.5% to +0.3%). */
const NAMES = ["CMG", "SPY", "DRI", "YUM", "MCD", "SBUX", "QSR", "DPZ", "WEN"], VALS = [16.4, 15.7, 15.3, 10.5, 10.2, 8.4, 8.0, 7.2, -2.3], SPY = 15.7, EIGHT = 11.9, ROWS = [["Eight combined, a year", "11.9%", "#4a95f0"], ["SPY, a year", "15.7%", "#ff8a3d"], ["Mean pair correlation, 2020 crash", "0.69", "#e8c25a"], ["Winners minus losers, 12 months", "-1.1%", "#eef0f4"]];
scene({
  slug: "fast-food-stocks", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GD = "#e8c25a";
    const x0 = W * 0.2, x1 = W * 0.57, y0 = H * 0.2, y1 = H * 0.8, N = NAMES.length, bh = (y1 - y0) / N * 0.62, X = (v) => x0 + (x1 - x0) * Math.max(v, 0) / 20, Y = (i) => y0 + (y1 - y0) * (i + 0.5) / N;
    txt(g, "GROWTH PER YEAR, % (NOV 2016 TO OCT 2026)", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [0, 5, 10, 15, 20].forEach((v) => { line(g, X(v), y0 - H * 0.02, X(v), y1, hex(ink, v ? 0.07 : 0.3), 1); txt(g, String(v), X(v), y1 + H * 0.05, { size: H * 0.02, color: hex(ink, 0.4), align: "center" }); });
    NAMES.forEach((nm, i) => {
      const t = ease.out5(seg(u, 0.05 + i * 0.045, 0.3 + i * 0.045)), v = VALS[i], col = NAMES[i] === "SPY" ? ORG : v < 0 ? "#d95926" : (v > SPY ? BL : hex(ink, 0.55)), w = (x1 - x0) * Math.abs(v) / 20 * t;
      txt(g, nm, W * 0.115, Y(i) + H * 0.008, { size: H * 0.022, color: hex(ink, 0.8), align: "right" });
      rr(g, v >= 0 ? x0 : x0 - w, Y(i) - bh / 2, Math.max(w, 1), bh, bh * 0.2); g.fillStyle = col; g.fill();
      txt(g, (v < 0 ? "-" : "") + Math.abs(v * t).toFixed(1), (v >= 0 ? x0 + w : x0 + H * 0.0) + H * 0.015, Y(i) + H * 0.008, { size: H * 0.021, color: col, alpha: t });
    });
    const ts = ease.out5(seg(u, 0.4, 0.6)); g.setLineDash([H * 0.008, H * 0.01]); line(g, X(SPY), y0 - H * 0.02, X(SPY), y1, hex(ORG, 0.9 * ts), 1.5); g.setLineDash([]); txt(g, "SPY " + SPY.toFixed(1), X(SPY) + H * 0.012, y0 - H * 0.03, { size: H * 0.021, color: ORG, alpha: ts });
    const rx = W * 0.64, rw = W * 0.29; txt(g, "WHAT THE DATA SAYS", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    ROWS.forEach(([nm, v, c], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.55 + i * 0.07, 0.75 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1); txt(g, nm, rx, y, { size: H * 0.022, color: hex(ink, 0.8), weight: 400, alpha: t }); txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.04, color: c, align: "right", alpha: t });
    });
  },
});
