/* Handwritten Digits: a 28x28 pixel grid is drawn, the slant is straightened (the project is about preprocessing), and ten bars
   show the network's confidence settling on one digit. Four digits per loop. */
scene({
  slug: "mnist-digits", aspect: 1.527, seconds: 6, bg: ["#0a0e14", "#030508"],
  init(W, H, { rng }) {
    const digits = [3, 7, 2, 9], r = rng(4), out = [];
    const cv = document.createElement("canvas"); cv.width = cv.height = 28; const c = cv.getContext("2d", { willReadFrequently: true });
    const bitmap = (d, slant) => {
      c.setTransform(1, 0, 0, 1, 0, 0); c.fillStyle = "#000"; c.fillRect(0, 0, 28, 28); c.fillStyle = c.strokeStyle = "#fff"; c.lineWidth = 1.1; c.lineJoin = "round";
      c.font = '500 21px Geist, Helvetica, Arial, sans-serif'; c.textAlign = "center"; c.textBaseline = "alphabetic";
      c.setTransform(1, 0, -slant, 1, slant * 14, 0); c.fillText(String(d), 14, 21.5); c.strokeText(String(d), 14, 21.5);
      const px = c.getImageData(0, 0, 28, 28).data, a = new Float32Array(784); for (let i = 0; i < 784; i++) a[i] = px[i * 4] / 255; return a;
    };
    digits.forEach((d) => out.push({ d, slanted: bitmap(d, 0.32), upright: bitmap(d, 0), order: Float32Array.from({ length: 784 }, () => r()) }));
    return { out };
  },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, dot, rr, clamp }) {
    const CY = "#5fd3ff", ink = "#e8f1fa", n = S.out.length, k = Math.min(n - 1, Math.floor(u * n)), lu = (u * n) - k, d = S.out[k];
    const gs = H * 0.78, cell = gs / 28, gx = W * 0.05, gy = H * 0.11;
    // phases inside a digit: draw .0-.32, straighten .36-.56, read .56-.9, leave .9-1
    const draw = seg(lu, 0, 0.32), straight = ease.inOut(seg(lu, 0.36, 0.56)), read = ease.out5(seg(lu, 0.56, 0.84)), leave = 1 - ease.smooth(seg(lu, 0.9, 1)), enter = ease.smooth(seg(lu, 0, 0.06));
    g.save(); g.globalAlpha *= leave * enter;
    g.fillStyle = hex(ink, 0.03); g.fillRect(gx, gy, gs, gs);
    const sheared = 1 - straight;
    for (let y = 0; y < 28; y++) for (let x = 0; x < 28; x++) {
      const i = y * 28 + x, a = lerp(d.slanted[i], d.upright[i], straight) * (draw > d.order[i] ? 1 : 0);
      g.fillStyle = hex(ink, 0.05); g.fillRect(gx + x * cell + 1, gy + y * cell + 1, cell - 2, cell - 2);
      if (a > 0.02) { g.fillStyle = `rgba(${Math.round(95 + 160 * a)},${Math.round(211 + 40 * a)},255,${Math.min(1, a * 1.15)})`; g.fillRect(gx + x * cell + 1, gy + y * cell + 1, cell - 2, cell - 2); }
    }
    if (straight > 0 && straight < 1) { g.strokeStyle = hex(CY, 0.8 * Math.sin(straight * Math.PI)); g.lineWidth = 2; g.strokeRect(gx - 4, gy - 4, gs + 8, gs + 8); }
    txt(g, straight < 0.5 ? "28 × 28 PIXELS" : "DESKEWED", gx, gy - H * 0.022, { size: H * 0.024, color: hex(ink, 0.5), spacing: 2.5 });
    // ten class bars
    const bx = W * 0.62, bw = W * 0.31, by = H * 0.12, rowH = H * 0.079;
    for (let c = 0; c < 10; c++) {
      const y = by + c * rowH, hit = c === d.d, p = hit ? 0.55 + 0.44 * read : (0.05 + 0.2 * Math.sin(c * 2.3 + k) ** 2) * (1 - read * 0.9);
      txt(g, String(c), bx - H * 0.03, y + rowH * 0.54, { size: H * 0.034, color: hit && read > 0.5 ? CY : hex(ink, 0.5), align: "right", weight: hit ? 500 : 400 });
      g.fillStyle = hex(ink, 0.06); rr(g, bx, y + rowH * 0.2, bw, rowH * 0.45, 6); g.fill();
      g.fillStyle = hit && read > 0.3 ? CY : hex(ink, 0.4); rr(g, bx, y + rowH * 0.2, Math.max(0.001, bw * clamp(p) * Math.max(draw, 0.2)), rowH * 0.45, 6); g.fill();
    }
    g.restore();
  },
});
