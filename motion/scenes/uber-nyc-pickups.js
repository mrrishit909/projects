/* When and Where Does New York Take an Uber? Pickups per hour of the day, by weekday, averaged over April to September 2014 (4,534,327 pickups): a sweep lights the 7 x 24 grid and the counter settles on the busiest hour, Thursday 5 to 6 pm
   (2,181 pickups). Right: the quietest day was Memorial Day (10,202 pickups), 72.7% of 2015 pickups were in Manhattan, and pickups a day grew 82.1% from April to September 2014. */
const HM = [[248, 144, 113, 240, 371, 578, 913, 1198, 1126, 854, 780, 782, 788, 899, 1083, 1259, 1491, 1616, 1423, 1314, 1263, 1112, 775, 454], [231, 130, 95, 166, 280, 527, 995, 1356, 1257, 927, 877, 877, 883, 1077, 1291, 1531, 1802, 2056, 1859, 1659, 1654, 1478, 1026, 551], [294, 166, 121, 187, 289, 531, 1036, 1404, 1301, 986, 950, 960, 982, 1122, 1352, 1669, 1949, 2140, 2028, 1808, 1837, 1714, 1264, 698], [357, 203, 143, 217, 327, 545, 1041, 1425, 1363, 1070, 995, 999, 1018, 1186, 1412, 1709, 1945, 2181, 2147, 1996, 2000, 1998, 1700, 1068], [528, 314, 206, 267, 339, 517, 900, 1233, 1212, 970, 930, 969, 996, 1167, 1393, 1680, 1853, 1998, 2106, 1908, 1675, 1859, 1900, 1587], [1063, 738, 489, 367, 263, 272, 330, 424, 554, 680, 792, 874, 935, 1024, 1208, 1491, 1674, 1648, 1765, 1581, 1489, 1686, 1844, 1661], [1264, 885, 594, 408, 245, 237, 254, 336, 466, 631, 763, 879, 920, 1016, 1083, 1197, 1271, 1212, 1088, 998, 964, 922, 753, 468]];
scene({
  slug: "uber-nyc-pickups", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, line, rr, mix, lerp }) {
    const ink = "#eef0f4", ORG = "#ff8a3d", BL = "#4a95f0", DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], MAXV = 2181;
    const gx = W * 0.125, gw = W * 0.45, gy = H * 0.2, gh = H * 0.56, cw = gw / 24, ch = gh / 7;
    const heat = (t) => (t < 0.5 ? mix("#1c110c", "#8f330f", t / 0.5) : t < 0.8 ? mix("#8f330f", ORG, (t - 0.5) / 0.3) : mix(ORG, "#fff0d0", (t - 0.8) / 0.2));
    txt(g, "PICKUPS PER HOUR, BY WEEKDAY AND HOUR", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    DAYS.forEach((d, r) => txt(g, d, gx - W * 0.012, gy + ch * (r + 0.62), { size: H * 0.022, color: hex(ink, 0.5), align: "right" }));
    [[0, "12 am"], [6, "6 am"], [12, "noon"], [18, "6 pm"]].forEach(([c, l]) => txt(g, l, gx + cw * c, gy + gh + H * 0.055, { size: H * 0.021, color: hex(ink, 0.45) }));
    const sweep = seg(u, 0.06, 0.56); let cur = 0;
    for (let c = 0; c < 24; c++) {
      const a = Math.max(0, Math.min(1, (sweep * 1.08 - c / 24) / 0.06));
      for (let r = 0; r < 7; r++) {
        rr(g, gx + cw * c + 1, gy + ch * r + 1, cw - 2, ch - 2, 3); g.fillStyle = hex("#1c110c", 0.55); g.fill();
        if (a > 0) { rr(g, gx + cw * c + 1, gy + ch * r + 1, cw - 2, ch - 2, 3); g.fillStyle = heat(HM[r][c] / MAXV); g.globalAlpha = a; g.fill(); g.globalAlpha = 1; }
        cur = Math.max(cur, HM[r][c] * a);
      }
    }
    if (sweep > 0 && sweep < 1) line(g, gx + gw * Math.min(1, sweep * 1.08), gy - H * 0.01, gx + gw * Math.min(1, sweep * 1.08), gy + gh + H * 0.01, hex(ORG, 0.7), 2);
    const rx = W * 0.65, rw = W * 0.28;
    txt(g, "BUSIEST HOUR, PICKUPS PER DAY", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, Math.round(cur).toLocaleString("en-US"), rx, H * 0.29, { size: H * 0.12, color: sweep >= 1 ? ORG : BL, spacing: -3 });
    txt(g, sweep >= 1 ? "Thursday, 5 to 6 pm" : "the busiest hour so far", rx, H * 0.345, { size: H * 0.026, color: hex(ink, 0.7), weight: 400 });
    [["Quietest day: Memorial Day", "10,202", BL], ["Manhattan, share of 2015 pickups", "72.7%", ORG], ["Pickups a day, Apr to Sep 2014", "+82.1%", ink]].forEach(([nm, v, c], i) => {
      const y = H * 0.54 + i * H * 0.14, t = ease.out5(seg(u, 0.64 + i * 0.07, 0.82 + i * 0.07));
      line(g, rx, y - H * 0.05, rx + rw, y - H * 0.05, hex(ink, 0.12), 1);
      txt(g, nm, rx, y, { size: H * 0.024, color: hex(ink, 0.8), weight: 400, alpha: t });
      txt(g, v, rx + rw, y + H * 0.05, { size: H * 0.038, color: c, align: "right", alpha: t });
    });
  },
});
