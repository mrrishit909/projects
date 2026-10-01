/* Business Finder: type a US city, get a cleaned table of its businesses, each labelled active / unknown / likely closed.
   The split at the bottom is the real Tampa result: 39% active, 60% unknown, 1% closed. */
scene({
  slug: "business-finder", aspect: 1.614, seconds: 6, bg: ["#0c1514", "#050a0a"],
  init() {
    const status = ["a", "u", "a", "u", "u", "a", "u", "c", "a", "u", "u", "a"];
    const cats = ["Food & Drink", "Retail", "Services", "Health", "Auto", "Food & Drink", "Retail", "Services", "Beauty", "Auto", "Retail", "Food & Drink"];
    const wide = [0.52, 0.38, 0.62, 0.45, 0.57, 0.4, 0.5, 0.34, 0.6, 0.43, 0.55, 0.47];
    return { rows: status.map((s, i) => ({ s, c: cats[i], w: wide[i] })) };
  },
  draw(g, u, W, H, S, { clamp, lerp, seg, ease, hex, txt, line, dot, rr }) {
    const ink = "#e8f3f1", G = "#3ddc97", Y = "#7f8c8a", R = "#ff6b61", M = W * 0.07;
    // search bar
    const bx = M, by = H * 0.08, bw = W - 2 * M, bh = H * 0.105;
    g.fillStyle = hex(ink, 0.07); rr(g, bx, by, bw, bh, bh / 2); g.fill();
    g.strokeStyle = hex(ink, 0.18); g.lineWidth = 1.5; rr(g, bx, by, bw, bh, bh / 2); g.stroke();
    const word = "Tampa, FL", n = Math.round(word.length * ease.out3(seg(u, 0.07, 0.2)));
    const sz = H * 0.05, typed = word.slice(0, n);
    txt(g, typed, bx + bh * 0.55, by + bh / 2 + sz * 0.34, { size: sz, color: ink, spacing: -0.5 });
    g.font = `500 ${sz}px Geist`; const tw = g.measureText(typed).width;
    if (u < 0.3 && Math.floor(u * 40) % 2 === 0) { g.fillStyle = G; g.fillRect(bx + bh * 0.55 + tw + 4, by + bh * 0.24, 3, bh * 0.52); }
    const go = ease.back(seg(u, 0.21, 0.27)); dot(g, bx + bw - bh / 2, by + bh / 2, bh * 0.36 * (0.9 + 0.1 * go), G, hex(G, 0.6));
    line(g, bx + bw - bh / 2 - 7, by + bh / 2, bx + bw - bh / 2 + 7, by + bh / 2, "#06110d", 3); line(g, bx + bw - bh / 2 + 1, by + bh / 2 - 6, bx + bw - bh / 2 + 8, by + bh / 2, "#06110d", 3); line(g, bx + bw - bh / 2 + 1, by + bh / 2 + 6, bx + bw - bh / 2 + 8, by + bh / 2, "#06110d", 3);
    // table
    const ty = H * 0.26, rowH = H * 0.047, cols = [M, M + (W - 2 * M) * 0.5, M + (W - 2 * M) * 0.74];
    ["BUSINESS", "CATEGORY", "STATUS"].forEach((h, i) => txt(g, h, cols[i], ty, { size: H * 0.024, color: hex(ink, 0.4), spacing: 2 * H / 720 }));
    line(g, M, ty + H * 0.02, W - M, ty + H * 0.02, hex(ink, 0.15));
    S.rows.forEach((r, i) => {
      const t = ease.out5(seg(u, 0.24 + i * 0.03, 0.24 + i * 0.03 + 0.07)); if (t <= 0) return;
      const y = ty + H * 0.045 + i * rowH + (1 - t) * 16;
      g.save(); g.globalAlpha *= t;
      g.fillStyle = hex(ink, 0.2); rr(g, cols[0], y - H * 0.013, (cols[1] - cols[0] - W * 0.05) * r.w * 1.5, H * 0.026, H * 0.013); g.fill();
      txt(g, r.c, cols[1], y + H * 0.01, { size: H * 0.03, color: hex(ink, 0.62), weight: 400 });
      const col = r.s === "a" ? G : r.s === "c" ? R : Y, label = r.s === "a" ? "likely active" : r.s === "c" ? "likely closed" : "unknown";
      g.font = `500 ${H * 0.027}px Geist`; const w = g.measureText(label).width + H * 0.05;
      g.fillStyle = hex(col, r.s === "u" ? 0.16 : 0.18); rr(g, cols[2], y - H * 0.0215, w, H * 0.043, H * 0.0215); g.fill();
      dot(g, cols[2] + H * 0.024, y, H * 0.0085, col); txt(g, label, cols[2] + H * 0.042, y + H * 0.01, { size: H * 0.027, color: col });
      g.restore();
    });
    // the real split, as a stacked bar
    const st = ease.out5(seg(u, 0.66, 0.84)), by2 = H * 0.925, bw2 = W - 2 * M;
    g.fillStyle = hex(ink, 0.08); rr(g, M, by2, bw2, H * 0.028, H * 0.014); g.fill();
    g.save(); rr(g, M, by2, bw2, H * 0.028, H * 0.014); g.clip();
    g.fillStyle = G; g.fillRect(M, by2, bw2 * 0.39 * st, H * 0.028);
    g.fillStyle = Y; g.fillRect(M + bw2 * 0.39 * st, by2, bw2 * 0.60 * st, H * 0.028);
    g.fillStyle = R; g.fillRect(M + bw2 * 0.99 * st, by2, bw2 * 0.01 * st, H * 0.028); g.restore();
    txt(g, "39%", M, by2 - H * 0.02, { size: H * 0.03, color: G, alpha: st }); txt(g, "60%", M + bw2 * 0.39 + 8, by2 - H * 0.02, { size: H * 0.03, color: "#aab4b2", alpha: st }); txt(g, "1%", W - M, by2 - H * 0.02, { size: H * 0.03, color: R, align: "right", alpha: st });
  },
});
