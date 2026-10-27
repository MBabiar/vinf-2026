"""robots.txt matching per RFC 9309: `*` and `$` wildcards, longest match wins, Allow wins a tie.

Python's urllib.robotparser is not used for Allow/Disallow: on 3.14 it percent-encodes the `&` in
ANN's `Disallow: /encyclopedia/*&lookup=` (no `?` in the rule), so it wrongly allows
`anime.php?id=13&lookup=error`; before 3.14 it has no wildcard support at all.
"""

import contextlib
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass
class Rules:
    """The robots.txt rules that apply to our User-Agent.

    Attributes
    ----------
    rules : list[tuple[bool, re.Pattern[str], int]]
        One entry per Allow/Disallow line: (is Allow, compiled path pattern, path length).
    crawl_delay : float or None
        The Crawl-delay in seconds, if the group sets one.
    disallow_all : bool
        Block every URL (until robots.txt is loaded, or while it answers an error).
    """

    rules: list[tuple[bool, re.Pattern[str], int]] = field(default_factory=list)
    crawl_delay: float | None = None
    disallow_all: bool = False

    def allowed(self, url: str) -> bool:
        """Check a URL against the rules.

        The longest matching rule wins; on a tie, Allow wins. No matching rule means allowed.

        Parameters
        ----------
        url : str
            An absolute URL; only its path and query are matched.

        Returns
        -------
        bool
            True if the URL may be fetched.
        """
        if self.disallow_all:
            return False

        parts = urlsplit(url)
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        if target == "/robots.txt":
            return True

        best_len, best_allow = -1, True
        for allow, pattern, length in self.rules:
            if pattern.match(target) and (
                length > best_len or (length == best_len and allow and not best_allow)
            ):
                best_len, best_allow = length, allow

        return best_allow


def _compile(path: str) -> re.Pattern[str]:
    anchored = path.endswith("$")
    body = path[:-1] if anchored else path
    regex = ".*".join(re.escape(part) for part in body.split("*"))
    return re.compile(regex + ("$" if anchored else ""))


def parse(text: str, product: str) -> Rules:
    """Parse robots.txt and keep the rules for our crawler.

    Uses the group naming our product token, otherwise the `*` group.

    Parameters
    ----------
    text : str
        The robots.txt body.
    product : str
        Our product token (the User-Agent name, matched case-insensitively).

    Returns
    -------
    Rules
        The rules of the chosen group(s); empty if no group applies.
    """
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    lines: list[tuple[str, str]] = []
    in_rules = False

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (s.strip() for s in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if in_rules:
                groups.append((agents, lines))
                agents, lines, in_rules = [], [], False
            agents.append(value.lower())
        elif key in ("allow", "disallow", "crawl-delay") and agents:
            in_rules = True
            lines.append((key, value))

    if agents:
        groups.append((agents, lines))

    token = product.lower()
    chosen = [ls for ags, ls in groups if token in ags] or [ls for ags, ls in groups if "*" in ags]
    rules = Rules()
    for group in chosen:
        for key, value in group:
            if key == "crawl-delay":
                with contextlib.suppress(ValueError):
                    rules.crawl_delay = float(value)
            elif value:  # an empty Disallow allows everything
                rules.rules.append((key == "allow", _compile(value), len(value)))

    return rules
