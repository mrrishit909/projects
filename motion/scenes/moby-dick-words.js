/* What Is Moby-Dick Made Of? Where each word falls in the book: a row per word (whale in any form, Ahab, Queequeg, Starbuck, the Pequod, "white", Ishmael), a column per tenth
   of the book's words; brighter means more uses per 10,000 words (the heat-map on the case-study page; real counts). Ahab climbs to the last tenth, Queequeg peaks in the second.
   Right: 213,516 words, 18,281 different ones, 47% of them used only once, and the Zipf slope of -1.08. */
const ROWS = [["whale (any form)", 78.7, 30.0, 137.7, 78.2, 97.4, 117.1, 120.8, 91.8, 49.6, 50.6], ["Ahab", 2.8, 15.5, 30.9, 32.3, 10.8, 9.8, 3.7, 14.5, 42.2, 76.8], ["Queequeg", 11.2, 61.8, 5.6, 2.3, 3.3, 10.8, 8.0, 0.9, 11.2, 2.8], ["Starbuck", 0.5, 1.9, 11.7, 14.5, 6.1, 6.6, 8.0, 0.9, 18.3, 24.4], ["Pequod", 2.3, 14.1, 8.0, 3.7, 6.1, 12.6, 8.4, 8.9, 8.9, 8.0], ["white", 3.3, 1.4, 11.2, 39.3, 12.2, 8.0, 3.3, 9.8, 6.1, 22.0], ["Ishmael", 3.3, 2.3, 0.0, 1.9, 0.0, 0.0, 0.5, 1.4, 0.0, 0.0]];
scene({
  slug: "moby-dick-words", aspect: 1.72, seconds: 6, bg: ["#0c1117", "#030507"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, mix }) {
    const ink = "#eef2f7", ORG = "#ff8a3d", BL = "#4a95f0";
    const x0 = W * 0.2, x1 = W * 0.6, y0 = H * 0.2, y1 = H * 0.78, cw = (x1 - x0) / 10, ch = (y1 - y0) / ROWS.length;
    txt(g, "WHERE EACH WORD FALLS IN THE BOOK", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    ROWS.forEach((r, i) => {
      const vals = r.slice(1), mx = Math.max(...vals);
      txt(g, r[0], x0 - W * 0.012, y0 + i * ch + ch * 0.62, { size: H * 0.026, color: hex(ink, 0.8), weight: 400, align: "right" });
      vals.forEach((v, j) => {
        const t = ease.out3(seg(u, 0.05 + j * 0.045, 0.2 + j * 0.045)), a = v / mx;
        g.fillStyle = mix("#141a22", a > 0.5 ? "#bcd6f7" : BL, Math.min(1, a * 1.25) * t); rr(g, x0 + j * cw + 2, y0 + i * ch + 2, cw - 4, ch - 4, 5); g.fill();
      });
    });
    [["start", 0], ["end", 9]].forEach(([s, j]) => txt(g, s === "start" ? "first tenth" : "last tenth", x0 + j * cw + (j ? cw : 0), y1 + H * 0.05, { size: H * 0.021, color: hex(ink, 0.45), align: j ? "right" : "left" }));
    const rx = W * 0.67, rw = W * 0.28, k = ease.out5(seg(u, 0.4, 0.7));
    txt(g, "WORDS IN THE BOOK", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, Math.round(213516 * k).toLocaleString("en-US"), rx, H * 0.27, { size: H * 0.115, color: "#fff", spacing: -3 });
    txt(g, "in 138 sections, 18,281 of them different", rx, H * 0.325, { size: H * 0.024, color: hex(ink, 0.7), weight: 400, alpha: k });
    [["Different words used only once", "47%", ORG], ["Zipf's law slope", "\u22121.08", BL], ["Words containing \u201cwhal\u201d", "1,819", ink]].forEach(([n, v, c], i) => {
      const y = H * 0.52 + i * H * 0.14, t = ease.out5(seg(u, 0.6 + i * 0.07, 0.78 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12), 1);
      txt(g, n, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.038, color: c, align: "right", alpha: t });
    });
  },
});
