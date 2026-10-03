/* What Does a Night in New York Cost on Airbnb? 100 listings as 100 squares: 19 can be booked for under 30 nights (orange), 81 need 30 nights or more (blue) (19.1% and 80.9% of 30,555). Right: the median price a night is $303
   for the short stays and $143 for the monthly ones; 88.6% of short stays show a registration number or Exempt, against 0.5% of monthly stays. */
scene({
  slug: "nyc-airbnb-cleaning", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0";
    const cell = H * 0.052, gap = H * 0.011, gx = W * 0.075, gy = H * 0.2, SHORTSQ = 19;
    txt(g, "100 NEW YORK AIRBNB LISTINGS", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    const k = ease.out3(seg(u, 0.05, 0.5)) * 103;
    for (let i = 0; i < 100; i++) {
      const r = Math.floor(i / 10), c = i % 10, a = Math.max(0, Math.min(1, (k - i) / 3)), col = i < SHORTSQ ? ORG : BL;
      rr(g, gx + c * (cell + gap), gy + r * (cell + gap), cell, cell, cell * 0.2); g.fillStyle = hex(col, 0.12 + 0.88 * a); g.fill();
    }
    const ly = gy + 10 * (cell + gap) + H * 0.045, la = ease.out3(seg(u, 0.4, 0.55));
    g.save(); g.globalAlpha = la; rr(g, gx, ly - H * 0.02, H * 0.022, H * 0.022, 3); g.fillStyle = ORG; g.fill(); rr(g, gx + W * 0.19, ly - H * 0.02, H * 0.022, H * 0.022, 3); g.fillStyle = BL; g.fill(); g.restore();
    txt(g, "19 under 30 nights", gx + H * 0.035, ly, { size: H * 0.022, color: hex(ink, 0.75), weight: 400, alpha: la }); txt(g, "81 need 30 nights or more", gx + W * 0.19 + H * 0.035, ly, { size: H * 0.022, color: hex(ink, 0.75), weight: 400, alpha: la });
    const rx = W * 0.62, rw = W * 0.31, k2 = ease.out3(seg(u, 0.5, 0.74));
    txt(g, "MEDIAN PRICE A NIGHT", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, "$" + Math.round(303 + (143 - 303) * k2), rx, H * 0.29, { size: H * 0.12, color: k2 > 0.5 ? BL : ORG, spacing: -3 });
    txt(g, k2 < 0.5 ? "a short stay, under 30 nights" : "a monthly stay, 30 nights or more", rx, H * 0.345, { size: H * 0.026, color: hex(ink, 0.7), weight: 400 });
    [["Listings needing 30 nights or more", "80.9%", BL], ["Short stays with a number or Exempt", "88.6%", ORG], ["Monthly stays with one", "0.5%", ink]].forEach(([nm, v, c], i) => {
      const y = H * 0.54 + i * H * 0.14, t = ease.out5(seg(u, 0.66 + i * 0.07, 0.84 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.038, color: c, align: "right", alpha: t });
    });
  },
});
