"""Fetching and parsing RSS, RDF, Atom and JSON Feed.

Ported from the Nim reader. Feeds in the wild are not well-formed in the way a
spec implies, so the rules that matter are the fallbacks: a missing GUID falls
back to the link, a missing date stays empty rather than becoming "now", and an
unparseable date does not discard the article.

Elements are matched by local name, ignoring namespaces: feeds use prefixes
inconsistently enough (`content:`, `media:`, occasionally none) that matching
the local name is both simpler and more forgiving.
"""

import asyncio
import html.entities
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

ACCEPT_FEED = (
    "application/xml,application/atom+xml,application/rss+xml,"
    "application/rdf+xml,application/feed+json,text/html;q=0.9"
)
USER_AGENT = "pulseboard/0.2 (+https://github.com/codegod100/pulseboard)"


class FeedError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


@dataclass
class ParsedArticle:
    guid: str = ""
    title: str = ""
    url: str = ""
    author: str = ""
    content: str = ""
    summary: str = ""
    published: datetime | None = None
    updated: datetime | None = None


@dataclass
class ParsedFeed:
    url: str
    title: str = ""
    site_url: str = ""
    description: str = ""
    kind: str = ""
    favicon_url: str = ""
    articles: list[ParsedArticle] = field(default_factory=list)


# --- dates -------------------------------------------------------------------


def parse_time(raw: str) -> datetime | None:
    """Best-effort, always UTC. An unparseable date is not an error."""
    s = (raw or "").strip()
    if not s:
        return None
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            t = parsedate_to_datetime(s)
        except (TypeError, ValueError, IndexError):
            return None
    if t is None:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc)


# --- XML helpers -------------------------------------------------------------


def _local(tag) -> str:
    if not isinstance(tag, str):
        return ""
    tag = tag.rsplit("}", 1)[-1]
    return tag.rsplit(":", 1)[-1]


def _child(n, name):
    if n is None:
        return None
    for c in n:
        if _local(c.tag) == name:
            return c
    return None


def _children(n, name):
    if n is None:
        return []
    return [c for c in n if _local(c.tag) == name]


def _deep_text(n) -> str:
    # Element.itertext includes CDATA (expat folds it into text), which is
    # where RSS ships its HTML bodies.
    return "".join(n.itertext())


def _text(n, name) -> str:
    c = _child(n, name)
    return _deep_text(c).strip() if c is not None else ""


def _attr(n, name) -> str:
    if n is None:
        return ""
    for k, v in n.attrib.items():
        if _local(k) == name:
            return v
    return ""


def _clean_favicon(url: str) -> str:
    u = (url or "").strip()
    return u if u.startswith(("http://", "https://")) else ""


def _pick_atom_link(entry) -> str:
    """Prefer rel="alternate" (or no rel), then the first link. A feed whose
    first link is rel="self" would otherwise point every article at the feed."""
    first = ""
    for link in _children(entry, "link"):
        href = link.get("href", "")
        if not href:
            continue
        first = first or href
        if link.get("rel", "") in ("", "alternate"):
            return href
    return first


# --- formats -----------------------------------------------------------------


def _convert_rss(root, url: str) -> ParsedFeed:
    channel = _child(root, "channel")
    if channel is None:
        channel = ET.Element("channel")
    image = _child(channel, "image")
    feed = ParsedFeed(
        url=url,
        title=_text(channel, "title"),
        site_url=_text(channel, "link"),
        description=_text(channel, "description"),
        kind="rss",
        favicon_url=_clean_favicon(_text(image, "url") if image is not None else ""),
    )
    for item in _children(channel, "item"):
        a = ParsedArticle(
            guid=_text(item, "guid"),
            title=_text(item, "title"),
            url=_text(item, "link"),
            # content:encoded is the full body; description is the summary.
            content=_text(item, "encoded"),
            summary=_text(item, "description"),
            author=_text(item, "author") or _text(item, "creator"),
            published=parse_time(_text(item, "pubDate") or _text(item, "date")),
        )
        a.guid = a.guid or a.url
        feed.articles.append(a)
    return feed


def _convert_rdf(root, url: str) -> ParsedFeed:
    channel = _child(root, "channel")
    feed = ParsedFeed(
        url=url,
        title=_text(channel, "title"),
        site_url=_text(channel, "link"),
        description=_text(channel, "description"),
        kind="rss",
    )
    # In RDF the items are siblings of <channel>, not inside it.
    for item in _children(root, "item"):
        a = ParsedArticle(
            title=_text(item, "title"),
            url=_text(item, "link"),
            content=_text(item, "encoded"),
            summary=_text(item, "description"),
            author=_text(item, "creator"),
            published=parse_time(_text(item, "date")),
        )
        a.guid = _attr(item, "about") or a.url
        feed.articles.append(a)
    return feed


def _convert_atom(root, url: str) -> ParsedFeed:
    feed = ParsedFeed(
        url=url,
        title=_text(root, "title"),
        site_url=_pick_atom_link(root),
        description=_text(root, "subtitle"),
        kind="atom",
        favicon_url=_clean_favicon(_text(root, "icon") or _text(root, "logo")),
    )
    for entry in _children(root, "entry"):
        author = _child(entry, "author")
        a = ParsedArticle(
            guid=_text(entry, "id"),
            title=_text(entry, "title"),
            url=_pick_atom_link(entry),
            content=_text(entry, "content"),
            summary=_text(entry, "summary"),
            author=_text(author, "name") if author is not None else "",
            published=parse_time(_text(entry, "published")),
            updated=parse_time(_text(entry, "updated")),
        )
        a.guid = a.guid or a.url
        # Atom requires <updated> but not <published>.
        a.published = a.published or a.updated
        feed.articles.append(a)
    return feed


def _s(v) -> str:
    return v if isinstance(v, str) else ""


def _convert_json(doc: dict, url: str) -> ParsedFeed:
    feed = ParsedFeed(
        url=url,
        title=_s(doc.get("title")),
        site_url=_s(doc.get("home_page_url")),
        description=_s(doc.get("description")),
        kind="json",
        favicon_url=_clean_favicon(_s(doc.get("icon"))),
    )
    for item in doc.get("items") or []:
        if not isinstance(item, dict):
            continue
        a = ParsedArticle(
            guid=str(item.get("id") or ""),
            title=_s(item.get("title")),
            url=_s(item.get("url")),
            content=_s(item.get("content_html")) or _s(item.get("content_text")),
            summary=_s(item.get("summary")),
            published=parse_time(_s(item.get("date_published"))),
            updated=parse_time(_s(item.get("date_modified"))),
        )
        author = item.get("author")
        if isinstance(author, dict):
            a.author = _s(author.get("name"))
        authors = item.get("authors")
        if not a.author and isinstance(authors, list) and authors and isinstance(authors[0], dict):
            a.author = _s(authors[0].get("name"))
        a.guid = a.guid or a.url
        feed.articles.append(a)
    return feed


_XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}
_ENTITY = re.compile(r"&([A-Za-z][A-Za-z0-9]*);")
_XML_DECL = re.compile(r"^\s*<\?xml[^>]*\?>")


def _fix_entities(text: str) -> str:
    """HTML named entities (&nbsp;, &mdash;) are undefined in XML, and plenty of
    feeds use them anyway. Rewrite them as numeric references."""

    def sub(m):
        name = m.group(1)
        if name in _XML_ENTITIES:
            return m.group(0)
        cp = html.entities.name2codepoint.get(name)
        return f"&#{cp};" if cp else f"&amp;{name};"

    return _ENTITY.sub(sub, text)


def _parse_xml(body: bytes):
    try:
        return ET.fromstring(body)
    except ET.ParseError as first:
        text = body.decode("utf-8", errors="replace").lstrip("﻿")
        text = _fix_entities(_XML_DECL.sub("", text, count=1))
        try:
            return ET.fromstring(text)
        except ET.ParseError:
            raise FeedError(f"not valid XML: {first}") from None


def parse_feed(body: bytes | str, url: str) -> ParsedFeed:
    """Sniff the format and parse. The document decides, not the Content-Type:
    servers mislabel feeds constantly."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    trimmed = body.strip().lstrip(b"\xef\xbb\xbf").strip()
    if not trimmed:
        raise FeedError("empty document")
    if trimmed[:1] == b"{":
        try:
            doc = json.loads(trimmed.decode("utf-8", errors="replace"))
        except ValueError:
            raise FeedError("not valid JSON") from None
        if not isinstance(doc, dict):
            raise FeedError("not a JSON Feed")
        return _convert_json(doc, url)

    root = _parse_xml(trimmed)
    kind = _local(root.tag)
    if kind == "rss":
        return _convert_rss(root, url)
    if kind == "feed":
        return _convert_atom(root, url)
    if kind == "RDF":
        return _convert_rdf(root, url)
    raise FeedError(f"unrecognised feed root element: {kind}")


# --- fetching ----------------------------------------------------------------


def is_retryable(status: int) -> bool:
    """429 and 5xx only. Everything else is the server's settled opinion."""
    return status == 429 or status >= 500


async def fetch_feed(http, url: str, etag: str = "", last_modified: str = "",
                     retries: int = 2, base_delay: float = 0.5):
    """Fetch and parse, retrying only what is worth retrying.

    Returns (feed, etag, last_modified); feed is None when the server answered
    304 to the validators from last time. A 404 will still be a 404 in a
    second, and a document that does not parse will not parse differently on a
    second read, so both fail at once.
    """
    if not url.startswith(("http://", "https://")):
        raise FeedError(f"not an http(s) URL: {url}")
    headers = {"Accept": ACCEPT_FEED, "User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    message, status = "feed fetch failed", 0
    for attempt in range(retries + 1):
        if attempt:
            await asyncio.sleep(base_delay * (2 ** (attempt - 1)))
        try:
            res = await http.request("GET", url, headers=headers)
        except Exception as exc:  # the connection never completed
            message, status = f"fetching {url}: {exc}", 0
            continue
        if res.status == 304:
            return None, etag, last_modified
        if 200 <= res.status < 300:
            try:
                parsed = parse_feed(res.body, url)
            except FeedError as exc:
                raise FeedError(f"parsing {url}: {exc}", res.status) from None
            return parsed, res.headers.get("etag", ""), res.headers.get("last-modified", "")
        message, status = f"fetching {url}: HTTP {res.status}", res.status
        if not is_retryable(res.status):
            break
    raise FeedError(message, status)
