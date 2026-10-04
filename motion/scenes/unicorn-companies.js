/* Do Five Companies Hold Half the Unicorn Value? Wikipedia's list of unicorn startups at three dates: the share of the total valuation held by the 1, 5, 10, 20, 50 and 100 largest companies (October 2026: 18%, 51%, 57%, 63%, 71%, 80%; December 2021 top 10: 25%).
   Right: five companies hold 51% of the value, the US and China 79%, 84% of the valuations are at least 36 months old, and 22% of the December 2021 list is in neither table now. */
const CUR = {"2021-12-31": [5.9, 17.6, 24.7, 32.8, 46.8, 60.3], "2023-12-28": [9.5, 22.6, 28.2, 34.5, 46.5, 59.8], "2026-10-02": [17.9, 51.4, 57.1, 62.7, 71.1, 79.7]}, NS = [1, 5, 10, 20, 50, 100];
scene({
  slug: "unicorn-companies", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#46c28a", GY = "#8d9096";
    const x0 = W * 0.09, x1 = W * 0.53, y0 = H * 0.2, y1 = H * 0.78, X = (n) => x0 + (x1 - x0) * Math.log10(n) / 2, Y = (v) => y1 - (y1 - y0) * v / 100;
    txt(g, "SHARE OF TOTAL VALUATION HELD BY THE N LARGEST", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [0, 25, 50, 75, 100].forEach((v) => { line(g, x0 - H * 0.01, Y(v), x1, Y(v), hex(ink, v === 50 ? 0.25 : 0.07), 1); txt(g, v + "%", x0 - H * 0.02, Y(v) + H * 0.007, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    NS.forEach((n) => txt(g, String(n), X(n), y1 + H * 0.05, { size: H * 0.02, color: hex(ink, 0.4), align: "center" }));
    const draw = (vals, p, col, w) => {
      const q = p * (vals.length - 1), k = Math.floor(q); g.beginPath(); g.moveTo(X(NS[0]), Y(vals[0]));
      for (let i = 1; i <= k && i < vals.length; i++) g.lineTo(X(NS[i]), Y(vals[i]));
      if (k < vals.length - 1) { const t = q - k; g.lineTo(lerp(X(NS[k]), X(NS[k + 1]), t), lerp(Y(vals[k]), Y(vals[k + 1]), t)); }
      g.strokeStyle = col; g.lineWidth = w; g.lineJoin = "round"; g.stroke();
    };
    draw(CUR["2021-12-31"], ease.out5(seg(u, 0.05, 0.28)), "#5d6068", H * 0.004);
    draw(CUR["2023-12-28"], ease.out5(seg(u, 0.2, 0.43)), GY, H * 0.004);
    draw(CUR["2026-10-02"], ease.out5(seg(u, 0.38, 0.66)), BL, H * 0.006);
    const t5 = ease.out5(seg(u, 0.58, 0.72));
    dot(g, X(5), Y(CUR["2026-10-02"][1]), H * 0.011 * t5, ORG); txt(g, "five companies: 51%", X(5) + H * 0.03, Y(CUR["2026-10-02"][1]) - H * 0.025, { size: H * 0.021, color: ORG, align: "left", alpha: t5 });
    [["Dec 2021", "#5d6068"], ["Dec 2023", GY], ["Oct 2026", BL]].forEach(([nm, c], i) => { dot(g, x0 + W * 0.02, y0 + H * (0.03 + i * 0.05), H * 0.008, c); txt(g, nm, x0 + W * 0.035, y0 + H * (0.03 + i * 0.05) + H * 0.007, { size: H * 0.02, color: hex(ink, 0.7) }); });
    const rx = W * 0.64, rw = W * 0.29; txt(g, "WHAT THE LIST HIDES", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Held by the five largest", "51%", BL], ["Of the value in the US and China", "79%", ink], ["Valuations 3+ years old", "84%", ORG], ["Of the 2021 list gone, no record", "22%", GR]].forEach(([nm, v, c], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1); txt(g, nm, rx, y, { size: H * 0.021, color: hex(ink, 0.8), weight: 400, alpha: t }); txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.04, color: c, align: "right", alpha: t });
    });
  },
});
