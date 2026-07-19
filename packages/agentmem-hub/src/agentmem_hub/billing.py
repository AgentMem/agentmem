"""Turn Stripe subscription webhooks into team plan changes, verifying the signature with
stdlib HMAC so no Stripe SDK is needed. The operator sets the webhook secret and the
price-to-plan map in the environment; secrets never live in this code."""

from __future__ import annotations

import hashlib
import hmac
import json
import os


def verify_signature(payload: bytes, header: str, secret: str) -> bool:
    """Check a Stripe `Stripe-Signature` header against the raw body (HMAC-SHA256)."""
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    timestamp, sent = parts.get("t"), parts.get("v1")
    if not (timestamp and sent and secret):
        return False
    signed = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sent)


def _price_map() -> dict[str, str]:
    raw = os.environ.get("AGENTMEM_HUB_PRICES")
    if not raw:
        return {}
    try:
        return {str(k): str(v) for k, v in json.loads(raw).items()}
    except ValueError:
        return {}


def _first_price(obj: dict) -> str:
    items = obj.get("items", {}).get("data", [])
    if items and isinstance(items[0], dict):
        return str(items[0].get("price", {}).get("id", ""))
    return ""


def plan_change(event: dict) -> tuple[str, str] | None:
    """The (team, plan) a Stripe event implies, or None to ignore it. The team comes from the
    session's `client_reference_id` or `metadata.team`; the plan from the price-to-plan map,
    else `metadata.plan`, else `pro`."""
    event_type = str(event.get("type", ""))
    obj = event.get("data", {}).get("object", {})
    meta = obj.get("metadata", {}) or {}
    team = obj.get("client_reference_id") or meta.get("team")
    if not team:
        return None
    if event_type == "customer.subscription.deleted":
        return (str(team), "free")
    if event_type in (
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
    ):
        if event_type.startswith("customer.subscription") and obj.get("status") not in (
            "active",
            "trialing",
        ):
            return None
        plan = _price_map().get(_first_price(obj), "") or meta.get("plan", "") or "pro"
        return (str(team), str(plan))
    return None
