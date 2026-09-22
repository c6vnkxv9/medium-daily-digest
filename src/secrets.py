"""Load credentials from Secrets Manager (cached across warm invocations)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3

logger = logging.getLogger(__name__)

_cached: dict[str, Any] | None = None


def get_secrets(force_refresh: bool = False) -> dict[str, Any]:
    """
    Return secret JSON with at least:
      CLAUDE_API_KEY, LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID
    """
    global _cached
    if _cached is not None and not force_refresh:
        return _cached

    secret_arn = os.environ["SECRET_ARN"]
    client = boto3.client("secretsmanager")
    resp = client.get_secret_value(SecretId=secret_arn)
    payload = resp.get("SecretString") or ""
    data = json.loads(payload)

    required = ("CLAUDE_API_KEY", "LINE_CHANNEL_ACCESS_TOKEN", "LINE_USER_ID")
    missing = [k for k in required if not data.get(k)]
    if missing:
        raise ValueError(f"Secret missing keys: {', '.join(missing)}")

    _cached = data
    logger.info("secrets_loaded", extra={"keys": list(required)})
    return _cached
