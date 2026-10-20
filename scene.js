/* The environment behind the portfolio: one persistent Three.js scene driven by native scroll.
   A pale fog landscape; a "data cube" of frosted blocks around a lit core that assembles in the hero and splits into its three
   layers (raw / modelled / served) through the method strip; then the camera dollies through fog past one frosted block per
   flagship project (its real screenshot sealed inside, HUD labels drawn in the DOM); and lands on a ring stage under the
   sections after. Chapters are the elements carrying data-scene, in document order, so the choreography follows the page.
   Progressive: the page is complete without this file. Palette comes from theme.css (--c-scene-*). */
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

const root = document.documentElement, $ = id => document.getElementById(id);
const canvas = $("scene");
const motionQuery = matchMedia("(prefers-reduced-motion: reduce)");
let reduced = motionQuery.matches, paused = false;
const small = () => innerWidth < 900 || matchMedia("(pointer: coarse)").matches;
const lite = small();                                   // fewer segments, no transmission, no bloom
const col = name => { const d = document.createElement("div"); d.style.color = `var(${name})`; document.body.append(d); const c = getComputedStyle(d).color; d.remove(); return new THREE.Color(c); };
const chapters = [...document.querySelectorAll("[data-scene]")];                 // document order is the scene order
const LAST = chapters.length - 1;
const kindOf = k => chapters[k]?.dataset.scene;
const METHOD = chapters.findIndex(c => c.dataset.scene === "method");            // where the cube splits into its layers
const FEAT0 = chapters.findIndex(c => c.dataset.scene === "feature");            // first flagship chapter
const features = chapters.filter(c => c.dataset.scene === "feature");
const featureAt = k => FEAT0 + k, inRun = c => c >= FEAT0 && c < FEAT0 + features.length;
const report = state => { root.classList.toggle("scene-live", state === "live"); root.classList.toggle("scene-static", state === "static"); dispatchEvent(new CustomEvent("portfolio:scene", { detail: { state } })); };

/* ---- scroll -> chapter progress (chapter k is fully formed when its block is centred in the viewport) ---- */
let tops = [], target = 0, t = 0;
function measure() { tops = chapters.map((c, k) => { const r = c.getBoundingClientRect(); return r.top + scrollY + (k === chapters.length - 1 ? Math.min(r.height / 2, innerHeight / 2) : Math.min(r.height / 2, innerHeight * 0.6)); }); }
function onScroll() {
  if (!tops.length) return;                            // a hash jump can fire before the first measure
  const s = scrollY + innerHeight * 0.5;
  let i = 0;
  while (i < LAST && s >= tops[i + 1]) i++;
  const span = Math.max(1, (tops[i + 1] ?? tops[i] + innerHeight) - tops[i]);
  target = Math.min(LAST, Math.max(0, i + (s - tops[i]) / span));
  wake();
}

/* ---- deterministic noise for the terrain ---- */
let seed = 7;
const rnd = () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
const perm = Array.from({ length: 512 }, (_, i) => i & 255).sort(() => rnd() - 0.5);
const fade = x => x * x * x * (x * (x * 6 - 15) + 10);
const grad = (h, x, y) => ((h & 1) ? -x : x) + ((h & 2) ? -y : y);
function noise(x, y) {
  const X = Math.floor(x) & 255, Y = Math.floor(y) & 255; x -= Math.floor(x); y -= Math.floor(y);
  const u = fade(x), v = fade(y), A = perm[X] + Y, B = perm[X + 1] + Y;
  const l = (a, b, s) => a + (b - a) * s;
  return l(l(grad(perm[A], x, y), grad(perm[B], x - 1, y), u), l(grad(perm[A + 1], x, y - 1), grad(perm[B + 1], x - 1, y - 1), u), v);
}
const fbm = (x, y) => noise(x, y) * 0.6 + noise(x * 2.1, y * 2.1) * 0.25 + noise(x * 4.3, y * 4.3) * 0.1 + noise(x * 9, y * 9) * 0.05;
const smooth = (a, b, x) => { const k = Math.min(1, Math.max(0, (x - a) / (b - a))); return k * k * (3 - 2 * k); };

/* ---- scene ---- */
let renderer, scene, camera, composer, glitchPass, bloomPass, raf = 0, lastFrame = 0, clock = 0, lost = 0;
/* quality tiers, stepped down (never up) from a 60-frame median after a 30-frame settle, so compiles and tab switches never flip it:
   0 high (bloom, glass, DPR<=1.5)  1 lite (phones start here: no bloom, plain blocks)  2 low (DPR 0.66, no post)  3 static page */
let tier = lite ? 1 : 0, frames = 0, tierAt = 0, win = [];
const keep = new URLSearchParams(location.search).get("scene") === "keep";   // tests: hold the current tier
const cube = { blocks: [], cores: [], group: null, mesh: null }, blocks = [];   // cube instance data, featured blocks
const CAM = [];                                          // per chapter: position, look-at, fog density
const FEAT_Z0 = -16, FEAT_DZ = 13, STAGE_Z = FEAT_Z0 - features.length * FEAT_DZ - 24;   // the ring stage sits past the last block
const loader = new THREE.TextureLoader();
const palette = {};

function build() {
  performance.mark("scene:build");
  Object.assign(palette, { fog: col("--c-scene-fog"), ground: col("--c-scene-ground"), block: col("--c-scene-block").multiplyScalar(0.84), glow: col("--c-scene-glow"), sky: col("--c-scene-sky"), shadow: col("--c-scene-shadow"), raw: col("--c-scene-core-raw"), accent: col("--c-scene-accent") });
  renderer = new THREE.WebGLRenderer({ canvas, antialias: lite, alpha: false, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, lite ? 1 : 1.5));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  scene = new THREE.Scene();
  scene.background = palette.fog.clone();
  scene.fog = new THREE.FogExp2(palette.fog.clone(), 0.03);
  camera = new THREE.PerspectiveCamera(38, 1, 0.1, 400);

  // light: a lower ambient sky, one key from the upper left, a warm rim from behind right so the blocks separate from the land
  scene.add(new THREE.HemisphereLight(palette.sky, palette.shadow, 0.95));
  const sun = new THREE.DirectionalLight(0xffffff, 2.3); sun.position.set(-9, 14, 7); scene.add(sun);
  const rim = new THREE.DirectionalLight(palette.glow.clone().lerp(palette.accent, 0.35), 1.1); rim.position.set(9, 4, -12); scene.add(rim);

  // terrain: a wide plane with fbm hills, flattened around the cube, the path, and the stage
  const seg = lite ? 90 : 128, W = 240, D = 240;
  const geo = new THREE.PlaneGeometry(W, D, seg, seg);
  geo.rotateX(-Math.PI / 2);
  const pos = geo.attributes.position;
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i), z = pos.getZ(i) - 60;
    const h = (fbm(x * 0.035 + 3, z * 0.035 + 1) + 0.45) * 6.5;
    const nearCube = 1 - smooth(5, 13, Math.hypot(x, z));
    const nearPath = (1 - smooth(4, 10, Math.abs(x))) * smooth(-8, -2, -z) * (1 - smooth(-STAGE_Z - 10, -STAGE_Z + 4, -z));
    const nearStage = 1 - smooth(16, 26, Math.hypot(x, z - STAGE_Z));
    const flat = Math.max(nearCube, nearPath, nearStage);
    pos.setY(i, h * (1 - flat) - 0.2 * flat + fbm(x * 0.4, z * 0.4) * 0.12);
    pos.setZ(i, z);
  }
  geo.computeVertexNormals();
  const colors = new Float32Array(pos.count * 3), nrm = geo.attributes.normal;
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i), z = pos.getZ(i);
    const grain = 0.78 + 0.3 * (fbm(x * 0.9 + 9, z * 0.9) + 0.5) + 0.12 * (1 - nrm.getY(i));
    colors[i * 3] = grain; colors[i * 3 + 1] = grain; colors[i * 3 + 2] = grain * 1.03;
  }
  geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  scene.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: palette.ground, roughness: 1, metalness: 0, vertexColors: true })));

  performance.mark("scene:terrain");
  // the data cube: 4 x 4 x 4 frosted blocks around a glowing core, one core slab per layer
  const grainTex = grain();
  performance.mark("scene:grain");
  const n = 4, pitch = 1.0, size = 0.86;
  const blockGeo = new RoundedBoxGeometry(size, size, size, 3, 0.14);
  const liteBlock = new THREE.MeshStandardMaterial({ color: palette.block, roughness: 0.5, metalness: 0, transparent: true, opacity: 0.92 });
  const blockMat = lite ? liteBlock : new THREE.MeshPhysicalMaterial({ color: palette.block, roughness: 0.38, metalness: 0, transmission: 0.5, thickness: 0.9, ior: 1.35, clearcoat: 0.3, clearcoatRoughness: 0.45, attenuationColor: palette.glow, attenuationDistance: 2.5, bumpMap: grainTex, bumpScale: 0.5, roughnessMap: grainTex });
  cube.group = new THREE.Group();
  cube.mesh = new THREE.InstancedMesh(blockGeo, blockMat, n * n * n);   // one draw call for the 64 blocks (two with the glass pass)
  cube.mesh.frustumCulled = false;
  cube.group.add(cube.mesh);
  // layers read bottom-up as the method: raw (two unlit source layers, matte and a touch darker), modelled (lit), served (lit, a warm note)
  const GROUP = [0, 0, 1, 2], tint = [0.9, 0.9, 1.0, 1.06], coreCol = [palette.raw, palette.raw, palette.glow, palette.glow.clone().lerp(palette.accent, 0.22)];
  const ic = new THREE.Color();
  for (let y = 0; y < n; y++) {
    const core = new THREE.Mesh(new THREE.BoxGeometry(n * pitch - 1.15, pitch * 0.42, n * pitch - 1.15), new THREE.MeshBasicMaterial({ color: coreCol[y] }));
    core.userData = { y, group: GROUP[y], base: y * pitch + 0.5, col: coreCol[y] };
    cube.group.add(core); cube.cores.push(core);
    for (let x = 0; x < n; x++) for (let z = 0; z < n; z++) {
      const home = new THREE.Vector3((x - (n - 1) / 2) * pitch, y * pitch + 0.5, (z - (n - 1) / 2) * pitch);
      const dir = new THREE.Vector3(rnd() - 0.5, rnd() * 0.6 + 0.2, rnd() - 0.5).normalize();
      cube.mesh.setColorAt(cube.blocks.length, ic.setScalar(tint[y]));
      cube.blocks.push({ home, y, group: GROUP[y], away: dir.multiplyScalar(6 + rnd() * 6).add(home), spin: new THREE.Euler((rnd() - 0.5) * 3, (rnd() - 0.5) * 3, (rnd() - 0.5) * 3), delay: rnd() * 0.35, hover: rnd() < 0.12 ? 0.35 + rnd() * 0.5 : 0 });
    }
  }
  cube.mesh.instanceColor.needsUpdate = true;
  scene.add(cube.group);

  // featured projects: a frosted shell with the screenshot sealed inside, lit from within
  const shellGeo = new RoundedBoxGeometry(2.9, 1.95, 0.6, 3, 0.16);
  const liteShell = new THREE.MeshStandardMaterial({ color: palette.block, roughness: 0.4, transparent: true, opacity: 0.35 });
  const shellMat = lite ? liteShell : new THREE.MeshPhysicalMaterial({ color: palette.block, roughness: 0.1, metalness: 0, transmission: 0.92, thickness: 0.5, ior: 1.3, clearcoat: 0.5, clearcoatRoughness: 0.25, attenuationColor: palette.glow, attenuationDistance: 4, bumpMap: grainTex, bumpScale: 0.15 });
  const slabGeo = new THREE.BoxGeometry(2.4, 1.5, 0.12);
  const blank = new THREE.DataTexture(new Uint8Array([235, 240, 245, 255]), 1, 1); blank.needsUpdate = true;
  features.forEach((el, k) => {
    const g = new THREE.Group();
    const x = small() ? 0 : 1.9;
    g.position.set(x, 2.6, FEAT_Z0 - k * FEAT_DZ);
    const shell = new THREE.Mesh(shellGeo, shellMat);
    const glow = new THREE.MeshBasicMaterial({ color: palette.glow });
    const face = new THREE.MeshBasicMaterial({ color: new THREE.Color(1.35, 1.35, 1.35), map: blank });   // a map from the start, so the screenshot swaps in without a recompile
    const slab = new THREE.Mesh(slabGeo, [glow, glow, glow, glow, face, glow]);
    g.add(shell, slab);
    g.userData = { k, el, slab, face, loaded: false, phase: rnd() * 6.28 };
    scene.add(g); blocks.push(g);
  });

  // the dot grid that fills the fog along the fly-through
  const dots = new Float32Array(lite ? 900 * 3 : 2200 * 3);
  for (let i = 0; i < dots.length; i += 3) { dots[i] = (rnd() - 0.5) * 70; dots[i + 1] = rnd() * 16 - 2; dots[i + 2] = -4 + rnd() * (STAGE_Z - 16); }
  const dotGeo = new THREE.BufferGeometry(); dotGeo.setAttribute("position", new THREE.BufferAttribute(dots, 3));
  scene.add(new THREE.Points(dotGeo, new THREE.PointsMaterial({ color: palette.sky, size: 0.07, transparent: true, opacity: 0.55, sizeAttenuation: true })));

  // the ring stage under the catalogue
  const stage = new THREE.Group(); stage.position.set(0, 0, STAGE_Z);
  stage.add(new THREE.Mesh(new THREE.CircleGeometry(18, 64).rotateX(-Math.PI / 2), new THREE.MeshStandardMaterial({ color: palette.ground, roughness: 1 })));
  for (const r of [4.5, 8, 12]) {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(r, 0.05, 8, 128).rotateX(Math.PI / 2), new THREE.MeshBasicMaterial({ color: palette.glow }));
    ring.position.y = 0.06; stage.add(ring);
    const step = new THREE.Mesh(new THREE.CylinderGeometry(r + 1.6, r + 1.6, 0.18, 96), new THREE.MeshStandardMaterial({ color: palette.ground, roughness: 1 }));
    step.position.y = -0.09 - (r / 12) * 0.2; stage.add(step);
  }
  scene.add(stage);

  // camera path, one keyframe per chapter, chosen by the chapter's kind so it follows the document
  const STAGE_VIEWS = [[[0, 9.5, STAGE_Z + 15], [0, 0.5, STAGE_Z - 3], 0.028], [[7, 8, STAGE_Z + 12], [0, 0.6, STAGE_Z], 0.028], [[9, 6.5, STAGE_Z + 4], [0, 0.6, STAGE_Z], 0.028], [[3, 7, STAGE_Z - 11], [0, 0.6, STAGE_Z], 0.028], [[-6, 8.5, STAGE_Z - 8], [0, 0.6, STAGE_Z], 0.028]];
  let feat = 0, sv = 0;
  for (const c of chapters) {
    if (c.dataset.scene === "hero") CAM.push([[0.5, 3.2, 15.5], [-1.9, 1.7, 0], 0.022]);
    else if (c.dataset.scene === "method") CAM.push([[-10.5, 11.5, 15.5], [0.2, 3.3, 0], 0.024]);
    else if (c.dataset.scene === "feature") { const z = FEAT_Z0 - feat++ * FEAT_DZ; CAM.push([[0, 2.2, z + 7.5], [0.5, 1.7, z - 2], 0.05]); }
    else CAM.push(STAGE_VIEWS[Math.min(sv++, STAGE_VIEWS.length - 1)]);
  }

  // post: bloom for the glowing seams, then a chromatic / scan "glitch" pulse on chapter changes, then output
  scene.userData.lite = { liteBlock, liteShell };
  composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  if (!lite) { bloomPass = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.65, 0.55, 0.8); composer.addPass(bloomPass); }
  glitchPass = new ShaderPass({
    uniforms: { tDiffuse: { value: null }, uAmount: { value: 0 }, uTime: { value: 0 }, uFog: { value: palette.fog } },
    vertexShader: "varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: `uniform sampler2D tDiffuse; uniform float uAmount, uTime; uniform vec3 uFog; varying vec2 vUv;
      float hash(float n){ return fract(sin(n) * 43758.5453); }
      void main(){
        vec2 uv = vUv;
        float row = floor(uv.y * 28.0);
        float slice = step(0.72, hash(row + floor(uTime * 9.0))) * uAmount;
        uv.x += (hash(row * 3.1 + uTime) - 0.5) * 0.12 * slice;
        vec2 d = (uv - 0.5) * uAmount * 0.03;
        vec3 c = vec3(texture2D(tDiffuse, uv + d).r, texture2D(tDiffuse, uv).g, texture2D(tDiffuse, uv - d).b);
        float v = smoothstep(1.25, 0.35, length((vUv - 0.5) * vec2(1.3, 1.0)));
        c = mix(c * (0.92 + 0.08 * v), uFog, uAmount * 0.35);
        c += (hash(uv.x * 913.0 + uv.y * 271.0 + uTime) - 0.5) * 0.025;
        gl_FragColor = vec4(c, 1.0);
      }` });
  composer.addPass(glitchPass);
  composer.addPass(new OutputPass());
  resize();
  performance.mark("scene:objects");
}

function grain() {                                     // 256px value-noise, tiled: frost on the glass
  const c = document.createElement("canvas"); c.width = c.height = 256;
  const ctx = c.getContext("2d"), img = ctx.createImageData(256, 256);
  for (let y = 0; y < 256; y++) for (let x = 0; x < 256; x++) {
    const v = 150 + 70 * fbm(x * 0.09, y * 0.09) + 25 * (rnd() - 0.5), i = (y * 256 + x) * 4;
    img.data[i] = img.data[i + 1] = img.data[i + 2] = Math.max(0, Math.min(255, v)); img.data[i + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  const tex = new THREE.CanvasTexture(c); tex.wrapS = tex.wrapT = THREE.RepeatWrapping; tex.repeat.set(2, 2);
  return tex;
}

function loadCover(g) {
  if (g.userData.loaded) return;
  g.userData.loaded = true;
  loader.load(g.userData.el.dataset.cover, tex => { tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4; g.userData.face.map = tex; g.userData.face.needsUpdate = true; });
}

const v3 = new THREE.Vector3(), look = new THREE.Vector3(), tmp = new THREE.Vector3(), dummy = new THREE.Object3D();
let intro = 0, introStart = 0, glitch = 0, lastChapter = -1;
function pose(ch) {
  const i = Math.min(LAST - 1, Math.floor(ch)), f = ch - i, s = f * f * (3 - 2 * f);
  const A = CAM[i], B = CAM[i + 1];
  v3.set(A[0][0] + (B[0][0] - A[0][0]) * s, A[0][1] + (B[0][1] - A[0][1]) * s, A[0][2] + (B[0][2] - A[0][2]) * s);
  look.set(A[1][0] + (B[1][0] - A[1][0]) * s, A[1][1] + (B[1][1] - A[1][1]) * s, A[1][2] + (B[1][2] - A[1][2]) * s);
  scene.fog.density = A[2] + (B[2] - A[2]) * s;
  if (small()) { v3.z += 7; v3.x *= 0.4; v3.y += 0.4; look.x = Math.min(look.x + 1.6, 0.2); look.y -= t < 0.5 ? 3.7 : t < FEAT0 - 0.5 ? 1.7 : 0.9; }   // hero: the cube sits above the open copy   // phones: aim lower so objects sit above the plates
  camera.position.copy(v3);
  camera.lookAt(look);
}

function layout(dt) {
  const live = !reduced && !paused;
  if (live) clock += dt;
  if (!introStart) introStart = performance.now();
  intro = reduced ? 1 : Math.min(1, (performance.now() - introStart) / 2000);
  // cube: assembly (intro), then the layer split through the method chapter; a few blocks hover in the hero like the reference
  const split = smooth(METHOD - 0.6, METHOD, t) * 1.25 * (1 - smooth(FEAT0 - 0.8, FEAT0, t));
  const lit = smooth(METHOD - 0.5, METHOD + 0.45, t) * 3;          // 0..3: the lit group walks up raw -> modelled -> served
  cube.blocks.forEach((u, i) => {
    const a = smooth(u.delay, u.delay + 0.5, intro), e = 1 - Math.pow(1 - a, 3);
    tmp.copy(u.home); tmp.y += u.y * split;
    const hover = u.hover * (1 - smooth(0.0, 0.6, t));
    tmp.y += hover * (0.6 + 0.25 * Math.sin(clock * 0.8 + u.delay * 9));
    tmp.x += hover * 0.35 * Math.cos(clock * 0.5 + u.delay * 7);
    dummy.position.lerpVectors(u.away, tmp, e);
    dummy.rotation.set(u.spin.x * (1 - e), u.spin.y * (1 - e), u.spin.z * (1 - e));
    dummy.updateMatrix();
    cube.mesh.setMatrixAt(i, dummy.matrix);
  });
  cube.mesh.instanceMatrix.needsUpdate = true;
  for (const c of cube.cores) {
    c.position.y = c.userData.base + c.userData.y * split;
    const on = lit <= 0 ? 1 : 0.45 + 0.8 * Math.max(0, 1 - Math.abs(Math.min(lit, 2.6) - 0.3 - c.userData.group));
    c.material.color.copy(c.userData.col).multiplyScalar(0.5 * on * (0.92 + 0.08 * Math.sin(clock * 1.7 + c.userData.y)));
  }
  cube.group.rotation.y = 0.35 + (live ? clock * 0.02 : 0);
  // featured blocks: float, face the camera a little, load the screenshot when near
  let active = -1, activeW = 0;
  blocks.forEach(g => {
    const k = g.userData.k, d = t - featureAt(k), w = Math.max(0, 1 - Math.abs(d) / 0.75);
    if (Math.abs(d) < 2.2) loadCover(g);
    g.visible = Math.abs(d) < 2.6 && t > FEAT0 - 0.7 && !small();   // phones show the screenshot inline instead
    g.position.y = 2.6 + (live ? Math.sin(clock * 0.6 + g.userData.phase) * 0.08 : 0);
    g.rotation.y = -0.35 + d * 0.25 + (live ? Math.sin(clock * 0.3 + g.userData.phase) * 0.04 : 0);
    g.rotation.x = (live ? Math.sin(clock * 0.4 + g.userData.phase) * 0.03 : 0) + d * 0.05;
    if (w > activeW) { activeW = w; active = k; }
  });
  hud(active, activeW);
  // glitch pulse when the chapter changes; stronger into and out of the fly-through
  const ch = Math.round(t);
  if (ch !== lastChapter) { if (lastChapter >= 0 && !reduced) glitch = inRun(ch) !== inRun(lastChapter) ? 1 : 0.45; lastChapter = ch; }
  glitch = Math.max(0, glitch - dt * 2.2);
  glitchPass.uniforms.uAmount.value = glitch;
  glitchPass.uniforms.uTime.value = clock;
}

/* ---- HUD: monospace labels with leader lines around the active featured block ---- */
const hudEl = $("hud"), tagA = $("hud-a"), tagB = $("hud-b"), tagC = $("hud-c"), lines = $("hud-lines");
let hudFor = -1;
function toScreen(p) { tmp.copy(p).project(camera); return [(tmp.x + 1) / 2 * innerWidth, (1 - tmp.y) / 2 * innerHeight, tmp.z < 1]; }
function hud(k, w) {
  const mw = METHOD < 0 ? 0 : Math.max(0, 1 - Math.abs(t - METHOD) / 0.6);   // the three layer labels while the cube is split
  const mode = k >= 0 && w > 0.15 ? "feature" : mw > 0.15 ? "method" : "";
  const on = !!mode && !small();
  root.classList.toggle("hud-on", on);
  if (!on) { hudFor = -1; hudEl.style.opacity = ""; return; }
  let ax, ay, bx, by, cx, cy, off = [[-70, -70], [120, -30], [110, 60]];
  if (mode === "method") {
    off = [[-150, -60], [-150, 0], [-150, -30]];              // all three to the left of the cube, clear of the strip below
    if (hudFor !== -2) {
      hudFor = -2;
      tagA.innerHTML = `03 // Served<b>Reports, forecasts, assistants</b>`;
      tagB.innerHTML = `02 // Modelled<b>Tested transformations</b>`;
      tagC.innerHTML = `01 // Raw<b>Source data, illustration</b>`;
    }
    hudEl.style.opacity = mw;
    cube.group.updateMatrixWorld();
    [ax, ay] = toScreen(tmp.set(-1.9, cube.cores[3].position.y, 0).applyMatrix4(cube.group.matrixWorld));
    [bx, by] = toScreen(tmp.set(-1.9, cube.cores[2].position.y, 0).applyMatrix4(cube.group.matrixWorld));
    [cx, cy] = toScreen(tmp.set(-1.9, cube.cores[1].position.y, 0).applyMatrix4(cube.group.matrixWorld));
  } else {
    const g = blocks[k], el = g.userData.el;
    if (hudFor !== k) {
      hudFor = k;
      tagA.innerHTML = `Portfolio_${el.dataset.no}<b>${el.dataset.title}</b>`;
      tagB.innerHTML = `${el.dataset.area}<b>${el.dataset.date}</b>`;
      tagC.innerHTML = `Open case study<b>Click the block</b>`;
    }
    hudEl.style.opacity = w;
    off = [[-70, -70], [120, -70], [130, 10]];                 // above and beside the block: the figure card owns the lower right
    [ax, ay] = toScreen(tmp.set(-1.45, 0.98, 0.3).applyMatrix4(g.matrixWorld));
    [bx, by] = toScreen(tmp.set(1.45, 0.9, 0.3).applyMatrix4(g.matrixWorld));
    [cx, cy] = toScreen(tmp.set(1.45, -0.2, 0.3).applyMatrix4(g.matrixWorld));
  }
  const place = (tag, x, y, dx, dy) => { const hw = tag.offsetWidth / 2 + 16, hh = tag.offsetHeight / 2 + 12; const px = Math.min(innerWidth - hw, Math.max(hw, x + dx)), py = Math.min(innerHeight - hh, Math.max(80, y + dy)); tag.style.transform = `translate(${(px - tag.offsetWidth / 2).toFixed(1)}px, ${(py - tag.offsetHeight / 2).toFixed(1)}px)`; return [px, py]; };   // transform, so moving labels never count as layout shift
  const [a1, a2] = place(tagA, ax, ay, ...off[0]);
  const [b1, b2] = place(tagB, bx, by, ...off[1]);
  const [c1, c2] = place(tagC, cx, cy, ...off[2]);
  const end = (px, x, w) => px + (x < px ? -w : w);           // the leader meets the tag on the side that faces the anchor
  lines.innerHTML = `<line x1="${ax}" y1="${ay}" x2="${end(a1, ax, 50)}" y2="${a2 + 8}"/><line x1="${bx}" y1="${by}" x2="${end(b1, bx, 60)}" y2="${b2}"/><line x1="${cx}" y1="${cy}" x2="${end(c1, cx, 60)}" y2="${c2}"/>`;
}

/* ---- frame loop: runs only while something changes ---- */
function stepDown() {                                  // one tier at a time; each tier really draws less
  tier++; tierAt = performance.now(); win = [];
  if (tier === 1) {                                    // lite: no bloom, plain blocks (no glass pass), DPR 1
    if (bloomPass) { composer.removePass(bloomPass); bloomPass = null; }
    renderer.setPixelRatio(1);
    const { liteBlock, liteShell } = scene.userData.lite;
    cube.mesh.material = liteBlock;
    for (const g of blocks) g.children[0].material = liteShell;
  } else if (tier === 2) {                             // low: two thirds resolution, single pass, no glitch
    renderer.setPixelRatio(0.66);
  } else {                                             // still stuttering: the polished static page
    cancelAnimationFrame(raf); raf = 0;
    root.classList.remove("hud-on"); hudEl.style.opacity = "";
    report("static");
    renderer.dispose();
    renderer = null;
    console.info("scene: static presentation (renderer too slow)");
    return;
  }
  resize();
  console.info("scene: quality tier " + tier + " (slow frames)");
}
function frame(now) {
  raf = 0;
  const raw = (now - (lastFrame || now)) / 1000;
  if (lastFrame && raw < 1 && !keep && now - tierAt > 800) {   // after a settle (shader links, tab switches): a 1.5 s / 60-frame window, judged by its median
    win.push(raw);
    if (win.length >= 60 || (win.length >= 8 && now - tierAt > 2300)) { const med = win.sort((a, b) => a - b)[win.length >> 1]; win = []; tierAt = now; if (med > 0.04) stepDown(); }
  }
  if (!renderer) return;
  const dt = Math.min(0.05, raw); lastFrame = now;
  t += (target - t) * (reduced ? 1 : Math.min(1, dt * 6));
  if (Math.abs(target - t) < 0.0005) t = target;
  layout(dt);
  pose(t);
  if (tier >= 2) renderer.render(scene, camera); else composer.render();
  if (!frames++) performance.mark("scene:first-frame");
  const moving = (!reduced && !paused) || t !== target || intro < 1 || glitch > 0;
  const idle = t === target && intro >= 1 && glitch <= 0;   // only the ambient drift: half rate is plenty
  if (moving && !document.hidden) raf = idle ? (idleTimer = setTimeout(() => { idleTimer = 0; raf = requestAnimationFrame(frame); }, 24), -1) : requestAnimationFrame(frame); else lastFrame = 0;
}
window.__scene = { get t() { return t; }, get target() { return target; }, get renderer() { return renderer; }, get tier() { return tier; } };   // read by tests/portfolio-check.cjs
let idleTimer = 0;
function wake() { if (!renderer || document.hidden) return; if (idleTimer) { clearTimeout(idleTimer); idleTimer = 0; raf = 0; } if (!raf) raf = requestAnimationFrame(frame); }
function resize() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  camera.aspect = w / h; camera.updateProjectionMatrix();
  renderer.setSize(w, h, false); composer.setSize(w, h);
  if (bloomPass) bloomPass.resolution.set(w, h);
}

/* ---- pointer: the block is a supplementary way in; the DOM links are the real ones ---- */
const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
function pick(e) {
  if (!renderer || small()) return null;
  ndc.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
  ray.setFromCamera(ndc, camera);
  const hit = ray.intersectObjects(blocks.filter(g => g.visible), true)[0];
  return hit ? hit.object.parent : null;
}
let hoverTimer = 0;
document.addEventListener("pointermove", e => { if (hoverTimer) return; hoverTimer = setTimeout(() => { hoverTimer = 0; if (e.target.closest("a, button, input, select, .plate, dialog")) return; document.body.style.cursor = pick(e) ? "pointer" : ""; }, 60); });
document.addEventListener("click", e => { if (e.target.closest("a, button, input, select, label, .plate, dialog, .nav")) return; const g = pick(e); if (g) location.assign(g.userData.el.dataset.slug + "/"); });

/* ---- lifecycle ---- */
async function start() {
  if (!(canvas.getContext("webgl2") || canvas.getContext("webgl"))) return report("static");   // probe here, off the first paint
  try {
    build();
    await warm();                                     // shaders link in parallel; the page stays interactive meanwhile
    performance.mark("scene:compiled");
    report("live");                                   // hides the static figures, so measure after the layout settles
    measure(); onScroll(); t = target; lastChapter = Math.round(t);
    new ResizeObserver(() => { measure(); onScroll(); }).observe(document.body);
    wake();
  } catch (e) { console.warn("scene: static fallback (" + e.message + ")"); report("static"); }
}
function warm() {                                      // compile every program the first frame needs, with the same render-target state the composer uses
  const quad = new THREE.PlaneGeometry(2, 2), passes = new THREE.Scene();
  const mats = [glitchPass.material];
  if (bloomPass) mats.push(...bloomPass.separableBlurMaterials, bloomPass.compositeMaterial, bloomPass.materialHighPassFilter, bloomPass.blendMaterial);
  for (const m of mats) passes.add(new THREE.Mesh(quad, m));
  const cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  renderer.setRenderTarget(composer.writeBuffer);
  for (const g of blocks) g.visible = true;            // so the shell and slab programs link now, not on the first fly-through frame
  const done = Promise.all([renderer.compileAsync(scene, camera), renderer.compileAsync(passes, cam)]).finally(() => { renderer.setRenderTarget(null); quad.dispose(); });
  return Promise.race([done, new Promise(r => setTimeout(r, 8000))]);
}
canvas.addEventListener("webglcontextlost", e => { e.preventDefault(); cancelAnimationFrame(raf); raf = 0; if (++lost > 1) report("static"); });
canvas.addEventListener("webglcontextrestored", () => { if (lost <= 1 && renderer) wake(); });
addEventListener("portfolio:motion", e => { paused = e.detail.paused; wake(); });
motionQuery.addEventListener("change", () => { reduced = motionQuery.matches; t = target; wake(); });
addEventListener("scroll", onScroll, { passive: true });
let resizeTimer = 0;
addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { if (renderer) { measure(); resize(); onScroll(); } }, 120); });
document.addEventListener("visibilitychange", () => { if (document.hidden) { cancelAnimationFrame(raf); raf = 0; lastFrame = 0; } else wake(); });
addEventListener("pagehide", () => { renderer?.dispose(); });
if ("requestIdleCallback" in window) requestIdleCallback(start, { timeout: 800 }); else setTimeout(start, 50);
