"""Lambda entry: Medium RSS → Claude summary → LINE push."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from line_notify import push_message
from rss import html_to_text, load_today_articles
from secrets import get_secrets
from store import is_done, put_done, put_error
from summarize import summarize
from timeutil import taipei_today

logger = logging.getLogger()
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)
logger.setLevel(logging.INFO)

DEFAULT_RSS = "https://medium.com/feed/@h9r2sx0m"


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing env var: {name}")
    return value


def process_once() -> dict[str, Any]:
    """Run one digest cycle; return structured counters for logs."""
    rss_url = os.environ.get("MEDIUM_RSS_URL") or DEFAULT_RSS
    _env("DDB_TABLE_NAME")
    _env("SECRET_ARN")

    secrets = get_secrets()
    today = taipei_today()
    articles = load_today_articles(rss_url, today=today)

    result: dict[str, Any] = {
        "taipei_date": today.isoformat(),
        "checked": len(articles),
        "new": 0,
        "notified": 0,
        "skipped": 0,
        "errors": [],
    }

    for article in articles:
        article_id = article.article_id
        log_extra = {"article_id": article_id, "title": article.title}

        try:
            if is_done(article_id):
                result["skipped"] += 1
                logger.info("skip_already_done", extra=log_extra)
                continue

            result["new"] += 1
            body_text = html_to_text(article.body_html)
            summary = summarize(
                title=article.title,
                body_text=body_text,
                api_key=secrets["CLAUDE_API_KEY"],
                model=os.environ.get("CLAUDE_MODEL"),
            )
            push_message(
                access_token=secrets["LINE_CHANNEL_ACCESS_TOKEN"],
                user_id=secrets["LINE_USER_ID"],
                title=article.title,
                summary=summary,
                url=article.url,
            )
            notified_at = datetime.now(tz=timezone.utc).isoformat()
            written = put_done(
                article_id=article_id,
                title=article.title,
                url=article.url,
                published_at=article.published_at,
                summary_zh=summary,
                notified_at=notified_at,
            )
            if written:
                result["notified"] += 1
                logger.info("article_done", extra=log_extra)
            else:
                # Race: another invoke wrote first; treat as skip
                result["skipped"] += 1
                result["new"] -= 1
                logger.info("article_race_skipped", extra=log_extra)

        except Exception as exc:  # noqa: BLE001 — per-article isolation
            msg = str(exc)
            result["errors"].append({"article_id": article_id, "error": msg})
            logger.exception("article_failed", extra=log_extra)
            try:
                put_error(
                    article_id=article_id,
                    title=article.title,
                    url=article.url,
                    published_at=article.published_at,
                    error_message=msg,
                )
            except Exception:  # noqa: BLE001
                logger.exception("ddb_error_write_failed", extra=log_extra)

    return result


def handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    """AWS Lambda handler."""
    logger.info("invoke_start", extra={"event_keys": list((event or {}).keys())})
    result = process_once()
    logger.info("invoke_done", extra={k: result[k] for k in ("checked", "new", "notified", "skipped")})
    return {
        "statusCode": 200 if not result["errors"] else 207,
        "body": json.dumps(result, ensure_ascii=False),
    }


if __name__ == "__main__":
    # Local: export env vars, then python handler.py
    out = handler({}, None)
    print(json.dumps(out, ensure_ascii=False, indent=2))
