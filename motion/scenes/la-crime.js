/* When and Where Does Crime Happen in Los Angeles? Crimes by hour of the day (the chart on the case-study page; real counts): blue bars are crimes logged at any other minute, the orange
   cap at 12:00 is the 32,715 crimes logged at exactly 12:00, a default time (3.6% of all). Without it the busiest hour is 6 pm. Right: 39.3% of crimes fall exactly on the hour; monthly
   reports fall from 19,321 in September 2023 to 4,697 in December 2024 after the LAPD changed records systems on 7 March 2024. */
const D = {"base": [37619, 27397, 23252, 20379, 17249, 15835, 20770, 23570, 33767, 33160, 39197, 39764, 29503, 41344, 44656, 47773, 48093, 53226, 54327, 50291, 50787, 46168, 44475, 38330], "noon": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 32715, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]};
scene({
  slug: "la-crime", aspect: 1.72, seconds: 6, bg: ["#13110e", "#050403"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line }) {
    const ink = "#f4efe9", ORG = "#ff8a3d", BL = "#4a95f0";
    const x0 = W * 0.06, x1 = W * 0.58, y0 = H * 0.2, y1 = H * 0.78, bw = (x1 - x0) / 24, mx = 64000;
    txt(g, "CRIMES BY HOUR OF THE DAY", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    D.base.forEach((v, i) => {
      const t = ease.out3(seg(u, 0.05 + i * 0.015, 0.2 + i * 0.015)), x = x0 + i * bw + bw * 0.1, w = bw * 0.8, hb = (y1 - y0) * v / mx * t;
      g.fillStyle = BL; g.fillRect(x, y1 - hb, w, hb);
      if (D.noon[i]) { const tn = ease.out3(seg(u, 0.45, 0.62)), hn = (y1 - y0) * D.noon[i] / mx * tn; g.fillStyle = ORG; g.fillRect(x, y1 - hb - hn, w, hn); }
    });
    line(g, x0, y1 + 1, x1, y1 + 1, hex(ink, 0.25), 1);
    [0, 6, 12, 18].forEach((hh) => txt(g, hh + ":00", x0 + hh * bw + bw / 2, y1 + H * 0.05, { size: H * 0.021, color: hex(ink, 0.5), align: "center" }));
    const a = seg(u, 0.55, 0.68);
    txt(g, "12:00 is a default time", x0 + 11.7 * bw, y0 + H * 0.05, { size: H * 0.026, color: ORG, align: "right", alpha: a });
    txt(g, "real peak: 6 pm", x0 + 18 * bw + bw / 2, y1 - (y1 - y0) * 54327 / mx - H * 0.02, { size: H * 0.023, color: hex(ink, 0.85), align: "center", alpha: seg(u, 0.62, 0.74) });
    const rx = W * 0.67, rw = W * 0.28, k = ease.out5(seg(u, 0.45, 0.72));
    txt(g, "LOGGED AT EXACTLY 12:00", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, (3.6 * k).toFixed(1) + "%", rx, H * 0.29, { size: H * 0.13, color: "#fff", spacing: -3 });
    txt(g, "of 913,647 crimes: 52 times a normal minute", rx, H * 0.345, { size: H * 0.024, color: hex(ink, 0.7), weight: 400, alpha: k });
    [["Crimes exactly on the hour", "39.3%", BL], ["Victim age recorded as 0", "25.1%", ORG], ["Reports a month, Sep 2023 \u2192 Dec 2024", "19,321 \u2192 4,697", ink]].forEach(([n, v, c], i) => {
      const y = H * 0.52 + i * H * 0.14, t = ease.out5(seg(u, 0.62 + i * 0.07, 0.8 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12), 1);
      txt(g, n, rx, y, { size: H * 0.023, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.036, color: c, align: "right", alpha: t });
    });
  },
});
