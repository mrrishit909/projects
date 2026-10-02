/* ER Wait Dashboard Requirements. Requirement cards drop into a backlog with their MoSCoW priority; two get stamped "rejected with
   evidence". Right: why the data can't do it all: the CMS figure is 12 months old, and state median ED times run from 105 minutes
   (North Dakota) to 241 (Maryland). */
scene({
  slug: "er-wait-requirements", aspect: 1.72, seconds: 6, bg: ["#0c1220", "#03050b"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, rr, lerp }) {
    const ink = "#ecf1fb", MUST = "#ff6b6b", SHOULD = "#ffc35a", COULD = "#5c9dff", GRY = "#8a93a6";
    txt(g, "REQUIREMENTS, TRACED TO EVIDENCE", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    const reqs = [["REQ-01", "Live feed, under 15 min old", "MUST", MUST], ["REQ-02", "Compare only within volume group", "MUST", MUST], ["REQ-03", "Psychiatric wait beside overall", "SHOULD", SHOULD],
      ["REQ-04", "Explain every blank", "MUST", MUST], ["REQ-05", "Label every period", "MUST", MUST], ["REQ-06", "Left-without-being-seen rate", "SHOULD", SHOULD], ["REQ-07", "State view", "COULD", COULD],
      ["×", "National league table", "REJECTED", GRY], ["×", "Head-CT as a headline", "REJECTED", GRY]];
    reqs.forEach(([id, t, pr, c], i) => {
      const k = ease.out3(seg(u, 0.04 + i * 0.045, 0.14 + i * 0.045)); if (k <= 0) return;
      const y = H * 0.17 + i * H * 0.083 + (1 - k) * H * 0.03, x = W * 0.05, w = W * 0.47;
      g.save(); g.globalAlpha *= k; g.fillStyle = hex(ink, pr === "REJECTED" ? 0.03 : 0.07); rr(g, x, y, w, H * 0.068, 8); g.fill();
      g.fillStyle = c; g.fillRect(x, y + 6, 3, H * 0.068 - 12);
      txt(g, id, x + 14, y + H * 0.044, { size: H * 0.024, color: hex(ink, 0.5), mono: true });
      txt(g, t, x + W * 0.075, y + H * 0.044, { size: H * 0.028, color: pr === "REJECTED" ? hex(ink, 0.45) : ink, weight: 400 });
      txt(g, pr, x + w - 12, y + H * 0.044, { size: H * 0.022, color: c, align: "right", spacing: 1.5 });
      g.restore();
    });
    const rx = W * 0.6, rw = W * 0.34, k1 = ease.out5(seg(u, 0.4, 0.6));
    txt(g, "THE CMS FIGURE IS", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, Math.round(12 * k1) + " months", rx, H * 0.26, { size: H * 0.1, color: "#fff", spacing: -2 });
    txt(g, "old, so REQ-01 needs a live feed", rx, H * 0.32, { size: H * 0.028, color: MUST, weight: 400, alpha: k1 });
    txt(g, "STATE MEDIAN TIME IN THE ED", rx, H * 0.48, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["North Dakota", 105, COULD], ["Maryland", 241, MUST]].forEach(([n, v, c], i) => {
      const y = H * 0.56 + i * H * 0.15, t = ease.out5(seg(u, 0.6 + i * 0.08, 0.8 + i * 0.08));
      txt(g, n, rx, y + H * 0.03, { size: H * 0.03, color: hex(ink, 0.85), weight: 400 });
      txt(g, Math.round(v * t) + " min", rx + rw, y + H * 0.03, { size: H * 0.034, color: c, align: "right" });
      g.fillStyle = hex(ink, 0.07); rr(g, rx, y + H * 0.055, rw, H * 0.02, 10); g.fill();
      g.fillStyle = c; rr(g, rx, y + H * 0.055, Math.max(0.001, rw * v / 260 * t), H * 0.02, 10); g.fill();
    });
  },
});
