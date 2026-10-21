"""Sanitising feed markup and extracting articles from pages.

Ported from the Nim reader's scraper. Two things are deliberate:

* The output is sanitised HTML, not text. Paragraphs, headings, lists, code
  blocks and images are what make a long article readable.
* Nothing is trusted. Attributes are allowed rather than denied, `script`,
  `style`, `iframe` and friends never survive, and links that are not http(s)
  are flattened to their text, because this is markup from a stranger's server
  heading for the reader's browser.
"""

from html import escape
from html.parser import HTMLParser

MIN_CONTENT_LENGTH = 200

CONTENT_PATTERNS = (
    "post-content", "entry-content", "article-content",
    "article-body", "article__body", "article__content",
    "story-body", "story-content", "content-body",
    "post-body", "post-entry", "entry-body",
    "blog-content", "blog-post", "wp-content",
    "main-content", "page-content", "body-content",
)
UNWANTED_TAGS = {
    "script", "style", "nav", "header", "footer", "aside", "noscript",
    "iframe", "form", "svg", "button", "input", "textarea", "select",
    "object", "embed", "frame", "frameset", "link", "meta", "base", "template",
    "math", "head", "title",
}
UNWANTED_ROLES = {"complementary", "banner", "contentinfo", "navigation"}
UNWANTED_CLASS_PATTERNS = (
    "comment", "sidebar", "advertisement", "ad-banner",
    "social-share", "share-button", "newsletter", "popup",
    "cookie", "paywall", "related-post", "related-article",
    "taboola", "outbrain", "disqus",
)
# Narrower than the class list: an id of "header" is reliably the page header,
# while a class of "header" is often the article's own.
UNWANTED_ID_PATTERNS = ("comment", "sidebar", "footer", "header", "nav", "disqus")
VOID_ELEMENTS = {
    "br", "hr", "img", "input", "meta", "link", "area", "base", "col",
    "embed", "source", "track", "wbr",
}
ALLOWED_ATTRS = {
    "href", "src", "alt", "title", "class", "id", "width", "height",
    "type", "controls", "preload", "poster", "cite", "datetime",
    "colspan", "rowspan", "loading", "decoding", "itemprop",
    "role", "aria-label", "aria-hidden",
}
IMG_ALLOWED_ATTRS = {"alt", "width", "height", "class"}
# Elements whose content never belongs in the output even as text; the tree
# builder drops it as it parses.
RAW_TEXT = {"script", "style", "noscript", "template"}


class ScrapeError(Exception):
    pass


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict | None = None, parent=None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list = []  # Node or str
        self.parent = parent


# Closing one of these implicitly closes an open <p> (and so on). Enough of
# HTML's optional-end-tag rules to keep sloppy markup from nesting forever.
_IMPLIED_END = {
    "p": {"p"},
    "li": {"li"},
    "dt": {"dt", "dd"},
    "dd": {"dt", "dd"},
    "tr": {"tr", "td", "th"},
    "td": {"td", "th"},
    "th": {"td", "th"},
    "option": {"option"},
}
_BLOCK = {
    "address", "article", "aside", "blockquote", "div", "dl", "fieldset",
    "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header",
    "hr", "main", "nav", "ol", "pre", "section", "table", "ul",
}


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.cur = self.root
        self.skip = 0

    def _close_to(self, tags: set[str]):
        n = self.cur
        while n is not self.root:
            if n.tag in tags:
                self.cur = n.parent
                return
            n = n.parent

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag in RAW_TEXT:
                self.skip += 1
            return
        if tag in RAW_TEXT:
            self.skip = 1
            return
        if tag in _IMPLIED_END and self.cur.tag in _IMPLIED_END[tag]:
            self.cur = self.cur.parent
        elif tag in _BLOCK and self.cur.tag == "p":
            self.cur = self.cur.parent
        node = Node(tag, {k.lower(): (v or "") for k, v in attrs}, self.cur)
        self.cur.children.append(node)
        if tag not in VOID_ELEMENTS:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        if self.skip or tag in RAW_TEXT:
            return
        self.cur.children.append(Node(tag, {k.lower(): (v or "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        if self.skip:
            if tag in RAW_TEXT:
                self.skip -= 1
            return
        if tag in VOID_ELEMENTS:
            return
        self._close_to({tag})

    def handle_data(self, data):
        if not self.skip:
            self.cur.children.append(data)


def parse_html(markup: str) -> Node:
    b = _Builder()
    b.feed(markup)
    b.close()
    return b.root


def _elements(n: Node):
    stack = [n]
    while stack:
        cur = stack.pop()
        yield cur
        stack.extend(c for c in reversed(cur.children) if isinstance(c, Node))


def text_length(n) -> int:
    if isinstance(n, str):
        return len(n.strip())
    return sum(text_length(c) for c in n.children)


def _contains_any(s: str, patterns) -> bool:
    s = s.lower()
    return any(p in s for p in patterns)


# --- finding the article -----------------------------------------------------


def _by_tag(root, tag):
    return next((e for e in _elements(root) if e.tag == tag), None)


def _by_attr(root, key, value):
    return next((e for e in _elements(root) if e.attrs.get(key) == value), None)


def _by_content_class(root):
    best, best_len = None, 0
    for e in _elements(root):
        for key in ("class", "id"):
            v = e.attrs.get(key, "")
            if not v or not _contains_any(v, CONTENT_PATTERNS):
                continue
            tl = text_length(e)
            if tl > best_len and tl >= MIN_CONTENT_LENGTH:
                best, best_len = e, tl
    return best


def _largest_text_node(root):
    best, best_len = None, 0
    for e in _elements(root):
        if e.tag not in ("div", "section"):
            continue
        tl = text_length(e)
        if tl > best_len and tl >= MIN_CONTENT_LENGTH:
            best, best_len = e, tl
    return best


def find_article(doc: Node):
    for strategy in (
        lambda n: _by_tag(n, "article"),
        lambda n: _by_attr(n, "role", "main"),
        lambda n: _by_tag(n, "main"),
        lambda n: _by_attr(n, "itemprop", "articleBody"),
        _by_content_class,
        _largest_text_node,
    ):
        found = strategy(doc)
        if found is not None:
            return found
    return None


# --- stripping furniture -----------------------------------------------------


def is_unwanted(n) -> bool:
    if not isinstance(n, Node):
        return False
    if n.tag in UNWANTED_TAGS:
        return True
    if _contains_any(n.attrs.get("class", ""), UNWANTED_CLASS_PATTERNS):
        return True
    if _contains_any(n.attrs.get("id", ""), UNWANTED_ID_PATTERNS):
        return True
    return n.attrs.get("role", "").lower() in UNWANTED_ROLES


def remove_unwanted(n: Node):
    n.children = [c for c in n.children if not is_unwanted(c)]
    for c in n.children:
        if isinstance(c, Node):
            remove_unwanted(c)


# --- rendering ---------------------------------------------------------------


def _reachable(url: str) -> bool:
    return url.startswith(("http://", "https://", "//"))


def _img_src(n: Node) -> str:
    # Lazy-loaded images put a placeholder in src and the real URL elsewhere.
    for key in ("src", "data-src", "data-lazy-src"):
        v = n.attrs.get(key, "")
        if v and _reachable(v):
            return v
    return ""


def _safe_tag(tag: str) -> bool:
    return tag.replace("-", "").isalnum()


def _attrs(tag: str, attrs: dict) -> str:
    allowed = IMG_ALLOWED_ATTRS if tag == "img" else ALLOWED_ATTRS
    return "".join(
        f' {k}="{escape(v, quote=True)}"' for k, v in attrs.items() if k in allowed
    )


def _render(out: list, n):
    if isinstance(n, str):
        out.append(escape(n, quote=False))
        return
    tag = n.tag
    if tag in ("#root", "html", "body") or not _safe_tag(tag):
        for c in n.children:
            _render(out, c)
        return
    if tag == "a":
        href = n.attrs.get("href", "")
        if not _reachable(href):
            for c in n.children:
                _render(out, c)
            return
        out.append(f'<a href="{escape(href, quote=True)}" rel="noopener noreferrer">')
        for c in n.children:
            _render(out, c)
        out.append("</a>")
        return
    if tag == "img":
        src = _img_src(n)
        if src:
            out.append(f'<img src="{escape(src, quote=True)}"{_attrs(tag, n.attrs)}>')
        return
    if tag in ("source", "video", "audio") and not _reachable(n.attrs.get("src", "https:")):
        return
    out.append(f"<{tag}{_attrs(tag, n.attrs)}>")
    if tag in VOID_ELEMENTS:
        return
    for c in n.children:
        _render(out, c)
    out.append(f"</{tag}>")


def render(n: Node) -> str:
    out: list[str] = []
    for c in n.children:
        _render(out, c)
    return "".join(out).strip()


def sanitize_fragment(markup: str | None) -> str:
    """Run arbitrary HTML through the whitelist.

    Feed content needs this as much as scraped content does: an entry's
    content:encoded is markup from a stranger's server and never passes through
    extract_article.
    """
    if not markup or not markup.strip():
        return ""
    try:
        doc = parse_html(markup)
    except Exception:
        return ""
    remove_unwanted(doc)
    return render(doc)


def extract_article(body: str) -> str:
    """Pull the readable article out of a page, or raise rather than return a
    nav menu that a caller cannot tell apart from a short article."""
    if not body.strip():
        raise ScrapeError("empty document")
    doc = parse_html(body)
    node = find_article(doc)
    if node is None:
        raise ScrapeError("no article content found")
    remove_unwanted(node)
    if text_length(node) < MIN_CONTENT_LENGTH:
        raise ScrapeError("extracted content too short")
    return render(node)
