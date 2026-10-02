/* Live Wikipedia Edits in Spark Streaming. Events stream left to right into one-minute windows that fill and close behind a
   watermark line; bot edits in one colour. Right: from 30 minutes of the live stream, 71.9% of changes by bots, 24,763 edits on
   145 wikis. Stream dots are illustrative. */
scene({
  slug: "wiki-stream-spark", aspect: 1.72, seconds: 6, bg: ["#0f1016", "#040409"],
  init(W, H, { rng }) { const r = rng(53), e = []; for (let i = 0; i < 260; i++) e.push({ t: r(), y: r(), bot: r() < 0.719, late: r() < 0.03 }); return { e }; },
  draw(g, u, W, H, S, { seg, ease, hex, txt, rr, line, dot, lerp, clamp }) {
    const ink = "#eeeef8", BOT = "#8b7dff", HUM = "#46d39a", x0 = W * 0.05, x1 = W * 0.53, nw = 6, ww = (x1 - x0) / nw, y0 = H * 0.24, y1 = H * 0.8;
    txt(g, "EVENT TIME → ONE-MINUTE WINDOWS", x0, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    const now = lerp(0, nw, u), wm = now - 1.2;
    for (let i = 0; i < nw; i++) {
      const closed = i + 1 <= wm;
      g.fillStyle = hex(ink, closed ? 0.08 : 0.035); rr(g, x0 + i * ww + 3, y0, ww - 6, y1 - y0, 10); g.fill();
      txt(g, closed ? "written" : "open", x0 + i * ww + ww / 2, y1 + H * 0.05, { size: H * 0.022, color: closed ? HUM : hex(ink, 0.4), align: "center" });
    }
    S.e.forEach((p) => {
      const ts = p.t * nw; if (ts > now) return;
      const age = clamp((now - ts) / 0.4), x = x0 + ts * ww, y = lerp(H * 0.16, y0 + 10 + p.y * (y1 - y0 - 20), ease.out3(age));
      dot(g, x, y, 2.6, p.bot ? BOT : HUM);
    });
    if (wm > 0) { const xw = x0 + wm * ww; line(g, xw, y0 - 8, xw, y1 + 8, "#ffcc33", 2, [5, 5]); txt(g, "watermark", xw + 6, y0 - 12, { size: H * 0.022, color: "#ffcc33" }); }
    const rx = W * 0.62, k = ease.out5(seg(u, 0.3, 0.55));
    txt(g, "CHANGES MADE BY BOTS", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, (71.9 * k).toFixed(1) + "%", rx, H * 0.28, { size: H * 0.13, color: BOT, spacing: -3 });
    [["Edits", "24,763"], ["New pages", "1,655"], ["Wikis", "145"], ["Anonymous editors", "1.4%"]].forEach(([n, v], i) => {
      const y = H * 0.44 + i * H * 0.11, t = ease.out5(seg(u, 0.5 + i * 0.06, 0.66 + i * 0.06));
      line(g, rx, y - H * 0.045, rx + W * 0.32, y - H * 0.045, hex(ink, 0.12), 1);
      txt(g, n, rx, y, { size: H * 0.03, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + W * 0.32, y, { size: H * 0.034, color: "#fff", align: "right", alpha: t });
    });
    txt(g, "bot", rx, H * 0.9, { size: H * 0.024, color: BOT }); txt(g, "human", rx + W * 0.05, H * 0.9, { size: H * 0.024, color: HUM });
  },
});
