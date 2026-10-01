/* Shared helpers for the motion tiles. A scene is a pure function of loop phase u (0..1), so every frame is
   reproducible and the clip loops. Nothing here runs on the live site: it is only used by motion/render.cjs. */
(function () {
  const TAU = Math.PI * 2;
  const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
  const lerp = (a, b, t) => a + (b - a) * t;
  const seg = (u, a, b) => clamp((u - a) / (b - a));            // how far u is through the window [a, b]
  const ease = {
    out3: (t) => 1 - Math.pow(1 - t, 3),
    out5: (t) => 1 - Math.pow(1 - t, 5),
    in3: (t) => t * t * t,
    inOut: (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
    smooth: (t) => t * t * (3 - 2 * t),
    back: (t) => { const c = 1.70158; return 1 + (c + 1) * Math.pow(t - 1, 3) + c * Math.pow(t - 1, 2); },
    expo: (t) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t)),
  };
  function rng(seed) {                                         // mulberry32
    let a = seed >>> 0;
    return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  }
  function gauss(r) { let u = 0, v = 0; while (!u) u = r(); while (!v) v = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(TAU * v); }
  const hex = (c, a = 1) => { const n = parseInt(c.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; };
  const rgbOf = (c) => { if (c[0] === '#') { const n = parseInt(c.slice(1), 16); return [n >> 16, (n >> 8) & 255, n & 255]; } return c.match(/[\d.]+/g).slice(0, 3).map(Number); };
  const mix = (c1, c2, t) => { const a = rgbOf(c1), b = rgbOf(c2); return `rgb(${a.map((v, i) => Math.round(lerp(v, b[i], t))).join(',')})`; };
  const wrap01 = (x) => x - Math.floor(x);

  function rr(g, x, y, w, h, r) {                              // rounded-rect path
    r = Math.max(0, Math.min(r, w / 2, h / 2));
    g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath();
  }
  function txt(g, s, x, y, o = {}) {
    g.save();
    g.font = `${o.weight || 500} ${o.size || 18}px ${o.mono ? '"Geist Mono"' : 'Geist'}, Helvetica, Arial, sans-serif`;
    g.fillStyle = o.color || '#fff'; g.textAlign = o.align || 'left'; g.textBaseline = o.base || 'alphabetic';
    if (o.alpha != null) g.globalAlpha *= o.alpha;
    if (o.spacing != null && 'letterSpacing' in g) g.letterSpacing = o.spacing + 'px';
    g.fillText(s, x, y); g.restore();
  }
  function line(g, x1, y1, x2, y2, color, w = 1, dash) {
    g.save(); g.strokeStyle = color; g.lineWidth = w; if (dash) g.setLineDash(dash);
    g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke(); g.restore();
  }
  function dot(g, x, y, r, color, glow) {
    g.save(); g.fillStyle = color; if (glow) { g.shadowColor = glow; g.shadowBlur = r * 3; }
    g.beginPath(); g.arc(x, y, r, 0, TAU); g.fill(); g.restore();
  }
  // polyline through pts [[x,y],...] up to fraction p (0..1) of its length
  function path(g, pts, p, color, w = 2, glow) {
    const n = pts.length - 1, f = clamp(p) * n; if (n < 1 || f <= 0) return;
    g.save(); g.strokeStyle = color; g.lineWidth = w; g.lineJoin = 'round'; g.lineCap = 'round';
    if (glow) { g.shadowColor = glow; g.shadowBlur = w * 5; }
    g.beginPath(); g.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i <= Math.floor(f); i++) g.lineTo(pts[i][0], pts[i][1]);
    const i = Math.floor(f), t = f - i;
    if (i < n && t > 0) g.lineTo(lerp(pts[i][0], pts[i + 1][0], t), lerp(pts[i][1], pts[i + 1][1], t));
    g.stroke(); g.restore();
  }
  const pointOn = (pts, p) => { const n = pts.length - 1, f = clamp(p) * n, i = Math.min(n - 1, Math.floor(f)), t = f - i; return [lerp(pts[i][0], pts[i + 1][0], t), lerp(pts[i][1], pts[i + 1][1], t)]; };
  const quad = (a, c, b, t) => [(1 - t) * (1 - t) * a[0] + 2 * (1 - t) * t * c[0] + t * t * b[0], (1 - t) * (1 - t) * a[1] + 2 * (1 - t) * t * c[1] + t * t * b[1]];
  const fmt = (n, d = 0) => n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });

  window.T = { TAU, clamp, lerp, seg, ease, rng, gauss, hex, mix, wrap01, rr, txt, line, dot, path, pointOn, quad, fmt };
  window.SCENES = window.SCENES || {};
  window.scene = (def) => { window.SCENES[def.slug] = def; };
})();
