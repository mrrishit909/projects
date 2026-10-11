/* Atlas of Human Mobility. Left: the 263 taxi zones as a ring, with schematic chords drawn between zone pairs (positions are illustrative, not data;
   the site draws zone-to-zone lines and never routes) and 50 zones lit, the ones that account for half of all pickups. Counter: 280,236,580 kept trips.
   Right: 50 of 263 zones, Manhattan at 47.6% of free flow at the weekday AM peak (10.2 of 21.3 mph), weekday peaks 8 AM and 6 PM. All on the project page. */
const AHM_R = (function () { let a = 7; return () => { a = (a * 1664525 + 1013904223) >>> 0; return a / 4294967296; }; })();
const AHM_CH = Array.from({ length: 70 }, () => { const a = Math.floor(AHM_R() * 263); let b = Math.floor(AHM_R() * 263); if (Math.abs(a - b) < 20) b = (a + 70 + Math.floor(AHM_R() * 120)) % 263; return [a, b, AHM_R()]; });
scene({
  slug: "atlas-human-mobility", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, _S, { seg, ease, hex, txt, line, fmt, quad, TAU }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0";
    const cx = W * 0.3, cy = H * 0.54, R = H * 0.34, N = 263;
    const P = (i, r = R) => { const a = (i / N) * TAU - Math.PI / 2; return [cx + Math.cos(a) * r, cy + Math.sin(a) * r]; };
    txt(g, "263 ZONES, ONE RING", W * 0.06, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, "SCHEMATIC", W * 0.54, H * 0.12, { size: H * 0.02, color: hex(ink, 0.4), spacing: 2, align: "right" });
    const lit = ease.inOut(seg(u, 0.5, 0.75)) - ease.inOut(seg(u, 0.88, 1));
    for (let i = 0; i < N; i++) {
      const [x, y] = P(i), [x2, y2] = P(i, R * (i < 50 ? 1.07 : 1.025));
      line(g, x, y, x2, y2, i < 50 ? hex(ORG, 0.25 + 0.75 * lit) : hex(ink, 0.35), i < 50 ? 1.5 : 1);
    }
    AHM_CH.forEach(([a, b, k], i) => {
      const t = ease.out3(seg(u, 0.04 + k * 0.4, 0.28 + k * 0.4)), A = P(a), B = P(b);
      if (t <= 0) return;
      const c = [cx + (A[0] + B[0] - 2 * cx) * 0.12, cy + (A[1] + B[1] - 2 * cy) * 0.12];
      g.save(); g.strokeStyle = hex(BL, 0.12 + 0.5 * k); g.lineWidth = 1; g.beginPath(); g.moveTo(A[0], A[1]);
      for (let j = 1; j <= 24; j++) { const q = quad(A, c, B, (j / 24) * t); g.lineTo(q[0], q[1]); }
      g.stroke(); g.restore();
    });
    const n = Math.round(280236580 * ease.out3(seg(u, 0.08, 0.5)));
    txt(g, fmt(n), cx, cy + H * 0.015, { size: H * 0.058, color: ink, align: "center", weight: 500 });
    txt(g, "KEPT TRIPS, 2024", cx, cy + H * 0.07, { size: H * 0.022, color: hex(ink, 0.55), align: "center", spacing: 2 });
    const rx = W * 0.64, rw = W * 0.31;
    txt(g, "WHAT THE DATA SHOWS", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Zones for half of pickups", "50 of 263", ORG], ["Manhattan, AM peak, vs free flow", "47.6%", BL], ["Weekday peaks", "8 AM and 6 PM", ORG]].forEach(([nm, v, c], i) => {
      const y = H * 0.3 + i * H * 0.2, t = ease.out5(seg(u, 0.45 + i * 0.08, 0.65 + i * 0.08));
      line(g, rx, y - H * 0.06, rx + rw, y - H * 0.06, hex(ink, 0.12), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + rw, y + H * 0.07, { size: H * 0.05, color: c, align: "right", alpha: t });
    });
  },
});
