/* Jira Flow Analytics: a board where tickets flow left to right. Some move; most "in progress" tickets just age and turn red (the case
   study found 305 of 397 stale). Then the flow numbers: cycle time 7 / 60 / 271 days (50/85/95%) and 9.5 fixes a week. */
scene({
  slug: "jira-flow-analytics", aspect: 1.701, seconds: 6, bg: ["#0b1020", "#04050c"],
  init(W, H, { rng }) {
    const r = rng(37), cards = [];
    for (let i = 0; i < 26; i++) { const stale = i % 5 !== 0 && i > 5; cards.push({ col: stale ? 1 : Math.floor(r() * 3), row: i, stale, moveAt: 0.15 + r() * 0.45, w: 0.55 + r() * 0.4 }); }
    return { cards };
  },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, mix, txt, line, rr }) {
    const BL = "#5c8dff", RED = "#ff5f5f", GRN = "#4fdc93", ink = "#e8edfc", bx = W * 0.04, bw = W * 0.6, top = H * 0.14, colW = bw / 4;
    ["TO DO", "IN PROGRESS", "REVIEW", "DONE"].forEach((name, i) => {
      g.fillStyle = hex(ink, 0.035); rr(g, bx + i * colW + 4, top, colW - 8, H * 0.8, 12); g.fill();
      txt(g, name, bx + i * colW + 16, top + H * 0.045, { size: H * 0.022, color: hex(ink, 0.55), spacing: 2 });
    });
    const counts = [0, 0, 0, 0];
    S.cards.forEach((c) => {
      const k = ease.out3(seg(u, 0.03 + c.row * 0.006, 0.1 + c.row * 0.006)); if (k <= 0) return;
      const moving = !c.stale, mv = moving ? ease.inOut(seg(u, c.moveAt, c.moveAt + 0.12)) : 0, from = c.col, to = Math.min(3, c.col + 1);
      const colF = lerp(from, to, mv), slot = counts[Math.round(colF)]++;
      const x = bx + colF * colW + 12, y = top + H * 0.075 + (slot % 9) * H * 0.078, cw = colW - 24;
      const age = c.stale ? ease.inOut(seg(u, 0.2, 0.6)) : 0, col = c.stale ? mix("#5c8dff", "#ff5f5f", age) : to === 3 && mv > 0.9 ? GRN : BL;
      g.save(); g.globalAlpha *= k; g.fillStyle = hex(ink, 0.07); rr(g, x, y, cw, H * 0.062, 8); g.fill();
      g.fillStyle = col; g.fillRect(x, y + 6, 3, H * 0.062 - 12);
      g.fillStyle = hex(ink, 0.35); rr(g, x + 12, y + H * 0.018, (cw - 30) * c.w, 5, 2.5); g.fill(); rr(g, x + 12, y + H * 0.038, (cw - 30) * c.w * 0.5, 5, 2.5); g.fill();
      if (c.stale && age > 0.5) txt(g, Math.round(90 + age * 180) + "d", x + cw - 8, y + H * 0.04, { size: H * 0.02, color: RED, align: "right", alpha: (age - 0.5) * 2 });
      g.restore();
    });
    const rx = W * 0.7, k1 = ease.out5(seg(u, 0.55, 0.75));
    txt(g, "STALE IN PROGRESS", rx, H * 0.16, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, String(Math.round(305 * ease.out5(seg(u, 0.25, 0.6)))), rx, H * 0.3, { size: H * 0.12, color: RED, spacing: -3 }); txt(g, "of 397", rx + W * 0.15, H * 0.3, { size: H * 0.035, color: hex(ink, 0.6), weight: 400 });
    txt(g, "CYCLE TIME (50 / 85 / 95%)", rx, H * 0.45, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5, alpha: k1 });
    [["7", 7], ["60", 60], ["271", 271]].forEach(([lab, v], i) => { const y = H * 0.5 + i * H * 0.085, w = W * 0.22 * Math.sqrt(v / 271) * k1; g.fillStyle = [GRN, "#ffc35a", RED][i]; rr(g, rx, y, Math.max(0.001, w), H * 0.04, 8); g.fill(); txt(g, lab + " days", rx + w + 10, y + H * 0.03, { size: H * 0.028, color: ink, weight: 400, alpha: k1 }); });
    txt(g, "9.5 FIXES A WEEK", rx, H * 0.9, { size: H * 0.026, color: BL, spacing: 2, alpha: seg(u, 0.78, 0.9) });
  },
});
