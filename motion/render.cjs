#!/usr/bin/env node
/* Render the motion tiles: motion/scenes/<slug>.js  ->  <slug>/loop.mp4 + <slug>/loop.webm
 *
 *   node motion/render.cjs                 every scene
 *   node motion/render.cjs ames-housing    just those slugs
 *   node motion/render.cjs --sheet slug    contact sheet PNG (4 phases) instead of video, to eyeball a scene
 *
 * Needs: node, `playwright` (npm i -g playwright; its Chromium) and ffmpeg. The site itself needs none of this:
 * the finished clips are committed, and a project without a clip just gets a slow pan over its cover.jpg. */
const fs = require("fs"), path = require("path"), http = require("http"), { spawn } = require("child_process");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..");
const args = process.argv.slice(2);
const sheetMode = args[0] === "--sheet";
const wanted = args.filter((a) => !a.startsWith("--"));
const all = fs.readdirSync(path.join(__dirname, "scenes")).filter((f) => f.endsWith(".js")).map((f) => f.slice(0, -3));
const slugs = wanted.length ? wanted : all;
const OUT = process.env.SHEET_DIR || path.join(ROOT, "motion", ".sheets");
const US = (process.env.PHASES || "0.18,0.42,0.66,0.88").split(",").map(Number);

const MIME = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".woff2": "font/woff2", ".css": "text/css" };
const server = http.createServer((req, res) => {
  const p = path.join(ROOT, decodeURIComponent(req.url.split("?")[0]));
  if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": MIME[path.extname(p)] || "application/octet-stream" }); fs.createReadStream(p).pipe(res);
});

function encode(slug, info) {
  const dir = path.join(ROOT, slug);
  const common = ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(info.fps), "-i", "-", "-an"];
  const mp4 = ["-c:v", "libx264", "-preset", "slow", "-crf", "27", "-pix_fmt", "yuv420p", "-profile:v", "main", "-movflags", "+faststart", path.join(dir, "loop.mp4")];
  const webm = ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "36", "-pix_fmt", "yuv420p", "-row-mt", "1", "-deadline", "good", "-cpu-used", "2", path.join(dir, "loop.webm")];
  return spawn("ffmpeg", [...common, ...mp4, ...webm], { stdio: ["pipe", "inherit", "inherit"] });
}

async function one(browser, slug) {
  const page = await browser.newPage({ viewport: { width: 800, height: 600 } });
  page.on("pageerror", (e) => console.error(`[${slug}]`, e.message));
  page.on("console", (m) => { if (m.type() === "error") console.error(`[${slug}]`, m.text()); });
  await page.goto(`http://127.0.0.1:${server.address().port}/motion/lab.html?slug=${slug}`);
  await page.waitForFunction("window.ready || window.failed", null, { timeout: 30000 });
  const failed = await page.evaluate("window.failed"); if (failed) throw new Error(failed);
  const info = await page.evaluate("window.info");
  if (sheetMode) {
    fs.mkdirSync(OUT, { recursive: true });
    const url = await page.evaluate((us) => window.sheet(us), US);
    fs.writeFileSync(path.join(OUT, `${slug}.png`), Buffer.from(url.split(",")[1], "base64"));
    console.log(`sheet ${slug} (${info.W}x${info.H})`); await page.close(); return;
  }
  const ff = encode(slug, info), done = new Promise((r) => ff.on("close", r));
  for (let i = 0; i < info.frames; i++) {
    const url = await page.evaluate((n) => window.frame(n), i);
    if (!ff.stdin.write(Buffer.from(url.split(",")[1], "base64"))) await new Promise((r) => ff.stdin.once("drain", r));
  }
  ff.stdin.end(); await done; await page.close();
  const kb = (f) => Math.round(fs.statSync(path.join(ROOT, slug, f)).size / 1024);
  console.log(`${slug.padEnd(24)} ${info.W}x${info.H}  mp4 ${kb("loop.mp4")} KB  webm ${kb("loop.webm")} KB`);
}

(async () => {
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const browser = await chromium.launch();
  const queue = [...slugs], lanes = Number(process.env.LANES || 3);
  await Promise.all(Array.from({ length: lanes }, async () => {
    while (queue.length) { const s = queue.shift(); try { await one(browser, s); } catch (e) { console.error(`FAILED ${s}: ${e.message}`); process.exitCode = 1; } }
  }));
  await browser.close(); server.close();
})();
