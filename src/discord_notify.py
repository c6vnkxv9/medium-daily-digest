"""Discord Incoming Webhook notifications."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

# Discord message content limit is 2000 characters
MAX_TEXT_LEN = 1900


def format_message(title: str, summary: str, url: str) -> str:
    text = f"{title}\n\n{summary}\n\n{url}"
    if len(text) > MAX_TEXT_LEN:
        overhead = len(title) + len(url) + 6  # newlines
        budget = max(50, MAX_TEXT_LEN - overhead)
        text = f"{title}\n\n{summary[:budget]}…\n\n{url}"
    return text


def _error_hint(error: str) -> str:
    """針對常見錯誤給一行處理提示（只看錯誤字串，不含任何密鑰）。"""
    if "Claude HTTP 401" in error:
        return "Claude 金鑰無效或已失效，請更新 Secrets Manager 的 CLAUDE_API_KEY"
    if "Claude HTTP 429" in error:
        return "Claude 被限流或額度不足，請檢查 Console 用量與額度"
    if "Discord HTTP" in error:
        return "Discord 推播失敗，請檢查 DISCORD_WEBHOOK_URL"
    return ""


def format_alert(errors: list[dict], taipei_date: str) -> str:
    """把單次執行的失敗合併成一則告警訊息（約 1900 字元截斷）。"""
    lines = [f"【medium-daily-digest 告警】{taipei_date} 有 {len(errors)} 篇處理失敗"]
    hints: list[str] = []
    for item in errors:
        title = item.get("title") or item.get("article_id", "")
        error = str(item.get("error", ""))
        lines.append(f"\n- {title}\n  {error[:200]}")
        hint = _error_hint(error)
        if hint and hint not in hints:
            hints.append(hint)
    if hints:
        lines.append("\n處理建議：")
        lines.extend(f"- {h}" for h in hints)
    text = "\n".join(lines)
    if len(text) > MAX_TEXT_LEN:
        text = text[: MAX_TEXT_LEN - 1] + "…"
    return text


def _post(webhook_url: str, content: str) -> None:
    """POST text content to a Discord Incoming Webhook."""
    body = {"content": content}
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={
            "Content-Type": "application/json",
            # Cloudflare in front of Discord often returns 1010 without a UA
            "User-Agent": "MediumDailyDigest/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            _ = resp.read()
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Discord HTTP {exc.code}: {err_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Discord request failed: {exc.reason}") from exc

    logger.info("discord_webhook_ok")


def push_message(
    *,
    webhook_url: str,
    title: str,
    summary: str,
    url: str,
) -> None:
    """POST a single digest message to a Discord Incoming Webhook."""
    _post(webhook_url, format_message(title, summary, url))


def push_alert(*, webhook_url: str, errors: list[dict], taipei_date: str) -> None:
    """POST one aggregated failure alert to a Discord Incoming Webhook."""
    _post(webhook_url, format_alert(errors, taipei_date))
