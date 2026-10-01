/* CSV Data-Quality Checker: a scanner sweeps a table and flags what's wrong: empty values, wrong types, broken rows,
   duplicates and unusual numbers, while the report on the right fills in. */
scene({
  slug: "csv-quality-checker", aspect: 1.661, seconds: 6, bg: ["#0b130f", "#040806"],
  init(W, H, { rng }) {
    const r = rng(21), cols = 8, rows = 12, cells = [];
    for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) cells.push({ x, y, w: 0.35 + r() * 0.55, kind: "ok" });
    const set = (x, y, kind) => { cells[y * cols + x].kind = kind; };
    [[2, 2], [5, 4], [1, 6], [6, 8], [3, 10], [7, 1]].forEach(([x, y]) => set(x, y, "empty"));
    [[4, 3], [2, 7], [5, 9]].forEach(([x, y]) => set(x, y, "type"));
    [[6, 5], [1, 11]].forEach(([x, y]) => set(x, y, "odd"));
    return { cols, rows, cells, broken: 9, dupA: 4, dupB: 11 };
  },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, dot, rr }) {
    const GREEN = "#46d17a", RED = "#ff5d5d", AMB = "#ffc24d", BLUE = "#59a8ff", PUR = "#c58bff", ink = "#e6f4ea";
    const gx = W * 0.05, gy = H * 0.1, gw = W * 0.62, cw = gw / S.cols, rh = H * 0.0645, ch = rh * 0.34;
    const scan = ease.inOut(seg(u, 0.14, 0.78)), sy = gy + rh * (S.rows + 1) * scan;
    // header
    g.fillStyle = hex(GREEN, 0.14); rr(g, gx - 8, gy - rh * 0.5, gw + 16, rh * 0.95, 8); g.fill();
    for (let x = 0; x < S.cols; x++) { g.fillStyle = hex(GREEN, 0.75); rr(g, gx + x * cw + 6, gy - ch * 0.5 + rh * 0.02, cw * (0.35 + (x % 3) * 0.12), ch * 0.8, 4); g.fill(); }
    const found = { empty: 0, type: 0, broken: 0, dup: 0, odd: 0 };
    for (let y = 0; y < S.rows; y++) {
      const cy = gy + rh * (y + 1) , passed = sy > cy + rh * 0.3, fl = seg(sy, cy - rh * 0.2, cy + rh * 0.6);
      if (y % 2) { g.fillStyle = hex(ink, 0.025); g.fillRect(gx - 8, cy - rh * 0.5, gw + 16, rh); }
      const rowBroken = y === S.broken, dup = y === S.dupA || y === S.dupB;
      for (let x = 0; x < S.cols; x++) {
        const c = S.cells[y * S.cols + x], px = gx + x * cw + 6, py = cy - ch / 2, bw = (cw - 14) * c.w;
        if (rowBroken && x > 4) { if (passed) { g.strokeStyle = hex(RED, 0.5 * fl); g.setLineDash([4, 4]); g.lineWidth = 1.5; rr(g, px, py, cw - 14, ch, 4); g.stroke(); g.setLineDash([]); } continue; }
        let col = hex(ink, 0.2), flag = null;
        if (passed) {
          if (c.kind === "empty") flag = RED; else if (c.kind === "type") flag = AMB; else if (c.kind === "odd") flag = PUR;
        }
        if (c.kind === "empty") { if (passed) { g.strokeStyle = hex(RED, 0.9 * fl); g.setLineDash([4, 4]); g.lineWidth = 1.8; rr(g, px, py - 2, cw - 14, ch + 4, 5); g.stroke(); g.setLineDash([]); g.fillStyle = hex(RED, 0.1 * fl); rr(g, px, py - 2, cw - 14, ch + 4, 5); g.fill(); } continue; }
        if (flag) { g.fillStyle = hex(flag, 0.18 * fl); rr(g, px - 3, py - 4, cw - 8, ch + 8, 6); g.fill(); g.strokeStyle = hex(flag, 0.9 * fl); g.lineWidth = 1.8; rr(g, px - 3, py - 4, cw - 8, ch + 8, 6); g.stroke(); col = hex(flag, 0.95); }
        g.fillStyle = col; rr(g, px, py, c.kind === "type" ? (cw - 14) * 0.5 : bw, ch, 4); g.fill();
        if (c.kind === "odd" && passed) { g.fillStyle = hex(PUR, 0.95); rr(g, px, py, cw - 14, ch, 4); g.fill(); }
      }
      if (rowBroken && passed) { g.fillStyle = hex(RED, 0.9 * fl); g.fillRect(gx - 14, cy - rh * 0.4, 4, rh * 0.8); }
      if (dup && passed) { g.strokeStyle = hex(BLUE, 0.9 * fl); g.lineWidth = 2; rr(g, gx - 8, cy - rh * 0.47, gw + 16, rh * 0.94, 8); g.stroke(); g.fillStyle = hex(BLUE, 0.07 * fl); g.fill(); }
      if (passed) { S.cells.slice(y * S.cols, y * S.cols + S.cols).forEach((c) => { if (c.kind === "empty") found.empty++; else if (c.kind === "type") found.type++; else if (c.kind === "odd") found.odd++; }); if (rowBroken) found.broken++; if (dup) found.dup++; }
    }
    // scanner
    if (scan > 0 && scan < 1) { const sg = g.createLinearGradient(0, sy - 46, 0, sy); sg.addColorStop(0, "rgba(70,209,122,0)"); sg.addColorStop(1, "rgba(70,209,122,0.28)"); g.fillStyle = sg; g.fillRect(gx - 14, sy - 46, gw + 28, 46); line(g, gx - 14, sy, gx + gw + 14, sy, GREEN, 2.5); }
    // report
    const rx = W * 0.73, rw = W * 0.22;
    txt(g, "REPORT", rx, H * 0.1, { size: H * 0.027, color: hex(ink, 0.5), spacing: 3 });
    const items = [["Empty values", RED, found.empty, 6], ["Wrong types", AMB, found.type, 3], ["Broken rows", RED, found.broken, 1], ["Duplicates", BLUE, found.dup, 2], ["Unusual numbers", PUR, found.odd, 2]];
    items.forEach(([name, col, n, max], i) => {
      const y = H * 0.2 + i * H * 0.105;
      txt(g, name, rx, y, { size: H * 0.033, color: hex(ink, 0.85), weight: 400 });
      g.fillStyle = hex(ink, 0.08); rr(g, rx, y + H * 0.02, rw, H * 0.014, H * 0.007); g.fill();
      g.fillStyle = col; rr(g, rx, y + H * 0.02, Math.max(0.001, rw * (n / max) * 0.92), H * 0.014, H * 0.007); g.fill();
    });
    const all = seg(u, 0.8, 0.9); txt(g, "checked before anyone analyses it", rx, H * 0.86, { size: H * 0.028, color: hex(GREEN, 0.95), weight: 400, alpha: all });
  },
});
