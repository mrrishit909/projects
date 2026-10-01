/* E-mail A/B test: customers are assigned at random (a fair test), regroup by e-mail received, and the ones who visit light up.
   Visit rates are the case study's: 10.6% with no e-mail, +7.7 pts for the men's e-mail, +4.5 pts for the women's. */
scene({
  slug: "email-ab-test", aspect: 1.701, seconds: 6, bg: ["#0d1218", "#04070a"],
  init(W, H, { rng }) {
    const r = rng(9), N = 240, dots = [], rates = [0.106, 0.183, 0.151], cnt = [0, 0, 0];
    for (let i = 0; i < N; i++) {
      const gI = i % 3, k = cnt[gI]++;
      dots.push({ g: gI, k, mx: i % 24, my: Math.floor(i / 24), visit: r() < rates[gI] * 1.0, jx: r(), jy: r(), order: r() });
    }
    // shuffle the mixed grid so the groups interleave
    const slots = dots.map((_, i) => i).sort(() => r() - 0.5); dots.forEach((d, i) => { d.mx = slots[i] % 24; d.my = Math.floor(slots[i] / 24); });
    // make the visit counts exact for the picture
    [0, 1, 2].forEach((gI) => { const mine = dots.filter((d) => d.g === gI); mine.forEach((d) => (d.visit = false)); mine.sort((a, b) => a.order - b.order).slice(0, Math.round(80 * rates[gI])).forEach((d) => (d.visit = true)); });
    return { dots, rates };
  },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, dot, rr }) {
    const COL = ["#8794a3", "#4ea3ff", "#ff7a66"], NAME = ["NO E-MAIL", "MEN'S E-MAIL", "WOMEN'S E-MAIL"], ink = "#e9f1fb";
    const gx = W * 0.05, gw = W * 0.58, mixTop = H * 0.16, mixH = H * 0.7;
    const mixP = (d) => [gx + (d.mx + 0.5) * (gw / 24), mixTop + (d.my + 0.5) * (mixH / 10)];
    const clus = (d) => { const cw = gw / 3, cx = gx + d.g * cw + cw * 0.1, cols = 8, step = (cw * 0.8) / cols; return [cx + (d.k % cols + 0.5) * step, mixTop + H * 0.1 + (Math.floor(d.k / cols) + 0.5) * step]; };
    const colorT = ease.out3(seg(u, 0.1, 0.28)), moveT = ease.inOut(seg(u, 0.3, 0.5)), litT = seg(u, 0.52, 0.66);
    txt(g, u < 0.3 ? "64,000 CUSTOMERS, ASSIGNED AT RANDOM" : "WHO VISITED THE SITE", gx, H * 0.09, { size: H * 0.027, color: hex(ink, 0.55), spacing: 2.5 });
    S.dots.forEach((d) => {
      const a = mixP(d), b = clus(d), x = lerp(a[0], b[0], moveT), y = lerp(a[1], b[1], moveT);
      const base = hex(ink, 0.22), col = colorT > 0 ? COL[d.g] : ink;
      const pop = ease.out3(seg(u, 0.04 + (d.mx + d.my) * 0.004, 0.14 + (d.mx + d.my) * 0.004)); if (pop <= 0) return;
      const lit = d.visit && litT > 0 ? ease.back(litT) : 0;
      g.save(); g.globalAlpha *= pop * (litT > 0 ? (d.visit ? 1 : 0.35) : 1);
      dot(g, x, y, H * 0.0105 * (1 + lit * 0.35), colorT > 0.5 ? col : base, lit > 0 ? col : null); g.restore();
    });
    if (moveT > 0.3) [0, 1, 2].forEach((gI) => { const cw = gw / 3; txt(g, NAME[gI], gx + gI * cw + cw * 0.1, mixTop + H * 0.06, { size: H * 0.024, color: COL[gI], spacing: 1.8, alpha: seg(moveT, 0.3, 0.9) }); });
    // result bars with whiskers
    const bx = W * 0.7, bw = W * 0.24, bt = ease.out5(seg(u, 0.66, 0.86));
    txt(g, "VISITED", bx, H * 0.16, { size: H * 0.026, color: hex(ink, 0.5), spacing: 2.5 });
    S.rates.forEach((rt, i) => {
      const y = H * 0.27 + i * H * 0.2, w = bw * (rt / 0.2) * bt;
      g.fillStyle = hex(ink, 0.07); rr(g, bx, y, bw, H * 0.065, H * 0.014); g.fill();
      g.fillStyle = COL[i]; rr(g, bx, y, Math.max(0.001, w), H * 0.065, H * 0.014); g.fill();
      const err = bw * 0.03 * bt; line(g, bx + w + 6, y + H * 0.0325, bx + w + 6 + err, y + H * 0.0325, hex(ink, 0.7), 2); line(g, bx + w + 6 + err, y + H * 0.02, bx + w + 6 + err, y + H * 0.045, hex(ink, 0.7), 2);
      txt(g, (rt * 100).toFixed(1) + "%", bx, y - H * 0.012, { size: H * 0.036, color: COL[i], alpha: bt });
    });
  },
});
