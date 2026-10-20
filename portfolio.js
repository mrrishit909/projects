/* The portfolio's DOM behaviour (no libraries, classic script so it runs even where the 3D module cannot):
   content reveals, current-section nav, the motion control, the complete catalogue (search, kind filter, twelve-at-a-time
   reveal, project detail dialog on #<slug>), the flagship screenshot viewer, and the static fallback when the scene never
   reports in. */
(() => {
  "use strict";
  const root = document.documentElement, $ = id => document.getElementById(id);
  const motionQuery = matchMedia("(prefers-reduced-motion: reduce)");

  /* ---- reveals and current-section nav ---- */
  const reveals = [...document.querySelectorAll(".hero-copy, .section-intro, .plate, .sheet, .feature-figure, .method-strip li, .timeline li, .cap-grid li")];
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

  /* ---- the catalogue: twelve at a time, more only on request ---- */
  const DATA = JSON.parse($("projects-data").textContent);
  const bySlug = new Map(DATA.map((p, i) => [p.slug, { ...p, index: i }]));
  const tiles = [...document.querySelectorAll(".tile")], total = tiles.length, PAGE = 12;
  const search = $("search"), kind = $("kind"), clear = $("clear"), more = $("more"), resetAll = $("reset-all");
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
    resetAll.hidden = !search.value && !k;
    paint();
    clearTimeout(announceTimer);
    announceTimer = setTimeout(() => { $("announce").textContent = `${visible.length} of ${total} projects match`; }, 400);
  }
  search.addEventListener("input", () => applyFilter());
  kind.addEventListener("change", () => applyFilter());
  clear.addEventListener("click", () => { search.value = ""; applyFilter(); search.focus(); });            // the text only; the kind stays
  const resetFilters = () => { search.value = ""; kind.value = ""; applyFilter(); search.focus(); };       // both
  resetAll.addEventListener("click", resetFilters);
  $("reset").addEventListener("click", resetFilters);
  more.addEventListener("click", () => { const first = visible[shown]; shown += PAGE; paint(); first?.querySelector("a")?.focus({ preventScroll: true }); });
  const params = new URLSearchParams(location.search);          // the old archive address forwarded ?q= / ?kind=
  if (params.get("q")) search.value = params.get("q");
  if (params.get("kind") && [...kind.options].some(o => o.value === params.get("kind"))) kind.value = params.get("kind");
  applyFilter();

  /* ---- project detail: a dialog filled from the catalogue data, addressable as #<slug>.
     render (show) is separate from history: a click pushes one entry, Previous / Next replace it, popstate only renders. ---- */
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
  function show(slug, from = null) {                       // render only
    const p = bySlug.get(slug);
    if (!p) return false;
    if (!detail.open) trigger = from;
    current = slug;
    fill(p);
    if (!detail.open) detail.showModal();
    $("detail-title").focus({ preventScroll: true });
    return true;
  }
  function open(slug, from) {                              // a user opening a project: one history entry
    if (show(slug, from)) history.pushState({ project: slug }, "", "#" + slug);
  }
  function step(d) {                                       // Previous / Next: the URL follows, the trail does not grow
    const i = visible.indexOf(document.querySelector(`.tile[data-slug="${current}"]`)), t = visible[i + d];
    if (t && show(t.dataset.slug)) history.replaceState({ project: t.dataset.slug }, "", "#" + t.dataset.slug);
  }
  function hide() {                                        // close the dialog and put focus back; no history here
    if (!detail.open) return;
    detail.close();
    current = null;
    const t = trigger?.isConnected && !trigger.closest(".tile")?.hidden ? trigger : search;
    t.focus({ preventScroll: true });
    trigger = null;
  }
  function close() {                                       // the user closing: step back over the entry a click pushed
    if (!detail.open) return;
    if (history.state?.project) { history.back(); return; }   // popstate hides it
    hide();
    if (location.hash) history.replaceState(null, "", location.pathname + location.search);   // a deep-linked entry keeps no hash, so Back never reopens it
  }
  $("tiles").addEventListener("click", e => {
    const t = e.target.closest(".tile");
    if (!t || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;   // modified clicks stay native links
    e.preventDefault();
    open(t.dataset.slug, t.querySelector("a"));
  });
  $("detail-close").addEventListener("click", close);
  $("detail-prev").addEventListener("click", () => step(-1));
  $("detail-next").addEventListener("click", () => step(1));
  detail.addEventListener("cancel", e => { e.preventDefault(); close(); });
  detail.addEventListener("click", e => { if (e.target === detail) close(); });
  detail.addEventListener("keydown", e => { if (e.key === "ArrowLeft") step(-1); if (e.key === "ArrowRight") step(1); });
  addEventListener("popstate", () => {
    const slug = location.hash.slice(1);
    if (slug && bySlug.has(slug)) show(slug, trigger ?? document.querySelector(`.tile[data-slug="${slug}"] a`));
    else hide();
  });
  const initial = location.hash.slice(1);
  if (initial && bySlug.has(initial)) {
    const tile = document.querySelector(`.tile[data-slug="${initial}"]`);
    const i = visible.indexOf(tile);
    if (i >= shown) { shown = Math.ceil((i + 1) / PAGE) * PAGE; paint(); }
    $("projects").scrollIntoView({ block: "start", behavior: "instant" });
    show(initial, tile?.querySelector("a"));
  }

  /* ---- screenshot viewer for the flagship projects: the real image, full size, original aspect ratio ---- */
  const viewer = $("viewer");
  let viewerTrigger = null;
  document.addEventListener("click", e => {
    const a = e.target.closest("[data-inspect]");
    if (!a || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;   // modified clicks open the file itself
    const p = bySlug.get(a.dataset.inspect);
    if (!p) return;
    e.preventDefault();
    viewerTrigger = a;
    const img = $("viewer-img");
    img.src = p.slug + "/" + p.cover; img.alt = "Screenshot of " + p.title;
    if (p.size) { img.width = p.size[0]; img.height = p.size[1]; }
    $("viewer-title").textContent = p.title + " // " + p.kind;
    $("viewer-caption").textContent = p.caption || p.tagline || "";
    $("viewer-case").href = p.slug + "/";
    $("viewer-demo").hidden = !p.demo;
    if (p.demo) { $("viewer-demo").href = /^https?:/.test(p.demo) ? p.demo : p.slug + "/" + p.demo; $("viewer-demo").textContent = (p.demo_label || "Demo") + " ↗"; }
    viewer.showModal();
    $("viewer-close").focus();
  });
  const closeViewer = () => { if (viewer.open) viewer.close(); };
  $("viewer-close").addEventListener("click", closeViewer);
  viewer.addEventListener("cancel", e => { e.preventDefault(); closeViewer(); });
  viewer.addEventListener("click", e => { if (e.target === viewer) closeViewer(); });
  viewer.addEventListener("close", () => { viewerTrigger?.focus({ preventScroll: true }); viewerTrigger = null; });
})();
