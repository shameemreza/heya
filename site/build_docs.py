"""Build the docs site.

Reads the markdown guides in docs/guide/ and writes styled HTML pages into
site/docs/, wrapped in the same look as the landing page. The markdown stays the
single source of truth; this runs at deploy time, so editing a guide updates the
site with no duplicate content. Run it locally to preview:

    python site/build_docs.py
    cd site && python3 -m http.server 8080   # open /docs/
"""
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "guide"
OUT = ROOT / "site" / "docs"

# Order and display titles for the nav. Slug is the markdown file name.
PAGES = [
    ("getting-started", "Getting started"),
    ("configuration", "Configuration"),
    ("diagnostic-workflow", "Diagnostic workflow"),
    ("mcp", "Connect MCP servers"),
    ("hosting-claude-ecosystem", "Host your Claude skills"),
    ("tools-and-safety", "Tools and safety"),
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
    <nav aria-label="Documentation">{nav}</nav>
  </aside>
  <main class="docs-content">{content}</main>
</div>
<footer class="footer">
  <p class="foot-by">Built by <a href="https://shameemreza.com">Shameem Reza</a>.</p>
</footer>
</body>
</html>
"""


def nav_html(active):
    rows = []
    for slug, title in PAGES:
        cls = ' class="is-active"' if slug == active else ""
        rows.append(f'<li><a href="{slug}.html"{cls}>{title}</a></li>')
    return "<ul>" + "".join(rows) + "</ul>"


def render(md_text):
    md = markdown.Markdown(extensions=["fenced_code", "tables", "toc", "sane_lists"])
    html = md.convert(md_text)
    # Links between guides are written as `name.md`; point them at the built pages.
    return html.replace('.md"', '.html"')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for slug, title in PAGES:
        src = SRC / f"{slug}.md"
        if not src.exists():
            continue
        body = render(src.read_text())
        (OUT / f"{slug}.html").write_text(
            PAGE.format(title=title, nav=nav_html(slug), content=body))

    cards = "".join(
        f'<a class="doc" href="{slug}.html"><span class="doc-t">{title}</span></a>'
        for slug, title in PAGES)
    index = (
        '<h1>Documentation</h1>'
        '<p class="docs-intro">Everything you need to install Heya, point it at a '
        'model, and put it to work.</p>'
        f'<div class="doc-grid">{cards}</div>')
    (OUT / "index.html").write_text(
        PAGE.format(title="Documentation", nav=nav_html(None), content=index))

    print(f"built {len(PAGES)} guides + index into {OUT}")


if __name__ == "__main__":
    main()
