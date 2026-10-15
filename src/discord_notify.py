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


def push_message(
    *,
    webhook_url: str,
    title: str,
    summary: str,
    url: str,
) -> None:
    """POST a single text message to a Discord Incoming Webhook."""
    body = {"content": format_message(title, summary, url)}
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
