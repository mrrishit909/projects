/* Where Did the Fuel-Economy Gains Go? A waterfall from the case study: engine technology cut fuel use 14.4% at the same size,
   heavier and more powerful vehicles took it back, net -5.8%; 61% of the technology gain was taken back. */
scene({
  slug: "fuel-economy", aspect: 1.74, seconds: 6, bg: ["#0b1410", "#040806"],
  draw(g, u, W, H, S, { TAU, lerp, seg, ease, hex, txt, line, dot, rr }) {
    const GRN = "#4fe3a0", ORG = "#ff9a52", ink = "#e6f5ee", x0 = W * 0.07, pw = W * 0.58, top = H * 0.18, ph = H * 0.62, base = top + ph;
    // index 100 = fuel used in 2013, multiplicative steps
    const steps = [["2013", null, 100], ["Technology", -14.4], ["Heavier", 2.6], ["More power", 5.8], ["Body & drive", 1.3], ["2025", null]];
    let v = 100; const bars = [];
    steps.forEach(([name, d, abs], i) => { if (abs) { bars.push({ name, lo: 0, hi: abs, col: hex(ink, 0.7), end: abs }); return; } if (d == null) { bars.push({ name, lo: 0, hi: v, col: "#fff", end: v, final: true }); return; } const nv = v * (1 + d / 100); bars.push({ name, lo: Math.min(v, nv), hi: Math.max(v, nv), col: d < 0 ? GRN : ORG, d, end: nv }); v = nv; });
    const Y = (val) => base - ((val - 80) / 22) * ph, n = bars.length, bw = pw / n * 0.62;
    line(g, x0, base, x0 + pw, base, hex(ink, 0.3));
    bars.forEach((b, i) => {
      const k = ease.out5(seg(u, 0.1 + i * 0.1, 0.24 + i * 0.1)); if (k <= 0) return;
      const x = x0 + (i / n) * pw + (pw / n - bw) / 2, lo = Math.max(80, b.lo), top2 = Y(b.hi), bot = Y(lo);
      const h = (bot - top2) * k; g.fillStyle = b.col; rr(g, x, bot - h, bw, h, 6); g.fill();
      if (i > 0) { const prev = bars[i - 1]; line(g, x - (pw / n - bw), Y(prev.end), x, Y(prev.end), hex(ink, 0.25), 1.5, [3, 4]); }
      const lab = b.d != null ? (b.d > 0 ? "+" : "−") + Math.abs(b.d) + "%" : b.final ? "−5.8%" : "";
      if (lab && k > 0.8) txt(g, lab, x + bw / 2, bot - h - H * 0.02, { size: H * 0.036, color: b.final ? "#fff" : b.col, align: "center" });
      txt(g, b.name.toUpperCase(), x + bw / 2, base + H * 0.05, { size: H * 0.02, color: hex(ink, 0.5), align: "center", spacing: 1.2 });
    });
    // ring: how much of the gain was taken back
    const cx = W * 0.82, cy = H * 0.46, R = H * 0.17, t = ease.out5(seg(u, 0.64, 0.9));
    g.lineWidth = H * 0.045; g.strokeStyle = hex(ink, 0.1); g.beginPath(); g.arc(cx, cy, R, 0, TAU); g.stroke();
    g.strokeStyle = ORG; g.lineCap = "round"; g.beginPath(); g.arc(cx, cy, R, -Math.PI / 2, -Math.PI / 2 + TAU * 0.61 * t); g.stroke(); g.lineCap = "butt";
    txt(g, Math.round(61 * t) + "%", cx, cy + H * 0.025, { size: H * 0.085, color: "#fff", align: "center", spacing: -2 });
    txt(g, "OF THE GAIN", cx, cy + R + H * 0.085, { size: H * 0.024, color: hex(ink, 0.55), align: "center", spacing: 2.5, alpha: t }); txt(g, "TAKEN BACK", cx, cy + R + H * 0.12, { size: H * 0.024, color: ORG, align: "center", spacing: 2.5, alpha: t });
    txt(g, "FUEL USED, 2013 = 100", x0, H * 0.09, { size: H * 0.025, color: hex(ink, 0.5), spacing: 2.5 });
  },
});
