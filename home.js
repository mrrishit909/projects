/* The record shelf. Every project is a sleeve on the shelf: open it, slide the vinyl out, press play, and the record
   drops onto the turntable before the case study opens. The project list comes from build.py (#projects-data). */
const PROJECTS = JSON.parse(document.getElementById("projects-data").textContent);
const $ = id => document.getElementById(id);
const perPage = 24, perShelf = 8;
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const idle = [PROJECTS.length + " PROJECTS / RISHIT MATHUR", "PICK A RECORD FROM THE SHELF."];
let page = 0, filtered = PROJECTS, selected = null, lastButton = null, revealed = false;
let flight = null, playing = false, elapsed = 0, lastTime = 0, raf = 0, sequenceToken = 0;

const number = p => String(PROJECTS.indexOf(p) + 1).padStart(3, "0");
/* Spines are shades of one colour (the theme's --accent mixed into the paper), light to dark along each shelf;
   a record's sleeve and label use the shade of its spot on an unfiltered shelf. */
const shade = k => `color-mix(in srgb, var(--accent) ${14 + (k % perShelf) * 6}%, var(--paper))`;
const color = p => shade(PROJECTS.indexOf(p));
const url = p => new URL(p.slug + "/", location.href).href;
const asset = (p, f) => new URL(p.slug + "/" + f, location.href).href;

function render() {
  const max = Math.max(1, Math.ceil(filtered.length / perPage));
  page = Math.min(page, max - 1);
  $("cabinet").replaceChildren();
  const subset = filtered.slice(page * perPage, (page + 1) * perPage);
  if (!subset.length) {
    const no = document.createElement("p");
    no.className = "no-results";
    no.textContent = "No records found. Try another title or technology.";
    $("cabinet").append(no);
  }
  for (let row = 0; row < Math.ceil(subset.length / perShelf); row++) {
    const shelf = document.createElement("div");
    shelf.className = "shelf";
    subset.slice(row * perShelf, (row + 1) * perShelf).forEach((p, i) => {
      const b = document.createElement("button");
      b.className = "spine";
      b.style.setProperty("--color", shade(i));
      b.style.setProperty("--height", (105 + (i % 4) * 3) + "px");
      b.setAttribute("aria-label", p.title + " — " + p.kind);
      b.title = p.title;
      const n = document.createElement("span");
      n.className = "num";
      n.textContent = number(p);
      const t = document.createElement("span");
      t.className = "name";
      t.textContent = p.title;
      b.append(n, t);
      b.onclick = () => openRecord(p, b);
      shelf.append(b);
    });
    const tag = document.createElement("span");
    tag.className = "shelf-label";
    tag.textContent = "SIDE " + String.fromCharCode(65 + row);
    shelf.append(tag);
    $("cabinet").append(shelf);
  }
  $("count").textContent = filtered.length + " RECORDS";
  $("page-label").textContent = (page + 1) + " / " + max;
  $("prev").disabled = page === 0;
  $("next").disabled = page >= max - 1;
}

function fillLabel(el, p) {
  el.replaceChildren();
  el.style.setProperty("--color", color(p));
  const sm = document.createElement("small");
  sm.textContent = "RM / " + number(p);
  const st = document.createElement("strong");
  st.textContent = p.title;
  el.append(sm, st);
}

/* The sleeve art: the project's motion loop when it has one (poster = cover), else its cover image. */
function fillSleeve(p) {
  const img = $("cover"), video = $("cover-loop");
  video.pause();
  video.replaceChildren();
  video.removeAttribute("poster");
  const loops = (p.loops || []).slice().sort().reverse();   // loop.webm first, then loop.mp4
  if (loops.length) {
    img.style.display = "none";
    if (p.cover) video.poster = asset(p, p.cover);
    for (const f of loops) {
      const s = document.createElement("source");
      s.src = asset(p, f);
      s.type = "video/" + f.split(".").pop();
      video.append(s);
    }
    video.style.display = "block";
    video.load();
    if (!reduced) video.play().catch(() => {});
  } else {
    video.style.display = "none";
    img.style.display = p.cover ? "block" : "none";
    img.onerror = () => { img.style.display = "none"; };
    if (p.cover) img.src = asset(p, p.cover);
    img.alt = p.title + " project preview";
  }
}

function openRecord(p, b) {
  cancelPlayback(false);
  selected = p;
  lastButton = b;
  revealed = false;
  $("stage").classList.remove("revealed");
  $("stage").style.setProperty("--color", color(p));
  $("catalog").textContent = "RM—" + number(p) + " / " + p.date;
  $("cover-title").textContent = p.title;
  $("cover-kind").textContent = p.kind;
  $("cover-number").textContent = number(p) + " / 33⅓";
  $("modal-title").textContent = p.title;
  $("kind").textContent = p.kind;
  fillLabel($("label"), p);
  fillSleeve(p);
  $("direct").href = url(p);
  $("reveal").textContent = "Reveal vinyl";
  $("hint").textContent = "Click the sleeve to slide out the record.";
  $("jacket").setAttribute("aria-expanded", "false");
  $("dialog").showModal();
}

function reveal() {
  revealed = !revealed;
  $("stage").classList.toggle("revealed", revealed);
  $("reveal").textContent = revealed ? "Return to sleeve" : "Reveal vinyl";
  $("jacket").setAttribute("aria-expanded", String(revealed));
  $("hint").textContent = revealed ? "Press Play to put this project on the turntable." : "Click the sleeve to slide out the record.";
}

function closeRecord() {
  $("dialog").close();
  lastButton?.focus();
}

async function start() {
  if (!selected || playing) return;
  const token = ++sequenceToken;
  if (!revealed) {
    reveal();
    await new Promise(r => setTimeout(r, reduced ? 0 : 750));
  }
  if (token !== sequenceToken || !$("dialog").open) return;
  const bounds = $("record").getBoundingClientRect();
  flight = document.createElement("div");
  flight.className = "flight-record";
  Object.assign(flight.style, { left: bounds.left + "px", top: bounds.top + "px", width: bounds.width + "px", height: bounds.height + "px" });
  const spin = document.createElement("div");
  spin.className = "disc-spin";
  const label = document.createElement("div");
  label.className = "label";
  fillLabel(label, selected);
  spin.append(label);
  flight.append(spin);
  document.body.append(flight);
  $("dialog").close();
  $("station-disc").classList.add("hidden");
  fillLabel($("station-label"), selected);
  $("deck").classList.add("loaded");
  $("rest-label").style.visibility = "hidden";
  if (innerWidth <= 760) $("deck").scrollIntoView({ behavior: "instant", block: "center" });
  $("now-title").textContent = selected.title;
  $("now-small").textContent = "ON THE TURNTABLE / RM—" + number(selected);
  $("play-strip").classList.add("show");
  $("pause").textContent = "Ⅱ Pause";
  $("status").textContent = "Dropping the needle…";
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const target = $("platter").getBoundingClientRect();
    Object.assign(flight.style, { left: target.left + "px", top: target.top + "px", width: target.width + "px", height: target.height + "px" });
  }));
  elapsed = 0;
  playing = true;
  lastTime = performance.now();
  raf = requestAnimationFrame(tick);
}

const duration = reduced ? 2200 : 6200;
function tick(time) {
  if (!playing) return;
  elapsed += time - lastTime;
  lastTime = time;
  if (elapsed > (reduced ? 100 : 1000)) {
    $("deck").classList.add("active");
    $("station-disc").classList.remove("hidden");
    if (flight) flight.style.visibility = "hidden";
    $("status").textContent = "Playing · opening project…";
  }
  $("progress").style.width = Math.min(100, elapsed / duration * 100) + "%";
  if (elapsed >= duration) {
    playing = false;
    $("room").classList.add("launching");
    $("play-strip").classList.remove("show");
    if (flight) flight.style.opacity = "0";
    setTimeout(() => location.assign(url(selected)), reduced ? 0 : 650);
    return;
  }
  raf = requestAnimationFrame(tick);
}

function togglePause() {
  playing = !playing;
  if (playing) {
    lastTime = performance.now();
    raf = requestAnimationFrame(tick);
    $("pause").textContent = "Ⅱ Pause";
    $("status").textContent = "Playing · opening project…";
    if (elapsed > 1000) {
      flight?.classList.add("spinning");
      $("deck").classList.add("active");
    }
  } else {
    cancelAnimationFrame(raf);
    flight?.classList.remove("spinning");
    $("deck").classList.remove("active");
    $("pause").textContent = "▶ Resume";
    $("status").textContent = "Paused · take your time";
  }
}

function cancelPlayback(restore = true) {
  sequenceToken++;
  playing = false;
  cancelAnimationFrame(raf);
  flight?.remove();
  flight = null;
  elapsed = 0;
  $("deck").classList.remove("active", "loaded");
  $("station-disc").classList.remove("hidden");
  $("room").classList.remove("launching");
  $("play-strip").classList.remove("show");
  $("rest-label").style.visibility = "visible";
  $("progress").style.width = "0";
  if (restore) {
    [$("now-small").textContent, $("now-title").textContent] = idle;
    lastButton?.focus();
  }
}

const step = d => PROJECTS[(PROJECTS.indexOf(selected) + d + PROJECTS.length) % PROJECTS.length];

$("close").onclick = closeRecord;
$("dialog").addEventListener("click", e => { if (e.target === $("dialog")) closeRecord(); });
$("dialog").addEventListener("close", () => {
  $("cover-loop").pause();
  if (!flight) sequenceToken++;
});
$("jacket").onclick = reveal;
$("reveal").onclick = reveal;
$("prev").onclick = () => { page--; render(); };
$("next").onclick = () => { page++; render(); };
$("search").oninput = e => {
  page = 0;
  const q = e.target.value.toLowerCase();
  filtered = PROJECTS.filter(p => (p.title + " " + p.kind).toLowerCase().includes(q));
  render();
};
$("play").onclick = start;
$("pause").onclick = togglePause;
$("cancel").onclick = () => cancelPlayback();
$("station-play").onclick = () => openRecord(selected || PROJECTS[0], $("station-play"));
$("station-prev").onclick = () => openRecord(step(-1), $("station-prev"));
$("station-next").onclick = () => openRecord(step(1), $("station-next"));
$("station-shuffle").onclick = () => openRecord(PROJECTS[Math.floor(Math.random() * PROJECTS.length)], $("station-shuffle"));
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    sequenceToken++;
    if (flight) cancelPlayback();
  }
});
window.addEventListener("pageshow", e => { if (e.persisted) cancelPlayback(); });
document.addEventListener("visibilitychange", () => { if (document.hidden && playing) togglePause(); });
render();
