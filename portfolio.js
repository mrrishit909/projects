/* The portfolio's DOM behaviour (no libraries, classic script so it runs even where the 3D module cannot):
   content reveals, current-section nav, the motion control, the complete catalogue (search, kind filter, progressive
   reveal, project detail dialog on #<slug>), and the static fallback when the scene never reports in. */
(() => {
  "use strict";
  const root = document.documentElement, $ = id => document.getElementById(id);
  const motionQuery = matchMedia("(prefers-reduced-motion: reduce)");

  /* ---- reveals and current-section nav ---- */
  const reveals = [...document.querySelectorAll(".plate, .timeline li, .cap-grid li")];
  reveals.forEach(el => el.classList.add("reveal"));
  const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add("is-in"); io.unobserve(e.target); } }), { rootMargin: "0px 0px -6% 0px" });
  reveals.forEach(el => { if (el.getBoundingClientRect().top < innerHeight) el.classList.add("is-in"); else io.observe(el); });
  const navLinks = [...document.querySelectorAll(".nav-links a[href^='#']")];
  const spy = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) navLinks.forEach(a => a.classList.toggle("is-current", a.hash === "#" + e.target.id)); }), { rootMargin: "-40% 0px -55% 0px" });
  navLinks.forEach(a => { const s = document.querySelector(a.hash); if (s) spy.observe(s); });

  /* ---- motion control: scene.js listens for the event; the preference is remembered per browser ---- */
  const toggle = $("motion-toggle");
  let paused = false;
  const setPaused = p => { paused = p; toggle.setAttribute("aria-pressed", String(p)); toggle.textContent = p ? "Motion: Off" : "Motion: On"; try { localStorage.setItem("portfolio-motion", p ? "off" : "on"); } catch (_) {} dispatchEvent(new CustomEvent("portfolio:motion", { detail: { paused: p } })); };
  toggle.addEventListener("click", () => setPaused(!paused));
  try { if (localStorage.getItem("portfolio-motion") === "off") setPaused(true); } catch (_) {}
  addEventListener("portfolio:scene", e => { toggle.hidden = e.detail.state !== "live" || motionQuery.matches; });
  motionQuery.addEventListener("change", () => { toggle.hidden = motionQuery.matches || !root.classList.contains("scene-live"); });
  // if the 3D module never reports (old browser, blocked file, GPU trouble), show the static capture instead
  setTimeout(() => { if (!root.classList.contains("scene-live")) root.classList.add("scene-static"); }, 9000);
  addEventListener("error", e => { if (/scene\.js|three/.test(e.filename || "")) root.classList.add("scene-static"); }, true);

  /* ---- the catalogue ---- */
  const DATA = JSON.parse($("projects-data").textContent);
  const bySlug = new Map(DATA.map((p, i) => [p.slug, { ...p, index: i }]));
  const tiles = [...document.querySelectorAll(".tile")], total = tiles.length, PAGE = 36;
  const search = $("search"), kind = $("kind"), clear = $("clear"), more = $("more");
  let visible = tiles, shown = PAGE, announceTimer = 0;
  function paint() {
    visible.forEach((t, i) => t.classList.toggle("is-beyond", i >= shown));
    const n = Math.min(shown, visible.length);
    more.hidden = n >= visible.length;
    $("shown").textContent = visible.length ? `${n} of ${visible.length} shown` : "";
  }
  function applyFilter(resetPage = true) {
    const q = search.value.trim().toLowerCase(), k = kind.value;
    visible = [];
    for (const t of tiles) {
      const show = (!k || t.dataset.kind === k) && (!q || t.dataset.search.includes(q));
      t.hidden = !show;
      if (show) visible.push(t);
    }
    if (resetPage) shown = PAGE;
    $("count-n").textContent = visible.length;
    $("empty").hidden = visible.length > 0;
    clear.hidden = !search.value;
    paint();
    clearTimeout(announceTimer);
    announceTimer = setTimeout(() => { $("announce").textContent = `${visible.length} of ${total} projects match`; }, 400);
  }
  search.addEventListener("input", () => applyFilter());
  kind.addEventListener("change", () => applyFilter());
  const resetFilter = () => { search.value = ""; kind.value = ""; applyFilter(); search.focus(); };
  clear.addEventListener("click", resetFilter);
  $("reset").addEventListener("click", resetFilter);
  more.addEventListener("click", () => { const first = visible[shown]; shown += PAGE; paint(); first?.querySelector("a")?.focus({ preventScroll: true }); });
  const sentinel = new IntersectionObserver(es => { if (es[0].isIntersecting && !more.hidden && !document.getElementById("detail").open) { shown += PAGE; paint(); } }, { rootMargin: "400px 0px" });
  sentinel.observe(more);
  const params = new URLSearchParams(location.search);          // the old archive address forwarded ?q= / ?kind=
  if (params.get("q")) search.value = params.get("q");
  if (params.get("kind") && [...kind.options].some(o => o.value === params.get("kind"))) kind.value = params.get("kind");
  applyFilter();

  /* ---- project detail: a dialog filled from the catalogue data, addressable as #<slug> ---- */
  const detail = $("detail");
  let current = null, trigger = null;
  function fill(p) {
    const n = String(p.index + 1).padStart(3, "0");
    $("detail-catalog").textContent = `Project_${n} // ${p.kind} // ${p.date}`;
    $("detail-cover").src = p.slug + "/" + p.cover;
    $("detail-cover").alt = "Screenshot of " + p.title;
    $("detail-title").textContent = p.title;
    $("detail-tagline").textContent = p.tagline || "";
    $("detail-tech").replaceChildren(...(p.tech || []).map(t => Object.assign(document.createElement("li"), { textContent: t })));
    $("detail-open").href = p.slug + "/";
    $("detail-repo").href = p.repo;
    $("detail-demo").hidden = !p.demo;
    if (p.demo) { $("detail-demo").href = /^https?:/.test(p.demo) ? p.demo : p.slug + "/" + p.demo; $("detail-demo").textContent = (p.demo_label || "Live demo") + " ↗"; }
    const pos = visible.indexOf(document.querySelector(`.tile[data-slug="${p.slug}"]`));
    $("detail-pos").textContent = pos < 0 ? n : `${pos + 1} / ${visible.length}`;
    $("detail-prev").disabled = pos <= 0;
    $("detail-next").disabled = pos < 0 || pos >= visible.length - 1;
  }
  function open(slug, { push = true, from = null } = {}) {
    const p = bySlug.get(slug);
    if (!p) return;
    if (!detail.open) trigger = from;
    current = slug;
    if (push) history.pushState({ project: slug }, "", "#" + slug);
    fill(p);
    if (!detail.open) detail.showModal();
    $("detail-title").focus({ preventScroll: true });
  }
  function close({ fromHistory = false } = {}) {
    if (!detail.open) return;
    if (!fromHistory && history.state?.project) { history.back(); return; }
    detail.close();
    if (location.hash) history.replaceState(history.state, "", location.pathname + location.search);   // a deep-linked entry keeps no hash, so Back never reopens it
    current = null;
    const t = trigger?.isConnected && !trigger.closest(".tile")?.hidden ? trigger : search;
    t.focus({ preventScroll: true });
    trigger = null;
  }
  const step = d => { const i = visible.indexOf(document.querySelector(`.tile[data-slug="${current}"]`)); const t = visible[i + d]; if (t) open(t.dataset.slug, { push: false }); };
  $("tiles").addEventListener("click", e => {
    const t = e.target.closest(".tile");
    if (!t || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;   // modified clicks stay native links
    e.preventDefault();
    open(t.dataset.slug, { from: t.querySelector("a") });
  });
  $("detail-close").addEventListener("click", () => close());
  $("detail-prev").addEventListener("click", () => step(-1));
  $("detail-next").addEventListener("click", () => step(1));
  detail.addEventListener("cancel", e => { e.preventDefault(); close(); });
  detail.addEventListener("click", e => { if (e.target === detail) close(); });
  detail.addEventListener("keydown", e => { if (e.key === "ArrowLeft") step(-1); if (e.key === "ArrowRight") step(1); });
  addEventListener("popstate", () => {
    const slug = location.hash.slice(1);
    if (slug && bySlug.has(slug)) open(slug, { push: false, from: trigger ?? document.querySelector(`.tile[data-slug="${slug}"] a`) });
    else close({ fromHistory: true });
  });
  const initial = location.hash.slice(1);
  if (initial && bySlug.has(initial)) {
    const tile = document.querySelector(`.tile[data-slug="${initial}"]`);
    const i = visible.indexOf(tile);
    if (i >= shown) { shown = Math.ceil((i + 1) / PAGE) * PAGE; paint(); }
    $("projects").scrollIntoView({ block: "start", behavior: "instant" });
    open(initial, { push: false, from: tile?.querySelector("a") });
  }
})();
