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
        projects.append(p)
    # newest first; "order" breaks ties / pins
    return sorted(projects, key=lambda p: (p["date"], -p.get("order", 0)), reverse=True)


def page(title, desc, body, css="style.css"):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{escape(desc)}">
<title>{escape(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Urbanist:wght@300;400;500;600;700&display=swap">
<link rel="stylesheet" href="{css}">
</head>
<body>
<div class="wrap">
{body}
<footer>&copy; 2026 Rishit Raj Mathur &middot; <a href="{PORTFOLIO}">mrrishit909.github.io</a></footer>
</div>
</body>
</html>
"""


def pills(items):
    return "".join(f'<span class="pill">{escape(t)}</span>' for t in items)


def links(p, prefix=""):
    out = [f'<a class="btn" href="{escape(p["repo"])}" target="_blank" rel="noopener">Code on GitHub</a>']
    if p.get("demo"):
        href = p["demo"] if "://" in p["demo"] else prefix + p["demo"]
        out.insert(0, f'<a class="btn primary" href="{escape(href)}">{escape(p.get("demo_label", "See it"))}</a>')
    return "".join(out)


def project_page(p):
    steps = []
    for i, s in enumerate(p["steps"], 1):
        code = f'<pre><code>{escape(s["code"])}</code></pre>' if s.get("code") else ""
        steps.append(f'<li><div class="n">{i}</div><div><h3>{escape(s["title"])}</h3>{s["body"]}{code}</div></li>')
    note = f'<p class="note">{p["note"]}</p>' if p.get("note") else ""
    body = f"""<nav class="crumbs"><a href="../">&larr; All projects</a><a href="{PORTFOLIO}">Portfolio</a></nav>
<header class="card head-card">
  <span class="kind">{escape(p["kind"])}</span>
  <h1>{escape(p["title"])}</h1>
  <p class="tagline">{escape(p["tagline"])}</p>
  <div class="pills">{pills(p["tech"])}</div>
  <div class="actions">{links(p)}</div>
  {note}
</header>
<section class="card"><h2>The problem</h2>{p["problem"]}</section>
<section class="card"><h2>What I built</h2>{p["built"]}</section>
<section class="card"><h2>How it was built, step by step</h2><ol class="steps">{"".join(steps)}</ol></section>
<section class="card"><h2>Results</h2>{p["results"]}</section>
<section class="card"><h2>What I'd do next</h2>{p["next"]}</section>"""
    return page(f'{p["title"]} · Rishit Mathur', p["tagline"], body, css="../style.css")


def index_page(projects):
    cards = "".join(
        f"""<a class="card proj" href="{p["slug"]}/">
  <span class="kind">{escape(p["kind"])}</span>
  <h2>{escape(p["title"])}</h2>
  <p>{escape(p["tagline"])}</p>
  <div class="pills">{pills(p["tech"][:5])}</div>
  <span class="more">{len(p["steps"])} build steps &rarr;</span>
</a>"""
        for p in projects
    )
    body = f"""<nav class="crumbs"><a href="{PORTFOLIO}">&larr; Portfolio</a></nav>
<header class="intro">
  <h1>Projects</h1>
  <p>Analyst projects I built end to end, each with the full build log: the problem, every step and why, and what came out.</p>
</header>
<main class="grid">{cards}</main>"""
    return page("Projects · Rishit Mathur", "Analyst projects by Rishit Raj Mathur, with step-by-step build logs.", body)


if __name__ == "__main__":
    projects = load()
    for p in projects:
        (ROOT / p["slug"] / "index.html").write_text(project_page(p))
    (ROOT / "index.html").write_text(index_page(projects))
    print(f"built {len(projects)} project pages + index.html")
