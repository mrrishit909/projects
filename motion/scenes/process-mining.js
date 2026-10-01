/* Where a Loan Process Loses Time: the mined process map with applications flowing through it as tokens. Most of the 18.1 days are
   spent waiting for the customer to return the offer (9.9 days, 54%); outcomes are 55% approved, 33% cancelled, 12% denied. */
scene({
  slug: "process-mining", aspect: 1.701, seconds: 6, bg: ["#120e18", "#06040a"],
  init(W, H, { rng }) {
    const r = rng(47), toks = Array.from({ length: 40 }, (_, i) => { const x = r(); return { off: i / 40, out: x < 0.55 ? "ok" : x < 0.88 ? "cancel" : "deny", j: (r() - 0.5) }; });
    return { toks };
  },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, dot, rr, wrap01, clamp }) {
    const ink = "#f1eaf8", GRN = "#4fdc93", AMB = "#ffb44d", RED = "#ff6262", PUR = "#b58cff";
    const N = { sub: [0.07, 0.42], prep: [0.25, 0.42], wait: [0.45, 0.42], val: [0.64, 0.42], ok: [0.84, 0.2], cancel: [0.84, 0.42], deny: [0.84, 0.64] };
    const P = (k) => [N[k][0] * W, N[k][1] * H], labels = { sub: "Submitted", prep: "Bank prepares offer", wait: "Customer returns offer", val: "Bank validates", ok: "Approved", cancel: "Cancelled", deny: "Denied" };
    const edges = [["sub", "prep"], ["prep", "wait"], ["wait", "val"], ["val", "ok"], ["wait", "cancel"], ["val", "deny"]];
    edges.forEach(([a, b]) => { const A = P(a), B = P(b); line(g, A[0], A[1], B[0], B[1], hex(ink, 0.15), 2); });
    // the slow stage glows: waiting on the customer
    const glow = ease.out3(seg(u, 0.35, 0.5)), wp = P("wait");
    if (glow > 0) { const rg = g.createRadialGradient(wp[0], wp[1], 0, wp[0], wp[1], H * 0.22); rg.addColorStop(0, hex(AMB, 0.35 * glow)); rg.addColorStop(1, hex(AMB, 0)); g.fillStyle = rg; g.fillRect(wp[0] - H * 0.25, wp[1] - H * 0.25, H * 0.5, H * 0.5); }
    S.toks.forEach((t) => {
      const p = wrap01(u * 1.5 + t.off), dest = t.out, route = dest === "cancel" ? ["sub", "prep", "wait", "cancel"] : ["sub", "prep", "wait", "val", dest];
      // time per leg weighted like the real stages: the customer wait is the long one
      const w = dest === "cancel" ? [0.12, 0.6, 0.28] : [0.1, 0.48, 0.32, 0.1], n = w.length; let acc = 0, leg = 0; while (leg < n - 1 && p > acc + w[leg]) { acc += w[leg]; leg++; }
      const lt = clamp((p - acc) / w[leg], 0, 1), A = P(route[leg]), B = P(route[leg + 1]);
      const x = lerp(A[0], B[0], ease.inOut(lt)), y = lerp(A[1], B[1], ease.inOut(lt)) + t.j * H * 0.04;
      const col = leg === n - 1 && lt > 0.5 ? (dest === "ok" ? GRN : dest === "cancel" ? AMB : RED) : PUR, a = seg(u, 0.04, 0.12) * Math.sin(Math.min(1, p * 1.05) * Math.PI) ** 0.3;
      g.save(); g.globalAlpha *= a; dot(g, x, y, H * 0.009, col, col); g.restore();
    });
    Object.keys(N).forEach((k) => { const [x, y] = P(k), end = ["ok", "cancel", "deny"].includes(k), c = k === "ok" ? GRN : k === "cancel" ? AMB : k === "deny" ? RED : ink; g.fillStyle = "#0d0a12"; g.strokeStyle = hex(c, 0.8); g.lineWidth = 2; g.beginPath(); g.arc(x, y, H * 0.022, 0, 6.3); g.fill(); g.stroke(); txt(g, labels[k], end ? x + H * 0.04 : x, end ? y + H * 0.01 : y - H * 0.05, { size: H * 0.024, color: hex(c, 0.9), align: end ? "left" : "center", weight: 400 }); });
    const pct = { ok: "55%", cancel: "33%", deny: "12%" }, po = seg(u, 0.6, 0.72);
    ["ok", "cancel", "deny"].forEach((k) => { const [x, y] = P(k); txt(g, pct[k], x + H * 0.04, y + H * 0.05, { size: H * 0.032, color: "#fff", alpha: po }); });
    // where the 18.1 days go
    const bx = W * 0.07, bw = W * 0.7, by = H * 0.82, t = ease.out5(seg(u, 0.5, 0.75));
    txt(g, "WHERE THE 18.1 DAYS GO", bx + W * 0.12, by - H * 0.03, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [[1.4, PUR, "bank 1.4d"], [9.9, AMB, "waiting on the customer 9.9d · 54%"], [6.8, "#8fa6ff", "validation 6.8d"]].reduce((x0, [d, c, lab]) => {
      const w = (bw * d) / 18.1 * t; g.fillStyle = c; rr(g, x0, by, Math.max(0.001, w - 4), H * 0.05, 6); g.fill();
      if (t > 0.9) txt(g, lab, x0 + 8, d < 2 ? by - H * 0.075 + H * 0.0 : by + H * 0.1, { size: H * 0.024, color: c, weight: 400 }); return x0 + w;
    }, bx);
  },
});
