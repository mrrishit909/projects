/* Regression checks for the unified portfolio (index.html). Run against a local server of the built site:
     python3 -m http.server 8800 --bind 127.0.0.1 &  NODE_PATH=$(npm root -g) node tests/portfolio-check.cjs
   Covers: content and links without JavaScript, every internal link resolving to a real file, the page order, the complete
   catalogue and its search / filter / twelve-at-a-time reveal / detail dialog (#<slug>, Previous / Next keeping the URL and
   history in step), the screenshot viewer, keyboard order, reduced motion, WebGL unavailable, the slow-renderer hand-off,
   the archive redirect, case-study navigation, contrast from computed styles, overflow at five breakpoints, console errors. */
const { chromium } = require("playwright");
const fs = require("fs"), path = require("path");
const BASE = process.env.BASE || "http://127.0.0.1:8800/";
const KEEP = BASE + "?scene=keep";          // hold the starting quality tier: headless SwiftShader would otherwise (correctly) hand off to the static page
const root = path.join(__dirname, "..");
const assert = (ok, msg) => { if (!ok) { console.error("FAIL:", msg); process.exit(1); } console.log("ok:", msg); };
const GL = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"];

(async () => {
  const b = await chromium.launch({ args: GL });
  const errors = [];
  const page = async (opts = {}, init, url = KEEP, settle = 3500) => {
    const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, ...opts });
    if (init) await ctx.addInitScript(init);
    const p = await ctx.newPage();
    p.on("pageerror", e => errors.push(String(e)));
    p.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
    await p.goto(url, { waitUntil: "networkidle" });
    await p.waitForTimeout(settle);
    return p;
  };
  const featured = JSON.parse(fs.readFileSync(path.join(root, "featured.json"), "utf8"));
  const slugs = fs.readdirSync(root).filter(d => fs.existsSync(path.join(root, d, "project.json")));

  // 1. without JavaScript: identity, navigation, featured work, the whole catalogue, résumé and contact are plain HTML
  let p = await page({ javaScriptEnabled: false }, null, BASE, 0);
  assert(await p.$eval("h1", h => h.textContent.trim()) === "Rishit Mathur", "name is the h1 without JavaScript");
  assert(await p.$$eval(".nav-links a", as => as.map(a => a.textContent)).then(t => ["Work", "Projects", "About", "Experience", "Résumé", "Contact"].every(x => t.includes(x))), "persistent nav: Work / About / Experience / Projects / Résumé / Contact");
  const order = await p.$$eval("main > section", els => els.map(e => e.id));
  assert(JSON.stringify(order) === JSON.stringify(["top", "method", "work", "about", "experience", "capabilities", "projects", "contact"]), `page order: hero, method, work, about, experience, capabilities, projects, contact (${order.join(" > ")})`);
  assert(featured.length === 4 && await p.$$eval(".feature", els => els.length) === 4, "four flagship projects rendered as static HTML");
  assert(await p.$$eval(".feature-figure img", imgs => imgs.length === 4 && imgs.every(i => getComputedStyle(i.closest("figure")).display !== "none" && i.naturalWidth > 0)), "no-JS: every flagship screenshot is in the page");
  assert(await p.$$eval(".feature .inspect", as => as.every(a => /cover\.jpg$/.test(a.getAttribute("href")) && /Enlarge screenshot/.test(a.getAttribute("aria-label")))), "no-JS: the enlarge control is a real link to the full-size image");
  assert(await p.$eval("#work-title", h => h.textContent.trim()) === "Selected work" && await p.$$eval(".feature .headline", hs => hs.length === 4), "'Selected work' heading and one prominent result per flagship");
  assert(await p.$$eval(".foot a", as => as.some(a => a.getAttribute("href") === "#about") && !as.some(a => /mrrishit909\.github\.io\/$/.test(a.href))), "footer links to the integrated About, not a separate site");
  const tiles = await p.$$eval(".tile", els => els.map(e => ({ slug: e.dataset.slug, href: e.querySelector("a").getAttribute("href"), shown: getComputedStyle(e).display !== "none" })));
  assert(tiles.length === slugs.length, `${tiles.length} catalogue entries rendered for ${slugs.length} project folders`);
  assert(tiles.every(t => t.href === t.slug + "/"), "every catalogue entry links to its own project folder");
  assert(tiles.every(t => t.shown), "no-JS: the whole catalogue is visible");
  assert(new Set(tiles.map(t => t.slug)).size === tiles.length, "no duplicate entries");
  assert(await p.$$eval("a[href$='resume.pdf']", as => as.length) >= 2, "résumé link present (nav and contact)");
  assert(await p.$$eval("a[href^='mailto:rishit.mathur@yahoo.com']", as => as.length) === 1, "verified e-mail link present");
  assert(await p.$eval("a[href*='linkedin.com/in/rishitrajmathur']", a => !!a), "verified LinkedIn link present");
  const hrefs = await p.$$eval("a[href]", as => as.map(a => a.getAttribute("href")));
  const internal = hrefs.filter(h => !/^(https?:|mailto:|#)/.test(h));
  const missing = internal.filter(h => { const f = path.join(root, h.split(/[?#]/)[0]); return !(fs.existsSync(f) && (fs.statSync(f).isFile() || fs.existsSync(path.join(f, "index.html")))); });
  assert(missing.length === 0, `all ${internal.length} internal links resolve on disk` + (missing.length ? ": missing " + missing.join(", ") : ""));
  await p.close();

  // 2. with JavaScript: scene live, content visible, motion control, keyboard order, chapters follow scroll
  p = await page();
  assert(await p.evaluate(() => document.documentElement.classList.contains("scene-live")), "WebGL scene initialises (headless SwiftShader)");
  assert(await p.evaluate(() => getComputedStyle(document.querySelector(".hero-copy")).opacity === "1" && !document.getElementById("motion-toggle").hidden), "hero copy visible and the motion control is shown");
  await p.keyboard.press("Tab");
  assert(await p.evaluate(() => document.activeElement.className === "skip"), "first Tab lands on the skip link");
  await p.keyboard.press("Tab"); await p.keyboard.press("Tab");
  assert(await p.evaluate(() => document.activeElement.textContent === "Work"), "nav is reachable by keyboard");
  await p.click("#motion-toggle");
  assert(await p.$eval("#motion-toggle", b => b.getAttribute("aria-pressed") === "true" && b.textContent === "Motion: Off"), "motion control pauses and reports its state");
  await p.click("#motion-toggle");
  const want = await p.evaluate(() => [...document.querySelectorAll("[data-scene]")].indexOf(document.querySelectorAll(".feature")[2]));
  await p.evaluate(() => scrollTo(0, document.querySelectorAll(".feature")[2].getBoundingClientRect().top + scrollY - innerHeight * 0.2)); await p.waitForTimeout(2500);
  const t = await p.evaluate(() => window.__scene.t);
  assert(Math.abs(t - want) < 0.6 && await p.evaluate(() => document.documentElement.classList.contains("hud-on") && /US Retail Sales Forecast/i.test(document.getElementById("hud-a").textContent)), `scroll drives the chapters in document order: third flagship is chapter ${want} (t = ${t.toFixed(2)}, HUD labels it)`);
  await p.evaluate(() => document.getElementById("about").scrollIntoView({ block: "start", behavior: "instant" })); await p.waitForTimeout(2500);
  const tAbout = await p.evaluate(() => window.__scene.t), aboutIdx = await p.evaluate(() => [...document.querySelectorAll("[data-scene]")].indexOf(document.getElementById("about")));
  assert(tAbout > want && Math.abs(tAbout - aboutIdx) < 0.7 && !(await p.evaluate(() => document.documentElement.classList.contains("hud-on"))), `About follows the flagships in the scene (chapter ${aboutIdx}, t = ${tAbout.toFixed(2)}, HUD off)`);
  await p.evaluate(() => document.querySelectorAll(".feature")[0].scrollIntoView({ block: "center", behavior: "instant" })); await p.waitForTimeout(2500);
  const tBack = await p.evaluate(() => window.__scene.t);
  assert(Math.abs(tBack - (want - 2)) < 0.7, `scrolling back up returns to the first flagship chapter (t = ${tBack.toFixed(2)})`);
  // the screenshot viewer: opens from the figure, shows the full image, closes on Escape and returns focus
  await p.click(".feature:nth-of-type(1) .inspect"); await p.waitForTimeout(500);
  const viewer = await p.evaluate(() => { const v = document.getElementById("viewer"), i = document.getElementById("viewer-img"); return [v.open, document.activeElement.id, i.getAttribute("src"), i.naturalWidth > 1000, i.getBoundingClientRect().width > 900, document.getElementById("viewer-caption").textContent.length > 20, document.getElementById("viewer-case").getAttribute("href")]; });
  assert(viewer[0] && viewer[1] === "viewer-close" && /florida-flight-delays\/cover\.jpg/.test(viewer[2]) && viewer[3] && viewer[4] && viewer[5] && viewer[6] === "florida-flight-delays/", `screenshot viewer opens with the full image, a caption and the case-study link (${JSON.stringify(viewer)})`);
  await p.keyboard.press("Escape"); await p.waitForTimeout(300);
  assert(await p.evaluate(() => !document.getElementById("viewer").open && document.activeElement === document.querySelector(".feature:nth-of-type(1) .inspect") && location.hash === ""), "Escape closes the viewer, focus returns to the enlarge control, the URL is untouched");
  const contrast = await p.evaluate(() => {
    const lum = c => { const v = c.match(/[\d.]+/g).slice(0, 3).map(x => x / 255).map(x => x <= .03928 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4); return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]; };
    const bg = lum("rgb(233, 237, 242)");     // the plate at its lightest; text also sits on the fog canvas in the nav and HUD
    const canvas = lum(getComputedStyle(document.body).backgroundColor);
    const r = (fg, b) => ((Math.max(fg, b) + .05) / (Math.min(fg, b) + .05));
    return [".nav-links a", ".eyebrow", ".lede", ".hero-aside", ".method-strip li", ".headline", ".facts dt", ".tools li", ".feature-figure figcaption", ".tile-kind", ".tl-when", ".hud-tag", ".section-intro .section-lede"].map(s => { const el = document.querySelector(s); const l = lum(getComputedStyle(el).color); return [s, Math.min(r(l, bg), r(l, canvas)).toFixed(2)]; });
  });
  assert(contrast.every(([, r]) => +r >= 4.5), "sampled text clears 4.5:1 on the plate and on the fog canvas: " + contrast.map(x => x.join(" ")).join(", "));
  // the catalogue: progressive reveal, search, filter, detail dialog with history and focus restoration
  await p.evaluate(() => document.getElementById("projects").scrollIntoView({ block: "start", behavior: "instant" })); await p.waitForTimeout(600);
  const visibleTiles = () => p.$$eval(".tile", els => els.filter(e => getComputedStyle(e).display !== "none").length);
  const firstShown = await visibleTiles();
  assert(firstShown === 12 && !(await p.$eval("#more", b => b.hidden)) && await p.$eval("#shown", e => e.textContent) === `12 of ${slugs.length} shown`, `catalogue starts with ${firstShown} projects and an accurate count`);
  await p.evaluate(() => document.getElementById("more").scrollIntoView({ block: "center", behavior: "instant" })); await p.evaluate(() => scrollBy(0, 300)); await p.waitForTimeout(800);
  assert(await visibleTiles() === 12, "scrolling near the end reveals nothing by itself");
  await p.click("#more"); await p.waitForTimeout(200);
  assert(await visibleTiles() === 24 && await p.$eval("#shown", e => e.textContent) === `24 of ${slugs.length} shown`, "Show more projects reveals twelve more (24) and the count follows");
  await p.fill("#search", "spark"); await p.waitForTimeout(150);
  const shown = await p.$$eval(".tile:not([hidden])", els => els.length);
  assert(shown > 0 && await p.$eval("#count-n", e => +e.textContent) === shown && shown === slugs.filter(s => fs.existsSync(path.join(root, s, "project.json")) && /spark/i.test(JSON.stringify(JSON.parse(fs.readFileSync(path.join(root, s, "project.json"), "utf8")), ["title", "kind", "tech"]))).length, `search for "spark" matches ${shown} across the whole dataset and the count agrees`);
  await p.selectOption("#kind", "SQL"); await p.waitForTimeout(150);
  assert(await p.$$eval(".tile:not([hidden])", els => els.every(e => e.dataset.kind === "SQL")), "the kind filter keeps only that kind");
  await p.fill("#search", "zzzz-nothing"); await p.waitForTimeout(150);
  assert(await p.$eval("#empty", e => !e.hidden) && await p.$eval("#reset", b => b.textContent.trim()) === "Reset all filters", "zero results shows the empty state with a 'Reset all filters' action");
  await p.click("#clear"); await p.waitForTimeout(150);
  assert(await p.$eval("#search", i => i.value) === "" && await p.$eval("#kind", s => s.value) === "SQL" && await p.$$eval(".tile:not([hidden])", els => els.length > 0 && els.every(e => e.dataset.kind === "SQL")) && await p.evaluate(() => document.activeElement.id === "search"), "Clear search clears only the text and keeps the kind filter");
  await p.click("#reset-all"); await p.waitForTimeout(150);
  assert(await p.$eval("#kind", s => s.value) === "" && await p.$$eval(".tile:not([hidden])", els => els.length) === slugs.length && await p.$eval("#reset-all", b => b.hidden), "Reset all filters clears both and shows the whole collection");
  await p.fill("#search", "zzzz-nothing"); await p.selectOption("#kind", "SQL"); await p.waitForTimeout(150);
  await p.click("#reset"); await p.waitForTimeout(150);
  assert(await p.$$eval(".tile:not([hidden])", els => els.length) === slugs.length && await p.$eval("#kind", s => s.value) === "", "the empty state's reset clears both filters too");
  await p.focus(".tile:nth-child(2) a"); await p.keyboard.press("Enter"); await p.waitForTimeout(400);
  assert(await p.evaluate(() => document.getElementById("detail").open && document.activeElement.id === "detail-title"), "Enter on a tile opens the detail and focuses its heading");
  const detailLinks = await p.evaluate(() => [document.getElementById("detail-open").getAttribute("href"), document.getElementById("detail-repo").href, location.hash]);
  assert(detailLinks[0] === tiles[1].slug + "/" && detailLinks[2] === "#" + tiles[1].slug && /github\.com/.test(detailLinks[1]), "detail links to the real case study and repo; URL hash names the project");
  const lenBefore = await p.evaluate(() => history.length);
  await p.click("#detail-next"); await p.waitForTimeout(200); await p.click("#detail-next"); await p.waitForTimeout(200); await p.click("#detail-prev"); await p.waitForTimeout(200);
  const stepped = await p.evaluate(() => [document.getElementById("detail-title").textContent, location.hash, history.state && history.state.project, history.length]);
  assert(stepped[1] === "#" + tiles[2].slug && stepped[2] === tiles[2].slug && stepped[3] === lenBefore && await p.$eval("#detail-open", a => a.getAttribute("href")) === tiles[2].slug + "/", `Previous / Next keep the hash, history state and links on the displayed project without growing history (${stepped[1]}, length ${stepped[3]})`);
  await p.reload({ waitUntil: "networkidle" }); await p.waitForTimeout(1200);
  assert(await p.evaluate(() => document.getElementById("detail").open && location.hash) === "#" + tiles[2].slug && await p.$eval("#detail-open", a => a.getAttribute("href")) === tiles[2].slug + "/", "reload after stepping opens the project the URL names");
  await p.keyboard.press("Escape"); await p.waitForTimeout(400);
  assert(await p.evaluate(() => !document.getElementById("detail").open && location.hash === ""), "Escape on a reloaded deep link closes it and clears the hash");
  await p.focus(".tile:nth-child(2) a"); await p.keyboard.press("Enter"); await p.waitForTimeout(400);
  await p.keyboard.press("Escape"); await p.waitForTimeout(400);
  assert(await p.evaluate(() => !document.getElementById("detail").open && location.hash === "" && document.activeElement === document.querySelector(".tile:nth-child(2) a")), "Escape closes it, clears the hash and restores focus");
  await p.focus(".tile:nth-child(3) a"); await p.keyboard.press("Enter"); await p.waitForTimeout(400);
  await p.goBack(); await p.waitForTimeout(400);
  const back = await p.evaluate(() => [document.getElementById("detail").open, location.hash]);
  await p.goForward(); await p.waitForTimeout(400);
  const fwd = await p.evaluate(() => [document.getElementById("detail").open, location.hash, document.getElementById("detail-title").textContent]);
  assert(!back[0] && back[1] === "" && fwd[0] && fwd[1] === "#" + tiles[2].slug, `Back closes the dialog, Forward reopens the same project (${fwd[2]})`);
  await p.keyboard.press("Escape"); await p.waitForTimeout(400);
  const prevented = await p.evaluate(() => { const a = document.querySelector(".tile:first-child a"); const seen = []; document.addEventListener("click", e => { seen.push(e.defaultPrevented); e.preventDefault(); }); const fire = init => { a.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0, ...init })); return seen.pop(); }; return { meta: fire({ metaKey: true }), plain: fire({}) }; });
  assert(!prevented.meta && prevented.plain, "cmd-click stays a native link; a plain click opens the detail");
  await p.close();

  // 3. deep link: #<slug> lands on the catalogue with that project open; the old archive address redirects there
  p = await page({}, null, KEEP + "#sec-10k-rag", 1500);
  assert(await p.evaluate(() => document.getElementById("detail").open) && await p.$eval("#detail-title", e => e.textContent) === "Ask the 10-K", "a direct link #sec-10k-rag opens that project");
  await p.close();
  p = await page({}, null, BASE + "archive/?q=spark", 1500);
  assert(/\/#projects$/.test(p.url()) || /\/$/.test(p.url().split("#")[0]), `the archive address forwards to the portfolio (${p.url()})`);
  await p.close();
  p = await page({}, null, BASE + featured[0].slug + "/", 0);
  const nav = await p.$$eval("header.bar nav a", as => as.map(a => a.getAttribute("href")));
  assert(nav.includes("../") && nav.includes("../#projects"), "case studies link back to the portfolio and the projects section");
  await p.close();

  // 4. reduced motion: no self-driven animation, no motion control; content intact
  p = await page({ reducedMotion: "reduce" });
  assert(await p.evaluate(() => document.getElementById("motion-toggle").hidden), "reduced motion hides the motion control (nothing moves on its own)");
  await p.close();

  // 5. WebGL unavailable: static capture, featured screenshots shown inline, all content and navigation intact
  p = await page({}, () => { const g = HTMLCanvasElement.prototype.getContext; HTMLCanvasElement.prototype.getContext = function (t, ...a) { return /webgl/.test(t) ? null : g.call(this, t, ...a); }; }, BASE, 1500);
  assert(await p.evaluate(() => document.documentElement.classList.contains("scene-static") && getComputedStyle(document.getElementById("scene-fallback")).display === "block"), "no WebGL: static fallback image shown");
  assert(await p.$eval(".feature-figure", f => getComputedStyle(f).display !== "none") && await p.$$eval(".tile", els => els.length) === slugs.length, "no WebGL: flagship screenshots in place, catalogue intact");
  await p.close();

  // 5b. a persistently slow renderer (headless SwiftShader, no ?scene=keep) hands off to the static page by itself; everything stays usable
  {
    const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } }); p = await ctx.newPage();
    p.on("pageerror", e => errors.push(String(e))); p.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
    await (await ctx.newCDPSession(p)).send("Emulation.setCPUThrottlingRate", { rate: 6 });   // make "persistently slow" certain, whatever the host
    await p.goto(BASE, { waitUntil: "networkidle" });
    await p.waitForFunction(() => document.documentElement.classList.contains("scene-static"), null, { timeout: 40000 }).catch(() => {});
  }
  const tiers = await p.evaluate(() => [document.documentElement.classList.contains("scene-static"), document.documentElement.classList.contains("hud-on"), getComputedStyle(document.getElementById("scene-fallback")).display, document.getElementById("motion-toggle").hidden]);
  assert(tiers[0] && !tiers[1] && tiers[2] === "block" && tiers[3], `slow renderer: tiers stepped down to the static presentation (${JSON.stringify(tiers)})`);
  await p.fill("#search", "spark"); await p.waitForTimeout(300);
  assert(await p.$$eval(".tile:not([hidden])", els => els.length) === 3 && await p.$eval("#projects", el => el.getBoundingClientRect().height > 0), "slow renderer: catalogue search and sections still work after the hand-off");
  await p.close();

  // 5c. controls respond while the scene is still initialising (shaders compile in parallel; nothing blocks input)
  {
    const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } }); p = await ctx.newPage();
    p.on("pageerror", e => errors.push(String(e))); p.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
    await p.goto(KEEP, { waitUntil: "domcontentloaded" });
    const t0 = Date.now(); await p.fill("#search", "spark"); const typed = Date.now() - t0;
    await p.waitForTimeout(250);
    const live = await p.evaluate(() => document.documentElement.classList.contains("scene-live"));
    assert(await p.$$eval(".tile:not([hidden])", els => els.length) === 3 && typed < 1500, `search usable during initialisation (typed in ${typed} ms, scene live yet: ${live})`);
    await p.close();
  }

  // 6. no horizontal overflow at the required breakpoints
  for (const [w, h] of [[1440, 900], [1280, 800], [768, 1024], [390, 844], [360, 800]]) {
    p = await page({ viewport: { width: w, height: h } }, null, KEEP, 500);
    const sw = await p.evaluate(() => document.documentElement.scrollWidth);
    assert(sw <= w, `${w}x${h}: no horizontal overflow (scrollWidth ${sw})`);
    await p.close();
  }
  await b.close();
  assert(errors.length === 0, "no console errors or unhandled rejections" + (errors.length ? ": " + errors.join(" | ") : ""));
  console.log("all checks passed");
})().catch(e => { console.error(e); process.exit(1); });
