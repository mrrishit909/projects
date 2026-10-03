/* Is the World's Warming Speeding Up? Each bar is one year's global temperature, 1880 to 2025, against the 1951-1980 average (NASA GISTEMP); blue is below it and orange above. Right: the warming
   rate per decade, 0.04 degrees C before 1970 and 0.27 from 2000 to 2025; the warmest year is 2024 at +1.29; the eleven warmest years are 2015 to 2025; carbon dioxide's yearly rise went
   from 0.86 ppm in the 1960s to 2.62 from 2020 to 2025. */
const A = [-0.18,-0.09,-0.12,-0.18,-0.29,-0.34,-0.32,-0.37,-0.18,-0.11,-0.36,-0.23,-0.28,-0.32,-0.31,-0.23,-0.12,-0.12,-0.28,-0.18,-0.09,-0.16,-0.29,-0.38,-0.48,-0.27,-0.23,-0.39,-0.43,-0.49,-0.44,-0.45,-0.37,-0.36,-0.17,-0.15,-0.37,-0.46,-0.3,-0.28,-0.28,-0.19,-0.29,-0.27,-0.27,-0.22,-0.11,-0.22,-0.2,-0.36,-0.16,-0.09,-0.16,-0.29,-0.13,-0.2,-0.15,-0.03,-0.01,-0.02,0.12,0.18,0.06,0.09,0.2,0.09,-0.07,-0.03,-0.11,-0.11,-0.18,-0.07,0.01,0.08,-0.13,-0.14,-0.19,0.05,0.06,0.03,-0.02,0.06,0.03,0.05,-0.2,-0.11,-0.06,-0.02,-0.08,0.05,0.03,-0.08,0.01,0.16,-0.07,-0.01,-0.1,0.18,0.07,0.16,0.26,0.32,0.14,0.31,0.16,0.12,0.18,0.32,0.39,0.27,0.45,0.41,0.22,0.23,0.32,0.45,0.33,0.47,0.61,0.38,0.39,0.53,0.63,0.62,0.53,0.68,0.64,0.66,0.54,0.66,0.72,0.61,0.65,0.68,0.75,0.9,1.01,0.92,0.85,0.98,1.01,0.85,0.89,1.17,1.29,1.19];
scene({
  slug: "climate-warming-signal", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0";
    const x0 = W * 0.1, x1 = W * 0.58, y0 = H * 0.2, y1 = H * 0.8, bw = (x1 - x0) / A.length;
    const X = (i) => x0 + i * bw, Y = (v) => y1 - (v + 0.6) / 2.0 * (y1 - y0);
    txt(g, "GLOBAL TEMPERATURE BY YEAR (°C)", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [[-0.5, "−0.5"], [0, "0"], [0.5, "0.5"], [1, "1.0"]].forEach(([v, l]) => { line(g, x0, Y(v), x1, Y(v), hex(ink, v === 0 ? 0.35 : 0.08), 1); txt(g, l, x0 - H * 0.015, Y(v) + H * 0.008, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    [1900, 1950, 2000].forEach((yr) => txt(g, String(yr), X(yr - 1880) + bw / 2, y1 + H * 0.055, { size: H * 0.021, color: hex(ink, 0.45), align: "center" }));
    const n = Math.floor(A.length * ease.out3(seg(u, 0.04, 0.55)));
    for (let i = 0; i < n; i++) { g.fillStyle = A[i] > 0 ? ORG : BL; const yv = Y(A[i]), y00 = Y(0); g.fillRect(X(i), Math.min(yv, y00), bw * 0.78, Math.abs(yv - y00)); }
    const rx = W * 0.67, rw = W * 0.28, k = ease.inOut(seg(u, 0.5, 0.76));
    txt(g, "WARMING PER DECADE", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, (0.04 + (0.27 - 0.04) * k).toFixed(2) + "°", rx, H * 0.29, { size: H * 0.13, color: k > 0.5 ? ORG : BL, spacing: -3 });
    txt(g, k < 0.5 ? "1880 to 1969" : "2000 to 2025", rx, H * 0.345, { size: H * 0.026, color: hex(ink, 0.7), weight: 400 });
    [["Warmest year", "2024: +1.29 °C", ORG], ["The 11 warmest years", "2015–2025", ink], ["CO2 rise a year, 1960s → 2020s", "0.86 → 2.62 ppm", BL]].forEach(([nm, v, c], i) => {
      const y = H * 0.54 + i * H * 0.14, t = ease.out5(seg(u, 0.64 + i * 0.07, 0.82 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.038, color: c, align: "right", alpha: t });
    });
  },
});
