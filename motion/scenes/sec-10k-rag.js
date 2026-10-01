/* Ask the 10-K: a question retrieves the passages behind the answer, which cites them; a second question the reports can't answer
   gets an honest refusal ("says when the answer isn't there"). */
scene({
  slug: "sec-10k-rag", aspect: 1.614, seconds: 6, bg: ["#0d1120", "#04060d"],
  init(W, H, { rng }) { const r = rng(8), lines = Array.from({ length: 30 }, () => 0.55 + r() * 0.45); return { lines }; },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, dot, rr, quad }) {
    const BL = "#6aa8ff", AM = "#ffc46b", ink = "#e8eefc", second = u > 0.58;
    // the filing: two stacked pages
    const px = W * 0.05, py = H * 0.1, pw = W * 0.4, ph = H * 0.8;
    g.fillStyle = hex(ink, 0.04); rr(g, px + 12, py - 10, pw, ph, 12); g.fill(); g.fillStyle = hex(ink, 0.07); rr(g, px, py, pw, ph, 12); g.fill(); g.strokeStyle = hex(ink, 0.16); g.lineWidth = 1.5; rr(g, px, py, pw, ph, 12); g.stroke();
    txt(g, "ANNUAL REPORT · 10-K", px + 24, py + H * 0.05, { size: H * 0.023, color: hex(ink, 0.5), spacing: 2.5 });
    const hits = second ? [] : [4, 11, 18], lh = (ph - H * 0.12) / 30;
    S.lines.forEach((w, i) => {
      const y = py + H * 0.09 + i * lh, hit = hits.includes(i) || hits.includes(i - 1), k = hit ? ease.out3(seg(u, 0.28, 0.4)) : 0;
      if (k > 0) { g.fillStyle = hex(BL, 0.22 * k); rr(g, px + 14, y - 7, pw - 28, lh * (hits.includes(i) ? 2 : 1) - 2, 5); g.fill(); }
      g.fillStyle = hex(ink, hit && k > 0 ? 0.55 : 0.2); rr(g, px + 24, y, (pw - 48) * w, 5, 2.5); g.fill();
    });
    // question + answer
    const qx = W * 0.52, qw = W * 0.43, q = second ? "Will the stock rise next year?" : "What are the biggest risks?", t = second ? seg(u, 0.6, 0.7) : seg(u, 0.05, 0.22);
    g.fillStyle = hex(ink, 0.07); rr(g, qx, H * 0.1, qw, H * 0.1, H * 0.05); g.fill(); g.strokeStyle = hex(ink, 0.2); g.lineWidth = 1.5; rr(g, qx, H * 0.1, qw, H * 0.1, H * 0.05); g.stroke();
    txt(g, q.slice(0, Math.round(q.length * t)), qx + H * 0.045, H * 0.1 + H * 0.063, { size: H * 0.04, color: ink });
    const ay = H * 0.27, ah = H * 0.52, a = ease.out3(second ? seg(u, 0.72, 0.8) : seg(u, 0.4, 0.48));
    g.save(); g.globalAlpha *= a; g.fillStyle = hex(ink, 0.05); rr(g, qx, ay + (1 - a) * 20, qw, ah, 16); g.fill(); g.strokeStyle = hex(second ? AM : BL, 0.5); g.lineWidth = 1.5; rr(g, qx, ay + (1 - a) * 20, qw, ah, 16); g.stroke();
    if (!second) {
      for (let i = 0; i < 6; i++) { const k = ease.out3(seg(u, 0.44 + i * 0.03, 0.52 + i * 0.03)); g.fillStyle = hex(ink, 0.4); rr(g, qx + 26, ay + 34 + i * H * 0.055, (qw - 52) * (i === 5 ? 0.45 : 0.95) * k, 7, 3.5); g.fill(); if (i === 1 || i === 3 || i === 5) { const n = (i + 1) / 2, cx = qx + 26 + (qw - 52) * (i === 5 ? 0.45 : 0.95) * k + 20; if (k > 0.9) { g.fillStyle = hex(BL, 0.95); rr(g, cx - 14, ay + 22 + i * H * 0.055, 28, 24, 12); g.fill(); txt(g, "[" + n + "]", cx, ay + 40 + i * H * 0.055, { size: H * 0.023, color: "#06101f", align: "center" }); } } }
    } else { txt(g, "The filings don't say.", qx + 26, ay + H * 0.12, { size: H * 0.05, color: AM, spacing: -0.5 }); txt(g, "Not in these reports, so no answer.", qx + 26, ay + H * 0.19, { size: H * 0.03, color: hex(ink, 0.55), weight: 400 }); }
    g.restore();
    // retrieval beams from highlighted passages to the answer
    if (!second) hits.forEach((h, i) => { const y = py + H * 0.09 + h * lh, p = ease.inOut(seg(u, 0.3 + i * 0.03, 0.46 + i * 0.03)); if (p <= 0 || p >= 1) return; const a2 = [px + pw, y + 2], b2 = [qx, ay + H * 0.1 + i * H * 0.06], c = [(a2[0] + b2[0]) / 2, a2[1]], pt = quad(a2, c, b2, p); dot(g, pt[0], pt[1], 5, BL, BL); });
    txt(g, second ? "SAYS WHEN THE ANSWER ISN'T THERE" : "CITES THE PASSAGE BEHIND EVERY FACT", qx, H * 0.915, { size: H * 0.023, color: hex(ink, 0.45), spacing: 2.5 });
  },
});
