/* Where Do Bengaluru's Food Places Cluster? Bars: OpenStreetMap food places per km2 by distance from the centre, 47 within 2 km down to 4 beyond 15 km, against 9.3 for the whole city (6,681 places, 719 km2).
   Right: the nearest other place is 60 m away on average against 165 m for random points in the city; 45% of the places carry a cuisine tag; chains (names repeated 5 or more times) are 21% of named places. */
const DENS = [47.3, 15.0, 13.5, 5.0, 4.0], WHOLE = 9.3, LAB = ["0-2", "2-5", "5-10", "10-15", "15+"];
scene({
  slug: "bengaluru-restaurants", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#46c28a";
    const x0 = W * 0.09, x1 = W * 0.54, y0 = H * 0.2, y1 = H * 0.78, N = DENS.length, bw = (x1 - x0) / N, Y = (v) => y1 - (y1 - y0) * v / 50;
    txt(g, "FOOD PLACES PER KM\u00b2, BY DISTANCE FROM THE CENTRE", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [0, 10, 20, 30, 40, 50].forEach((v) => { line(g, x0 - H * 0.01, Y(v), x1, Y(v), hex(ink, v === 0 ? 0.25 : 0.07), 1); txt(g, String(v), x0 - H * 0.02, Y(v) + H * 0.007, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    DENS.forEach((v, i) => {
      const t = ease.out5(seg(u, 0.05 + i * 0.08, 0.35 + i * 0.08)), h = (y1 - Y(v)) * t, bx = x0 + i * bw + bw * 0.16;
      rr(g, bx, y1 - h, bw * 0.68, h, H * 0.004); g.fillStyle = i === 0 ? ORG : BL; g.fill();
      txt(g, v.toFixed(0), bx + bw * 0.34, y1 - h - H * 0.02, { size: H * 0.03, color: ink, align: "center", alpha: t });
      txt(g, LAB[i] + " km", x0 + i * bw + bw / 2, y1 + H * 0.05, { size: H * 0.02, color: hex(ink, 0.4), align: "center" });
    });
    const tw = ease.out5(seg(u, 0.5, 0.65)); g.save(); g.setLineDash([H * 0.012, H * 0.01]); line(g, x0, Y(WHOLE), x0 + (x1 - x0) * tw, Y(WHOLE), GR, H * 0.003); g.restore();
    txt(g, "whole city: " + WHOLE.toFixed(1), x1, Y(WHOLE) - H * 0.02, { size: H * 0.021, color: GR, align: "right", alpha: tw });
    const rx = W * 0.64, rw = W * 0.29; txt(g, "6,681 PLACES, 719 KM\u00b2", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Nearest other place, on average", "60 m", BL], ["...for random points in the city", "165 m", ORG], ["Places that say their cuisine", "45%", ink], ["Named places in chains", "21%", GR]].forEach(([nm, v, c], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1); txt(g, nm, rx, y, { size: H * 0.021, color: hex(ink, 0.8), weight: 400, alpha: t }); txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.04, color: c, align: "right", alpha: t });
    });
  },
});
