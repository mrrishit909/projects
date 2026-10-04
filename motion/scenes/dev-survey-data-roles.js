/* Who Does Data Work, and Does It Pay? Stack Overflow Developer Survey 2025: 2,372 of 43,680 respondents (5.4%) hold a data role; 75% of them use Python and SQL against 41% of other developers.
   Left: median pay of each role relative to peers in the same country and experience band (1.00 = same), with the 95% interval: data engineers 1.08, AI/ML engineers 1.31, data scientists 1.03, analysts 0.72, other developers 1.00. */
const IDX = [1.079, 1.306, 1.029, 0.723, 1.0], LO = [1.03, 1.176, 0.97, 0.636, 1.0], HI = [1.133, 1.361, 1.118, 0.794, 1.0], NAMES = ["Data eng.", "AI/ML eng.", "Data sci.", "Analyst", "Other devs"];
scene({
  slug: "dev-survey-data-roles", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#46c28a", COLS = [BL, ORG, GR, "#d9bd5c", "#8a8f98"];
    const x0 = W * 0.09, x1 = W * 0.54, y0 = H * 0.2, y1 = H * 0.78, Y = (v) => y1 - (y1 - y0) * v / 1.6, bw = (x1 - x0) / 5;
    txt(g, "PAY VS PEERS, SAME COUNTRY AND EXPERIENCE", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [0, 0.5, 1, 1.5].forEach((v) => { line(g, x0 - H * 0.01, Y(v), x1, Y(v), hex(ink, v === 1 ? 0.3 : 0.07), 1); txt(g, v.toFixed(1), x0 - H * 0.02, Y(v) + H * 0.007, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    IDX.forEach((v, i) => {
      const t = ease.out5(seg(u, 0.05 + i * 0.07, 0.4 + i * 0.07)), cx = x0 + bw * (i + 0.5), w = bw * 0.58;
      g.fillStyle = COLS[i]; rr(g, cx - w / 2, Y(v * t), w, Math.max(0.001, y1 - Y(v * t)), 4); g.fill();
      const e = ease.out5(seg(u, 0.4 + i * 0.07, 0.55 + i * 0.07)); line(g, cx, Y(LO[i]), cx, Y(LO[i] + (HI[i] - LO[i]) * e), hex(ink, 0.85), 2);
      txt(g, NAMES[i], cx, y1 + H * 0.05, { size: H * 0.019, color: hex(ink, 0.5), align: "center" }); txt(g, v.toFixed(2), cx, Y(v * t) - H * 0.035, { size: H * 0.024, color: hex(ink, 0.9), align: "center", alpha: t });
    });
    const rx = W * 0.64, rw = W * 0.29; txt(g, "THE DATA ROLES", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Data roles, share of respondents", "5.4%", "BL"], ["Python + SQL (other devs 41%)", "75%", "GR"], ["AI/ML engineers' pay vs peers", "1.31x", "ORG"], ["Analysts' pay vs peers", "0.72x", "ink"]].forEach(([nm, v, c], i) => {
      const y = H * 0.27 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.8 + i * 0.07)), col = { BL, GR, ORG, ink }[c];
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1); txt(g, nm, rx, y, { size: H * 0.021, color: hex(ink, 0.8), weight: 400, alpha: t }); txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.04, color: col, align: "right", alpha: t });
    });
  },
});
