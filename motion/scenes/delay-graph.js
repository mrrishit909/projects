/* How One Late Plane Delays Its Day. Aircraft rotations as chains of flight nodes; a root delay turns red and the delay walks along
   NEXT links to later legs, fading as turnarounds absorb it. Right: the case study's turnaround table (next flight late: 95.5% under
   40 min ... 41.1% at 120+) and 46.3% of 28,615 root delays spreading. */
scene({
  slug: "delay-graph", aspect: 1.72, seconds: 6, bg: ["#0b1220", "#03060c"],
  init(W, H, { rng }) {
    const r = rng(5), rows = [];
    for (let k = 0; k < 6; k++) rows.push({ root: 1 + Math.floor(r() * 2), spread: Math.floor(r() * 4), start: 0.08 + k * 0.05 });
    return { rows };
  },
  draw(g, u, W, H, S, { seg, ease, hex, mix, txt, line, rr, dot, lerp }) {
    const ink = "#eaf0fb", BL = "#5c8dff", RED = "#ff5f5f", x0 = W * 0.06, x1 = W * 0.5, n = 6;
    txt(g, "ONE AIRCRAFT PER ROW, LEGS IN ORDER", x0, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    S.rows.forEach((row, k) => {
      const y = H * 0.22 + k * H * 0.115, nx = (i) => lerp(x0 + 10, x1, i / (n - 1));
      for (let i = 0; i < n - 1; i++) line(g, nx(i) + 9, y, nx(i + 1) - 9, y, hex(ink, 0.18), 2);
      for (let i = 0; i < n; i++) {
        const d = i - row.root, hit = d === 0 ? seg(u, row.start, row.start + 0.08) : d > 0 && d <= row.spread ? seg(u, row.start + 0.1 + d * 0.07, row.start + 0.16 + d * 0.07) : 0;
        const c = mix(BL, RED, ease.out3(hit) * (d > 0 ? 1 - d * 0.18 : 1));
        dot(g, nx(i), y, d === 0 ? 9 : 7, c, hit > 0.5 ? RED : null);
      }
    });
    const rx = W * 0.58, rw = W * 0.36;
    txt(g, "NEXT FLIGHT LEAVES LATE, BY TURNAROUND", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["< 40 min", 95.5], ["40–54", 92.0], ["55–69", 80.6], ["70–89", 63.3], ["90–119", 48.3], ["120+", 41.1]].forEach(([nm, v], i) => {
      const y = H * 0.19 + i * H * 0.075, t = ease.out5(seg(u, 0.3 + i * 0.04, 0.55 + i * 0.04)), bx = rx + W * 0.08;
      txt(g, nm, rx, y + H * 0.032, { size: H * 0.026, color: hex(ink, 0.75), weight: 400 });
      g.fillStyle = mix(RED, BL, i / 5); rr(g, bx, y + H * 0.008, Math.max(0.001, (rw - W * 0.14) * v / 100 * t), H * 0.034, 6); g.fill();
      txt(g, (v * t).toFixed(1) + "%", rx + rw, y + H * 0.034, { size: H * 0.027, color: ink, align: "right", alpha: t });
    });
    const k2 = ease.out5(seg(u, 0.62, 0.8));
    txt(g, (46.3 * k2).toFixed(1) + "%", rx, H * 0.79, { size: H * 0.1, color: RED, spacing: -2, alpha: k2 });
    txt(g, "of 28,615 root delays spread to later flights", rx, H * 0.87, { size: H * 0.028, color: hex(ink, 0.7), weight: 400, alpha: k2 });
  },
});
