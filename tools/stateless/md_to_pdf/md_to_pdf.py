#!/usr/bin/env python3
"""Convert a Markdown file to a clean print-ready PDF using WeasyPrint."""

import argparse
import json
import os
import sys

# Accommodate user-local install when not on system path
sys.path.insert(0, os.path.expanduser("~/.local/lib/python3.12/site-packages"))

import re
import html


CSS = """
@page {
    size: letter;
    margin: 1in 1.1in 1in 1.1in;
}

body {
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 11pt;
    line-height: 1.65;
    color: #1a1a1a;
    max-width: 100%;
}

h1 {
    font-size: 20pt;
    font-weight: bold;
    text-align: center;
    margin-top: 0;
    margin-bottom: 4pt;
    color: #1a1a1a;
}

h2 {
    font-size: 14pt;
    font-weight: bold;
    text-align: center;
    margin-top: 0;
    margin-bottom: 18pt;
    color: #444;
}

h3 {
    font-size: 12pt;
    font-weight: bold;
    margin-top: 18pt;
    margin-bottom: 4pt;
    color: #1a1a1a;
}

h4 {
    font-size: 11pt;
    font-weight: bold;
    margin-top: 14pt;
    margin-bottom: 2pt;
    color: #1a1a1a;
}

p {
    margin-top: 0;
    margin-bottom: 9pt;
}

em {
    font-style: italic;
}

strong {
    font-weight: bold;
}

blockquote, .scripture {
    margin: 10pt 0 10pt 18pt;
    padding-left: 12pt;
    border-left: 3px solid #bbb;
    font-style: italic;
    color: #333;
}

hr {
    border: none;
    border-top: 1px solid #ccc;
    margin: 16pt 0;
}

ul, ol {
    margin-top: 6pt;
    margin-bottom: 6pt;
    padding-left: 24pt;
}

li {
    margin-bottom: 4pt;
}
"""


def md_to_html(text: str) -> str:
    """Minimal Markdown to HTML converter for the subset used in CMFF docs."""
    lines = text.split("\n")
    html_lines = []
    in_ul = False

    for line in lines:
        # Headings
        if line.startswith("#### "):
            if in_ul:
                html_lines.append("</ul>"); in_ul = False
            html_lines.append(f"<h4>{inline(line[5:])}</h4>")
        elif line.startswith("### "):
            if in_ul:
                html_lines.append("</ul>"); in_ul = False
            html_lines.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("## "):
            if in_ul:
                html_lines.append("</ul>"); in_ul = False
            html_lines.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("# "):
            if in_ul:
                html_lines.append("</ul>"); in_ul = False
            html_lines.append(f"<h1>{inline(line[2:])}</h1>")
        # HR
        elif line.strip() == "---":
            if in_ul:
                html_lines.append("</ul>"); in_ul = False
            html_lines.append("<hr>")
        # Bullet list
        elif line.startswith("- "):
            if not in_ul:
                html_lines.append("<ul>"); in_ul = True
            html_lines.append(f"<li>{inline(line[2:])}</li>")
        # Block quote / italic-only line (scripture quotes)
        elif line.startswith("*") and line.endswith("*") and line.count("*") == 2:
            if in_ul:
                html_lines.append("</ul>"); in_ul = False
            inner = line[1:-1]
            html_lines.append(f'<blockquote>{inline(inner)}</blockquote>')
        # Empty line
        elif line.strip() == "":
            if in_ul:
                html_lines.append("</ul>"); in_ul = False
            html_lines.append("")
        # Normal paragraph
        else:
            if in_ul:
                html_lines.append("</ul>"); in_ul = False
            html_lines.append(f"<p>{inline(line)}</p>")

    if in_ul:
        html_lines.append("</ul>")

    # Wrap consecutive <p> blocks that are blank into nothing
    result = "\n".join(html_lines)
    # Collapse multiple blank lines
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result


def inline(text: str) -> str:
    """Convert inline markdown (bold, italic, escapes) to HTML."""
    # Escape HTML entities first
    text = html.escape(text)
    # Bold+italic ***text***
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", text)
    # Bold **text**
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic *text* (not at line boundaries handled by caller)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    # Em dash
    text = text.replace("—", "—")
    return text


def convert(md_path: str, out_path: str | None = None) -> str:
    from weasyprint import HTML, CSS as WeasyCss

    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    body_html = md_to_html(md_text)
    full_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{CSS}</style></head>
<body>{body_html}</body></html>"""

    if out_path is None:
        base = os.path.splitext(md_path)[0]
        out_path = base + ".pdf"

    HTML(string=full_html, base_url=os.path.dirname(os.path.abspath(md_path))).write_pdf(
        out_path, stylesheets=[WeasyCss(string=CSS)]
    )
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a Markdown file to PDF")
    parser.add_argument("input", help="Path to the .md file")
    parser.add_argument("-o", "--output", help="Output PDF path (default: same dir, .pdf extension)")
    args = parser.parse_args()

    try:
        out = convert(args.input, args.output)
        print(json.dumps({"ok": True, "pdf": out}))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
