/* Projects home page.
 *
 * A flat row of project cards (video loops, or a slow pan over the cover when a project has no loop yet) that you drag, scroll or
 * arrow through forever. Everything on screen is drawn by one WebGL canvas: the cards, and also the text, so that the whole
 * picture can be bent by one swirl whose strength follows how fast you are moving. The DOM underneath only provides layout,
 * hit areas, focus and screen-reader text.
 *
 * Adding a project needs nothing here: build.py lists it in #projects-data, and it appears as another card.
 */
import * as THREE from "./vendor/three.module.min.js";

/* ---------- the feel: tweak here ---------- */
const SWIRL = 1.25;        // twist in radians at the centre of the screen when moving at full speed
const CHROMA = 0.009;      // colour fringing at full speed
const FOLLOW = 6.5;        // how quickly the row catches up with the wheel / your finger (per second)
const WHEEL = 1.0;         // wheel pixels -> row pixels
const MOMENTUM = 0.32;     // seconds of drag speed carried on after you let go
const INTRO = 1.7;         // seconds for the cards to glide in on load

const PROJECTS = JSON.parse(document.getElementById("projects-data").textContent);
const $ = (id) => document.getElementById(id);
const html = document.documentElement, body = document.body, canvas = $("gl"), rowEl = $("row");
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const mobileMQ = matchMedia("(max-width: 649.98px)"), hoverMQ = matchMedia("(hover: hover) and (pointer: fine)");
const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
const lerp = (a, b, t) => a + (b - a) * t;
const damp = (a, b, k, dt) => lerp(a, b, 1 - Math.exp(-k * dt));
const mod = (a, n) => ((a % n) + n) % n;
const smooth = (t) => { t = clamp(t, 0, 1); return t * t * (3 - 2 * t); };

let mode = "full", panel = null, gl = null;

/* =========================================================================================================
   Full view: every project by name, with a preview that trails the cursor (unchanged behaviour)
   ========================================================================================================= */
const cap = $("cap"), peek = $("peek"), peekv = $("peekv");
let px = 0, py = 0, tx = 0, ty = 0, showing = false, raf = 0, peekEl = peek;
function trail() {
  const vx = tx - px; px += vx * 0.16; py += (ty - py) * 0.16;
  const t = `translate(${px}px,${py}px) translate(-50%,calc(-100% - 36px)) rotate(${clamp(vx * 0.08, -8, 8)}deg)`;
  peek.style.transform = t; peekv.style.transform = t;
  raf = showing || Math.abs(vx) > 0.5 ? requestAnimationFrame(trail) : 0;
}
function peekShow(p, e) {
  const hasLoop = p.loops && p.loops.length;
  if (!hasLoop && !p.cover) return;
  if (hoverMQ.matches === false) return;
  if (!showing) { px = tx = e.clientX; py = ty = e.clientY; }
  const prev = peekEl;
  peekEl = hasLoop ? peekv : peek;
  if (prev !== peekEl) prev.style.opacity = 0;
  if (hasLoop) {
    peekv.replaceChildren(...p.loops.map((f) => Object.assign(document.createElement("source"), { src: `${p.slug}/${f}`, type: f.endsWith(".mp4") ? "video/mp4" : "video/webm" })));
    peekv.load(); peekv.play().catch(() => {});
  } else peek.src = `${p.slug}/${p.cover}`;
  showing = true;
  peekEl.animate([{ opacity: peekEl.style.opacity || 0 }, { opacity: 1 }], { duration: reduce ? 0 : 220, fill: "forwards" });
  if (!raf) raf = requestAnimationFrame(trail);
}
document.querySelectorAll("#full .item").forEach((a) => {
  const p = PROJECTS.find((q) => q.slug === a.dataset.slug);
  a.addEventListener("mouseenter", (e) => { cap.textContent = `${p.kind} — ${p.date}`; peekShow(p, e); });
  a.addEventListener("mouseleave", () => {
    cap.textContent = ""; showing = false;
    peekEl.animate([{ opacity: 1 }, { opacity: 0 }], { duration: reduce ? 0 : 180, fill: "forwards" }).finished.then(() => { if (!showing) peekv.pause(); }).catch(() => {});
  });
  a.addEventListener("focus", () => { cap.textContent = `${p.kind} — ${p.date}`; });
});
addEventListener("mousemove", (e) => { tx = e.clientX; ty = e.clientY; });

/* =========================================================================================================
   Modes and the Profile panel
   ========================================================================================================= */
function setMode(next) {
  const full = next === "full" || !gl;
  mode = full ? "full" : "featured";
  body.classList.toggle("full", full);
  body.classList.toggle("featured", !full);
  html.classList.toggle("featured-lock", !full);
  html.classList.remove("boot");
  $("m-featured").setAttribute("aria-pressed", String(!full));
  $("m-full").setAttribute("aria-pressed", String(full));
  try { history.replaceState(null, "", full ? "#full" : location.pathname + location.search); } catch (e) {}
  if (full) { setPanel(null); window.scrollTo(0, 0); }
  if (gl) gl.setMode(mode);
}
function setPanel(name) {
  if (name === panel) return;
  panel = name;
  if (name) body.dataset.panel = name; else delete body.dataset.panel;
  $("btn-profile").setAttribute("aria-expanded", String(!!name));
  $("panel-profile").inert = name !== "profile";
  if (gl) gl.setPanel(!!name);
}
$("m-featured").onclick = () => setMode("featured");
$("m-full").onclick = () => setMode("full");
$("btn-profile").onclick = (e) => { e.stopPropagation(); setPanel(panel ? null : "profile"); };
addEventListener("keydown", (e) => { if (e.key === "Escape") setPanel(null); });
addEventListener("pointerdown", (e) => { if (panel && !e.target.closest("#panel-profile, #btn-profile")) setPanel(null); });
$("full").addEventListener("focusin", () => { if (mode === "featured") setMode("full"); });
addEventListener("hashchange", () => { if (gl) setMode(location.hash === "#full" ? "full" : "featured"); });

/* =========================================================================================================
   The carousel
   ========================================================================================================= */
async function buildCarousel() {
  const R = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: "high-performance" });   // throws without WebGL
  R.outputColorSpace = THREE.LinearSRGBColorSpace;          // colours go straight through: what's in the video is what's on screen
  R.setClearColor(0x000000, 1);
  const scene = new THREE.Scene();
  const cam = new THREE.OrthographicCamera(0, 1, 0, 1, -10, 10);   // 1 unit = 1 CSS pixel, y down, so planes sit exactly on their DOM boxes
  const plane = new THREE.PlaneGeometry(1, 1);
  const BLANK = Object.assign(new THREE.DataTexture(new Uint8Array([16, 16, 16, 255]), 1, 1), { needsUpdate: true });
  await Promise.all([document.fonts.load("500 16px Geist"), document.fonts.load("400 16px Geist")]);

  /* ---- shaders ---- */
  const VERT = `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
  const CARD = `
    precision highp float;
    uniform sampler2D uVideo, uCover, uLabel;
    uniform vec2 uSize; uniform float uRadius, uStrip, uAlpha, uHover, uVid, uHasVideo, uHasCover, uTime, uSeed, uVidAspect, uCoverAspect, uLabelT;
    varying vec2 vUv;
    float sdRR(vec2 p, vec2 b, float r){ vec2 q = abs(p) - b + r; return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r; }
    vec2 fit(vec2 uv, float cardA, float texA, float zoom, vec2 drift){        // "cover": fill the card, crop the overflow
      vec2 s = cardA > texA ? vec2(1.0, texA / cardA) : vec2(cardA / texA, 1.0);
      return (uv - 0.5) * s / zoom + 0.5 + drift;
    }
    void main(){
      vec2 px = vUv * uSize;                                   // origin top-left, y down
      float d = sdRR(px - 0.5 * uSize, 0.5 * uSize, uRadius);
      float aa = max(fwidth(d), 1e-3);
      float mask = 1.0 - smoothstep(-aa, aa, d);
      vec2 uv = vec2(vUv.x, 1.0 - vUv.y);                      // textures are bottom-up
      float cardA = uSize.x / uSize.y, zoom = 1.0 + 0.035 * uHover;
      vec3 col = vec3(0.063);
      if (uHasCover > 0.5) {                                   // a project without a clip: slow drift over its cover
        float kb = 1.0 - uHasVideo;
        float z = zoom + kb * (0.075 + 0.03 * sin(uTime * 0.23 + uSeed));
        vec2 drift = kb * vec2(0.026 * sin(uTime * 0.16 + uSeed * 3.0), 0.02 * cos(uTime * 0.12 + uSeed));
        col = texture2D(uCover, fit(uv, cardA, uCoverAspect, z, drift)).rgb;
      }
      if (uHasVideo > 0.5) col = mix(col, texture2D(uVideo, fit(uv, cardA, uVidAspect, zoom, vec2(0.0))).rgb, uVid);
      col *= 1.0 - 0.52 * smoothstep(uSize.y * 0.5, uSize.y, px.y) * uLabelT;      // a soft floor under the title
      float ly = px.y - (uSize.y - uStrip);
      if (ly > 0.0) {
        float rise = (1.0 - uLabelT) * uStrip * 0.12;
        vec4 lb = texture2D(uLabel, vec2(px.x / uSize.x, 1.0 - (ly + rise) / uStrip));
        col = mix(col, lb.rgb, lb.a * uLabelT);
      }
      gl_FragColor = vec4(col, mask * uAlpha);
    }`;
  const TEXT = `
    precision highp float; uniform sampler2D uMap; uniform float uAlpha; varying vec2 vUv;
    void main(){ vec4 t = texture2D(uMap, vec2(vUv.x, 1.0 - vUv.y)); gl_FragColor = vec4(t.rgb, t.a * uAlpha); }`;
  const POST = `
    precision highp float;
    uniform sampler2D tDiffuse; uniform vec2 uRes; uniform float uVel, uAxis; varying vec2 vUv;
    void main(){
      float asp = uRes.x / uRes.y;
      vec2 p = (vUv - 0.5) * vec2(asp, 1.0);
      float fall = smoothstep(1.0, 0.0, length(p));            // strongest in the middle, nothing at the corners
      float ang = uVel * ${SWIRL.toFixed(3)} * fall * fall;    // the swirl: the picture twists around the centre
      float s = sin(ang), c = cos(ang);
      vec2 q = mat2(c, -s, s, c) * p;
      vec2 uv = q / vec2(asp, 1.0) + 0.5;
      vec2 dir = mix(vec2(1.0, 0.0), vec2(0.0, 1.0), uAxis);
      float ab = abs(uVel) * ${CHROMA.toFixed(4)} * fall;
      gl_FragColor = vec4(texture2D(tDiffuse, uv + dir * ab).r, texture2D(tDiffuse, uv).g, texture2D(tDiffuse, uv - dir * ab).b, 1.0);
    }`;
  const postScene = new THREE.Scene(), postCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const postMat = new THREE.ShaderMaterial({ vertexShader: `varying vec2 vUv; void main(){ vUv = position.xy * 0.5 + 0.5; gl_Position = vec4(position.xy, 0.0, 1.0); }`, fragmentShader: POST, depthTest: false, depthWrite: false, side: THREE.DoubleSide,
    uniforms: { tDiffuse: { value: null }, uRes: { value: new THREE.Vector2(1, 1) }, uVel: { value: 0 }, uAxis: { value: 0 } } });
  postScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), postMat));
  let rt = null;

  /* ---- cards ---- */
  const dprCap = () => Math.min(devicePixelRatio || 1, 2);
  const reps = PROJECTS.length >= 6 ? 1 : Math.ceil(6 / Math.max(1, PROJECTS.length));
  const cards = [];
  for (let r = 0; r < reps; r++) PROJECTS.forEach((p, i) => {
    const el = document.createElement("article");
    el.className = "card"; el.dataset.slug = p.slug;
    if (r) el.setAttribute("aria-hidden", "true");
    el.innerHTML = `<a class="sr" href="${p.slug}/"${r ? ' tabindex="-1"' : ""}>${p.title.replace(/&/g, "&amp;").replace(/</g, "&lt;")}</a>`;
    rowEl.append(el);
    const mat = new THREE.ShaderMaterial({ vertexShader: VERT, fragmentShader: CARD, transparent: true, depthTest: false, depthWrite: false, side: THREE.DoubleSide,
      uniforms: { uVideo: { value: BLANK }, uCover: { value: BLANK }, uLabel: { value: BLANK }, uSize: { value: new THREE.Vector2(1, 1) }, uRadius: { value: 20 }, uStrip: { value: 60 },
        uAlpha: { value: 0 }, uHover: { value: 0 }, uVid: { value: 0 }, uHasVideo: { value: 0 }, uHasCover: { value: 0 }, uTime: { value: 0 }, uSeed: { value: (i * 1.731) % 6.28 },
        uVidAspect: { value: p.aspect || 1.7 }, uCoverAspect: { value: 1.7 }, uLabelT: { value: 0 } } });
    const mesh = new THREE.Mesh(plane, mat); mesh.frustumCulled = false; mesh.renderOrder = 1; scene.add(mesh);
    const c = { p, i, r, el, mat, mesh, aspect: p.aspect || 1.7, w: 1, h: 1, base: 0, x: 0, y: 0, hover: 0, hovering: false, vid: 0, video: null, vtex: null, cover: false, label: null, labelT: 0, near: false };
    el.addEventListener("pointerenter", () => { if (hoverMQ.matches) c.hovering = true; wake(); });
    el.addEventListener("pointerleave", () => { c.hovering = false; });
    cards.push(c);
  });

  /* ---- layout: desktop is one row, centred vertically; phones stack the cards in a column ---- */
  let vw = 0, vh = 0, rem = 10, mobile = false, total = 1, pad = 0, lead = 0, axisSize = 1;
  function layout() {
    vw = innerWidth; vh = innerHeight; mobile = mobileMQ.matches;
    rem = parseFloat(getComputedStyle(html).fontSize) || 10;
    const gap = (mobile ? 2 : 1) * rem, cardH = Math.min(vh * 0.435, 55 * rem);
    let acc = 0;
    for (const c of cards) {
      if (mobile) { c.w = vw - 4 * rem; c.h = c.w / c.aspect; } else { c.h = cardH; c.w = cardH * c.aspect; }
      c.base = acc; acc += (mobile ? c.h : c.w) + gap;
      c.el.style.width = c.w + "px"; c.el.style.height = c.h + "px";
    }
    total = acc; axisSize = mobile ? vh : vw;
    pad = Math.max(...cards.map((c) => (mobile ? c.h : c.w))) + gap;
    lead = mobile ? 8 * rem : 8 * rem;                          // first card starts clear of the labels (desktop: where they start)
    for (const c of cards) paintLabel(c);
    R.setPixelRatio(dprCap()); R.setSize(vw, vh, false);
    cam.left = 0; cam.right = vw; cam.top = 0; cam.bottom = vh; cam.updateProjectionMatrix();
    rt && rt.dispose();
    rt = new THREE.WebGLRenderTarget(Math.round(vw * dprCap()), Math.round(vh * dprCap()), { samples: 4, depthBuffer: false });
    postMat.uniforms.uRes.value.set(vw, vh); postMat.uniforms.uAxis.value = mobile ? 1 : 0;
    forceText = true;
  }

  /* the title and the arrow button, drawn once per card into a strip along its bottom edge */
  function paintLabel(c) {
    const dpr = dprCap(), strip = 6 * rem, fs = (mobile ? 1.6 : 1.8) * rem, padX = (mobile ? 1 : 2) * rem;
    const cv = document.createElement("canvas"); cv.width = Math.ceil(c.w * dpr); cv.height = Math.ceil(strip * dpr);
    const g = cv.getContext("2d"); g.scale(dpr, dpr);
    const cy = strip - 1 * rem - 1.25 * rem;
    g.font = `400 ${fs}px Geist, "Helvetica Neue", Arial, sans-serif`; g.fillStyle = "#fff"; g.textBaseline = "middle";
    if ("letterSpacing" in g) g.letterSpacing = `${-0.05 * fs}px`;
    g.fillText(c.p.title, padX, cy + fs * 0.04);
    const bx = c.w - padX - 1.25 * rem;                              // black disc with a white arrow
    g.fillStyle = "#000"; g.beginPath(); g.arc(bx, cy, 1.25 * rem, 0, Math.PI * 2); g.fill();
    g.strokeStyle = "#fff"; g.lineWidth = Math.max(1.2, 0.14 * rem); g.lineCap = "round"; g.lineJoin = "round";
    const a = 0.45 * rem; g.beginPath(); g.moveTo(bx - a, cy); g.lineTo(bx + a, cy); g.moveTo(bx + a * 0.15, cy - a * 0.8); g.lineTo(bx + a, cy); g.lineTo(bx + a * 0.15, cy + a * 0.8); g.stroke();
    if (!c.label) { c.label = new THREE.CanvasTexture(cv); c.label.generateMipmaps = false; c.label.minFilter = c.label.magFilter = THREE.LinearFilter; c.mat.uniforms.uLabel.value = c.label; }
    else { c.label.image = cv; c.label.needsUpdate = true; }
    c.mat.uniforms.uStrip.value = strip; c.mat.uniforms.uRadius.value = (mobile ? 1.5 : 2) * rem;
  }

  /* ---- media: a clip when the project has one, otherwise its cover (always the fallback if a clip fails) ---- */
  const loader = new THREE.TextureLoader(); let live = 0;
  function loadCover(c) {
    if (c.cover || !c.p.cover) return; c.cover = true;
    loader.load(`${c.p.slug}/${c.p.cover}`, (t) => {
      t.generateMipmaps = false; t.minFilter = t.magFilter = THREE.LinearFilter;
      c.mat.uniforms.uCover.value = t; c.mat.uniforms.uHasCover.value = 1; c.mat.uniforms.uCoverAspect.value = t.image.width / t.image.height; c.coverTex = t;
    }, undefined, () => { c.cover = false; });
  }
  function startVideo(c) {
    if (c.video || !c.p.loops || !c.p.loops.length || c.videoFailed) return;
    const v = document.createElement("video");
    v.muted = true; v.loop = true; v.playsInline = true; v.preload = "auto"; v.setAttribute("muted", ""); v.setAttribute("playsinline", "");
    for (const f of c.p.loops) { const s = document.createElement("source"); s.src = `${c.p.slug}/${f}`; s.type = f.endsWith(".mp4") ? "video/mp4" : "video/webm"; v.append(s); }
    v.addEventListener("error", (e) => { if (e.target === v || e.target === v.lastElementChild) { c.videoFailed = true; stopVideo(c); loadCover(c); } }, true);
    v.addEventListener("loadeddata", () => {
      c.vtex = new THREE.VideoTexture(v); c.vtex.generateMipmaps = false; c.vtex.minFilter = c.vtex.magFilter = THREE.LinearFilter;
      c.mat.uniforms.uVideo.value = c.vtex; c.mat.uniforms.uHasVideo.value = 1; c.mat.uniforms.uVidAspect.value = v.videoWidth / v.videoHeight;
    });
    c.video = v; live++;
    if (!reduce) v.play().catch(() => {});
    else v.addEventListener("loadeddata", () => { v.currentTime = 0.4; }, { once: true });
    if (reduce) loadCover(c);
  }
  function stopVideo(c) {
    if (!c.video) return;
    c.video.pause(); c.video.removeAttribute("src"); c.video.replaceChildren(); c.video.load();
    c.vtex && c.vtex.dispose(); c.vtex = null; c.video = null; c.vid = 0; live--;
    c.mat.uniforms.uHasVideo.value = 0; c.mat.uniforms.uVideo.value = BLANK;
  }

  /* ---- text: every [data-gl] label becomes a plane textured with its own rendered text ---- */
  const texts = []; let forceText = true;
  document.querySelectorAll("[data-gl]").forEach((el) => {
    const mat = new THREE.ShaderMaterial({ vertexShader: VERT, fragmentShader: TEXT, transparent: true, depthTest: false, depthWrite: false, side: THREE.DoubleSide, uniforms: { uMap: { value: BLANK }, uAlpha: { value: 0 } } });
    const mesh = new THREE.Mesh(plane, mat); mesh.frustumCulled = false; mesh.renderOrder = 10; mesh.visible = false; scene.add(mesh);
    texts.push({ el, mat, mesh, key: "", cw: 1, ch: 1, pad: 0, tex: null });
  });
  const effOpacity = (el) => { let o = 1; for (let n = el; n && n !== html; n = n.parentElement) { o *= +getComputedStyle(n).opacity; if (o < 0.004) return 0; } return o; };
  function paintText(t, r, cs) {
    const dpr = dprCap(), size = parseFloat(cs.fontSize), padPx = Math.ceil(size * 0.4);
    const cw = Math.ceil(r.width + padPx * 2), ch = Math.ceil(r.height + padPx * 2);
    const cv = document.createElement("canvas"); cv.width = Math.ceil(cw * dpr); cv.height = Math.ceil(ch * dpr);
    const g = cv.getContext("2d"); g.scale(dpr, dpr);
    g.font = `${cs.fontWeight} ${size}px ${cs.fontFamily}`; g.fillStyle = cs.color; g.textBaseline = "alphabetic";
    const ls = cs.letterSpacing === "normal" ? 0 : parseFloat(cs.letterSpacing) || 0;
    const hasLS = "letterSpacing" in g; if (hasLS) g.letterSpacing = `${ls}px`;
    let text = t.el.textContent.replace(/\s+/g, " ").trim(); if (cs.textTransform === "uppercase") text = text.toUpperCase();
    const width = (s) => (hasLS || !ls ? g.measureText(s).width : g.measureText(s).width + ls * s.length);
    const lines = []; let cur = "";
    for (const w of text.split(" ")) { const tryLine = cur ? cur + " " + w : w; if (cur && width(tryLine) > r.width + 1) { lines.push(cur); cur = w; } else cur = tryLine; }
    lines.push(cur);
    const m = g.measureText("Hg"), asc = m.fontBoundingBoxAscent ?? size * 0.92, desc = m.fontBoundingBoxDescent ?? size * 0.24, lh = r.height / lines.length;
    const align = cs.textAlign === "center" ? "center" : cs.textAlign === "right" || cs.textAlign === "end" ? "right" : "left";
    lines.forEach((ln, i) => {
      const y = padPx + i * lh + (lh - (asc + desc)) / 2 + asc;
      const x = align === "center" ? padPx + r.width / 2 - (hasLS ? ls / 2 : 0) : align === "right" ? padPx + r.width : padPx;
      g.textAlign = align;
      if (hasLS || !ls) g.fillText(ln, x, y);
      else { let cx = align === "center" ? x - width(ln) / 2 : align === "right" ? x - width(ln) : x; g.textAlign = "left"; for (const ch1 of ln) { g.fillText(ch1, cx, y); cx += g.measureText(ch1).width + ls; } }
    });
    if (!t.tex) { t.tex = new THREE.CanvasTexture(cv); t.tex.generateMipmaps = false; t.tex.minFilter = t.tex.magFilter = THREE.LinearFilter; t.mat.uniforms.uMap.value = t.tex; }
    else { t.tex.image = cv; t.tex.needsUpdate = true; }
    t.cw = cw; t.ch = ch; t.pad = padPx;
  }
  function syncText() {
    for (const t of texts) {
      const r = t.el.getBoundingClientRect(), o = r.width ? effOpacity(t.el) : 0;
      if (o < 0.004) { t.mesh.visible = false; continue; }
      const cs = getComputedStyle(t.el), key = [t.el.textContent, cs.fontSize, cs.fontWeight, cs.color, cs.letterSpacing, cs.textTransform, r.width.toFixed(1), r.height.toFixed(1), dprCap()].join("|");
      if (key !== t.key || forceText) { t.key = key; paintText(t, r, cs); }
      t.mesh.visible = true; t.mesh.position.set(r.left - t.pad + t.cw / 2, r.top - t.pad + t.ch / 2, 1); t.mesh.scale.set(t.cw, t.ch, 1); t.mat.uniforms.uAlpha.value = o;
    }
    forceText = false;
  }

  /* ---- movement: wheel, drag with a little momentum, arrow keys ---- */
  let pos = 0, target = 0, sv = 0, dragging = null, opening = null, introT = reduce ? 1 : 0, featT = 0, panelT = 0, openT = 0, idleUntil = 0;
  let wantFeat = 1, wantPanel = 0;
  const start = () => -lead;                                       // pos at which the first card sits at the left margin
  const stride = () => (cards[0] ? (mobile ? cards[0].h + 2 * rem : cards[0].w + rem) : 1);
  const wrapDelta = (d) => mod(d + total / 2, total) - total / 2;

  const axisOf = (e) => (mobile ? e.clientY : e.clientX);
  addEventListener("wheel", (e) => {
    if (mode !== "featured" || panel) return;
    e.preventDefault();
    const k = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? innerHeight : 1;
    const d = mobile ? e.deltaY : (Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY);
    target += d * k * WHEEL; wake();
  }, { passive: false });
  addEventListener("pointerdown", (e) => {
    if (mode !== "featured" || panel || (e.pointerType === "mouse" && e.button !== 0) || e.target.closest("#ui, #panel-profile")) return;
    dragging = { id: e.pointerId, last: axisOf(e), x0: e.clientX, y0: e.clientY, moved: 0, v: 0, t: performance.now() };
    wake();
  });
  addEventListener("pointermove", (e) => {
    if (!dragging || e.pointerId !== dragging.id) return;
    const a = axisOf(e), d = a - dragging.last, now = performance.now(); dragging.last = a;
    dragging.moved += Math.abs(d); dragging.v = lerp(dragging.v, d / Math.max(1, now - dragging.t), 0.35); dragging.t = now;
    if (dragging.moved > 5) { html.classList.add("grabbing"); cards.forEach((c) => (c.hovering = false)); }
    target -= d; wake();
  });
  const release = (e) => {
    if (!dragging || e.pointerId !== dragging.id) return;
    const d = dragging; dragging = null; html.classList.remove("grabbing");
    if (d.moved < 6) { const el = e.target.closest && e.target.closest(".card"); if (el) { const c = cards.find((q) => q.el === el); if (c) openCard(c); } }
    else target -= d.v * 1000 * MOMENTUM;
    wake();
  };
  addEventListener("pointerup", release); addEventListener("pointercancel", release);
  addEventListener("keydown", (e) => {
    if (mode !== "featured" || panel) return;
    const f = mobile ? ["ArrowDown", "ArrowUp"] : ["ArrowRight", "ArrowLeft"], g2 = mobile ? ["ArrowRight", "ArrowLeft"] : ["ArrowDown", "ArrowUp"];
    if (e.key === f[0] || e.key === g2[0]) target += stride(); else if (e.key === f[1] || e.key === g2[1]) target -= stride(); else return;
    e.preventDefault(); wake();
  });
  rowEl.addEventListener("focusin", (e) => {                       // tabbing to a card brings it into view
    const c = cards.find((q) => q.el.contains(e.target)); if (!c) return;
    const centred = mobile ? (vh - c.h) / 2 : (vw - c.w) / 2;
    target += wrapDelta(c.base - centred - target); wake();
  });

  function openCard(c) {
    if (opening) return;
    opening = { c, t0: performance.now() }; sv = clamp(sv + 0.9, -1.4, 1.4); wake(900);
    setTimeout(() => { location.href = `${c.p.slug}/`; }, reduce ? 0 : 520);
  }
  addEventListener("pageshow", (e) => { if (e.persisted) { opening = null; openT = 0; wake(); } });   // back button from a project

  /* ---- the frame ---- */
  let last = 0, rafId = 0, time = 0, lastNow = -1;
  function wake(ms = 900) { idleUntil = Math.max(idleUntil, performance.now() + ms); if (!rafId) { last = performance.now(); rafId = requestAnimationFrame(frame); } }
  document.addEventListener("transitionrun", () => wake(900), true);
  function frame(now) {
    rafId = 0;
    const dt = Math.min(0.05, Math.max(0.001, (now - last) / 1000)); last = now; time += dt;
    // the row
    const prev = pos;
    pos = damp(pos, target, dragging ? 30 : FOLLOW, dt);
    const v = (pos - prev) / dt;
    sv = damp(sv, clamp(v / (axisSize * 1.8), -1, 1), 9, dt);
    introT = Math.min(1, introT + dt / INTRO);
    if (introT < 1) target = start();                                  // keep gliding to the resting place
    featT = damp(featT, wantFeat, 4, dt); panelT = damp(panelT, wantPanel, 5, dt); openT = opening ? Math.min(1, openT + dt / 0.45) : 0;
    const showCards = smooth(featT) * (1 - 0.95 * smooth(panelT)) * (1 - smooth(openT));
    const titlesAlways = !hoverMQ.matches;

    let nearest = -1, bestD = 1e9;
    for (const c of cards) {
      const along = mod(c.base - pos - lead + pad, total) - pad + lead;       // where this card starts along the row
      if (mobile) { c.x = 2 * rem; c.y = along; } else { c.x = along; c.y = (vh - c.h) / 2; }
      const size = mobile ? c.h : c.w, vwAxis = mobile ? vh : vw;
      const onscreen = along + size > -4 && along < vwAxis + 4, near = along + size > -vwAxis * 1.1 && along < vwAxis * 2.1;
      c.el.style.transform = `translate3d(${c.x}px,${c.y}px,0)`;
      const mid = Math.abs(along + size / 2 - vwAxis / 2); if (mid < bestD && !c.r) { bestD = mid; nearest = c.i; }
      // media follows the viewport: nothing decodes that isn't about to be seen
      if (near && !c.near) { c.near = true; if (c.p.loops && c.p.loops.length) startVideo(c); else loadCover(c); }
      if (c.near && !near) { c.near = false; if (c.video && live > 6) stopVideo(c); }
      if (c.video && !reduce) { if (onscreen && c.video.paused && !c.videoFailed) c.video.play().catch(() => {}); else if (!onscreen && !c.video.paused) c.video.pause(); }
      const playing = c.video && c.video.readyState >= 2 && c.mat.uniforms.uHasVideo.value > 0;
      c.vid = damp(c.vid, playing ? 1 : 0, 6, dt);
      c.hover = damp(c.hover, c.hovering && !dragging && !panel ? 1 : 0, 9, dt);
      const stagger = clamp(introT * 2.1 - clamp(c.x / Math.max(vw, 1), 0, 1) * 1.1, 0, 1);
      const u = c.mat.uniforms;
      c.mesh.visible = onscreen && showCards > 0.002;
      if (!c.mesh.visible) continue;
      c.mesh.position.set(c.x + c.w / 2, c.y + c.h / 2, 0); c.mesh.scale.set(c.w, c.h, 1);
      u.uSize.value.set(c.w, c.h); u.uAlpha.value = showCards * smooth(stagger); u.uHover.value = reduce ? 0 : c.hover; u.uVid.value = c.vid; u.uTime.value = reduce ? 0 : time;
      c.labelT = damp(c.labelT, titlesAlways ? 1 : c.hover, 12, dt); u.uLabelT.value = c.labelT;
    }
    if (nearest !== lastNow && nearest >= 0) { lastNow = nearest; $("now").textContent = `${PROJECTS[nearest].title}, ${nearest + 1} of ${PROJECTS.length}`; }
    syncText();

    // the swirl: render the whole picture off-screen and twist it, but only while it is moving, so everything at rest is razor sharp
    const swirl = reduce ? 0 : sv * (mobile ? -1 : 1);
    if (Math.abs(swirl) > 0.004) {
      postMat.uniforms.uVel.value = swirl; R.setRenderTarget(rt); R.render(scene, cam); R.setRenderTarget(null);
      postMat.uniforms.tDiffuse.value = rt.texture; R.render(postScene, postCam);
    } else R.render(scene, cam);

    const busy = mode === "featured" || now < idleUntil || Math.abs(sv) > 0.002 || Math.abs(featT - wantFeat) > 0.003 || Math.abs(panelT - wantPanel) > 0.003 || openT > 0 && openT < 1;
    if (busy && !document.hidden) rafId = requestAnimationFrame(frame);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) wake(); });
  let resizeT = 0;
  addEventListener("resize", () => { clearTimeout(resizeT); resizeT = setTimeout(() => { layout(); wake(); }, 90); });   // layout repaints every label, so wait for the drag to settle
  layout(); html.classList.add("gl");
  target = start(); pos = target - (reduce ? 0 : Math.min(vw, 1400) * 0.5);      // cards glide in from the right
  await new Promise((r) => requestAnimationFrame(r));

  return {
    setMode(m) { wantFeat = m === "featured" ? 1 : 0; sv = clamp(sv + 0.8 * (m === "featured" ? -1 : 1), -1.4, 1.4); wake(1400); },
    setPanel(open) { wantPanel = open ? 1 : 0; sv = clamp(sv + (open ? 0.5 : -0.5), -1.4, 1.4); wake(1400); },
    ready() { wake(); },
  };
}

/* Featured by default; Full when asked for (#full), when motion is reduced, or when WebGL isn't there */
try {
  gl = await buildCarousel();
  $("modes").hidden = false;
  setMode(location.hash === "#full" || reduce ? "full" : "featured");
  gl.ready();
} catch (err) {
  console.warn("carousel unavailable, showing the list", err);
  gl = null; html.classList.remove("gl"); setMode("full");
}
