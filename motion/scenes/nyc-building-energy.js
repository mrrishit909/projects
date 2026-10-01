/* NYC Building Energy: a skyline wakes up window by window, then each building is washed with how much energy it uses per square foot.
   The effects on the right are the case study's regression results (holding the others fixed). */
scene({
  slug: "nyc-building-energy", aspect: 1.701, seconds: 6, bg: ["#0b0f1f", "#03040a"],
  init(W, H, { rng }) {
    const r = rng(40), blds = []; let x = W * 0.02;
    while (x < W * 0.98) { const w = W * (0.032 + r() * 0.04), h = H * (0.18 + Math.pow(r(), 1.6) * 0.42); blds.push({ x, w, h, heat: r(), cols: Math.max(2, Math.round(w / 15)), seed: r(), at: r() }); x += w + W * 0.006; }
    return { blds };
  },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, mix, txt, line, dot, rr }) {
    const ground = H * 0.96, ink = "#e8ecff", WIN = "#ffd479";
    const sky = g.createLinearGradient(0, 0, 0, ground); sky.addColorStop(0, "rgba(40,50,110,0)"); sky.addColorStop(1, "rgba(90,70,140,0.22)"); g.fillStyle = sky; g.fillRect(0, 0, W, ground);
    const heatT = ease.inOut(seg(u, 0.5, 0.72));
    S.blds.forEach((b) => {
      const grow = ease.out5(seg(u, 0.04 + b.at * 0.12, 0.26 + b.at * 0.12)), h = b.h * grow, y = ground - h;
      const heat = mix("#3a6dff", "#ff7a3a", b.heat);
      g.fillStyle = mix("#141a33", "#242b4d", b.seed); g.fillRect(b.x, y, b.w, h);
      g.fillStyle = hex(ink, 0.07); g.fillRect(b.x, y, 2, h);
      // windows light up bottom-up with a little flicker
      const rowsN = Math.floor(h / 17);
      for (let ry = 0; ry < rowsN - 1; ry++) for (let cx = 0; cx < b.cols; cx++) {
        const on = seg(u, 0.22 + b.at * 0.15 + (ry / Math.max(1, rowsN)) * 0.12, 0.3 + b.at * 0.15 + (ry / Math.max(1, rowsN)) * 0.12); if (on <= 0) continue;
        const lit = ((b.seed * 97 + ry * 13 + cx * 7) % 5) / 5 > 0.28 ? 1 : 0.15, fl = 0.8 + 0.2 * Math.sin(u * 40 + ry * 3 + cx);
        g.fillStyle = hex(WIN, 0.7 * on * lit * fl); g.fillRect(b.x + 5 + cx * ((b.w - 8) / b.cols), y + 8 + ry * 17, ((b.w - 8) / b.cols) - 4, 10);
      }
      // energy wash
      if (heatT > 0) { const wg = g.createLinearGradient(0, y, 0, ground); wg.addColorStop(0, hex(heat, 0.55 * heatT)); wg.addColorStop(1, hex(heat, 0.05 * heatT)); g.fillStyle = wg; g.fillRect(b.x, y, b.w, h); g.fillStyle = heat; g.globalAlpha *= heatT; g.fillRect(b.x, y - 3, b.w, 3); g.globalAlpha /= Math.max(heatT, 0.001); }
    });
    line(g, 0, ground, W, ground, hex(ink, 0.25));
    // effects
    const px = W * 0.06, py = H * 0.1, k = ease.out3(seg(u, 0.62, 0.8));
    txt(g, "ENERGY USE PER SQ FT, HOLDING THE REST FIXED", px, py, { size: H * 0.024, color: hex(ink, 0.55), spacing: 2.5, alpha: k });
    [["District steam", 14.0, "#ff8a4c"], ["Built 2000–09", 13.1, "#ffb25c"], ["Electricity share +10 pts", -15.9, "#6ea4ff"]].forEach(([name, v, col], i) => {
      const y = py + H * 0.065 + i * H * 0.085, mid = px + W * 0.19, len = (Math.abs(v) / 16) * W * 0.17 * k;
      txt(g, name, mid - W * 0.2, y + H * 0.012, { size: H * 0.029, color: hex(ink, 0.8), weight: 400, alpha: k });
      g.fillStyle = col; v > 0 ? rr(g, mid + W * 0.02, y - H * 0.017, len, H * 0.036, 6) : rr(g, mid + W * 0.02, y - H * 0.017, len, H * 0.036, 6); g.fill();
      txt(g, (v > 0 ? "+" : "−") + Math.abs(v) + "%", mid + W * 0.02 + len + 12, y + H * 0.012, { size: H * 0.032, color: col, alpha: k });
    });
  },
});
