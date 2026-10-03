/* How Many More People Died Than the Official COVID-19 Count Says? Pooled over the eligible countries (105, 104 and 94): official COVID-19 deaths (grey) and excess deaths against a 2015-2019 trend (orange), in
   millions, for 2020, 2021 and 2022: 1.55 and 2.63, 2.78 and 4.55, 1.06 and 1.87. Right: 4.55 million excess deaths in 2021 against 2.78 million official; excess over official 1.7, 1.6 and 1.8 times;
   72 of 104 countries beyond their 95% prediction interval in 2021. */
const REP = [1.55, 2.78, 1.06], EXC = [2.63, 4.55, 1.87];
scene({
  slug: "covid-excess-deaths", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", GR = "#8f918d";
    const x0 = W * 0.1, x1 = W * 0.58, y0 = H * 0.2, y1 = H * 0.8, Y = (v) => y1 - v / 5 * (y1 - y0), gw = (x1 - x0) / 3;
    txt(g, "DEATHS IN MILLIONS, ALL ELIGIBLE COUNTRIES", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [0, 1, 2, 3, 4, 5].forEach((v) => { line(g, x0, Y(v), x1, Y(v), hex(ink, v ? 0.08 : 0.3), 1); txt(g, String(v), x0 - H * 0.015, Y(v) + H * 0.008, { size: H * 0.02, color: hex(ink, 0.4), align: "right" }); });
    [2020, 2021, 2022].forEach((yr, i) => {
      const cx = x0 + gw * (i + 0.5), bw = gw * 0.3, t1 = ease.out3(seg(u, 0.06 + i * 0.1, 0.3 + i * 0.1)), t2 = ease.out3(seg(u, 0.14 + i * 0.1, 0.38 + i * 0.1));
      [[REP[i], GR, -bw * 0.55, t1], [EXC[i], ORG, bw * 0.55, t2]].forEach(([v, c, dx, t]) => {
        g.fillStyle = c; g.fillRect(cx + dx - bw / 2, Y(v * t), bw, Y(0) - Y(v * t));
        txt(g, (v * t).toFixed(2), cx + dx, Y(v * t) - H * 0.015, { size: H * 0.024, color: "#fff", align: "center", alpha: Math.min(1, t * 2) });
      });
      txt(g, String(yr), cx, y1 + H * 0.055, { size: H * 0.026, color: hex(ink, 0.6), align: "center" });
    });
    const rx = W * 0.67, rw = W * 0.28, k = ease.out3(seg(u, 0.45, 0.72));
    txt(g, "EXCESS DEATHS IN 2021", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, (4.55 * k).toFixed(2) + "M", rx, H * 0.29, { size: H * 0.12, color: ORG, spacing: -3 });
    txt(g, "against 2.78M official COVID-19 deaths", rx, H * 0.345, { size: H * 0.026, color: hex(ink, 0.7), weight: 400 });
    [["Excess ÷ official, 2020 · 2021 · 2022", "1.7 · 1.6 · 1.8", BL], ["Beyond their interval, 2021", "72 of 104", ORG], ["The five biggest hold, 2021", "49.6%", ink]].forEach(([nm, v, c], i) => {
      const y = H * 0.54 + i * H * 0.14, t = ease.out5(seg(u, 0.64 + i * 0.07, 0.82 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.038, color: c, align: "right", alpha: t });
    });
  },
});
