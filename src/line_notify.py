"""LINE Messaging API push notifications."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
# LINE text message limit is 5000 characters
MAX_TEXT_LEN = 4900


def format_message(title: str, summary: str, url: str) -> str:
    text = f"{title}\n\n{summary}\n\n{url}"
    if len(text) > MAX_TEXT_LEN:
        # Keep title + link; trim summary
        overhead = len(title) + len(url) + 6  # newlines
        budget = max(50, MAX_TEXT_LEN - overhead)
        text = f"{title}\n\n{summary[:budget]}…\n\n{url}"
    return text


def push_message(
    *,
    access_token: str,
    user_id: str,
    title: str,
    summary: str,
    url: str,
) -> None:
    """Push a single text message to LINE_USER_ID."""
    body = {
        "to": user_id,
        "messages": [{"type": "text", "text": format_message(title, summary, url)}],
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        LINE_PUSH_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            # 200 with empty body on success
            _ = resp.read()
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"LINE HTTP {exc.code}: {err_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LINE request failed: {exc.reason}") from exc

    logger.info("line_push_ok", extra={"user_id_suffix": user_id[-4:] if user_id else ""})
