"""Lambda entry: Medium RSS → Claude summary → Discord webhook."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from discord_notify import push_alert, push_message
from rss import html_to_text, load_recent_articles
from secrets import get_secrets
from store import is_done, put_done, put_error
from summarize import summarize
from timeutil import DEFAULT_LOOKBACK_HOURS, taipei_today

logger = logging.getLogger()
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)
logger.setLevel(logging.INFO)


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing env var: {name}")
    return value


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines into os.environ without overriding existing vars."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_rss_url(secrets: dict[str, Any]) -> str:
    """
    RSS 目標來源（優先序）：
      1. 環境變數 MEDIUM_RSS_URL（本機 .env 可設）
      2. Secrets Manager 的 MEDIUM_RSS_URL
      3. 環境變數 MEDIUM_USERNAME → https://medium.com/feed/@{username}
      4. Secrets Manager 的 MEDIUM_USERNAME
    """
    full = (os.environ.get("MEDIUM_RSS_URL") or secrets.get("MEDIUM_RSS_URL") or "").strip()
    if full:
        return full

    username = (os.environ.get("MEDIUM_USERNAME") or secrets.get("MEDIUM_USERNAME") or "").strip()
    if username:
        username = username.lstrip("@")
        return f"https://medium.com/feed/@{username}"

    raise RuntimeError(
        "Missing Medium target: set MEDIUM_USERNAME or MEDIUM_RSS_URL "
        "in .env (local) or Secrets Manager (cloud)"
    )


def process_once() -> dict[str, Any]:
    """Run one digest cycle; return structured counters for logs."""
    _env("DDB_TABLE_NAME")
    _env("SECRET_ARN")

    secrets = get_secrets()
    rss_url = resolve_rss_url(secrets)
    logger.info("rss_target", extra={"rss_url": rss_url})
    lookback_hours = DEFAULT_LOOKBACK_HOURS
    articles = load_recent_articles(rss_url, hours=lookback_hours)

    result: dict[str, Any] = {
        "taipei_date": taipei_today().isoformat(),
        "window_hours": lookback_hours,
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
                webhook_url=secrets["DISCORD_WEBHOOK_URL"],
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
            result["errors"].append(
                {"article_id": article_id, "title": article.title, "error": msg}
            )
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

    if result["errors"]:
        # 單次執行的所有失敗合併成一則告警；告警失敗不得影響主流程
        try:
            push_alert(
                webhook_url=secrets["DISCORD_WEBHOOK_URL"],
                errors=result["errors"],
                taipei_date=result["taipei_date"],
            )
            logger.info("alert_sent", extra={"errors": len(result["errors"])})
        except Exception:  # noqa: BLE001
            logger.exception("alert_failed")

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
    # Local: load repo-root .env (does not override already-exported vars)
    _load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    out = handler({}, None)
    print(json.dumps(out, ensure_ascii=False, indent=2))
