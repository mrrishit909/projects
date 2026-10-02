/* Do Customer Votes Decide What Gets Built? Suggestion cards (illustrative) with vote counts sort themselves into built / declined / still open;
   the high-vote cards almost never land in declined. Right, from the case study: among suggestions decided after 1-3 years, 13% of
   those with 1-9 votes were built against 84% with 10-49 and 97% with 50-199; 70,257 suggestions; top 100 open waited 10.7 years. */
scene({
  slug: "jira-feature-votes", aspect: 1.72, seconds: 6, bg: ["#0b1020", "#04050c"],
  init(W, H, { rng }) {
    const r = rng(61), cards = [];
    for (let i = 0; i < 20; i++) { const hi = i % 3 === 0, v = hi ? 40 + Math.floor(r() * 900) : Math.floor(r() * 9);
      const dest = hi ? (r() < 0.55 ? 0 : 2) : (r() < 0.15 ? 0 : r() < 0.8 ? 1 : 2); cards.push({ v, dest, t: 0.06 + i * 0.019, x: r() }); }
    return { cards };
  },
  draw(g, u, W, H, S, { seg, ease, hex, txt, rr, lerp, fmt }) {
    const ink = "#e8edfc", GRN = "#3aa57a", ORG = "#d95926", BL = "#3987e5", cols = [["BUILT", GRN], ["DECLINED", ORG], ["STILL OPEN", BL]];
    const x0 = W * 0.04, cw = W * 0.165, top = H * 0.2;
    txt(g, "70,257 CUSTOMER SUGGESTIONS", x0, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    cols.forEach(([n, c], i) => { g.fillStyle = hex(ink, 0.035); rr(g, x0 + i * cw, top, cw - 10, H * 0.72, 12); g.fill();
      txt(g, n, x0 + i * cw + 14, top + H * 0.045, { size: H * 0.022, color: c, spacing: 2 }); });
    const fill = [0, 0, 0];
    S.cards.forEach((c) => {
      const k = ease.inOut(seg(u, c.t, c.t + 0.14)); if (k <= 0) return;
      const slot = k >= 1 ? fill[c.dest]++ : fill[c.dest];
      const tx = x0 + c.dest * cw + 10, ty = top + H * 0.075 + slot * H * 0.064, sx = x0 + c.x * cw * 3, sy = H * 0.06;
      const x = lerp(sx, tx, k), y = lerp(sy, ty, k), hi = c.v >= 10, col = cols[c.dest][1];
      g.save(); g.globalAlpha *= Math.min(1, k * 3); g.fillStyle = hex(ink, 0.08); rr(g, x, y, cw - 30, H * 0.056, 7); g.fill();
      g.fillStyle = col; g.fillRect(x, y + 5, 3, H * 0.056 - 10);
      g.fillStyle = hex(ink, 0.3); rr(g, x + 12, y + H * 0.023, (cw - 30) * 0.42, 5, 2.5); g.fill();
      txt(g, "▲ " + fmt(c.v), x + cw - 40, y + H * 0.037, { size: H * 0.022, color: hi ? "#fff" : hex(ink, 0.45), align: "right", weight: hi ? 500 : 400 });
      g.restore();
    });
    const rx = W * 0.58, rw = W * 0.36;
    txt(g, "BUILT, IF DECIDED AFTER 1–3 YEARS", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["1–9 votes", 13], ["10–49 votes", 84], ["50–199 votes", 97]].forEach(([n, v], i) => {
      const y = H * 0.19 + i * H * 0.13, t = ease.out5(seg(u, 0.45 + i * 0.07, 0.68 + i * 0.07));
      txt(g, n, rx, y + H * 0.03, { size: H * 0.03, color: hex(ink, 0.85), weight: 400 });
      txt(g, Math.round(v * t) + "%", rx + rw, y + H * 0.03, { size: H * 0.036, color: GRN, align: "right" });
      g.fillStyle = hex(ink, 0.07); rr(g, rx, y + H * 0.055, rw, H * 0.02, 10); g.fill();
      g.fillStyle = GRN; rr(g, rx, y + H * 0.055, Math.max(0.001, rw * v / 100 * t), H * 0.02, 10); g.fill();
    });
    const k = ease.out5(seg(u, 0.7, 0.86));
    txt(g, "THE 100 MOST-VOTED OPEN IDEAS HAVE WAITED", rx, H * 0.66, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2, alpha: k });
    txt(g, (10.7 * k).toFixed(1) + " years", rx, H * 0.8, { size: H * 0.1, color: BL, spacing: -2, alpha: k });
  },
});
