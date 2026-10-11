/* The Planet Is Speaking in Data. Left: one temperature record (schematic bars, no axis values) redrawn as the zero line slides between the
   1951-1980 and 1991-2020 baselines: the picture is the same, only the zero moves, a constant +0.611 C shift. Right: 2025 ranks 2nd of 146 years;
   trend 0.207 C/decade (0.177 to 0.236); GISTEMP and HadCRUT5 correlate at 0.992. Every figure is on the project page. */
const CSO_N = 56, CSO = Array.from({ length: CSO_N }, (_, i) => 0.1 + 0.8 * (i / (CSO_N - 1)) + 0.07 * Math.sin(i * 0.9) + 0.05 * Math.sin(i * 2.3 + 1));
scene({
  slug: "climate-signal-observatory", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, _S, { seg, ease, hex, txt, line, rr }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0";
    const x0 = W * 0.06, x1 = W * 0.58, y0 = H * 0.2, y1 = H * 0.82, bw = (x1 - x0) / CSO_N;
    const Y = (v) => y1 - v * (y1 - y0);
    // zero line: 1951-1980 (low) -> 1991-2020 (high) and back; the series never changes
    const p = ease.inOut(seg(u, 0.12, 0.4)) - ease.inOut(seg(u, 0.62, 0.9));
    const z = 0.28 + 0.34 * p, grow = ease.out3(seg(u, 0, 0.1));
    txt(g, "ONE RECORD, TWO ZEROES", x0, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, "SCHEMATIC", x1, H * 0.12, { size: H * 0.02, color: hex(ink, 0.4), spacing: 2, align: "right" });
    CSO.forEach((v, i) => {
      const yv = Y(z + (v - z) * grow), yz = Y(z), up = v > z;
      g.fillStyle = up ? ORG : BL; g.fillRect(x0 + i * bw, Math.min(yv, yz), bw * 0.78, Math.abs(yv - yz));
    });
    line(g, x0, Y(z), x1, Y(z), hex(ink, 0.7), 1.5);
    txt(g, p < 0.5 ? "ZERO = 1951-1980" : "ZERO = 1991-2020", x1, Y(z) + H * 0.05, { size: H * 0.026, color: ink, weight: 500, align: "right" });
    txt(g, "Shift +0.611 °C, a constant", x0, H * 0.93, { size: H * 0.03, color: ORG });
    const rx = W * 0.67, rw = W * 0.28;
    txt(g, "WHAT THE RECORD SHOWS", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["2025 rank in 146 years", "2nd", ORG], ["Trend since 1975", "0.207 °C/decade", ORG], ["GISTEMP vs HadCRUT5", "r = 0.992", BL]].forEach(([nm, v, c], i) => {
      const y = H * 0.3 + i * H * 0.2, t = ease.out5(seg(u, 0.45 + i * 0.08, 0.65 + i * 0.08));
      line(g, rx, y - H * 0.06, rx + rw, y - H * 0.06, hex(ink, 0.12), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + rw, y + H * 0.07, { size: H * 0.05, color: c, align: "right", alpha: t });
    });
  },
});
