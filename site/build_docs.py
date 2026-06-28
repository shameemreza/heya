"""Build the docs site.

Reads the markdown guides in docs/guide/ and writes styled HTML pages into
site/docs/, wrapped in the same look as the landing page. The markdown stays the
single source of truth; this runs at deploy time, so editing a guide updates the
site with no duplicate content. Run it locally to preview:

    python site/build_docs.py
    cd site && python3 -m http.server 8080   # open /docs/
"""
import json
from html.parser import HTMLParser
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "guide"
OUT = ROOT / "site" / "docs"

# Slug (the markdown file name), nav title, and a one-line description for the
# docs index cards.
PAGES = [
    ("getting-started", "Getting started", "Install, point it at a model, first runs."),
    ("commands", "Commands and usage", "Slash commands, CLI flags, and how to run it."),
    ("configuration", "Configuration", "Every config block: profiles, workspace, context."),
    ("diagnostic-workflow", "Diagnostic workflow", "Reproduce, diagnose, remediate, triage."),
    ("mcp", "Connect MCP servers", "Add your own tools over stdio or http."),
    ("hosting-claude-ecosystem", "Host your Claude skills", "Use your skills, plugins, and sub-agents."),
    ("tools-and-safety", "Tools and safety", "What runs, what asks first, what is off by default."),
]

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} - Heya docs</title>
<link rel="icon" href="../assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="../styles.css">
<link rel="stylesheet" href="../docs.css">
</head>
<body class="docs-body">
<header class="topbar">
  <a class="brand" href="../index.html" aria-label="Heya home"><span class="brand-he">heya</span><span class="brand-cursor" aria-hidden="true">_</span></a>
  <nav class="nav" aria-label="Primary">
    <a href="../index.html">Home</a>
    <a href="index.html">Docs</a>
    <a class="nav-ext" href="https://github.com/shameemreza/heya">GitHub</a>
  </nav>
</header>
<div class="docs-layout">
  <aside class="docs-side">
    <input type="search" class="docs-search" id="docs-search" placeholder="Search docs" aria-label="Search docs" autocomplete="off">
    <ul class="search-results" id="search-results" hidden></ul>
    <nav class="docs-nav" aria-label="Documentation">{nav}</nav>
  </aside>
  <main class="docs-content">{content}</main>
</div>
<footer class="footer">
  <p class="foot-by">Built by <a href="https://shameemreza.com">Shameem Reza</a>.</p>
</footer>
<script src="../docs.js" defer></script>
</body>
</html>
"""


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def strip_text(html):
    p = _Text()
    p.feed(html)
    return " ".join(" ".join(p.parts).split())


def nav_html(active):
    rows = []
    for slug, title, _desc in PAGES:
        cls = ' class="is-active"' if slug == active else ""
        rows.append(f'<li><a href="{slug}.html"{cls}>{title}</a></li>')
    return "<ul>" + "".join(rows) + "</ul>"


def render(md_text):
    md = markdown.Markdown(
        extensions=["fenced_code", "codehilite", "tables", "toc", "sane_lists"],
        extension_configs={"codehilite": {"guess_lang": False}})
    html = md.convert(md_text)
    # Links between guides are written as `name.md`; point them at the built pages.
    return html.replace('.md"', '.html"')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    built = []
    search_index = []
    for slug, title, desc in PAGES:
        src = SRC / f"{slug}.md"
        if not src.exists():
            continue
        body = render(src.read_text())
        (OUT / f"{slug}.html").write_text(
            PAGE.format(title=title, nav=nav_html(slug), content=body))
        built.append((slug, title, desc))
        search_index.append({
            "url": f"{slug}.html",
            "title": title,
            "text": strip_text(body)[:6000],
        })

    cards = "".join(
        f'<a class="doc" href="{slug}.html"><span class="doc-t">{title}</span>'
        f'<span class="doc-d">{desc}</span></a>'
        for slug, title, desc in built)
    index = (
        '<h1>Documentation</h1>'
        '<p class="docs-intro">Everything you need to install Heya, point it at a '
        'model, and put it to work.</p>'
        f'<div class="doc-grid">{cards}</div>')
    (OUT / "index.html").write_text(
        PAGE.format(title="Documentation", nav=nav_html(None), content=index))

    (OUT / "search-index.json").write_text(json.dumps(search_index, ensure_ascii=False))

    print(f"built {len(built)} guides + index + search into {OUT}")


if __name__ == "__main__":
    main()
