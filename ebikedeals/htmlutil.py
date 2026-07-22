"""Minimal DOM built on the stdlib HTML parser.

The project deliberately avoids BeautifulSoup/lxml so it runs on a bare Python
install. This gives us the ~5% of a DOM API the adapters actually need:
find elements by tag/class/attribute, read attributes, read text.
"""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

# Tags whose content is never markup - the parser must not try to nest into them.
RAW_TAGS = {"script", "style"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent", "data")

    def __init__(self, tag: str, attrs: dict[str, str] | None = None, parent: "Node | None" = None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list[Node] = []
        self.parent = parent
        self.data = ""  # only set for text nodes (tag == "#text")

    # -- attribute access -------------------------------------------------
    def get(self, name: str, default: str = "") -> str:
        return self.attrs.get(name, default)

    @property
    def classes(self) -> list[str]:
        return self.attrs.get("class", "").split()

    def has_class(self, name: str) -> bool:
        return name in self.classes

    # -- text -------------------------------------------------------------
    @property
    def text(self) -> str:
        """Whitespace-collapsed text of this subtree, scripts/styles excluded."""
        out: list[str] = []
        self._collect_text(out)
        return re.sub(r"\s+", " ", "".join(out)).strip()

    def _collect_text(self, out: list[str]) -> None:
        if self.tag == "#text":
            out.append(self.data)
            return
        if self.tag in RAW_TAGS:
            return
        for c in self.children:
            c._collect_text(out)

    @property
    def own_text(self) -> str:
        """Text of direct text children only - ignores nested elements.

        Shopware renders the sale price as a bare text node next to the
        <span class="list-price"> element, so this distinction matters.
        """
        parts = [c.data for c in self.children if c.tag == "#text"]
        return re.sub(r"\s+", " ", "".join(parts)).strip()

    # -- traversal --------------------------------------------------------
    def walk(self):
        yield self
        for c in self.children:
            if c.tag != "#text":
                yield from c.walk()

    def find_all(
        self,
        tag: str | None = None,
        cls: str | None = None,
        attrs: dict[str, str] | None = None,
        limit: int | None = None,
    ) -> list["Node"]:
        found: list[Node] = []
        for node in self.walk():
            if node is self:
                continue
            if tag and node.tag != tag:
                continue
            if cls and not node.has_class(cls):
                continue
            if attrs and any(node.get(k) != v for k, v in attrs.items()):
                continue
            found.append(node)
            if limit and len(found) >= limit:
                break
        return found

    def find(self, tag=None, cls=None, attrs=None) -> "Node | None":
        hits = self.find_all(tag=tag, cls=cls, attrs=attrs, limit=1)
        return hits[0] if hits else None

    def find_by_class_prefix(self, prefix: str) -> list["Node"]:
        return [n for n in self.walk() if n is not self and any(c.startswith(prefix) for c in n.classes)]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Node {self.tag} class={self.attrs.get('class', '')!r}>"


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v or "") for k, v in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, {k: (v or "") for k, v in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag):
        # Close the innermost matching tag; tolerate unbalanced markup.
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if data.strip():
            node = Node("#text", parent=self.stack[-1])
            node.data = data
            self.stack[-1].children.append(node)


def parse(html: str) -> Node:
    """Parse an HTML document into a Node tree."""
    builder = _TreeBuilder()
    try:
        builder.feed(html)
    except Exception:
        # Malformed markup: keep whatever was parsed so far rather than failing
        # the whole shop.
        pass
    return builder.root


def strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def script_blocks(html: str, type_attr: str | None = None) -> list[str]:
    """Return the bodies of <script> tags, optionally filtered by type."""
    out = []
    for m in re.finditer(r"<script([^>]*)>(.*?)</script>", html, re.S | re.I):
        if type_attr and type_attr not in m.group(1):
            continue
        out.append(m.group(2))
    return out
