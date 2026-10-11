/* Synapse Tribunal: one income prediction (Adult census, case 35) put on trial. Left: its closed-form linear SHAP
   attributions, in logit units, as the app shows them. Right: the logistic model's 73.8% against the 0.50 threshold, stamped
   like the app's verdict. Every figure is on the case study. */
const ATTR = [["Years of schooling", 1.351], ["Marital status", 1.172], ["Occupation", 0.507], ["Capital gain", -0.34], ["Sex", 0.248], ["Capital loss", -0.056]];
scene({
  slug: "synapse-tribunal", aspect: 1.72, seconds: 6, bg: ["#15161c", "#08080b"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr }) {
    const paper = "#f0eee9", RED = "#df514b", DIM = "#c9c6bd";
    txt(g, "CASE 00035 · WHY THE MODEL SAID YES (LOGIT)", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(paper, 0.55), spacing: 2.5 });
    const lx = W * 0.05, labW = W * 0.17, zx = lx + labW + W * 0.11, scale = W * 0.12;
    line(g, zx, H * 0.18, zx, H * 0.86, hex(paper, 0.3), 1);
    ATTR.forEach(([nm, v], i) => {
      const y = H * 0.24 + i * H * 0.105, t = ease.out5(seg(u, 0.04 + i * 0.06, 0.3 + i * 0.06)), w = v * scale * t;
      txt(g, nm, lx, y + H * 0.012, { size: H * 0.025, color: hex(paper, 0.8), weight: 400 });
      g.fillStyle = v > 0 ? RED : DIM; g.fillRect(Math.min(zx, zx + w), y - H * 0.022, Math.abs(w), H * 0.044);
      txt(g, (v > 0 ? "+" : "") + v.toFixed(3), zx + Math.max(0, v) * scale + H * 0.02, y + H * 0.012, { size: H * 0.022, color: hex(paper, 0.6 * t) });
    });
    const rx = W * 0.62, rw = W * 0.32, p = 0.738 * ease.inOut(seg(u, 0.35, 0.6));
    txt(g, "PROBABILITY OF EXCEEDING $50K", rx, H * 0.12, { size: H * 0.024, color: hex(paper, 0.55), spacing: 2.5 });
    txt(g, (p * 100).toFixed(1) + "%", rx, H * 0.3, { size: H * 0.12, color: paper, spacing: -3 });
    const by = H * 0.4;
    g.fillStyle = hex(paper, 0.12); g.fillRect(rx, by, rw, H * 0.02);
    g.fillStyle = RED; g.fillRect(rx, by, rw * p, H * 0.02);
    line(g, rx + rw * 0.5, by - H * 0.025, rx + rw * 0.5, by + H * 0.045, hex(paper, 0.7), 1.5);
    txt(g, "threshold 0.50", rx + rw * 0.5, by + H * 0.085, { size: H * 0.02, color: hex(paper, 0.5), align: "center" });
    const st = ease.out5(seg(u, 0.62, 0.7)), sc = 1 + (1 - st) * 0.6;
    if (st > 0) {
      g.save(); g.translate(rx + rw * 0.48, H * 0.64); g.rotate(-0.06); g.scale(sc, sc); g.globalAlpha = st;
      g.strokeStyle = RED; g.lineWidth = H * 0.006; rr(g, -rw * 0.46, -H * 0.06, rw * 0.92, H * 0.12, H * 0.008); g.stroke();
      txt(g, "PREDICTED: EXCEEDS $50K", 0, H * 0.012, { size: H * 0.032, color: RED, align: "center", spacing: 2 });
      g.restore();
    }
    const ft = ease.out5(seg(u, 0.74, 0.86));
    txt(g, "Test AUROC  logistic 0.9045  ·  boosted trees 0.9260", rx, H * 0.84, { size: H * 0.021, color: hex(paper, 0.6), alpha: ft });
  },
});
