/* Trading Bot: a paper-money system scans markets and every order has to pass one risk check before it counts. Orders ride the chart
   to the gate; within-limit ones go through to the decision log, the rest are bounced. No results are claimed (the case study makes none). */
scene({
  slug: "trading-bot", aspect: 1.661, seconds: 6, bg: ["#0b1210", "#040706"],
  init(W, H, { rng, gauss }) {
    const N = 34, r = rng(6), walk = [0]; for (let i = 1; i <= N; i++) walk.push(walk[i - 1] + gauss(r) * 0.5);
    const drift = walk[N]; const v = walk.map((x, i) => x - drift * (i / N));                  // periodic: the chart scrolls forever
    const candles = Array.from({ length: N }, (_, i) => ({ o: v[i], c: v[i + 1], h: Math.max(v[i], v[i + 1]) + r() * 0.35, l: Math.min(v[i], v[i + 1]) - r() * 0.35 }));
    const orders = [{ s: "BUY", a: "stock", ok: true, p: 0.1 }, { s: "SELL", a: "option", ok: true, p: 0.27 }, { s: "BUY", a: "crypto", ok: false, p: 0.44 }, { s: "BUY", a: "stock", ok: true, p: 0.6 }, { s: "SELL", a: "crypto", ok: false, p: 0.76 }];
    return { N, candles, orders };
  },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, dot, rr }) {
    const UP = "#3fe39a", DN = "#ff6159", ink = "#e5f3ee", cx0 = W * 0.04, cw = W * 0.58, top = H * 0.14, ch = H * 0.76, N = S.N, step = cw / N, gateX = W * 0.665;
    txt(g, "PAPER MONEY · STOCKS, OPTIONS, CRYPTO", cx0, H * 0.085, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    for (let i = 0; i <= 4; i++) line(g, cx0, top + (ch * i) / 4, cx0 + cw, top + (ch * i) / 4, hex(ink, 0.05));
    const lo = -2.6, hi = 2.6, Y = (p) => top + (1 - (p - lo) / (hi - lo)) * ch, scroll = u * N;
    g.save(); g.beginPath(); g.rect(cx0, top - 6, cw, ch + 12); g.clip();
    for (let k = -1; k <= N + 1; k++) {
      const idx = ((Math.floor(k + scroll) % N) + N) % N, c = S.candles[idx], x = cx0 + (k - (scroll % 1)) * step + step / 2, up = c.c >= c.o, col = up ? UP : DN;
      line(g, x, Y(c.h), x, Y(c.l), col, 2); g.fillStyle = col; g.fillRect(x - step * 0.3, Math.min(Y(c.o), Y(c.c)), step * 0.6, Math.max(3, Math.abs(Y(c.o) - Y(c.c))));
    }
    g.restore();
    // risk gate
    const gp = 0.5 + 0.5 * Math.sin(u * 40);
    const gg = g.createLinearGradient(gateX - 30, 0, gateX + 30, 0); gg.addColorStop(0, "rgba(255,196,77,0)"); gg.addColorStop(0.5, `rgba(255,196,77,${0.16 + 0.06 * gp})`); gg.addColorStop(1, "rgba(255,196,77,0)");
    g.fillStyle = gg; g.fillRect(gateX - 30, top - H * 0.04, 60, ch + H * 0.08); line(g, gateX, top - H * 0.04, gateX, top + ch + H * 0.04, "#ffc44d", 2.5);
    txt(g, "RISK CHECK", gateX, top - H * 0.06, { size: H * 0.022, color: "#ffc44d", align: "center", spacing: 2.5 });
    // orders
    const lx = W * 0.74, ly = H * 0.2, lh = H * 0.115;
    txt(g, "DECISION LOG", lx, H * 0.1, { size: H * 0.022, color: hex(ink, 0.5), spacing: 2.5 });
    S.orders.forEach((o, i) => {
      const t = seg(u, o.p, o.p + 0.12), y0 = Y(S.candles[Math.floor((o.p * N + N - 1) % N)].c) , gate = seg(t, 0.55, 0.62);
      const showLog = seg(u, o.p + 0.08, o.p + 0.15), col = o.ok ? UP : DN;
      if (t > 0 && t < 1) {
        let x, y = lerp(cx0 + cw - step, gateX, 0); const startX = cx0 + cw - step * 0.6, sy = top + ch * 0.5 - (i % 3 - 1) * ch * 0.2;
        if (t < 0.6) { x = lerp(startX, gateX - 8, ease.inOut(t / 0.6)); y = sy; }
        else if (o.ok) { x = lerp(gateX - 8, lx - 12, ease.out3((t - 0.6) / 0.4)); y = lerp(sy, ly + i * lh * 0.55, ease.inOut((t - 0.6) / 0.4)); }
        else { const b = (t - 0.6) / 0.4; x = lerp(gateX - 8, gateX - 90, ease.out3(b)) + Math.sin(b * 30) * 3 * (1 - b); y = sy + b * 30; }
        g.save(); g.globalAlpha *= o.ok ? 1 : 1 - seg(t, 0.8, 1); g.fillStyle = t < 0.6 ? "#ffc44d" : col; rr(g, x - 38, y - 15, 76, 30, 15); g.fill(); txt(g, o.s, x, y + 5, { size: H * 0.024, color: "#06100c", align: "center", spacing: 1.5 }); g.restore();
      }
      if (gate > 0) { dot(g, gateX, top + ch * 0.5, H * 0.028 * ease.out3(1 - seg(t, 0.62, 0.8)), hex(col, 0.35 * (1 - gate * 0.2))); }
      if (showLog > 0) {
        const y = ly + i * lh; g.save(); g.globalAlpha *= ease.out3(showLog); g.fillStyle = hex(col, 0.1); rr(g, lx, y, W * 0.22, lh * 0.82, 10); g.fill(); g.strokeStyle = hex(col, 0.6); g.lineWidth = 1.5; rr(g, lx, y, W * 0.22, lh * 0.82, 10); g.stroke();
        txt(g, `${o.s} · ${o.a}`, lx + 14, y + lh * 0.36, { size: H * 0.027, color: ink, mono: true, weight: 400 }); txt(g, o.ok ? "✓ within limits" : "✗ blocked by rule", lx + 14, y + lh * 0.68, { size: H * 0.024, color: col, weight: 500 }); g.restore();
      }
    });
  },
});
