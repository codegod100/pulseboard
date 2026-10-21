"""OPML, the portable backup format for subscriptions. Outlines nest
arbitrarily, but only entries with xmlUrl are subscriptions."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html import escape


@dataclass
class OpmlFeed:
    url: str
    title: str = ""
    site_url: str = ""
    description: str = ""
    category: str = ""


def _label(n) -> str:
    for key in ("title", "text", "htmlUrl", "xmlUrl"):
        v = (n.get(key) or "").strip()
        if v:
            return v
    return ""


def _collect(n, category: str, out: list):
    if n.tag.lower() == "outline":
        url = (n.get("xmlUrl") or "").strip()
        if url:
            out.append(OpmlFeed(
                url=url,
                title=_label(n),
                site_url=(n.get("htmlUrl") or "").strip(),
                description=(n.get("description") or "").strip(),
                category=category,
            ))
            return
        category = _label(n)
    for c in n:
        _collect(c, category, out)


def parse_opml(source: str) -> list[OpmlFeed]:
    """Raises ValueError for anything that is not an OPML document."""
    try:
        root = ET.fromstring(source.encode("utf-8"))
    except ET.ParseError as exc:
        raise ValueError(str(exc)) from None
    if root.tag.lower() != "opml":
        raise ValueError("expected an OPML document")
    out: list[OpmlFeed] = []
    _collect(root, "", out)
    return out


def render_opml(feeds: list[OpmlFeed], title: str = "Pulseboard subscriptions") -> str:
    def e(s):
        return escape(s, quote=True)

    def line(f: OpmlFeed, indent: str) -> str:
        s = (f'{indent}<outline text="{e(f.title)}" title="{e(f.title)}" '
             f'type="rss" xmlUrl="{e(f.url)}"')
        if f.site_url:
            s += f' htmlUrl="{e(f.site_url)}"'
        if f.description:
            s += f' description="{e(f.description)}"'
        return s + "/>\n"

    out = ['<?xml version="1.0" encoding="UTF-8"?>\n<opml version="2.0">\n',
           f"  <head><title>{e(title)}</title></head>\n  <body>\n"]
    categories: list[str] = []
    for f in feeds:
        if not f.category:
            out.append(line(f, "    "))
        elif f.category not in categories:
            categories.append(f.category)
    for c in categories:
        out.append(f'    <outline text="{e(c)}" title="{e(c)}">\n')
        out.extend(line(f, "      ") for f in feeds if f.category == c)
        out.append("    </outline>\n")
    out.append("  </body>\n</opml>\n")
    return "".join(out)
