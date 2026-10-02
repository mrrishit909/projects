/* Clock Change and Fatal Crashes. A clock face jumps forward an hour; then daily crash bars across the weeks either side of the change,
   with the week after lifted (stylised bars). Right: the case study's estimates: spring +5.8% (p 0.0001), fall back +0.3%,
   Arizona + Hawaii (no change) -5.4%, and the 207-Sunday placebo test. */
scene({
  slug: "dst-crashes-stats", aspect: 1.72, seconds: 6, bg: ["#15100c", "#060403"],
  init(W, H, { rng }) { const r = rng(3), b = []; for (let i = 0; i < 28; i++) b.push(0.55 + r() * 0.2 + i * 0.004); return { b }; },
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp, TAU }) {
    const ink = "#f6efe8", AMB = "#ffb23e", RED = "#ff6b5a", cx = W * 0.14, cy = H * 0.38, R = H * 0.17;
    txt(g, "SPRING FORWARD", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    g.strokeStyle = hex(ink, 0.35); g.lineWidth = 2; g.beginPath(); g.arc(cx, cy, R, 0, TAU); g.stroke();
    for (let i = 0; i < 12; i++) { const a = i / 12 * TAU; line(g, cx + Math.sin(a) * R * 0.86, cy - Math.cos(a) * R * 0.86, cx + Math.sin(a) * R * 0.96, cy - Math.cos(a) * R * 0.96, hex(ink, 0.5), 2); }
    const hr = 2 + ease.inOut(seg(u, 0.08, 0.2)), ah = hr / 12 * TAU, am = ease.inOut(seg(u, 0.08, 0.2)) * TAU;
    line(g, cx, cy, cx + Math.sin(ah) * R * 0.5, cy - Math.cos(ah) * R * 0.5, "#fff", 4); line(g, cx, cy, cx + Math.sin(am) * R * 0.78, cy - Math.cos(am) * R * 0.78, AMB, 3); dot(g, cx, cy, 4, "#fff");
    txt(g, hr > 2.99 ? "3:00 am" : "2:00 am", cx, cy + R + H * 0.06, { size: H * 0.03, color: AMB, align: "center" });
    const bx = W * 0.3, bw = W * 0.24, base = H * 0.58, k = ease.out3(seg(u, 0.18, 0.45));
    S.b.forEach((v, i) => { const after = i >= 14 && i < 21, h = H * 0.3 * v * (after ? 1 + 0.25 * ease.out3(seg(u, 0.4, 0.55)) : 1) * k;
      g.fillStyle = after ? RED : hex(ink, 0.25); rr(g, bx + i * bw / 28, base - h, bw / 28 - 2, h, 2); g.fill(); });
    line(g, bx + 14 * bw / 28 - 1, base - H * 0.42, bx + 14 * bw / 28 - 1, base + 4, hex(AMB, 0.8), 1.5, [4, 4]);
    txt(g, "week after", bx + 17.5 * bw / 28, base + H * 0.05, { size: H * 0.022, color: RED, align: "center", alpha: k });
    txt(g, "daily fatal crashes (illustration)", bx, base + H * 0.12, { size: H * 0.022, color: hex(ink, 0.4), alpha: k });
    const rx = W * 0.62, k1 = ease.out5(seg(u, 0.38, 0.6));
    txt(g, "FATAL CRASHES, WEEK AFTER", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, "+" + (5.8 * k1).toFixed(1) + "%", rx, H * 0.29, { size: H * 0.13, color: RED, spacing: -3 });
    txt(g, "spring forward · p = 0.0001", rx, H * 0.36, { size: H * 0.028, color: hex(ink, 0.7), weight: 400, alpha: k1 });
    [["Fall back", "+0.3%"], ["Arizona + Hawaii (no change)", "−5.4%"], ["Placebo Sundays tested", "207"]].forEach(([n, v], i) => {
      const y = H * 0.5 + i * H * 0.12, t = ease.out5(seg(u, 0.58 + i * 0.06, 0.74 + i * 0.06));
      line(g, rx, y - H * 0.045, rx + W * 0.33, y - H * 0.045, hex(ink, 0.12), 1);
      txt(g, n, rx, y, { size: H * 0.03, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + W * 0.33, y, { size: H * 0.034, color: "#fff", align: "right", alpha: t });
    });
  },
});
