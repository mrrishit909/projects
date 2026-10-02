/* Who Is Missed by Blood-Pressure Care. The care cascade from the case study (NHANES 2021-2023): 47.7% of adults have hypertension;
   of them 59.2% know, 51.2% are treated, 20.7% are controlled. Right: uninsured adults have 2.2x the odds of not knowing. */
scene({
  slug: "nhanes-sas", aspect: 1.72, seconds: 6, bg: ["#140f16", "#060407"],
  draw(g, u, W, H, S, { seg, ease, hex, mix, txt, rr }) {
    const ink = "#f5eef6", RED = "#ff5f6d", x0 = W * 0.06, base = H * 0.82, bw = W * 0.09, gap = W * 0.03, hmax = H * 0.55;
    txt(g, "THE CARE CASCADE, US ADULTS", x0, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Has it", 47.7, "of all adults"], ["Aware", 59.2, "of those"], ["Treated", 51.2, "of those"], ["Controlled", 20.7, "of those"]].forEach(([n, v, sub], i) => {
      const t = ease.out5(seg(u, 0.06 + i * 0.1, 0.3 + i * 0.1)), x = x0 + i * (bw + gap), h = hmax * v / 100 * t, c = mix("#7f6cff", RED, i / 3);
      g.fillStyle = hex(ink, 0.06); rr(g, x, base - hmax, bw, hmax, 10); g.fill();
      g.fillStyle = c; rr(g, x, base - h, bw, Math.max(0.001, h), 10); g.fill();
      txt(g, (v * t).toFixed(1) + "%", x + bw / 2, base - h - H * 0.02, { size: H * 0.032, color: "#fff", align: "center", alpha: t });
      txt(g, n, x + bw / 2, base + H * 0.05, { size: H * 0.026, color: ink, align: "center", weight: 400 });
      txt(g, sub, x + bw / 2, base + H * 0.09, { size: H * 0.02, color: hex(ink, 0.45), align: "center" });
    });
    const rx = W * 0.6, k = ease.out5(seg(u, 0.5, 0.72));
    txt(g, "UNINSURED, ODDS OF NOT KNOWING", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, (2.2 * k).toFixed(1) + "×", rx, H * 0.32, { size: H * 0.16, color: RED, spacing: -4 });
    txt(g, "the insured's (95% CI 1.51–3.19)", rx, H * 0.4, { size: H * 0.028, color: hex(ink, 0.7), weight: 400, alpha: k });
    const k2 = seg(u, 0.7, 0.82);
    txt(g, "CDC's figures rebuilt in SAS", rx, H * 0.62, { size: H * 0.03, color: ink, weight: 400, alpha: k2 });
    txt(g, "23 of 24 match to one decimal", rx, H * 0.69, { size: H * 0.03, color: hex(ink, 0.7), weight: 400, alpha: k2 });
    txt(g, "48 results recomputed in Python", rx, H * 0.76, { size: H * 0.03, color: hex(ink, 0.7), weight: 400, alpha: k2 });
  },
});
