"""Claude Messages API summarization (Traditional Chinese)."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 512

SYSTEM_PROMPT = (
    "你是嚴謹的文章摘要助手。只根據使用者提供的標題與正文撰寫摘要，"
    "不得捏造文中沒有的情節、數據或結論。"
)

USER_PROMPT_TEMPLATE = """請用繁體中文為下列文章寫摘要。

要求：
- 150–250 字
- 保留原文語氣與主題重點
- 不重複標題當結尾
- 只根據正文，不要加入外部知識

標題：{title}

正文：
{body}
"""


def summarize(
    *,
    title: str,
    body_text: str,
    api_key: str,
    model: str | None = None,
) -> str:
    """Call Claude Messages API; return Traditional Chinese summary text."""
    model = model or os.environ.get("CLAUDE_MODEL") or DEFAULT_MODEL
    user_content = USER_PROMPT_TEMPLATE.format(title=title, body=body_text or "(無正文)")
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_content}],
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=data,
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Claude HTTP {exc.code}: {err_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Claude request failed: {exc.reason}") from exc

    parsed = json.loads(raw)
    blocks = parsed.get("content") or []
    texts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
    summary = "\n".join(t for t in texts if t).strip()
    if not summary:
        raise RuntimeError("Claude returned empty summary")
    logger.info("claude_ok", extra={"chars": len(summary), "model": model})
    return summary
