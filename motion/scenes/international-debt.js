/* Who Do Developing Countries Owe? Public debt of the reporting countries by creditor, in five snapshots (2005, 2010, 2015, 2020, 2024; the stacked areas
   on the case-study chart): multilateral (green), bilateral (grey), bondholders (orange), banks (blue), other private. Bondholders go from 29% to 46%.
   Right: total external debt $1.8tn (2000) to $8.9tn (2024), owed to China peaked at $157bn in 2021, countries above 20% of exports on debt service 13 to 44. */
scene({
  slug: "international-debt", aspect: 1.72, seconds: 6, bg: ["#0b1412", "#030606"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line }) {
    const ink = "#edf4f1", GRN = "#3aa876", GRY = "#8f918d", ORG = "#ff8a3d", BL = "#4a95f0", DIM = "#5f6a66";
    const Y = [["2005", [31.4, 27.2, 28.8, 9.3, 3.4]], ["2010", [33.4, 24.5, 31.6, 8.4, 2.2]], ["2015", [26.5, 17.6, 42.1, 10.0, 3.9]], ["2020", [24.4, 15.5, 48.7, 8.5, 2.9]], ["2024", [27.8, 13.4, 46.0, 10.3, 2.6]]];
    const C = [GRN, GRY, ORG, BL, DIM], x0 = W * 0.06, x1 = W * 0.58, y0 = H * 0.2, y1 = H * 0.78, gw = (x1 - x0) / Y.length, bw = gw * 0.62;
    txt(g, "WHO LENDS: SHARE OF PUBLIC DEBT", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    Y.forEach(([yr, parts], i) => {
      const t = ease.out3(seg(u, 0.06 + i * 0.09, 0.22 + i * 0.09)), bx = x0 + i * gw + (gw - bw) / 2, tot = parts.reduce((a, b) => a + b, 0);
      let y = y1;
      parts.forEach((p, k) => { const h = (y1 - y0) * p / tot * t; g.fillStyle = C[k]; g.fillRect(bx, y - h, bw, h); if (k === 2 && (i === 0 || i === 4) && t > 0.9) txt(g, Math.round(p) + "%", bx + bw / 2, y - h / 2 + H * 0.01, { size: H * 0.03, color: "#1a0f06", align: "center" }); y -= h; });
      txt(g, yr, bx + bw / 2, y1 + H * 0.05, { size: H * 0.023, color: hex(ink, 0.55), align: "center" });
    });
    line(g, x0, y1 + 1, x1, y1 + 1, hex(ink, 0.25), 1);
    [["multilateral", GRN], ["bilateral", GRY], ["bondholders", ORG], ["banks", BL]].forEach(([s, c], i) => { const lx = x0 + i * W * 0.135; g.fillStyle = c; g.fillRect(lx, H * 0.905, H * 0.022, H * 0.022); txt(g, s, lx + H * 0.035, H * 0.925, { size: H * 0.023, color: hex(ink, 0.7), weight: 400 }); });
    const rx = W * 0.67, rw = W * 0.28, k = ease.out5(seg(u, 0.5, 0.78));
    txt(g, "EXTERNAL DEBT, 120 COUNTRIES", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, "$" + (1.8 + 7.1 * k).toFixed(1) + "tn", rx, H * 0.29, { size: H * 0.13, color: "#fff", spacing: -3 });
    txt(g, "in 2024, up from $1.8tn in 2000", rx, H * 0.345, { size: H * 0.026, color: hex(ink, 0.7), weight: 400, alpha: k });
    [["Owed to China, peak in 2021", "", "$157bn", ORG], ["Countries spending over 20% of exports", "on debt service, 2010 to 2020", "13 → 44", BL], ["Bondholders' share, 2005 to 2024", "", "29% → 46%", ink]].forEach(([n, n2, v, c], i) => {
      const y = H * 0.52 + i * H * 0.14, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.78 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12), 1);
      txt(g, n, rx, y, { size: H * 0.023, color: hex(ink, 0.8), weight: 400, alpha: t });
      if (n2) txt(g, n2, rx, y + H * 0.035, { size: H * 0.023, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.038, color: c, align: "right", alpha: t });
    });
  },
});
