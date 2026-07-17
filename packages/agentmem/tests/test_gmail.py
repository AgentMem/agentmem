"""The Gmail Sent adapter turns real sent mail into receipt changes: a message the agent
sent that it never mentioned is overreach, one it names is verified. Tested against a fake
transport, so no network and no token are involved."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agentmem.integrations.gmail import gmail_sent_recorder
from agentmem.verify import ReceiptStore


def _fake_gmail(sent: dict[str, tuple[str, str]]) -> Callable[[str, dict[str, str]], dict]:
    def fetch(url: str, headers: dict[str, str]) -> dict:
        assert headers["Authorization"].startswith("Bearer ")
        if "/messages/" in url:  # metadata get for a single message
            message_id = url.split("/messages/")[1].split("?")[0]
            subject, to = sent[message_id]
            return {
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": subject},
                        {"name": "To", "value": to},
                    ]
                }
            }
        return {"messages": [{"id": mid} for mid in sent]}  # list SENT

    return fetch


def test_unmentioned_sent_email_is_overreach(tmp_path: Path) -> None:
    sent = {"m1": ("Hello", "a@x.com")}
    recorder = gmail_sent_recorder("test-token", fetch=_fake_gmail(sent))
    store = ReceiptStore(tmp_path / ".am")
    work = tmp_path / "d"
    work.mkdir()

    rid = store.begin(work, recorders=[recorder])
    sent["m2"] = ("Invoice #42", "customer@co.com")  # the agent sends an email this span
    r = store.end(rid, "I finished the report.", work, recorders=[recorder])

    assert any("Invoice #42" in o for o in r.overreach)
    assert r.verdict == "OVERREACH"
    assert any(c.kind == "email" and "customer@co.com" in c.label for c in r.changes)


def test_named_sent_email_is_verified(tmp_path: Path) -> None:
    sent = {"m1": ("Hello", "a@x.com")}
    recorder = gmail_sent_recorder("test-token", fetch=_fake_gmail(sent))
    store = ReceiptStore(tmp_path / ".am")
    work = tmp_path / "d"
    work.mkdir()

    rid = store.begin(work, recorders=[recorder])
    sent["m2"] = ("Welcome", "new@co.com")
    r = store.end(rid, "Sent the `Welcome` email to new@co.com.", work, recorders=[recorder])

    assert any("Welcome" in v for v in r.verified)
    assert r.verdict == "FAITHFUL"
