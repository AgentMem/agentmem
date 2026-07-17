"""An `ApiRecorder` over the user's Gmail Sent folder: an OAuth token lists sent mail over
the REST API (stdlib, no Google SDK, injectable transport), to check against what was sent."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from ..verify.recorders import ApiRecorder

_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

# A transport is a function from (url, headers) to parsed JSON. The default hits the network;
# tests pass a fake so the adapter's shaping logic is exercised without Gmail or a token.
Fetch = Callable[[str, dict[str, str]], dict[str, Any]]


def _urllib_fetch(url: str, headers: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 (https only)
        data: dict[str, Any] = json.loads(response.read())
    return data


def _list_sent(token: str, fetch: Fetch, max_results: int) -> dict[str, str]:
    query = urllib.parse.urlencode({"labelIds": "SENT", "maxResults": max_results})
    data = fetch(f"{_BASE}/messages?{query}", {"Authorization": f"Bearer {token}"})
    # A sent message id is immutable, so id doubles as the fingerprint: a new id is a new
    # email, which is all the diff needs.
    return {
        m["id"]: m["id"] for m in data.get("messages", []) if isinstance(m, dict) and m.get("id")
    }


def _label(message_id: str, token: str, fetch: Fetch) -> str:
    query = urllib.parse.urlencode(
        [("format", "metadata"), ("metadataHeaders", "Subject"), ("metadataHeaders", "To")]
    )
    try:
        data = fetch(f"{_BASE}/messages/{message_id}?{query}", {"Authorization": f"Bearer {token}"})
    except Exception:
        return message_id  # a label is a convenience; never fail the audit over it
    headers = {
        str(h.get("name", "")).lower(): h.get("value", "")
        for h in data.get("payload", {}).get("headers", [])
        if isinstance(h, dict)
    }
    subject = headers.get("subject") or "(no subject)"
    to = headers.get("to") or "?"
    return f"{subject} -> {to}"


def gmail_sent_recorder(
    access_token: str,
    *,
    fetch: Fetch | None = None,
    max_results: int = 50,
) -> ApiRecorder:
    """An `ApiRecorder` over Gmail's Sent folder. Pass it to a `ReceiptStore` span so an
    agent's account of what it emailed is checked against what was actually sent."""
    transport = fetch or _urllib_fetch
    return ApiRecorder(
        "gmail-sent",
        lambda: _list_sent(access_token, transport, max_results),
        kind="email",
        label_fn=lambda message_id: _label(message_id, access_token, transport),
    )
