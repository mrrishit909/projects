"""Build the projects site: every <slug>/project.json -> <slug>/index.html, plus the root index.html.

    python3 build.py

Text fields in project.json are trusted HTML fragments (we write them ourselves).
Stdlib only, so GitHub never needs to run anything: we commit the built HTML.
"""
import hashlib
import json
import struct
from collections import Counter
from html import escape
from pathlib import Path

ROOT = Path(__file__).parent
PORTFOLIO = "https://mrrishit909.github.io/"
REQUIRED = ["title", "tagline", "kind", "tech", "date", "repo", "problem", "built", "steps", "results", "next"]


# ---- motion tiles -------------------------------------------------------------------------------------------
# A project's card on the home page plays <slug>/loop.mp4 (+ loop.webm) when those files exist; otherwise it shows a
# slow pan over cover.jpg. Nothing has to be declared in project.json: files are found by name, and the card's shape
# (aspect ratio) is read from the media itself.
LOOPS = ["loop.mp4", "loop.webm"]


def mp4_aspect(path):
    """Width / height from the track header (tkhd) of an .mp4, or None."""
    data = path.read_bytes()

    def walk(lo, hi):
        i = lo
        while i + 8 <= hi:
            size, kind = struct.unpack(">I4s", data[i:i + 8])
            if size == 1:
                size = struct.unpack(">Q", data[i + 8:i + 16])[0]
            if size < 8:
                return None
            end = min(hi, i + size)
            if kind == b"tkhd":
                w, h = struct.unpack(">II", data[end - 8:end])
                if w and h:
                    return (w >> 16) / (h >> 16)
            elif kind in (b"moov", b"trak"):
                found = walk(i + 8, end)
                if found:
                    return found
            i += size
        return None
    return walk(0, len(data))


def image_aspect(path):
    """Width / height of a .jpg or .png, or None."""
    d = path.read_bytes()
    if d[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", d[16:24])
        return w / h
    i = 2
    while d[:2] == b"\xff\xd8" and i + 9 < len(d):
        if d[i] != 0xFF:
            i += 1
            continue
        m = d[i + 1]
        if m in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", d[i + 5:i + 9])
            return w / h
        i += 2 + struct.unpack(">H", d[i + 2:i + 4])[0]
    return None


def tile_media(folder, p):
    """-> (existing loop files, card aspect ratio). Cards keep a calm range of shapes so the row stays balanced."""
    loops = [f for f in LOOPS if (folder / f).exists()]
    aspect = None
    if (folder / "loop.mp4").exists():
        aspect = mp4_aspect(folder / "loop.mp4")
    if aspect is None and p.get("cover") and (folder / p["cover"]).exists():
        aspect = image_aspect(folder / p["cover"])
        if aspect:                       # a screenshot is cropped to fit the card, so keep it in a sane range
            aspect = min(1.9, max(1.3, aspect))
    return loops, round(aspect or 1.7, 3)


def load():
    projects = []
    for f in sorted(ROOT.glob("*/project.json")):
        p = json.loads(f.read_text())
        missing = [k for k in REQUIRED if not p.get(k)]
        assert not missing, f"{f}: missing {missing}"
        assert all(s.get("title") and s.get("body") for s in p["steps"]), f"{f}: every step needs title + body"
        p["slug"] = f.parent.name
        p["loops"], p["aspect"] = tile_media(f.parent, p)
        if p.get("cover"):
            assert (f.parent / p["cover"]).exists(), f"{f}: cover {p['cover']} not found"
        projects.append(p)
    # newest first; "order" breaks ties / pins
    return sorted(projects, key=lambda p: (p["date"], -p.get("order", 0)), reverse=True)


def asset_version(name):
    """?v=<hash of the file>: a changed stylesheet or script gets a new URL, so browsers never use a stale cached copy."""
    return hashlib.sha1((ROOT / name).read_bytes()).hexdigest()[:10]


def page(title, desc, body):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{escape(desc)}">
<title>{escape(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500&family=Geist+Mono&display=swap">
<link rel="stylesheet" href="../site.css?v={asset_version("site.css")}">
<script src="../case.js?v={asset_version("case.js")}" defer></script>
</head>
<body>
{body}
</body>
</html>
"""


def project_page(p, nxt):
    steps = []
    for i, s in enumerate(p["steps"], 1):
        code = f'<pre><code>{escape(s["code"])}</code></pre>' if s.get("code") else ""
        steps.append(f'<li><span class="n">{i:02d}</span><div><h3>{escape(s["title"])}</h3>{s["body"]}{code}</div></li>')
    links = [f'<a href="{escape(p["repo"])}" target="_blank" rel="noopener">Code on GitHub &#8599;</a>']
    if p.get("demo"):
        links.insert(0, f'<a href="{escape(p["demo"])}">{escape(p.get("demo_label", "See it"))} &#8599;</a>')
    cover = (f'<figure class="cover"><img src="{escape(p["cover"])}" alt="Screenshot of {escape(p["title"])}"></figure>'
             if p.get("cover") else "")
    note = f'<p class="note">{p["note"]}</p>' if p.get("note") else ""
    # the next project's motion tile, played by case.js while the link is on screen
    peek = ("".join([f'<video muted loop playsinline preload="none" aria-hidden="true" poster="../{nxt["slug"]}/{escape(nxt["cover"])}">' if nxt.get("cover") else
                     '<video muted loop playsinline preload="none" aria-hidden="true">'] +
                    [f'<source src="../{nxt["slug"]}/{f}" type="video/{f.split(".")[1]}">' for f in sorted(nxt["loops"], reverse=True)] + ["</video>"])
            if nxt.get("loops") else "")
    sections = [("The problem", p["problem"]), ("What I built", p["built"]),
                ("How it was built", f'<ol class="steps">{"".join(steps)}</ol>'),
                ("Results", p["results"]), ("What I'd do next", p["next"])]
    ids = ["problem", "built", "how", "results", "next-steps"]
    secs = "".join(f'<section class="s" id="{ids[n - 1]}"><h2 class="cap">{n:02d} &mdash; {escape(t)}</h2><div class="body">{b}</div></section>'
                   for n, (t, b) in enumerate(sections, 1))
    body = f"""<header class="bar cap"><a href="{PORTFOLIO}">Rishit Mathur</a><nav><a href="../">All projects</a><a href="{PORTFOLIO}resume.pdf">Resume</a></nav></header>
<main class="wrap">
  <div class="hero">
    <p class="cap dim">{escape(p["kind"])} &middot; {escape(p["date"])}</p>
    <h1>{escape(p["title"])}</h1>
    <p class="tagline">{escape(p["tagline"])}</p>
    <div class="meta cap"><span class="tech">{" &middot; ".join(escape(t) for t in p["tech"])}</span><span class="links">{"".join(links)}</span></div>
  </div>
  {cover}
  {note}
  {secs}
  <a class="next" href="../{nxt["slug"]}/"><span class="cap">Next project</span><span class="t">{escape(nxt["title"])} &rarr;</span>{peek}</a>
</main>
<footer class="cap"><span>&copy; 2026 Rishit Raj Mathur</span><a href="https://github.com/mrrishit909">GitHub</a></footer>"""
    return page(f'{p["title"]} · Rishit Mathur', p["tagline"], body)


def index_page(projects):
    """The record-shelf page (index.template.html + home.js). A plain list of real links is rendered here for no-JS visitors."""
    items = "".join(f'<li><a href="{p["slug"]}/">{escape(p["title"])}</a></li>' for p in projects)
    data = [{k: p.get(k) for k in ("slug", "title", "kind", "date", "cover", "aspect", "loops")} for p in projects]
    # "Python, Statistics, LLM ...": the most common first word of each project's kind, so it follows new projects
    heads = Counter(p["kind"].split("·")[0].strip() for p in projects)
    kinds = ", ".join(escape(k) for k, _ in heads.most_common(5))
    # home.js?v=<hash of its contents>: a changed script gets a new URL, so browsers never run a stale cached copy
    version = hashlib.sha1((ROOT / "home.js").read_bytes()).hexdigest()[:10]
    tpl = (ROOT / "index.template.html").read_text()
    assert "<!--LIST-->" in tpl and "/*PROJECTS*/[]" in tpl
    # json.dumps output is safe inside <script> once "</" can't appear
    return (tpl.replace("<!--LIST-->", items).replace("/*PROJECTS*/[]", json.dumps(data).replace("</", "<\\/"))
               .replace("{{COUNT}}", str(len(projects))).replace("{{KINDS}}", kinds)
               .replace("{{V}}", version))


if __name__ == "__main__":
    projects = load()
    for i, p in enumerate(projects):
        if p.get("frozen"):   # page kept exactly as published; its old style.css stays too
            continue
        (ROOT / p["slug"] / "index.html").write_text(project_page(p, projects[(i + 1) % len(projects)]))
    (ROOT / "index.html").write_text(index_page(projects))
    nfrozen = sum(bool(p.get("frozen")) for p in projects)
    print(f"built {len(projects) - nfrozen} project pages (+{nfrozen} frozen) + index.html")
