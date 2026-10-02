/* Drug Safety Signals in MongoDB and PostgreSQL. Report documents drop into two stores at once, a document stack and a table grid;
   then the signal screen's labelled hits on a log scale: semaglutide-nausea ROR 4.0, dupilumab-conjunctivitis 8.6,
   lisinopril-angioedema 82.8, metformin-lactic acidosis 531 (9 of 10 labelled reactions flagged). */
scene({
  slug: "drug-events-mongo-postgres", aspect: 1.72, seconds: 6, bg: ["#0d1416", "#030607"],
  init(W, H, { rng }) { const r = rng(9), docs = []; for (let i = 0; i < 18; i++) docs.push({ t: 0.04 + i * 0.024, side: i % 2, x: r() }); return { docs }; },
  draw(g, u, W, H, S, { seg, ease, hex, txt, rr, lerp, line }) {
    const ink = "#e9f4f4", MG = "#4fd18b", PG = "#5c9dff", AMB = "#ffc35a";
    txt(g, "422,456 REPORTS, LOADED TWICE", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    const bx = [W * 0.08, W * 0.31], by = H * 0.56, bw = W * 0.19, bh = H * 0.3;
    [["MongoDB · documents", MG], ["PostgreSQL · tables", PG]].forEach(([n, c], s) => {
      g.strokeStyle = hex(c, 0.6); g.lineWidth = 2; rr(g, bx[s], by, bw, bh, 12); g.stroke();
      txt(g, n, bx[s], by + bh + H * 0.05, { size: H * 0.026, color: c });
      if (s) for (let r = 1; r < 6; r++) line(g, bx[s] + 8, by + r * bh / 6, bx[s] + bw - 8, by + r * bh / 6, hex(c, 0.25), 1);
      if (s) for (let q = 1; q < 4; q++) line(g, bx[s] + q * bw / 4, by + 8, bx[s] + q * bw / 4, by + bh - 8, hex(c, 0.25), 1);
    });
    let filled = [0, 0];
    S.docs.forEach((d) => {
      const t = ease.inOut(seg(u, d.t, d.t + 0.12)); if (t <= 0) return;
      const s = d.side, tx = bx[s] + 12 + (filled[s] % 3) * (bw - 24) / 3, ty = by + bh - 16 - Math.floor(filled[s] / 3) * 16;
      if (t >= 1) filled[s]++;
      const x = lerp(W * 0.18 + d.x * W * 0.2, tx, t), y = lerp(H * 0.2, ty, t);
      g.fillStyle = hex(s ? PG : MG, 0.8); rr(g, x, y, (bw - 30) / 3, 11, 3); g.fill();
    });
    const rx = W * 0.58, rw = W * 0.36, L = (v) => Math.log10(v) / Math.log10(600);
    txt(g, "REPORTING ODDS RATIO, LOG SCALE", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Semaglutide · nausea", 4.0], ["Dupilumab · conjunctivitis", 8.6], ["Lisinopril · angioedema", 82.8], ["Metformin · lactic acidosis", 531]].forEach(([n, v], i) => {
      const y = H * 0.2 + i * H * 0.13, t = ease.out5(seg(u, 0.42 + i * 0.06, 0.66 + i * 0.06));
      txt(g, n, rx, y + H * 0.028, { size: H * 0.028, color: hex(ink, 0.85), weight: 400 });
      txt(g, v >= 100 ? String(Math.round(v * t)) : (v * t).toFixed(1), rx + rw, y + H * 0.028, { size: H * 0.03, color: AMB, align: "right", alpha: t });
      g.fillStyle = hex(ink, 0.07); rr(g, rx, y + H * 0.045, rw, H * 0.014, 7); g.fill();
      g.fillStyle = AMB; rr(g, rx, y + H * 0.045, Math.max(0.001, rw * L(v) * t), H * 0.014, 7); g.fill();
    });
    const k = ease.out5(seg(u, 0.7, 0.86));
    txt(g, "9 of 10", rx, H * 0.8, { size: H * 0.09, color: "#fff", spacing: -2, alpha: k });
    txt(g, "reactions already on the drug labels were flagged", rx, H * 0.88, { size: H * 0.028, color: hex(ink, 0.7), weight: 400, alpha: k });
  },
});
