/* Does One Barcode Cost the Same Everywhere? Volunteers' shelf prices from Open Prices (Open Food Facts, ODbL), France, euro, 2025 on: the same barcode is a median 12.2% dearer in the dearest of 2 or more shops; fitting a shop effect removes 60% of the within-barcode variance and the median gap falls to 7.6%.
   Left: chain price levels against the same barcodes elsewhere, from -11% (E.Leclerc) to +27% (Franprix). Right: the gap, the share the shop explains, and across barcodes the 3.1% that pack size adds to category's 43.5%. */
const NAMES = ["Franprix", "Monoprix", "G20", "Carrefour", "Syst\u00e8me U", "Match", "Auchan", "Intermarch\u00e9", "E.Leclerc"], VALS = [26.9, 14.4, 10.5, 5.0, 2.9, 2.6, -0.3, -2.2, -11.0];
scene({
  slug: "open-prices", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#46c28a";
    const x0 = W * 0.2, x1 = W * 0.55, y0 = H * 0.2, y1 = H * 0.8, N = VALS.length, lo = -15, hi = 30, X = (v) => x0 + (x1 - x0) * (v - lo) / (hi - lo), bh = (y1 - y0) / N;
    txt(g, "PRICE LEVEL BY CHAIN, SAME BARCODES", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [-10, 0, 10, 20, 30].forEach((v) => { line(g, X(v), y0 - H * 0.02, X(v), y1, hex(ink, v === 0 ? 0.3 : 0.07), 1); txt(g, (v > 0 ? "+" : "") + v + "%", X(v), y1 + H * 0.05, { size: H * 0.02, color: hex(ink, 0.4), align: "center" }); });
    VALS.forEach((v, i) => {
      const t = ease.out5(seg(u, 0.05 + i * 0.045, 0.3 + i * 0.045)), y = y0 + i * bh, xa = X(0), xb = X(v * t);
      txt(g, NAMES[i], x0 - H * 0.03, y + bh * 0.62, { size: H * 0.022, color: hex(ink, 0.8), align: "right", alpha: Math.min(1, t * 3) });
      g.fillStyle = v < 0 ? GR : ORG; g.globalAlpha = 0.95; g.fillRect(Math.min(xa, xb), y + bh * 0.15, Math.abs(xb - xa), bh * 0.7); g.globalAlpha = 1;
      txt(g, (v > 0 ? "+" : "") + Math.round(v) + "%", v < 0 ? xb - H * 0.012 : xb + H * 0.012, y + bh * 0.62, { size: H * 0.02, color: hex(ink, 0.9), align: v < 0 ? "right" : "left", alpha: t });
    });
    const rx = W * 0.64, rw = W * 0.29; txt(g, "ONE BARCODE, MANY SHOPS", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Dearest over cheapest, median", "12%", BL], ["After the shop's price level", "8%", GR], ["Variance the shop explains", "60%", ORG], ["Pack size adds, across barcodes", "3.1%", ink]].forEach(([nm, v, c], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1); txt(g, nm, rx, y, { size: H * 0.021, color: hex(ink, 0.8), weight: 400, alpha: t }); txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.04, color: c, align: "right", alpha: t });
    });
  },
});
