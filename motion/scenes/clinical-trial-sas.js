/* The Alzheimer's Patch Patients Couldn't Keep On. Kaplan-Meier curves for time to the first skin reaction draw themselves: placebo
   levels off near 0.63, both doses fall past the median line by about day 33-36. Right: who stopped for side effects (9% / 52% / 48%)
   and the hazard ratio 5.0. Curves are smooth stand-ins for the study's KM curves (same medians and end levels), not plotted data. */
scene({
  slug: "clinical-trial-sas", aspect: 1.72, seconds: 6, bg: ["#0b1418", "#03070a"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, path }) {
    const ink = "#e9f3f5", PBO = "#7fb2ff", LOW = "#ffb454", HIGH = "#ff6b6b", x0 = W * 0.07, x1 = W * 0.52, y0 = H * 0.2, y1 = H * 0.84;
    const X = (d) => x0 + (x1 - x0) * d / 190, Y = (s) => y1 - (y1 - y0) * s;
    const curve = (f) => { const p = []; for (let d = 0; d <= 190; d += 4) { const s = f(d); p.push([X(d), Y(p.length ? Math.min(p[p.length - 1][2], s) : s), s]); } return p.flatMap((q, i) => i ? [[q[0], p[i - 1][1]], [q[0], q[1]]] : [[q[0], q[1]]]); };
    txt(g, "TIME TO FIRST SKIN REACTION", x0, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    line(g, x0, y1, x1, y1, hex(ink, 0.25), 1); line(g, x0, y0, x0, y1, hex(ink, 0.25), 1);
    line(g, x0, Y(0.5), x1, Y(0.5), hex(ink, 0.25), 1, [5, 6]); txt(g, "half", x1 + 6, Y(0.5) + 5, { size: H * 0.022, color: hex(ink, 0.45) });
    const k = ease.inOut(seg(u, 0.06, 0.5));
    [[(d) => 0.626 + 0.374 * Math.exp(-d / 40), PBO], [(d) => 0.12 + 0.88 * Math.exp(-d / 40), LOW], [(d) => 0.09 + 0.91 * Math.exp(-d / 37), HIGH]]
      .forEach(([f, c]) => path(g, curve(f), k, c, 2.5));
    txt(g, "days on study", x1, y1 + H * 0.05, { size: H * 0.022, color: hex(ink, 0.4), align: "right" });
    const rx = W * 0.6, rw = W * 0.34;
    txt(g, "STOPPED BECAUSE OF SIDE EFFECTS", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Placebo", 9, PBO], ["Low dose", 52, LOW], ["High dose", 48, HIGH]].forEach(([n, v, c], i) => {
      const y = H * 0.2 + i * H * 0.13, t = ease.out5(seg(u, 0.35 + i * 0.06, 0.6 + i * 0.06));
      txt(g, n, rx, y + H * 0.03, { size: H * 0.03, color: hex(ink, 0.85), weight: 400 });
      txt(g, Math.round(v * t) + "%", rx + rw, y + H * 0.03, { size: H * 0.034, color: c, align: "right" });
      g.fillStyle = hex(ink, 0.07); rr(g, rx, y + H * 0.05, rw, H * 0.016, 8); g.fill();
      g.fillStyle = c; rr(g, rx, y + H * 0.05, Math.max(0.001, rw * v / 60 * t), H * 0.016, 8); g.fill();
    });
    const k2 = ease.out5(seg(u, 0.62, 0.8));
    txt(g, "SKIN-REACTION HAZARD, HIGH DOSE", rx, H * 0.66, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5, alpha: k2 });
    txt(g, (5.0 * k2).toFixed(1) + "×", rx, H * 0.8, { size: H * 0.11, color: "#fff", spacing: -2, alpha: k2 });
    txt(g, "placebo's", rx + W * 0.13, H * 0.8, { size: H * 0.032, color: hex(ink, 0.6), weight: 400, alpha: k2 });
  },
});
