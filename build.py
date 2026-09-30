"""Build the projects site: every <slug>/project.json -> <slug>/index.html, plus the root index.html.

    python3 build.py

Text fields in project.json are trusted HTML fragments (we write them ourselves).
Stdlib only, so GitHub never needs to run anything: we commit the built HTML.
"""
import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).parent
PORTFOLIO = "https://mrrishit909.github.io/"
REQUIRED = ["title", "tagline", "kind", "tech", "date", "repo", "problem", "built", "steps", "results", "next"]


def load():
    projects = []
    for f in sorted(ROOT.glob("*/project.json")):
        p = json.loads(f.read_text())
        missing = [k for k in REQUIRED if not p.get(k)]
        assert not missing, f"{f}: missing {missing}"
        assert all(s.get("title") and s.get("body") for s in p["steps"]), f"{f}: every step needs title + body"
        p["slug"] = f.parent.name
        if p.get("cover"):
            assert (f.parent / p["cover"]).exists(), f"{f}: cover {p['cover']} not found"
        projects.append(p)
    # newest first; "order" breaks ties / pins
    return sorted(projects, key=lambda p: (p["date"], -p.get("order", 0)), reverse=True)


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
<link rel="stylesheet" href="../site.css">
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
    sections = [("The problem", p["problem"]), ("What I built", p["built"]),
                ("How it was built", f'<ol class="steps">{"".join(steps)}</ol>'),
                ("Results", p["results"]), ("What I'd do next", p["next"])]
    secs = "".join(f'<section class="s"><h2 class="cap">{n:02d} &mdash; {escape(t)}</h2><div class="body">{b}</div></section>'
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
  <a class="next" href="../{nxt["slug"]}/"><span class="cap">Next project</span><span class="t">{escape(nxt["title"])} &rarr;</span></a>
</main>
<footer class="cap"><span>&copy; 2026 Rishit Raj Mathur</span><a href="https://github.com/mrrishit909">GitHub</a></footer>"""
    return page(f'{p["title"]} · Rishit Mathur', p["tagline"], body)


def index_page(projects):
    """The 3D carousel page (index.template.html). The list of real links is rendered here, so it works without JS."""
    items = '<span class="sep" aria-hidden="true">·</span>'.join(
        f'<a class="item" href="{p["slug"]}/" data-slug="{p["slug"]}">{escape(p["title"])}</a>' for p in projects)
    data = [{k: p.get(k) for k in ("slug", "title", "kind", "date", "cover")} for p in projects]
    tpl = (ROOT / "index.template.html").read_text()
    assert "<!--LIST-->" in tpl and "/*PROJECTS*/[]" in tpl
    # json.dumps output is safe inside <script> once "</" can't appear
    return tpl.replace("<!--LIST-->", items).replace("/*PROJECTS*/[]", json.dumps(data).replace("</", "<\\/"))


if __name__ == "__main__":
    projects = load()
    for i, p in enumerate(projects):
        if p.get("frozen"):   # page kept exactly as published; its old style.css stays too
            continue
        (ROOT / p["slug"] / "index.html").write_text(project_page(p, projects[(i + 1) % len(projects)]))
    (ROOT / "index.html").write_text(index_page(projects))
    print(f"built {sum(not p.get("frozen") for p in projects)} project pages (+{sum(bool(p.get("frozen")) for p in projects)} frozen) + index.html")
