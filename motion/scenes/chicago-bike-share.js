/* How Chicago Rides: 6.1M trips. Members (blue) commute on the grid; casual riders (orange) hug the lakefront.
   The hourly chart underneath is the case study's finding: members peak at 8:00 and 17:00, casual riders have no morning peak. */
scene({
  slug: "chicago-bike-share", aspect: 1.838, seconds: 6, bg: ["#0b1119", "#04070b"],
  init(W, H, { rng, gauss }) {
    const r = rng(3), mapH = H * 0.66, stations = [];
    for (let i = 0; i < 90; i++) {
      const lake = r() < 0.4, x = lake ? 0.62 + r() * 0.24 : 0.04 + r() * 0.8;
      stations.push({ x: x * W, y: (0.06 + r() * 0.9) * mapH, lake });
    }
    const trips = [];
    for (let i = 0; i < 46; i++) {
      const casual = i % 3 === 0, pool = stations.filter((s) => (casual ? s.lake || r() < 0.2 : true));
      const a = pool[Math.floor(r() * pool.length)], b = pool[Math.floor(r() * pool.length)];
      trips.push({ a, b, casual, off: r(), cyc: 2, bend: (r() - 0.5) * 140 });
    }
    return { stations, trips, mapH };
  },
  draw(g, u, W, H, S, { TAU, lerp, seg, ease, hex, txt, line, dot, quad, wrap01, rr }) {
    const MB = "#4aa3ff", CO = "#ff7d3e", ink = "#e9f0f8", mapH = S.mapH;
    // lake on the east edge
    const lg = g.createLinearGradient(W * 0.9, 0, W, 0); lg.addColorStop(0, "rgba(20,70,130,0)"); lg.addColorStop(1, "rgba(30,100,170,0.35)");
    g.fillStyle = lg; g.fillRect(W * 0.9, 0, W * 0.1, mapH);
    // street grid
    for (let x = 0; x < W * 0.92; x += W / 22) line(g, x, 0, x, mapH, hex(ink, 0.04)); for (let y = 0; y < mapH; y += mapH / 12) line(g, 0, y, W, y, hex(ink, 0.04));
    S.stations.forEach((s) => dot(g, s.x, s.y, 2.6, hex(ink, 0.38)));
    S.trips.forEach((t) => {
      const p = wrap01(u * t.cyc + t.off), vis = Math.sin(p * Math.PI), col = t.casual ? CO : MB;
      const c = [(t.a.x + t.b.x) / 2 + t.bend * 0.4, (t.a.y + t.b.y) / 2 + t.bend];
      g.save(); g.globalAlpha *= vis; g.strokeStyle = hex(col, 0.6); g.lineWidth = 2.2; g.beginPath();
      const head = Math.min(1, p * 1.25), tail = Math.max(0, head - 0.3);
      for (let k = 0; k <= 14; k++) { const q = quad([t.a.x, t.a.y], c, [t.b.x, t.b.y], lerp(tail, head, k / 14)); k ? g.lineTo(q[0], q[1]) : g.moveTo(q[0], q[1]); } g.stroke();
      const h = quad([t.a.x, t.a.y], c, [t.b.x, t.b.y], head); dot(g, h[0], h[1], 5.5, col, col); g.restore();
    });
    // hourly profile: members (two commute peaks) vs casual (one afternoon hump); a cursor sweeps the day
    const cx = W * 0.07, cw = W * 0.58, cy = H * 0.97, ch = H * 0.24;
    const mem = (h) => 0.18 + 0.82 * (Math.exp(-((h - 8) ** 2) / 2.6) + 1.05 * Math.exp(-((h - 17) ** 2) / 3.4)) * 0.9, cas = (h) => 0.1 + 0.62 * Math.exp(-((h - 15) ** 2) / 22);
    const now = u * 24, bt = ease.out3(seg(u, 0.04, 0.2));
    for (let h = 0; h < 24; h++) {
      const bx = cx + (h / 24) * cw, bw = (cw / 24) * 0.38, hot = Math.abs(now - h - 0.5) < 1.2 ? 1 : 0.55;
      g.fillStyle = hex(MB, 0.9 * hot); g.fillRect(bx, cy - mem(h) * ch * bt, bw, mem(h) * ch * bt);
      g.fillStyle = hex(CO, 0.9 * hot); g.fillRect(bx + bw + 1, cy - cas(h) * ch * bt, bw, cas(h) * ch * bt);
    }
    line(g, cx, cy, cx + cw, cy, hex(ink, 0.3)); line(g, cx + (now / 24) * cw, cy - ch * 1.05, cx + (now / 24) * cw, cy, hex(ink, 0.7), 1.5);
    const hr = Math.floor(now); txt(g, `${((hr + 11) % 12) + 1}:00 ${hr < 12 ? "AM" : "PM"}`, cx + (now / 24) * cw + 8, cy - ch * 1.02, { size: H * 0.03, color: ink, weight: 500 });
    txt(g, "MEMBERS", W - W * 0.2, H * 0.84, { size: H * 0.028, color: MB, spacing: 2 }); txt(g, "CASUAL", W - W * 0.2, H * 0.89, { size: H * 0.028, color: CO, spacing: 2 });
    txt(g, "6.1M RIDES", W - W * 0.2, H * 0.95, { size: H * 0.028, color: hex(ink, 0.45), spacing: 2, weight: 400 });
  },
});
