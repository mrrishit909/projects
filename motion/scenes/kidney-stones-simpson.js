/* Which Kidney-Stone Treatment Works Better? Success rates of treatment A (blue) and B (orange): B leads over all patients (78% vs 83%), then A leads in
   small stones (93% vs 87%) and large stones (73% vs 69%). Right: the odds ratio for A against B flips from 0.75 (crude) to 1.45 (within stone size);
   75% of A's patients had large stones against 23% of B's; Berkeley 1973's men-vs-women odds ratio flips from 1.84 to 0.90 inside departments. */
scene({
  slug: "kidney-stones-simpson", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0";
    const G = [["All patients", 78, 83], ["Small stones", 93, 87], ["Large stones", 73, 69]];
    const x0 = W * 0.06, x1 = W * 0.58, y0 = H * 0.22, y1 = H * 0.78, gw = (x1 - x0) / 3, bw = gw * 0.3;
    txt(g, "KIDNEY STONES: SUCCESS RATE BY TREATMENT", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    G.forEach(([name, a, b], i) => {
      const t = ease.out3(seg(u, [0.06, 0.28, 0.42][i], [0.22, 0.4, 0.56][i])), gx = x0 + i * gw + gw * 0.5;
      [[a, BL, -1], [b, ORG, 1]].forEach(([v, c, side]) => {
        const h = (y1 - y0) * v / 100 * t, bx = gx + (side < 0 ? -bw - 3 : 3);
        g.fillStyle = c; g.fillRect(bx, y1 - h, bw, h);
        txt(g, Math.round(v * t) + "%", bx + bw / 2, y1 - h - H * 0.015, { size: H * 0.028, color: hex(ink, 0.9), align: "center", alpha: Math.min(1, t * 2) });
      });
      txt(g, name, gx, y1 + H * 0.05, { size: H * 0.024, color: hex(ink, 0.55), align: "center" });
    });
    line(g, x0, y1 + 1, x1, y1 + 1, hex(ink, 0.25), 1);
    const cap1 = seg(u, 0.2, 0.28) * (1 - seg(u, 0.5, 0.58)), cap2 = seg(u, 0.56, 0.66);
    txt(g, "B looks better", x0, H * 0.18, { size: H * 0.03, color: ORG, alpha: cap1 });
    txt(g, "A is better in each size", x0, H * 0.18, { size: H * 0.03, color: BL, alpha: cap2 });
    [["A: open surgery", BL], ["B: keyhole", ORG]].forEach(([s, c], i) => { const lx = x0 + i * W * 0.2; g.fillStyle = c; g.fillRect(lx, H * 0.905, H * 0.022, H * 0.022); txt(g, s, lx + H * 0.035, H * 0.925, { size: H * 0.024, color: hex(ink, 0.7), weight: 400 }); });
    const rx = W * 0.67, rw = W * 0.28, k = ease.inOut(seg(u, 0.52, 0.8));
    txt(g, "ODDS RATIO, A AGAINST B", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, (0.75 + (1.45 - 0.75) * k).toFixed(2), rx, H * 0.29, { size: H * 0.13, color: k > 0.5 ? BL : ORG, spacing: -3 });
    txt(g, k < 0.5 ? "crude, all patients" : "within stone size", rx, H * 0.345, { size: H * 0.026, color: hex(ink, 0.7), weight: 400 });
    [["A's patients with large stones", "75%", BL], ["B's patients with large stones", "23%", ORG], ["Berkeley 1973, men vs women", "1.84 → 0.90", ink]].forEach(([n, v, c], i) => {
      const y = H * 0.52 + i * H * 0.14, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.78 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12), 1);
      txt(g, n, rx, y, { size: H * 0.025, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.038, color: c, align: "right", alpha: t });
    });
  },
});
