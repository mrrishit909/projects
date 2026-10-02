/* Where Did the Recalled Food Go? Real distribution texts from the project slide in and their state codes light up on a tile grid
   (CA, FL, UT; CT FL GA IA IL IN MA NH NJ PA TX WI; MD VA DC). Right: food 79% named states vs drugs 81% nationwide, and the mess:
   14,659 nationwide events written 8,913 different ways. */
scene({
  slug: "fda-recalls-cleaning", aspect: 1.72, seconds: 6, bg: ["#14100c", "#050403"],
  draw(g, u, W, H, S, { seg, ease, hex, mix, txt, rr, lerp }) {
    const ink = "#f6efe6", ORG = "#ff8a3d", BL = "#3987e5";
    const grid = [". . . . . . . . . . ME", ". . . . . . . . . VT NH", "WA ID MT ND MN IL WI MI NY RI MA", "OR NV WY SD IA IN OH PA NJ CT", "CA UT CO NE MO KY WV VA MD DE",
      ". AZ NM KS AR TN NC SC DC", ". . . OK LA MS AL GA", "HI AK . TX . . . . FL"];       // tile map, "." = empty
    const pos = {}; grid.forEach((row, r) => row.split(" ").forEach((s, c) => { if (s !== ".") pos[s] = [c, r]; }));
    const texts = [["CA, FL and UT", "CA FL UT", 0.08], ["CT FL GA IA IL IN MA NH NJ PA TX WI", "CT FL GA IA IL IN MA NH NJ PA TX WI", 0.3], ["sold in Virginia, Maryland and Washington, D.C.", "VA MD DC", 0.52]];
    txt(g, "FREE TEXT IN, STATES OUT", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    const cur = texts.filter((t) => u >= t[2]).pop() || texts[0], k = ease.out3(seg(u, cur[2], cur[2] + 0.06)), lit = new Set(cur[1].split(" "));
    txt(g, "“" + cur[0] + "”", W * 0.05, H * 0.21, { size: H * 0.03, color: ORG, mono: true, alpha: k });
    const s = W * 0.039, gx = W * 0.05, gy = H * 0.3;
    Object.entries(pos).forEach(([st, [c, r]]) => {
      const on = lit.has(st) ? ease.out3(seg(u, cur[2] + 0.04, cur[2] + 0.12)) : 0;
      g.fillStyle = mix("#2a241f", ORG, on); rr(g, gx + c * s, gy + r * s * 0.95, s - 4, s * 0.95 - 4, 5); g.fill();
      txt(g, st, gx + c * s + (s - 4) / 2, gy + r * s * 0.95 + s * 0.55, { size: H * 0.02, color: on > 0.5 ? "#1a1209" : hex(ink, 0.45), align: "center", mono: true });
    });
    const rx = W * 0.62, rw = W * 0.32;
    txt(g, "HOW FAR RECALLS REACH", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    [["Food: named states", 79, ORG], ["Drugs: nationwide", 81, BL]].forEach(([n, v, c], i) => {
      const y = H * 0.18 + i * H * 0.14, t = ease.out5(seg(u, 0.25 + i * 0.08, 0.5 + i * 0.08));
      txt(g, n, rx, y + H * 0.03, { size: H * 0.03, color: hex(ink, 0.85), weight: 400 });
      txt(g, Math.round(v * t) + "%", rx + rw, y + H * 0.03, { size: H * 0.036, color: c, align: "right" });
      g.fillStyle = hex(ink, 0.07); rr(g, rx, y + H * 0.055, rw, H * 0.02, 10); g.fill();
      g.fillStyle = c; rr(g, rx, y + H * 0.055, Math.max(0.001, rw * v / 100 * t), H * 0.02, 10); g.fill();
    });
    const k2 = ease.out5(seg(u, 0.6, 0.8));
    txt(g, "“NATIONWIDE”, WRITTEN", rx, H * 0.56, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    txt(g, Math.round(8913 * k2).toLocaleString("en-US"), rx, H * 0.7, { size: H * 0.11, color: "#fff", spacing: -3 });
    txt(g, "different ways across 14,659 events", rx, H * 0.77, { size: H * 0.028, color: hex(ink, 0.7), weight: 400, alpha: k2 });
  },
});
