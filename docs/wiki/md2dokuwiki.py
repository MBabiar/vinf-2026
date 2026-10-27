"""Convert the wiki drafts in md/ to DokuWiki syntax in dokuwiki/ (python3 md2dokuwiki.py).

md/ is the source; dokuwiki/*.txt is generated, do not edit it by hand. Handles what the drafts use:
headings, tables, lists (with wrapped lines), code blocks, inline code, bold and links. A Mermaid
block (DokuWiki cannot draw it) becomes its PNG from mermaid2png.py:
{{user:mario.babiar:<name>.png}}.
"""

import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
WIKI_PAGE = re.compile(r"^https://vi2026\.ui\.sav\.sk/doku\.php\?id=([^&#\s]+)$")
LINK = re.compile(r"\[([^\]]+)\]\(((?:[^()\s]|\([^()\s]*\))+)\)")  # URL may hold (manga)
LIST_ITEM = re.compile(r"^( *)(-|\d+\.) (.*)$")
SEPARATOR = re.compile(r"^\|(\s*:?-+:?\s*\|)+\s*$")
PNG_NAME = re.compile(r"^\s*%%\s*png:\s*([\w-]+)\s*$")
MEDIA = "user:mario.babiar"


def inline(line: str) -> str:
    """Convert inline Markdown: `code` -> ''%%code%%'', [text](url) -> [[url|text]]; bold stays."""
    parts = line.split("`")
    for i, part in enumerate(parts):
        if i % 2:
            parts[i] = f"''%%{part}%%''"
        else:
            parts[i] = LINK.sub(_link, part)
    return "".join(parts)


def _link(m: re.Match) -> str:
    text, url = m.groups()
    page = WIKI_PAGE.match(url)
    return f"[[{page.group(1) if page else url}|{text}]]"


def png_width(name: str) -> int:
    """Display width of img/<name>.png: half its pixels (rendered at 2x), at most 800."""
    image = HERE / "img" / f"{name}.png"
    if not image.exists():
        sys.exit(f"img/{name}.png missing: run mermaid2png.py first")
    return min(800, int.from_bytes(image.read_bytes()[16:20], "big") // 2)  # PNG IHDR width


def cells(line: str) -> list[str]:
    """Split a Markdown table row into its cells."""
    return [c.strip() for c in line.strip().strip("|").split("|")]


def convert(markdown: str) -> str:
    """Convert one Markdown page to DokuWiki."""
    lines = markdown.splitlines()
    out: list[str] = []
    i = 0
    in_list = False

    while i < len(lines):
        line = lines[i]

        if line.startswith("```mermaid"):
            name = PNG_NAME.match(lines[i + 1])
            if not name:
                sys.exit("a mermaid block without '%% png: <name>' (see mermaid2png.py)")
            out.append(f"{{{{{MEDIA}:{name.group(1)}.png?{png_width(name.group(1))}|}}}}")
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                i += 1
            i += 1
            in_list = False
            continue

        if line.startswith("```"):
            lang = line[3:].strip()
            out.append(f"<code {lang}>" if lang else "<code>")
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                out.append(lines[i])
                i += 1
            out.append("</code>")
            i += 1
            in_list = False
            continue

        heading = re.match(r"^(#{1,5}) (.*)$", line)
        if heading:
            marks = "=" * (7 - len(heading.group(1)))
            out.append(f"{marks} {heading.group(2).strip()} {marks}")
            i += 1
            in_list = False
            continue

        if line.startswith("|"):
            header = i + 1 < len(lines) and SEPARATOR.match(lines[i + 1])
            if SEPARATOR.match(line):
                i += 1
                continue
            sep = "^" if header else "|"
            out.append(sep + sep.join(f" {inline(c)} " for c in cells(line)) + sep)
            i += 1
            in_list = False
            continue

        item = LIST_ITEM.match(line)
        if item:
            indent, marker, text = item.groups()
            depth = len(indent) // 2 + 1
            out.append("  " * depth + ("* " if marker == "-" else "- ") + inline(text))
            in_list = True
            i += 1
            continue

        if in_list and line.startswith(" ") and line.strip():
            out[-1] += " " + inline(line.strip())  # wrapped list item: DokuWiki items are one line
            i += 1
            continue

        in_list = False
        out.append(inline(line))
        i += 1

    return "\n".join(out) + "\n"


def main() -> None:
    """Convert every md/*.md to dokuwiki/<same name>.txt."""
    target = HERE / "dokuwiki"
    target.mkdir(exist_ok=True)
    for source in sorted((HERE / "md").glob("*.md")):
        page = target / f"{source.stem}.txt"
        page.write_text(convert(source.read_text(encoding="utf-8")), encoding="utf-8")
        print(f"{source.relative_to(HERE)} -> {page.relative_to(HERE)}", file=sys.stderr)


if __name__ == "__main__":
    main()
