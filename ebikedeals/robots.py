"""robots.txt handling.

Python's urllib.robotparser is not usable here: several shops answer 403 to it,
and it then reports "everything disallowed" - which looks exactly like a real
policy and would silently drop shops for the wrong reason. So we fetch through
the normal Fetcher and implement Google's matching rules ourselves:

* longest matching path wins
* on equal length, Allow beats Disallow
* '*' matches any sequence, '$' anchors the end
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass
class Rule:
    allow: bool
    pattern: str
    regex: re.Pattern


@dataclass
class Verdict:
    allowed: bool
    reason: str
    fetched: bool  # False when robots.txt could not be read at all


def _compile(path: str) -> re.Pattern:
    out = ["^"]
    for ch in path:
        if ch == "*":
            out.append(".*")
        elif ch == "$":
            out.append("$")
        else:
            out.append(re.escape(ch))
    return re.compile("".join(out))


def parse_robots(text: str) -> dict[str, list[Rule]]:
    """Return {user-agent: [Rule, ...]} with grouped consecutive UA lines."""
    groups: dict[str, list[Rule]] = {}
    current: list[str] = []
    expecting_ua = True

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()

        if field == "user-agent":
            if not expecting_ua:
                current = []
                expecting_ua = True
            current.append(value.lower())
            groups.setdefault(value.lower(), [])
        elif field in ("allow", "disallow"):
            expecting_ua = False
            if not current or not value:
                # 'Disallow:' with an empty value means "allow everything";
                # it adds no constraint.
                continue
            rule = Rule(field == "allow", value, _compile(value))
            for ua in current:
                groups.setdefault(ua, []).append(rule)
    return groups


def evaluate(robots_text: str, url: str, agent: str = "*") -> Verdict:
    groups = parse_robots(robots_text)
    agent = agent.lower()
    rules = groups.get(agent)
    matched_agent = agent
    if rules is None:
        rules = groups.get("*", [])
        matched_agent = "*"
    if not rules:
        return Verdict(True, "keine passende Regel", True)

    path = urlsplit(url).path or "/"
    if urlsplit(url).query:
        path += "?" + urlsplit(url).query

    best: Rule | None = None
    for rule in rules:
        if rule.regex.match(path):
            if best is None or len(rule.pattern) > len(best.pattern) or (
                len(rule.pattern) == len(best.pattern) and rule.allow and not best.allow
            ):
                best = rule
    if best is None:
        return Verdict(True, "keine passende Regel", True)
    verb = "Allow" if best.allow else "Disallow"
    return Verdict(best.allow, f"{verb}: {best.pattern} (User-agent: {matched_agent})", True)


class RobotsCache:
    """Fetches and caches robots.txt per host through the shared Fetcher."""

    def __init__(self, fetcher):
        self.fetcher = fetcher
        self._cache: dict[str, str | None] = {}

    def check(self, url: str, agent: str = "*") -> Verdict:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._cache:
            try:
                self._cache[origin] = self.fetcher.get(f"{origin}/robots.txt")
            except Exception:
                self._cache[origin] = None
        text = self._cache[origin]
        if text is None:
            # Unreadable robots.txt is not a prohibition - say so explicitly
            # rather than inventing a policy either way.
            return Verdict(True, "robots.txt nicht lesbar", False)
        return evaluate(text, url, agent)
