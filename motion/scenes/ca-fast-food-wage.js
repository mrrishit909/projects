/* California's $20 fast-food wage: an event study. Pay jumps at the law's start and stays out of the noise;
   jobs drift down about 3% but never leave the band of ordinary variation (placebo p = 0.14). Figures are from the case study. */
scene({
  slug: "ca-fast-food-wage", aspect: 1.701, seconds: 6, bg: ["#15120c", "#070605"],
  init(W, H, { rng, gauss }) {
    const r = rng(7), months = [], wage = [], jobs = [];
    for (let m = -12; m <= 24; m++) {
      months.push(m);
      const wob = (s) => gauss(r) * s;
      wage.push(m < 0 ? wob(0.55) : m < 2 ? 6.3 * (0.25 + 0.4 * m) + wob(0.35) : 6.3 + wob(0.45));
      jobs.push(m < 0 ? wob(0.7) : -2.9 * Math.min(1, (m + 1) / 14) + wob(0.55));
    }
    return { months, wage, jobs };
  },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, dot, path, rr }) {
    const GOLD = "#ffb531", BLUE = "#8fb4ff", ink = "#f6efe2";
    const pad = { l: W * 0.09, r: W * 0.2, t: H * 0.16, b: H * 0.14 }, pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;
    const X = (m) => pad.l + ((m + 12) / 36) * pw, Y = (v) => pad.t + (1 - (v + 6) / 14) * ph;   // -6..+8 %
    [-4, 0, 4, 8].forEach((v) => { line(g, pad.l, Y(v), pad.l + pw, Y(v), hex(ink, v === 0 ? 0.35 : 0.08)); txt(g, (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v) + "%", pad.l - 12, Y(v) + 6, { size: H * 0.028, color: hex(ink, 0.45), align: "right", weight: 400 }); });
    // ordinary-variation band (placebo range) fades in with the policy line
    const bt = ease.out3(seg(u, 0.12, 0.3));
    g.fillStyle = hex(BLUE, 0.1 * bt); g.fillRect(X(0), Y(3.6), (X(24) - X(0)) * bt, Y(-3.6) - Y(3.6));
    txt(g, "ordinary", X(24) + 14, Y(3.6) + 4, { size: H * 0.027, color: hex(BLUE, 0.8 * bt), weight: 400 });
    txt(g, "variation", X(24) + 14, Y(3.6) + 4 + H * 0.03, { size: H * 0.027, color: hex(BLUE, 0.8 * bt), weight: 400 });
    // the law starts here
    const pt = ease.out5(seg(u, 0.08, 0.2));
    line(g, X(0), pad.t - H * 0.02, X(0), pad.t + ph * pt, hex(ink, 0.7), 2, [6, 6]);
    txt(g, "APR 2024", X(0) + 10, pad.t - H * 0.045, { size: H * 0.03, color: ink, spacing: 1.5, alpha: pt });
    txt(g, "$20 minimum wage", X(0) + 10 + H * 0.17, pad.t - H * 0.045, { size: H * 0.03, color: hex(ink, 0.55), weight: 400, alpha: pt });
    // series
    const p1 = ease.inOut(seg(u, 0.2, 0.62)), p2 = ease.inOut(seg(u, 0.3, 0.8));
    const pts = (a) => S.months.map((m, i) => [X(m), Y(a[i])]);
    path(g, pts(S.jobs), p2, BLUE, 3.5, hex(BLUE, 0.6));
    path(g, pts(S.wage), p1, GOLD, 3.5, hex(GOLD, 0.7));
    const head = (a, p, c) => { const n = S.months.length - 1, f = p * n, i = Math.min(n - 1, Math.floor(f)), t = f - i; if (p > 0) dot(g, lerp(X(S.months[i]), X(S.months[i + 1]), t), lerp(Y(a[i]), Y(a[i + 1]), t), H * 0.013, c, c); };
    head(S.jobs, p2, BLUE); head(S.wage, p1, GOLD);
    const lt = ease.out3(seg(u, 0.78, 0.9));
    txt(g, "+6.3%", W - pad.r + 14, Y(6.3) + 2, { size: H * 0.06, color: GOLD, alpha: lt }); txt(g, "weekly pay", W - pad.r + 14, Y(6.3) + H * 0.045, { size: H * 0.027, color: hex(GOLD, 0.75), weight: 400, alpha: lt });
    txt(g, "−2.9%", W - pad.r + 14, Y(-2.9) - H * 0.075, { size: H * 0.06, color: BLUE, alpha: lt }); txt(g, "jobs, within the band", W - pad.r + 14, Y(-2.9) - H * 0.03, { size: H * 0.027, color: hex(BLUE, 0.75), weight: 400, alpha: lt });
    txt(g, "MONTHS FROM THE LAW", pad.l, H - H * 0.05, { size: H * 0.024, color: hex(ink, 0.4), spacing: 2 });
  },
});
