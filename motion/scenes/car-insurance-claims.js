/* What Predicts a Car Insurance Claim? The share of the Poisson model's out-of-sample gain in deviance that is lost when one variable is dropped (678,013 French policies, folds made of covariate profiles): vehicle age 40.2%, bonus-malus 35.2%,
   driver age 7.3%, then five variables under 3%. Right: the riskiest tenth of exposure claims 2.7 times the average frequency; the logistic model that ignores exposure cannot see that claims rise with time in force. */
const IMP = [["vehicle age", 40.2], ["bonus-malus", 35.2], ["driver age", 7.3], ["vehicle power", 2.3], ["region", 1.3], ["density", 1.2], ["vehicle brand", 0.6], ["fuel", 0.3]];
scene({
  slug: "car-insurance-claims", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0";
    const x0 = W * 0.2, x1 = W * 0.56, y0 = H * 0.2, ch = H * 0.073, bw = x1 - x0;
    txt(g, "SHARE OF THE MODEL'S GAIN LOST WITHOUT EACH VARIABLE", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [0, 10, 20, 30, 40].forEach((v) => { const x = x0 + bw * v / 45; line(g, x, y0 - H * 0.01, x, y0 + ch * IMP.length, hex(ink, v ? 0.07 : 0.3), 1); txt(g, v + "%", x, y0 + ch * IMP.length + H * 0.045, { size: H * 0.02, color: hex(ink, 0.4), align: "center" }); });
    let cur = 0;
    IMP.forEach(([nm, v], i) => {
      const t = ease.out5(seg(u, 0.06 + i * 0.06, 0.2 + i * 0.06)), w = bw * v / 45 * t, y = y0 + ch * i;
      txt(g, nm, x0 - H * 0.02, y + ch * 0.62, { size: H * 0.023, color: hex(ink, 0.7), align: "right" });
      rr(g, x0, y + ch * 0.15, Math.max(w, 0.1), ch * 0.62, 4); g.fillStyle = i < 2 ? ORG : BL; g.fill();
      txt(g, v.toFixed(1) + "%", x0 + w + H * 0.014, y + ch * 0.62, { size: H * 0.022, color: ink, alpha: t });
      if (i === 0) cur = v * t;
    });
    const rx = W * 0.65, rw = W * 0.28;
    txt(g, "WITHOUT VEHICLE AGE", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, cur.toFixed(1) + "%", rx, H * 0.29, { size: H * 0.12, color: ORG, spacing: -3 });
    txt(g, "of the out-of-sample gain is lost", rx, H * 0.345, { size: H * 0.026, color: hex(ink, 0.7), weight: 400 });
    [["Without bonus-malus, gain lost", "35.2%", ORG], ["Without driver age, gain lost", "7.3%", BL], ["Riskiest tenth of exposure claims", "2.7\u00d7", ink]].forEach(([nm, v, c], i) => {
      const y = H * 0.54 + i * H * 0.14, t = ease.out5(seg(u, 0.66 + i * 0.07, 0.84 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.038, color: c, align: "right", alpha: t });
    });
  },
});
