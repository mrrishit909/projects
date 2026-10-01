/* Costco Model in Excel: a driver-based forecast. A formula is typed into the formula bar, the sheet fills in around it, and the
   three scenarios land on their value per share. The per-share values (186 / 255 / 304) are the case study's real base figures. */
scene({
  slug: "excel-model", aspect: 1.74, seconds: 6, bg: ["#0a1510", "#040806"],
  init(W, H, { rng }) { const r = rng(2); return { fill: Array.from({ length: 10 * 6 }, () => ({ w: 0.4 + r() * 0.5, at: r() })) }; },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, dot, rr, fmt }) {
    const XG = "#22b36b", ink = "#e4f3ea", sx = W * 0.04, sy = H * 0.1, sw = W * 0.6, sh = H * 0.82;
    // window
    g.fillStyle = hex(ink, 0.04); rr(g, sx, sy, sw, sh, 14); g.fill(); g.strokeStyle = hex(ink, 0.14); g.lineWidth = 1.5; rr(g, sx, sy, sw, sh, 14); g.stroke();
    [0, 1, 2].forEach((i) => dot(g, sx + 22 + i * 18, sy + 22, 5, hex(ink, 0.25)));
    // formula bar with typed formula
    const fy = sy + 46, f = "=C6*(1+D4)-C7", n = Math.round(f.length * seg(u, 0.1, 0.26));
    g.fillStyle = hex(ink, 0.06); rr(g, sx + 14, fy, sw - 28, H * 0.06, 8); g.fill();
    txt(g, "fx", sx + 30, fy + H * 0.04, { size: H * 0.03, color: XG, weight: 500, mono: false }); line(g, sx + 62, fy + 8, sx + 62, fy + H * 0.052, hex(ink, 0.2));
    txt(g, f.slice(0, n), sx + 76, fy + H * 0.041, { size: H * 0.032, color: ink, mono: true, weight: 400 });
    // grid
    const gy = fy + H * 0.09, cols = 6, rows = 11, cw = (sw - 28 - 44) / cols, rh = (sh - (gy - sy) - 22) / (rows + 1);
    g.fillStyle = hex(XG, 0.18); g.fillRect(sx + 14, gy, sw - 28, rh);
    ["A", "B", "C", "D", "E", "F"].forEach((c, i) => txt(g, c, sx + 14 + 44 + i * cw + cw / 2, gy + rh * 0.7, { size: H * 0.026, color: hex(XG, 0.95), align: "center" }));
    for (let y = 0; y < rows; y++) {
      const yy = gy + rh * (y + 1); line(g, sx + 14, yy, sx + sw - 14, yy, hex(ink, 0.06)); txt(g, String(y + 1), sx + 14 + 30, yy + rh * 0.7, { size: H * 0.022, color: hex(ink, 0.35), align: "right", weight: 400 });
      for (let x = 0; x < cols; x++) {
        const c = S.fill[(y % 10) * 6 + x], k = ease.out3(seg(u, 0.18 + c.at * 0.3, 0.3 + c.at * 0.3)); if (k <= 0 || (y === 0)) continue;
        g.fillStyle = hex(x === 0 ? ink : XG, x === 0 ? 0.35 : 0.55 + 0.3 * (x / cols)); rr(g, sx + 14 + 44 + x * cw + 8, yy + rh * 0.28, (cw - 16) * c.w * k, rh * 0.4, 3); g.fill();
      }
    }
    // selection follows the typing
    const sel = ease.inOut(seg(u, 0.1, 0.4)), selX = sx + 14 + 44 + 3 * cw, selY = gy + rh * (3 + sel * 3);
    g.strokeStyle = XG; g.lineWidth = 3; g.strokeRect(selX, selY, cw, rh); g.fillStyle = XG; g.fillRect(selX + cw - 5, selY + rh - 5, 9, 9);
    // scenarios
    const px = W * 0.7, pw = W * 0.25, t = ease.out5(seg(u, 0.52, 0.86));
    txt(g, "VALUE PER SHARE", px, H * 0.14, { size: H * 0.026, color: hex(ink, 0.5), spacing: 2.5 });
    [["Downside", 186.33, "#ff7a66"], ["Base", 255.29, XG], ["Upside", 304.16, "#7be0ff"]].forEach(([name, v, col], i) => {
      const y = H * 0.24 + i * H * 0.21, w = pw * (v / 320) * t;
      txt(g, name.toUpperCase(), px, y, { size: H * 0.026, color: col, spacing: 2 });
      g.fillStyle = hex(ink, 0.07); rr(g, px, y + H * 0.02, pw, H * 0.075, 10); g.fill();
      g.fillStyle = col; rr(g, px, y + H * 0.02, Math.max(0.001, w), H * 0.075, 10); g.fill();
      txt(g, "$" + fmt(v * t, 2), px + 14, y + H * 0.073, { size: H * 0.04, color: "#04110a", weight: 500, mono: false, alpha: Math.min(1, t * 3) });
    });
    txt(g, "231 live formulas · 3 scenarios", px, H * 0.9, { size: H * 0.027, color: hex(ink, 0.45), weight: 400, alpha: seg(u, 0.7, 0.85) });
  },
});
