/* Would You Notice When a Fraud Model Breaks? A random forest trained on Bitcoin transactions up to step 29 (Elliptic, 203,769 transactions in 49 two-week steps): its F1 on each step's labelled transactions is about 0.88 until step 42 and 0.04 from step 43 on.
   Right: its score monitor (PSI above 0.25) and its flag-rate monitor never rang; the one rule that did, F1 under half of validation, needs labels: 7 of the 7 steps from the break on. */
const F1 = [0.9434, 0.9519, 0.9868, 0.878, 0.9275, 0.9644, 0.9014, 0.7302, 0.939, 0.9268, 0.7579, 0.9511, 0.865, 0.0, 0.04, 0.0, 0.1818, 0.0, 0.0, 0.0328];
scene({
  slug: "fraud-model-monitoring", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, dot, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#46c28a";
    const x0 = W * 0.08, x1 = W * 0.56, y0 = H * 0.2, y1 = H * 0.78, N = F1.length, X = (i) => x0 + (x1 - x0) * i / (N - 1), Y = (v) => y1 - (y1 - y0) * v;
    txt(g, "FOREST F1 ON EACH STEP'S LABELLED TRANSACTIONS", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    g.fillStyle = hex(ink, 0.05); g.fillRect(X(0) - (X(1) - X(0)) / 2, y0, (X(4) - X(0)) + (X(1) - X(0)), y1 - y0);
    [0, 0.25, 0.5, 0.75, 1].forEach((v) => { line(g, x0 - H * 0.01, Y(v), x1, Y(v), hex(ink, v ? 0.07 : 0.3), 1); txt(g, v.toFixed(2), x0 - H * 0.02, Y(v) + H * 0.007, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    [[0, "30"], [5, "35"], [10, "40"], [13, "43"], [15, "45"], [19, "49"]].forEach(([i, s]) => txt(g, s, X(i), y1 + H * 0.05, { size: H * 0.02, color: hex(ink, i === 13 ? 0.9 : 0.4), align: "center" }));
    txt(g, "time step", (x0 + x1) / 2, y1 + H * 0.1, { size: H * 0.02, color: hex(ink, 0.4), align: "center" });
    const bx = (X(12) + X(13)) / 2; g.setLineDash([H * 0.008, H * 0.01]); line(g, bx, y0, bx, y1, hex(ink, 0.5), 1.5); g.setLineDash([]); txt(g, "break", bx + H * 0.012, y0 + H * 0.03, { size: H * 0.021, color: hex(ink, 0.55) });
    const p = ease.out5(seg(u, 0.05, 0.55)) * (N - 1), k = Math.floor(p), fr = p - k;
    g.beginPath(); g.moveTo(X(0), Y(F1[0]));
    for (let i = 1; i <= k; i++) g.lineTo(X(i), Y(F1[i]));
    let hx = X(k), hy = Y(F1[k]);
    if (k < N - 1) { hx = X(k) + (X(k + 1) - X(k)) * fr; hy = Y(lerp(F1[k], F1[k + 1], fr)); g.lineTo(hx, hy); }
    g.strokeStyle = BL; g.lineWidth = H * 0.006; g.lineJoin = "round"; g.stroke();
    dot(g, hx, hy, H * 0.012, p > 12.5 ? ORG : BL);
    const rx = W * 0.64, rw = W * 0.29, tb = ease.out5(seg(u, 0.3, 0.42)), ta = ease.out5(seg(u, 0.52, 0.64));
    txt(g, "MEAN F1 OF THE FOREST", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, "STEPS 35 TO 42", rx, H * 0.2, { size: H * 0.021, color: hex(ink, 0.6), spacing: 2, alpha: tb });
    txt(g, "0.88", rx, H * 0.31, { size: H * 0.1, color: BL, spacing: -3, alpha: tb });
    txt(g, "STEPS 43 TO 49", rx + rw * 0.55, H * 0.2, { size: H * 0.021, color: hex(ink, 0.6), spacing: 2, alpha: ta });
    txt(g, "0.04", rx + rw * 0.55, H * 0.31, { size: H * 0.1, color: ORG, spacing: -3, alpha: ta });
    [["Score monitor, PSI above 0.25", "0 alarms", GR], ["Flag-rate monitor", "0 alarms", GR], ["F1 rule (needs labels)", "7 of 7 steps", ORG]].forEach(([nm, v, c], i) => {
      const y = H * 0.55 + i * H * 0.13, t = ease.out5(seg(u, 0.64 + i * 0.07, 0.76 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12 * t), 1);
      txt(g, nm, rx, y, { size: H * 0.023, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.036, color: c, align: "right", alpha: t });
    });
  },
});
