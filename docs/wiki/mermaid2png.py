"""Render the Mermaid diagrams of the wiki drafts to PNG for DokuWiki (it cannot draw Mermaid).

Each ```mermaid block in md/*.md starts with a comment naming its image, ``%% png: crawler``; the
image goes to img/crawler.png and md2dokuwiki.py puts {{user:mario.babiar:crawler.png}} in place of
the block. The same name in two pages is one image. Upload img/*.png to the wiki media manager
(namespace user:mario.babiar).

Run (Playwright and its Chromium only for this script, not in the project):

    uv run --no-project --with playwright==1.55.0 python -m playwright install chromium
    uv run --no-project --with playwright==1.55.0 python docs/wiki/mermaid2png.py
"""

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
MERMAID_JS = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js"
BLOCK = re.compile(r"^```mermaid\n(.*?)^```", re.MULTILINE | re.DOTALL)
NAME = re.compile(r"^\s*%%\s*png:\s*([\w-]+)\s*$", re.MULTILINE)


def diagrams() -> dict[str, str]:
    """Return image name -> Mermaid source of every named block in md/*.md."""
    found: dict[str, str] = {}
    for page in sorted((HERE / "md").glob("*.md")):
        for source in BLOCK.findall(page.read_text(encoding="utf-8")):
            name = NAME.search(source)
            if not name:
                sys.exit(f"{page.name}: a mermaid block without '%% png: <name>'")
            if found.get(name.group(1), source) != source:
                sys.exit(f"{page.name}: '{name.group(1)}' differs from the block of that name")
            found[name.group(1)] = source
    return found


def main() -> None:
    """Render every diagram to img/<name>.png (2x scale, white background)."""
    target = HERE / "img"
    target.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(device_scale_factor=2)
        page.set_content("<body style='margin:0;background:#fff'><div id='out'></div></body>")
        page.add_script_tag(url=MERMAID_JS)
        page.evaluate("mermaid.initialize({startOnLoad: false, theme: 'default'})")

        for name, source in diagrams().items():
            page.evaluate(
                "async s => { const {svg} = await mermaid.render('d', s);"
                " document.getElementById('out').innerHTML = svg; }",
                source,
            )
            page.locator("#out svg").screenshot(path=target / f"{name}.png")
            print(f"img/{name}.png", file=sys.stderr)
        browser.close()


if __name__ == "__main__":
    main()
