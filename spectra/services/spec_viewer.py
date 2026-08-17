"""Renders docs/SPECTRA_SPEC.md as a phone-readable page at GET /spectra/spec
(spectra/api/spec.py) — no new server, no new port: `/spectra/*` is already
reachable through spot-effects' reverse proxy at :8000, the address he
actually uses on his phone. He asked for a link three times and got a file
path twice; the spec is ~150KB of dense, table-heavy markdown, useless on a
phone served raw (a wall of text, technically a link, practically not a
deliverable) — so this renders it server-side instead of shipping the .md
verbatim.

Read fresh from disk on every request (`docs/SPECTRA_SPEC.md`, no cache) —
the spec is a living document under its own maintenance protocol, and a
stale cached render defeats the point of "bring the spec current."

Long tables are the hard part at phone width. Every `<table>` is wrapped in
its own `.table-scroll` (`overflow-x: auto`) container instead of forcing
every cell to wrap to viewport width — the same "contain the overflow,
don't force content narrower than it needs to be" shape the device-preview
strip already uses for a wide pixel strip (AGENTS.md's phone-matrix fix).
The PAGE itself never scrolls sideways (`body { overflow-x: hidden }`);
only a table's own container does, matching this task's own instruction and
the device-preview precedent it names.
"""
from __future__ import annotations

import re

import markdown

from spectra import config

SPEC_PATH = config.REPO_ROOT / "docs" / "SPECTRA_SPEC.md"

_TABLE_OPEN = re.compile(r"<table>")
_TABLE_CLOSE = re.compile(r"</table>")

_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>SPECTRA spec</title>
<style>
:root {{
  --bg: #0a0612; --surface: #140d1f; --surface2: #1f1430; --border: #372552;
  --accent: #a855f7; --accent2: #e879f9; --text: #ece7f7; --text-muted: #9585b5;
}}
* {{ box-sizing: border-box; }}
html {{ overflow-x: hidden; }}
body {{
  margin: 0; background: var(--bg); color: var(--text);
  font-family: 'Inter', system-ui, sans-serif; font-size: 15px; line-height: 1.55;
  overflow-x: hidden;
}}
header {{
  position: sticky; top: 0; z-index: 10;
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  background: var(--surface); border-bottom: 1px solid var(--border);
  padding: 10px 16px;
}}
header .logo {{ font-weight: 800; letter-spacing: 0.1em; color: var(--accent); font-size: 15px; }}
header .path {{ color: var(--text-muted); font-size: 12px; font-family: monospace; }}
header a.top {{ margin-left: auto; font-size: 12px; color: var(--text-muted); text-decoration: none; }}
header a.top:hover {{ color: var(--accent); }}
main {{ max-width: 900px; margin: 0 auto; padding: 16px; width: 100%; }}
h1, h2, h3, h4 {{ color: var(--text); line-height: 1.3; scroll-margin-top: 56px; }}
h1 {{ font-size: 22px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }}
h2 {{ font-size: 18px; margin-top: 2em; border-bottom: 1px solid var(--border); padding-bottom: 6px; }}
h3 {{ font-size: 16px; color: var(--accent2); margin-top: 1.6em; }}
h4 {{ font-size: 14px; margin-top: 1.4em; }}
p, li {{ overflow-wrap: break-word; }}
a {{ color: var(--accent); }}
hr {{ border: none; border-top: 1px solid var(--border); margin: 2em 0; }}
blockquote {{
  margin: 1em 0; padding: 8px 14px; border-left: 3px solid var(--accent);
  background: var(--surface); color: var(--text-muted); border-radius: 0 6px 6px 0;
}}
code {{
  background: var(--surface2); border: 1px solid var(--border); border-radius: 4px;
  padding: 1px 5px; font-size: 0.88em; font-family: monospace; overflow-wrap: anywhere;
}}
pre {{
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 12px; overflow-x: auto;
}}
pre code {{ border: none; padding: 0; background: none; }}
.table-scroll {{ overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 1em 0; border-radius: 8px; border: 1px solid var(--border); }}
table {{ border-collapse: collapse; width: max-content; min-width: 100%; }}
th, td {{ border-bottom: 1px solid var(--border); border-right: 1px solid var(--border); padding: 8px 10px; text-align: left; vertical-align: top; }}
th:last-child, td:last-child {{ border-right: none; }}
th {{ background: var(--surface2); white-space: nowrap; position: sticky; top: 0; }}
td {{ max-width: 62ch; }}
tr:last-child td {{ border-bottom: none; }}
.toc {{
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 12px 16px; margin-bottom: 20px; font-size: 13px;
}}
.toc summary {{ cursor: pointer; font-weight: 600; color: var(--accent); }}
.toc ul {{ margin: 10px 0 0; padding-left: 18px; }}
.toc ul ul {{ padding-left: 16px; }}
.toc li {{ margin: 4px 0; }}
.toc a {{ color: var(--text-muted); text-decoration: none; }}
.toc a:hover {{ color: var(--accent); }}
@media (max-width: 720px) {{
  main {{ padding: 12px; }}
  td {{ max-width: 46ch; }}
}}
</style>
</head>
<body>
<header>
  <span class="logo">SPECTRA</span>
  <span class="path">docs/SPECTRA_SPEC.md</span>
  <a class="top" href="#top">&uarr; top</a>
</header>
<main>
<a id="top"></a>
<details class="toc" open>
<summary>Contents</summary>
{toc}
</details>
{body}
</main>
</body>
</html>
"""


def render_spec_html() -> str:
    text = SPEC_PATH.read_text(encoding="utf-8")
    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
        extension_configs={"toc": {"toc_depth": "2-3", "permalink": False}},
    )
    body = md.convert(text)
    body = _TABLE_OPEN.sub('<div class="table-scroll"><table>', body)
    body = _TABLE_CLOSE.sub("</table></div>", body)
    return _PAGE_TEMPLATE.format(toc=md.toc, body=body)
