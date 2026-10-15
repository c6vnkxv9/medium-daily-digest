"""Lightweight checks runnable without AWS credentials."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Allow `python scripts/smoke_check.py` from repo root
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rss import filter_recent, html_to_text, parse_items  # noqa: E402
from timeutil import is_within_last_hours, parse_pub_date  # noqa: E402


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Sample</title>
    <item>
      <title>近期文章</title>
      <link>https://medium.com/@x/recent-post</link>
      <guid isPermaLink="false">https://medium.com/@x/recent-post</guid>
      <pubDate>{recent_rfc}</pubDate>
      <description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</description>
      <content:encoded><![CDATA[<p>完整內容一二三</p>]]></content:encoded>
    </item>
    <item>
      <title>舊文章</title>
      <link>https://medium.com/@x/old-post/</link>
      <guid>https://medium.com/@x/old-post</guid>
      <pubDate>Mon, 01 Jan 2024 04:00:00 GMT</pubDate>
      <description>old</description>
    </item>
  </channel>
</rss>
"""


def main() -> None:
    now = datetime.now(tz=ZoneInfo("UTC"))
    # Within last 24h
    recent_rfc = (now - timedelta(hours=3)).strftime("%a, %d %b %Y %H:%M:%S GMT")

    xml = SAMPLE_RSS.format(recent_rfc=recent_rfc)
    items = parse_items(xml)
    assert len(items) == 2, items

    recent_items = filter_recent(items, hours=24, now=now)
    assert len(recent_items) == 1, recent_items
    assert recent_items[0].title == "近期文章"
    assert "完整內容" in html_to_text(recent_items[0].body_html)

    old = parse_pub_date("Mon, 01 Jan 2024 04:00:00 GMT")
    assert old is not None
    assert not is_within_last_hours(old, hours=24, now=now)

    # 25h ago should fall outside a 24h window
    older = now - timedelta(hours=25)
    assert not is_within_last_hours(older, hours=24, now=now)
    assert is_within_last_hours(now - timedelta(hours=23), hours=24, now=now)

    text = html_to_text("<script>x</script><p>A  &amp; B</p>")
    assert text == "A & B", text

    print("smoke_check_ok", {"parsed": len(items), "recent": len(recent_items)})


if __name__ == "__main__":
    main()
