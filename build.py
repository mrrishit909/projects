"""Build the projects site: every <slug>/project.json -> <slug>/index.html, plus the root index.html.

    python3 build.py

Text fields in project.json are trusted HTML fragments (we write them ourselves).
Stdlib only, so GitHub never needs to run anything: we commit the built HTML.
"""
import hashlib
import json
import re
import struct
from collections import Counter
from html import escape
from pathlib import Path

ROOT = Path(__file__).parent
PORTFOLIO = "https://mrrishit909.github.io/"
REQUIRED = ["title", "tagline", "kind", "tech", "date", "repo", "problem", "built", "steps", "results", "next"]
# Every project carries the same format: one project.json, one cover.jpg, the standard case-study page, its record on the shelf,
# and the site-wide colours. These checks make the build refuse a project that would break that.
FROZEN_OK = {"trading-bot"}          # published before the standard format; kept as-is. No new project may be frozen.
OWN_STYLING = ("style=", "<style", "<script", "<link", "<font")   # text fields may not bring their own look


def text_fields(p):
    """Every HTML text fragment in a project.json (top-level strings, step titles and bodies)."""
    yield from (v for v in p.values() if isinstance(v, str))
    for st in p.get("steps", []):
        yield from (v for k, v in st.items() if k != "code" and isinstance(v, str))


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


def image_size(path):
    """(width, height) of a .jpg or .png, or None."""
    d = path.read_bytes()
    if d[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", d[16:24])
    i = 2
    while d[:2] == b"\xff\xd8" and i + 9 < len(d):
        if d[i] != 0xFF:
            i += 1
            continue
        m = d[i + 1]
        if m in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", d[i + 5:i + 9])
            return w, h
        i += 2 + struct.unpack(">H", d[i + 2:i + 4])[0]
    return None


def image_aspect(path):
    """Width / height of a .jpg or .png, or None."""
    wh = image_size(path)
    return wh[0] / wh[1] if wh else None


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
        assert p.get("cover") == "cover.jpg" and (f.parent / "cover.jpg").exists(), \
            f"{f}: every project needs \"cover\": \"cover.jpg\" and the file next to project.json (it is the record sleeve)"
        assert not p.get("frozen") or p["slug"] in FROZEN_OK, \
            f"{f}: new projects can't be frozen; they use the standard case-study format"
        bad = [t for t in OWN_STYLING for v in text_fields(p) if t in v.lower()]
        assert not bad, f"{f}: text fields can't carry their own styling or scripts ({', '.join(sorted(set(bad)))}); theme.css sets the look"
        if not p["loops"]:
            print(f"warning: {p['slug']} has no motion tile yet (loop.mp4/loop.webm); every project should get one, see CLAUDE.md")
        projects.append(p)
    # newest first; "order" breaks ties / pins
    return sorted(projects, key=lambda p: (p["date"], -p.get("order", 0)), reverse=True)


# ---- text contrast ------------------------------------------------------------------------------------------
# Readable text must clear WCAG AA (4.5:1) on the paper. theme.css keeps --faint, --wood and --accent for decorative marks;
# a case-study footer shipped in --faint at 1.95:1, so the build refuses page CSS that sets a text `color:` to any token
# under 4.5:1 against --paper. (--paper itself is allowed: it is the text colour on --deep buttons. ::marker is decoration.)
def contrast(a, b):
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def low_contrast_text():
    css = (ROOT / "theme.css").read_text()
    tokens = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})\b", css))
    aliases = dict(re.findall(r"--([\w-]+):\s*var\(--([\w-]+)\)", css))     # semantic -> primitive chains

    def resolve(tok, depth=0):
        return tokens.get(tok) if tok in tokens or depth > 8 else resolve(aliases.get(tok, ""), depth + 1)
    paper = resolve("paper")
    bad = []
    for name in ("site.css",):   # portfolio.css (the fog environment) is checked from computed styles by tests/portfolio-check.cjs
        for sel, decls in re.findall(r"([^{}]+)\{([^{}]*)\}", (ROOT / name).read_text()):
            if "::marker" in sel:
                continue
            for tok in re.findall(r"(?<![-\w])color:\s*var\(--([\w-]+)\)", decls):
                hexv = resolve(tok)
                if hexv and tok not in ("paper", "s-canvas", "s-text-inverse", "p-color-white") and contrast(hexv, paper) < 4.5:
                    bad.append(f"{name}: {sel.strip()[-60:]} uses --{tok} ({contrast(hexv, paper):.2f}:1)")
    return bad


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
<link rel="stylesheet" href="../theme.css?v={asset_version("theme.css")}">
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
    body = f"""<header class="bar cap"><a href="{PORTFOLIO}">Rishit Mathur</a><nav><a href="../">Portfolio</a><a href="../#projects">All projects</a><a href="{PORTFOLIO}resume.pdf">Resume</a></nav></header>
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


def demo_url(p):
    d = p.get("demo")
    return d if not d or d.startswith("http") else f'{p["slug"]}/{d}'


def index_page(projects):
    """The portfolio (index.template.html + portfolio.css + portfolio.js + scene.js): one continuous page. build.py fills the
    flagship chapters from featured.json (four slugs with a hand-written headline / problem / contribution / result / caption
    each, numbers from that project's case study), the complete catalogue as static links, the kind filter, and the data the
    detail dialog reads. Scene chapters are the elements carrying data-scene, in document order (scene.js reads them)."""
    by_slug = {p["slug"]: p for p in projects}
    order = {p["slug"]: i + 1 for i, p in enumerate(projects)}
    feats = []
    for i, f in enumerate(json.loads((ROOT / "featured.json").read_text()), 1):
        p = by_slug[f["slug"]]
        links = [f'<a href="{p["slug"]}/">Case study</a>', f'<a href="{escape(p["repo"])}" target="_blank" rel="noopener">Code</a>']
        if p.get("demo"):
            links.append(f'<a href="{escape(demo_url(p))}">{escape(p.get("demo_label", "Demo"))}</a>')
        tools = "".join(f"<li>{escape(t)}</li>" for t in p["tech"][:5])
        w, h = image_size(ROOT / p["slug"] / p["cover"])
        cover = f'{p["slug"]}/{p["cover"]}'
        feats.append(
            f'<article class="feature chapter" id="feature-{p["slug"]}" data-scene="feature" data-slug="{p["slug"]}" data-cover="{cover}" '
            f'data-title="{escape(p["title"], quote=True)}" data-area="{escape(f["area"], quote=True)}" data-date="{escape(p["date"], quote=True)}" data-no="{i:02d}">'
            f'<div class="plate copy feature-copy"><p class="hud-line cap"><span class="no">Portfolio_{i:02d}</span><span>{escape(f["area"])} · {escape(p["date"])}</span></p>'
            f'<h3><a href="{p["slug"]}/">{escape(p["title"])}</a></h3><p class="headline">{escape(f["headline"])}</p>'
            f'<dl class="facts"><dt>Problem</dt><dd>{f["problem"]}</dd><dt>What I did</dt><dd>{f["contribution"]}</dd><dt>Result</dt><dd>{f["result"]}</dd></dl>'
            f'<ul class="tools" aria-label="Tools">{tools}</ul><p class="links">{"".join(links)}</p></div>'
            f'<figure class="feature-figure"><a class="inspect" href="{cover}" data-inspect="{p["slug"]}" aria-label="Enlarge screenshot of {escape(p["title"], quote=True)}">'
            f'<img src="{cover}" alt="" width="{w}" height="{h}" loading="lazy" decoding="async"><span class="inspect-label cap" aria-hidden="true">Enlarge screenshot</span></a>'
            f'<figcaption>{escape(f["caption"])}</figcaption></figure></article>')
    heads = Counter(p["kind"].split("\u00b7")[0].strip() for p in projects)
    tiles = []
    for p in projects:
        head = p["kind"].split("\u00b7")[0].strip()
        search = escape(" ".join([p["title"], p["kind"], *p["tech"]]).lower(), quote=True)
        tiles.append(f'<li class="tile" data-slug="{p["slug"]}" data-kind="{escape(head, quote=True)}" data-search="{search}">'
                     f'<a class="tile-link" href="{p["slug"]}/"><span class="tile-no cap">{order[p["slug"]]:03d}</span>'
                     f'<span class="tile-title">{escape(p["title"])}</span><span class="tile-kind cap">{escape(p["kind"])}</span></a></li>')
    keys = ("slug", "title", "kind", "date", "cover", "tagline", "tech", "repo", "demo", "demo_label")
    data = [{k: p.get(k) for k in keys if p.get(k) is not None} for p in projects]
    captions = {f["slug"]: f["caption"] for f in json.loads((ROOT / "featured.json").read_text())}
    for d in data:
        if d["slug"] in captions:
            d["caption"] = captions[d["slug"]]
            d["size"] = list(image_size(ROOT / d["slug"] / d["cover"]))
    kinds = ", ".join(escape(k) for k, _ in heads.most_common(5))
    options = "".join(f'<option value="{escape(k, quote=True)}">{escape(k)} ({n})</option>' for k, n in heads.most_common())
    tpl = (ROOT / "index.template.html").read_text()
    assert "{{FEATURED}}" in tpl and "{{CATALOG}}" in tpl and "/*DATA*/[]" in tpl
    return (tpl.replace("{{FEATURED}}", "".join(feats)).replace("{{CATALOG}}", "".join(tiles))
               .replace("/*DATA*/[]", json.dumps(data).replace("</", "<\\/"))
               .replace("{{COUNT}}", str(len(projects))).replace("{{KINDS_OPTIONS}}", options).replace("{{KINDS}}", kinds)
               .replace("{{THEME}}", asset_version("theme.css")).replace("{{PORTFOLIO_CSS}}", asset_version("portfolio.css"))
               .replace("{{PORTFOLIO_JS}}", asset_version("portfolio.js")).replace("{{SCENE_JS}}", asset_version("scene.js")))


if __name__ == "__main__":
    bad = low_contrast_text()
    assert not bad, "text under 4.5:1 on the paper (use --muted or darker; see theme.css):\n  " + "\n  ".join(bad)
    projects = load()
    for i, p in enumerate(projects):
        if p.get("frozen"):   # page kept exactly as published; its old style.css stays too
            continue
        (ROOT / p["slug"] / "index.html").write_text(project_page(p, projects[(i + 1) % len(projects)]))
    (ROOT / "index.html").write_text(index_page(projects))
    nfrozen = sum(bool(p.get("frozen")) for p in projects)
    print(f"built {len(projects) - nfrozen} project pages (+{nfrozen} frozen) + index.html")
