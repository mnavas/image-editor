#!/usr/bin/env python3
"""Render every docs/*.md into a styled, standalone *.html (matching the landing
page) so GitHub Pages shows formatted docs instead of raw Markdown.

The .md files stay the source of truth (GitHub renders them itself); these .html
are for the Pages site. Intra-doc links to `*.md` are rewritten to `*.html`.

Usage:  .venv/bin/python docs/build_docs.py       (needs the `markdown` package)
"""
from __future__ import annotations

import re
from pathlib import Path

import markdown

DOCS = Path(__file__).resolve().parent

# order for the in-page docs nav
NAV = [
    ("index.html", "Home", "../index.html"),
    ("user-guide.html", "User Guide", "user-guide.html"),
    ("pro-guide.html", "Pro Guide", "pro-guide.html"),
    ("installation.html", "Install", "installation.html"),
    ("architecture.html", "Architecture", "architecture.html"),
    ("analysis.html", "Analysis", "analysis.html"),
    ("plan.html", "Plan", "plan.html"),
    ("changelog.html", "Changelog", "changelog.html"),
]

STYLE = """
:root{--violet:#7C5CFC;--violet-dark:#5B3EE8;--violet-pale:#F3F0FF;--ink:#2A2833;--muted:#56545F;--line:#E6E5EA;--bg:#FFFFFF;--code:#0D1117}
*{box-sizing:border-box}
body{margin:0;font-family:'Inter',-apple-system,Segoe UI,Roboto,sans-serif;color:var(--ink);background:var(--bg);line-height:1.7}
.topbar{position:sticky;top:0;z-index:10;background:rgba(255,255,255,.95);backdrop-filter:blur(8px);border-bottom:1px solid var(--line);padding:.7rem 1.25rem;display:flex;gap:1rem;align-items:center;flex-wrap:wrap}
.topbar .brand{font-weight:700;color:var(--violet);text-decoration:none;margin-right:.5rem}
.topbar a{font-size:.85rem;color:var(--muted);text-decoration:none}
.topbar a:hover{color:var(--violet)}
.topbar a.active{color:var(--violet);font-weight:600}
main{max-width:820px;margin:0 auto;padding:2.5rem 1.25rem 5rem}
h1,h2,h3,h4{line-height:1.25;color:#17161E;margin:1.8em 0 .6em}
h1{font-size:2rem;margin-top:.2em}h2{font-size:1.5rem;padding-bottom:.3rem;border-bottom:1px solid var(--line)}h3{font-size:1.15rem}
p,li{color:#33313c}
a{color:var(--violet-dark)}
code{background:var(--violet-pale);color:#3a2b8c;padding:.12em .4em;border-radius:5px;font-family:'JetBrains Mono',ui-monospace,monospace;font-size:.9em}
pre{background:var(--code);color:#E6EDF3;padding:1.1rem 1.25rem;border-radius:10px;overflow-x:auto;font-size:.85rem;line-height:1.6}
pre code{background:none;color:inherit;padding:0}
blockquote{margin:1.2em 0;padding:.4em 1.1em;border-left:4px solid var(--violet);background:var(--violet-pale);border-radius:0 8px 8px 0;color:var(--muted)}
table{border-collapse:collapse;width:100%;margin:1.2em 0;font-size:.92rem;display:block;overflow-x:auto}
th,td{border:1px solid var(--line);padding:.5rem .75rem;text-align:left}
th{background:var(--violet-pale)}
hr{border:none;border-top:1px solid var(--line);margin:2.2em 0}
img{max-width:100%}
"""

HEAD = """<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — image-editor</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{style}</style></head><body>
<div class="topbar"><a class="brand" href="../index.html">🎨 image-editor</a>{nav}</div>
<main>{body}</main></body></html>"""


def build():
    md = markdown.Markdown(extensions=["extra", "tables", "fenced_code", "toc", "sane_lists"])
    made = []
    for src in sorted(DOCS.glob("*.md")):
        html_name = src.stem + ".html"
        md.reset()
        body = md.convert(src.read_text())
        # keep intra-doc navigation formatted: point .md links at the .html twins
        body = re.sub(r'href="([^"]+)\.md(#[^"]*)?"', r'href="\1.html\2"', body)
        nav = "".join(
            f'<a href="{href}"{" class=\"active\" " if name==html_name else ""}>{label}</a>'
            for name, label, href in NAV
        )
        out = HEAD.format(title=src.stem.replace("-", " ").title(), style=STYLE, nav=nav, body=body)
        (DOCS / html_name).write_text(out)
        made.append(html_name)
    print("built:", ", ".join(made))


if __name__ == "__main__":
    build()
