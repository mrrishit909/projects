/* Complaint Sorter: free-text vehicle-safety complaints stream in; an LLM reads each one (no labelled examples)
   and drops it into the part that failed. Cards are grey until they cross the reader, then take their bin's colour. */
scene({
  slug: "complaint-sorter", aspect: 1.527, seconds: 6, bg: ["#120f1c", "#06050b"],
  init(W, H, { rng }) {
    const bins = [["Engine", "#ff8a4c"], ["Brakes", "#ff5c7a"], ["Steering", "#b583ff"], ["Air bags", "#5ec8ff"], ["Electrical", "#ffd45e"], ["Fuel system", "#5eeaa0"]];
    const r = rng(5), cards = [];
    for (let i = 0; i < 14; i++) cards.push({ bin: Math.floor(r() * bins.length), y: 0.12 + r() * 0.76, lines: 2 + Math.floor(r() * 2), off: i / 14, w: 0.7 + r() * 0.3 });
    return { bins, cards };
  },
  draw(g, u, W, H, S, { TAU, lerp, seg, ease, hex, txt, line, dot, rr, wrap01, quad }) {
    const ink = "#efeaff", binX = W * 0.74, binW = W * 0.2, binH = H * 0.1, gap = (H * 0.86 - binH * 6) / 5, top = H * 0.07;
    const scanX = W * 0.42;
    // reader: a vertical glass line with a soft glow
    const sg = g.createLinearGradient(scanX - 40, 0, scanX + 40, 0); sg.addColorStop(0, "rgba(181,131,255,0)"); sg.addColorStop(0.5, "rgba(181,131,255,0.22)"); sg.addColorStop(1, "rgba(181,131,255,0)");
    g.fillStyle = sg; g.fillRect(scanX - 40, 0, 80, H); line(g, scanX, 0, scanX, H, hex("#b583ff", 0.6), 1.5);
    txt(g, "LLM READS", scanX, H * 0.045, { size: H * 0.026, color: hex("#d6c2ff", 0.9), align: "center", spacing: 2.5 });
    const binY = (i) => top + i * (binH + gap);
    S.bins.forEach(([name, col], i) => {
      const y = binY(i); let flash = 0;
      S.cards.forEach((c) => { if (c.bin === i) { const p = wrap01(u * 2 + c.off); flash = Math.max(flash, p > 0.82 ? 1 - seg(p, 0.82, 1) * 0.9 : 0); } });
      g.fillStyle = hex(col, 0.1 + 0.2 * flash); rr(g, binX, y, binW, binH, H * 0.02); g.fill();
      g.strokeStyle = hex(col, 0.5 + 0.4 * flash); g.lineWidth = 1.5; rr(g, binX, y, binW, binH, H * 0.02); g.stroke();
    });
    S.cards.slice().sort((a, b) => wrap01(u * 2 + a.off) - wrap01(u * 2 + b.off)).forEach((c) => {
      const p = wrap01(u * 2 + c.off), cw = W * 0.16 * c.w, ch = H * 0.085, col = S.bins[c.bin][1];
      const from = [-cw, c.y * H], to = [binX + binW * 0.5, binY(c.bin) + binH / 2], mid = [scanX, lerp(from[1], to[1], 0.35)];
      const x = p < 0.5 ? lerp(from[0], mid[0], ease.out3(p / 0.5) * 0.98 + 0.02 * (p / 0.5)) : null;
      let pos; if (p < 0.5) pos = [lerp(from[0], mid[0], p / 0.5), lerp(from[1], mid[1], ease.smooth(p / 0.5))]; else pos = quad(mid, [lerp(mid[0], to[0], 0.5), mid[1]], to, ease.inOut((p - 0.5) / 0.5));
      const sorted = p > 0.5, k = sorted ? 1 : 0, scale = p > 0.82 ? 1 - seg(p, 0.82, 1) * 0.6 : 1;
      g.save(); g.translate(pos[0], pos[1]); g.scale(scale, scale); g.globalAlpha *= p > 0.9 ? 1 - seg(p, 0.9, 1) : 1;
      g.fillStyle = sorted ? hex(col, 0.22) : hex(ink, 0.1); rr(g, -cw / 2, -ch / 2, cw, ch, 8); g.fill();
      g.strokeStyle = sorted ? hex(col, 0.9) : hex(ink, 0.3); g.lineWidth = 1.5; rr(g, -cw / 2, -ch / 2, cw, ch, 8); g.stroke();
      for (let l = 0; l < c.lines; l++) { g.fillStyle = sorted ? hex(col, 0.7) : hex(ink, 0.35); g.fillRect(-cw / 2 + 10, -ch / 2 + 11 + l * 13, (cw - 20) * (l === c.lines - 1 ? 0.55 : 1), 4); }
      g.restore();
    });
    S.bins.forEach(([name, col], i) => txt(g, name.toUpperCase(), binX + binW / 2, binY(i) + binH / 2 + H * 0.01, { size: H * 0.027, color: col, align: "center", spacing: 1.5 }));
    txt(g, "NO LABELLED EXAMPLES", W * 0.03, H * 0.97, { size: H * 0.024, color: hex(ink, 0.4), spacing: 2.5 });
  },
});
