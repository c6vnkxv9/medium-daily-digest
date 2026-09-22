"""DynamoDB read/write for processed articles."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def _table():
    name = os.environ["DDB_TABLE_NAME"]
    return boto3.resource("dynamodb").Table(name)


def is_done(article_id: str) -> bool:
    """True if article already exists with status=done."""
    resp = _table().get_item(Key={"article_id": article_id})
    item = resp.get("Item")
    return bool(item and item.get("status") == "done")


def put_done(
    *,
    article_id: str,
    title: str,
    url: str,
    published_at: str,
    summary_zh: str,
    notified_at: str | None = None,
) -> bool:
    """
    Conditional PutItem when article_id does not exist.
    Returns True if written, False if a concurrent write already exists.
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    item: dict[str, Any] = {
        "article_id": article_id,
        "title": title,
        "url": url,
        "published_at": published_at,
        "summary_zh": summary_zh,
        "status": "done",
        "notified_at": notified_at or now,
        "created_at": now,
    }
    # Allow overwrite of missing / error rows; never overwrite status=done (dedupe).
    try:
        _table().put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(article_id) OR #st <> :done",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":done": "done"},
        )
        logger.info("ddb_put_done", extra={"article_id": article_id})
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.info("ddb_put_skipped_exists", extra={"article_id": article_id})
            return False
        raise


def put_error(
    *,
    article_id: str,
    title: str,
    url: str,
    published_at: str,
    error_message: str,
) -> None:
    """Write an error record without overwriting an existing status=done row."""
    now = datetime.now(tz=timezone.utc).isoformat()
    try:
        _table().put_item(
            Item={
                "article_id": article_id,
                "title": title,
                "url": url,
                "published_at": published_at,
                "summary_zh": "",
                "status": "error",
                "error_message": error_message[:1000],
                "created_at": now,
            },
            ConditionExpression="attribute_not_exists(article_id) OR #st <> :done",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":done": "done"},
        )
        logger.warning(
            "ddb_put_error",
            extra={"article_id": article_id, "error_message": error_message[:200]},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.info("ddb_error_skipped_done", extra={"article_id": article_id})
            return
        raise
