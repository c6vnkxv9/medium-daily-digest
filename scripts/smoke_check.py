"""Lightweight checks runnable without AWS credentials."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Allow `python scripts/smoke_check.py` from repo root
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rss import filter_taipei_today, html_to_text, parse_items  # noqa: E402
from timeutil import is_taipei_today, parse_pub_date, taipei_today  # noqa: E402


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Sample</title>
    <item>
      <title>今日文章</title>
      <link>https://medium.com/@x/today-post</link>
      <guid isPermaLink="false">https://medium.com/@x/today-post</guid>
      <pubDate>{today_rfc}</pubDate>
      <description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</description>
      <content:encoded><![CDATA[<p>完整內容一二三</p>]]></content:encoded>
    </item>
    <item>
      <title>昨日文章</title>
      <link>https://medium.com/@x/old-post/</link>
      <guid>https://medium.com/@x/old-post</guid>
      <pubDate>Mon, 01 Jan 2024 04:00:00 GMT</pubDate>
      <description>old</description>
    </item>
  </channel>
</rss>
"""


def main() -> None:
    taipei = ZoneInfo("Asia/Taipei")
    now = datetime.now(tz=taipei)
    # RFC 2822 in GMT approximating "now"
    today_rfc = now.astimezone(ZoneInfo("UTC")).strftime("%a, %d %b %Y %H:%M:%S GMT")

    xml = SAMPLE_RSS.format(today_rfc=today_rfc)
    items = parse_items(xml)
    assert len(items) == 2, items

    today_items = filter_taipei_today(items, today=taipei_today(now))
    assert len(today_items) == 1, today_items
    assert today_items[0].title == "今日文章"
    assert "完整內容" in html_to_text(today_items[0].body_html)

    old = parse_pub_date("Mon, 01 Jan 2024 04:00:00 GMT")
    assert old is not None
    assert not is_taipei_today(old, today=taipei_today(now))

    text = html_to_text("<script>x</script><p>A  &amp; B</p>")
    assert text == "A & B", text

    print("smoke_check_ok", {"parsed": len(items), "today": len(today_items)})


if __name__ == "__main__":
    main()
