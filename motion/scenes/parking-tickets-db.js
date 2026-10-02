/* 15 Million Parking Tickets in PostgreSQL. Tickets rain into twelve monthly partitions; camera tickets in one colour. Right: 15.28
   million tickets, $1.2 billion in fines, 35% from cameras, and the school-zone speed camera as the single biggest ticket (25%). */
scene({
  slug: "parking-tickets-db", aspect: 1.72, seconds: 6, bg: ["#0f1118", "#04050a"],
  init(W, H, { rng }) { const r = rng(17), d = []; for (let i = 0; i < 420; i++) d.push({ m: Math.floor(r() * 12), cam: r() < 0.35, t: r() * 0.55, x: r() }); return { d }; },
  draw(g, u, W, H, S, { seg, ease, hex, txt, rr, lerp }) {
    const ink = "#eef0f8", CAM = "#ffcc33", OFF = "#5c9dff", x0 = W * 0.05, pw = W * 0.038, base = H * 0.86;
    txt(g, "MONTHLY PARTITIONS · tickets_2025_01 … _12", x0, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2 });
    const fill = Array(12).fill(0);
    for (let m = 0; m < 12; m++) { g.strokeStyle = hex(ink, 0.2); g.lineWidth = 1.5; rr(g, x0 + m * pw, H * 0.24, pw - 6, base - H * 0.24, 6); g.stroke(); }
    S.d.forEach((p) => {
      const t = ease.in3(seg(u, 0.05 + p.t, 0.13 + p.t)); if (t <= 0) return;
      const slot = t >= 1 ? fill[p.m]++ : fill[p.m], y = lerp(H * 0.17, base - 6 - slot * 3.4, t), x = x0 + p.m * pw + 4 + p.x * (pw - 16);
      g.fillStyle = p.cam ? CAM : OFF; g.fillRect(x, y, 5, 3);
    });
    const rx = W * 0.6;
    const k = ease.out5(seg(u, 0.3, 0.6));
    txt(g, "TICKETS IN A YEAR", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, (15.28 * k).toFixed(2) + "M", rx, H * 0.27, { size: H * 0.12, color: "#fff", spacing: -3 });
    txt(g, "$1.2 billion in fines at face value", rx, H * 0.34, { size: H * 0.028, color: hex(ink, 0.7), weight: 400, alpha: k });
    [["From cameras", 35, CAM], ["School-zone speed camera", 25, CAM]].forEach(([n, v, c], i) => {
      const y = H * 0.46 + i * H * 0.15, t = ease.out5(seg(u, 0.55 + i * 0.07, 0.75 + i * 0.07));
      txt(g, n, rx, y + H * 0.03, { size: H * 0.03, color: hex(ink, 0.85), weight: 400 });
      txt(g, Math.round(v * t) + "%", rx + W * 0.34, y + H * 0.03, { size: H * 0.036, color: c, align: "right" });
      g.fillStyle = hex(ink, 0.07); rr(g, rx, y + H * 0.055, W * 0.34, H * 0.02, 10); g.fill();
      g.fillStyle = c; rr(g, rx, y + H * 0.055, Math.max(0.001, W * 0.34 * v / 100 * t), H * 0.02, 10); g.fill();
    });
    txt(g, "camera", rx, H * 0.86, { size: H * 0.024, color: CAM }); txt(g, "officer", rx + W * 0.08, H * 0.86, { size: H * 0.024, color: OFF });
  },
});
