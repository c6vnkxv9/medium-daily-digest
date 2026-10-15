"""Fetch and parse Medium RSS; filter by recent publication window."""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from typing import Iterable
from urllib.parse import urldefrag, urlparse, urlunparse

from timeutil import (
    DEFAULT_LOOKBACK_HOURS,
    is_within_last_hours,
    parse_pub_date,
    to_taipei_iso,
)

logger = logging.getLogger(__name__)

USER_AGENT = (
    "MediumDailyDigest/1.0 (+https://github.com/local/medium-daily-digest; RSS reader)"
)
DEFAULT_TIMEOUT = 15

CONTENT_NS = {"content": "http://purl.org/rss/1.0/modules/content/"}


@dataclass(frozen=True)
class Article:
    article_id: str
    title: str
    url: str
    published_at: str
    body_html: str
    pub_dt: datetime


def normalize_url(url: str) -> str:
    """Strip fragment and trailing slash for stable ids."""
    raw = (url or "").strip()
    if not raw:
        return ""
    raw, _frag = urldefrag(raw)
    parsed = urlparse(raw)
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", parsed.query, ""))


def _text(el: ET.Element | None) -> str:
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def _child_text(item: ET.Element, tag: str) -> str:
    return _text(item.find(tag))


def _body_html(item: ET.Element) -> str:
    encoded = item.find("content:encoded", CONTENT_NS)
    if encoded is not None:
        # content:encoded may use .text or nested text
        parts: list[str] = []
        if encoded.text:
            parts.append(encoded.text)
        for child in encoded:
            if child.text:
                parts.append(child.text)
            if child.tail:
                parts.append(child.tail)
        joined = "".join(parts).strip()
        if joined:
            return joined
    return _child_text(item, "description")


def fetch_rss(url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """GET RSS XML as string."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            return data.decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"RSS HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"RSS fetch failed: {exc.reason}") from exc


def parse_items(xml_text: str) -> list[Article]:
    """Parse RSS channel items into Article list (all dates, no day filter)."""
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        # Atom fallback not required for Medium RSS; still look for item under root
        items = root.findall(".//item")
    else:
        items = channel.findall("item")

    articles: list[Article] = []
    for item in items:
        title = unescape(_child_text(item, "title"))
        link = _child_text(item, "link")
        guid = _child_text(item, "guid") or link
        pub_raw = _child_text(item, "pubDate")
        pub_dt = parse_pub_date(pub_raw)
        if pub_dt is None:
            logger.warning("skip_item_bad_pubdate", extra={"title": title, "pubDate": pub_raw})
            continue
        url = normalize_url(link) or normalize_url(guid)
        article_id = (guid or url).strip()
        if not article_id:
            logger.warning("skip_item_no_id", extra={"title": title})
            continue
        articles.append(
            Article(
                article_id=article_id,
                title=title or "(untitled)",
                url=url or article_id,
                published_at=to_taipei_iso(pub_dt),
                body_html=_body_html(item),
                pub_dt=pub_dt,
            )
        )
    return articles


def filter_recent(
    articles: Iterable[Article],
    *,
    hours: float = DEFAULT_LOOKBACK_HOURS,
    now: datetime | None = None,
) -> list[Article]:
    """Keep articles whose pubDate is within the last `hours` (default 24)."""
    return [a for a in articles if is_within_last_hours(a.pub_dt, hours=hours, now=now)]


def html_to_text(html: str, max_chars: int = 8000) -> str:
    """Strip tags / scripts and collapse whitespace; truncate for token control."""
    if not html:
        return ""
    text = html
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "…"
    return text


def load_recent_articles(
    rss_url: str,
    *,
    hours: float = DEFAULT_LOOKBACK_HOURS,
    now: datetime | None = None,
) -> list[Article]:
    xml_text = fetch_rss(rss_url)
    all_items = parse_items(xml_text)
    recent = filter_recent(all_items, hours=hours, now=now)
    logger.info(
        "rss_parsed",
        extra={"total": len(all_items), "recent": len(recent), "hours": hours},
    )
    return recent
