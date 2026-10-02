/* Federal IT Contracts, Cleaned. The naive total of the transactions is 26 times the correct one and shrinks as the cleaning steps
   run; then the contractor ranking re-sorts once parent names are normalised: Leidos goes from 3rd to 1st ($3.73B, ahead of Booz
   Allen Hamilton $3.35B and General Dynamics $3.28B). */
scene({
  slug: "federal-contracts-cleaning", aspect: 1.72, seconds: 6, bg: ["#0e1420", "#04060b"],
  draw(g, u, W, H, S, { seg, ease, hex, txt, rr, lerp, line }) {
    const ink = "#eef2fb", ORG = "#d95926", BL = "#3987e5", GRY = "#7c818c";
    txt(g, "WHAT DID THE GOVERNMENT SPEND?", W * 0.05, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    const k = ease.inOut(seg(u, 0.12, 0.45)), x = W * 0.05, maxw = W * 0.47, w = lerp(maxw, maxw / 26, k);
    g.fillStyle = k < 1 ? ORG : BL; rr(g, x, H * 0.24, Math.max(4, w), H * 0.1, 10); g.fill();
    txt(g, k < 0.98 ? "every column added up: " + Math.round(lerp(26, 1, k)) + "× too high" : "after cleaning: the real total", x, H * 0.42, { size: H * 0.03, color: k < 0.98 ? ORG : BL, weight: 400 });
    ["dedupe modifications", "net out money taken back", "one row per action"].forEach((s, i) => {
      const t = seg(u, 0.12 + i * 0.1, 0.2 + i * 0.1);
      txt(g, (t >= 1 ? "✓ " : "· ") + s, x, H * 0.52 + i * H * 0.07, { size: H * 0.028, color: t >= 1 ? ink : hex(ink, 0.35), weight: 400 });
    });
    const rx = W * 0.6, top = H * 0.2, step = H * 0.13;
    txt(g, "BIGGEST CONTRACTOR, BY PARENT", rx, H * 0.12, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    const k2 = ease.inOut(seg(u, 0.5, 0.72));
    [["Booz Allen Hamilton", 0, 1, "$3.35B"], ["General Dynamics", 1, 2, "$3.28B"], ["Leidos", 2, 0, "$3.73B"]].forEach(([n, a, b, v]) => {
      const y = top + lerp(a, b, k2) * step, lead = n === "Leidos";
      g.fillStyle = hex(ink, 0.06); rr(g, rx, y, W * 0.34, H * 0.1, 10); g.fill();
      txt(g, String(Math.round(lerp(a, b, k2)) + 1), rx + 18, y + H * 0.065, { size: H * 0.04, color: lead ? ORG : GRY });
      txt(g, n, rx + W * 0.06, y + H * 0.063, { size: H * 0.032, color: lead ? "#fff" : hex(ink, 0.8), weight: 400 });
      txt(g, v, rx + W * 0.32, y + H * 0.063, { size: H * 0.03, color: lead ? ORG : GRY, align: "right", alpha: seg(u, 0.7, 0.8) });
    });
    txt(g, "names normalised: Leidos moves from 3rd to 1st", rx, H * 0.67, { size: H * 0.028, color: hex(ink, 0.7), weight: 400, alpha: seg(u, 0.72, 0.82) });
    txt(g, "124,996 transactions · FY2025", rx, H * 0.86, { size: H * 0.024, color: hex(ink, 0.45), spacing: 1, alpha: seg(u, 0.78, 0.88) });
  },
});
