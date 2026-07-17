"""Read the receipts store as a shared, multi-actor feed: filter by actor or verdict, check
integrity, and render it for a person to scan."""

from __future__ import annotations

import html as _html
import json
from datetime import UTC, datetime
from pathlib import Path

from .receipt import ActionReceipt, ReceiptStore

_BADGE = {"FAITHFUL": "ok", "MIXED": "mix"}  # anything else renders as a trust break


def _ago(iso: str) -> str:
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    seconds = (datetime.now(UTC) - then).total_seconds()
    if seconds < 90:
        return "just now"
    for size, unit in ((3600, "min"), (86400, "hour"), (float("inf"), "day")):
        if seconds < size:
            step = 60 if unit == "min" else (3600 if unit == "hour" else 86400)
            n = int(seconds // step)
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return iso


class Ledger:
    """A read view over a project's receipts: the shared timeline, filtered and rendered."""

    def __init__(self, base: Path) -> None:
        self.store = ReceiptStore(base)

    def _rows(self) -> list[dict[str, object]]:
        chain = self.store.dir / "chain.jsonl"
        if not chain.exists():
            return []
        return [json.loads(ln) for ln in chain.read_text().splitlines() if ln.strip()]

    def actors(self) -> list[str]:
        return sorted({str(r.get("actor", "agent")) for r in self._rows()})

    def receipts(
        self,
        *,
        actor: str | None = None,
        verdict: str | None = None,
        limit: int | None = None,
    ) -> list[ActionReceipt]:
        """Matching receipts, newest first."""
        out: list[ActionReceipt] = []
        for row in reversed(self._rows()):
            if actor and str(row.get("actor", "agent")) != actor:
                continue
            if verdict and row.get("verdict") != verdict:
                continue
            try:
                out.append(self.store.load(str(row["id"])))
            except (OSError, ValueError):
                continue
            if limit and len(out) >= limit:
                break
        return out

    def summary(self) -> dict[str, object]:
        rows = self._rows()
        by_verdict: dict[str, int] = {}
        by_actor: dict[str, int] = {}
        for row in rows:
            by_verdict[str(row.get("verdict", "?"))] = (
                by_verdict.get(str(row.get("verdict", "?")), 0) + 1
            )
            by_actor[str(row.get("actor", "agent"))] = (
                by_actor.get(str(row.get("actor", "agent")), 0) + 1
            )
        faithful = by_verdict.get("FAITHFUL", 0)
        return {
            "total": len(rows),
            "faithful": faithful,
            "flagged": len(rows) - faithful,
            "by_verdict": by_verdict,
            "by_actor": by_actor,
        }

    def verify(self) -> list[str]:
        return self.store.verify_chain()

    @staticmethod
    def _one_line(r: ActionReceipt) -> str:
        bits = []
        files = len(r.added) + len(r.modified) + len(r.deleted)
        if files:
            bits.append(f"{files} file{'s' if files != 1 else ''}")
        commits = sum(1 for c in r.changes if c.kind == "commit")
        if commits:
            bits.append(f"{commits} commit{'s' if commits != 1 else ''}")
        other = [c for c in r.changes if c.kind != "commit"]
        if other:
            bits.append(f"{len(other)} {other[0].kind}{'s' if len(other) != 1 else ''}")
        return ", ".join(bits) or "no changes"

    def to_markdown(self, **filters: str | int | None) -> str:
        s = self.summary()
        lines = [
            "# Agent action ledger",
            "",
            f"{s['total']} recorded - {s['faithful']} faithful, {s['flagged']} flagged"
            f" - {len(self.actors())} actor(s)",
            "",
        ]
        for r in self.receipts(**filters):  # type: ignore[arg-type]
            issue = f"  ({', '.join(r.issues)})" if r.issues else ""
            lines.append(
                f"- **{r.verdict}** - `{r.actor}` - {_ago(r.created_at)} - {self._one_line(r)}{issue}"
            )
        return "\n".join(lines) + "\n"

    def to_html(self, **filters: str | int | None) -> str:
        s = self.summary()
        cards = []
        for r in self.receipts(**filters):  # type: ignore[arg-type]
            cls = _BADGE.get(r.verdict, "bad")
            issues = (
                f'<div class="issues">{_html.escape(", ".join(r.issues))}</div>' if r.issues else ""
            )
            cards.append(
                _CARD.format(
                    cls=cls,
                    verdict=r.verdict,
                    actor=_html.escape(r.actor),
                    ago=_html.escape(_ago(r.created_at)),
                    summary=_html.escape(self._one_line(r)),
                    claim=_html.escape(r.claim.strip()[:240]),
                    issues=issues,
                )
            )
        return _FEED_HTML.format(
            total=s["total"],
            faithful=s["faithful"],
            flagged=s["flagged"],
            actors=len(self.actors()),
            cards="\n".join(cards) or '<p class="empty">No receipts yet.</p>',
        )


_CARD = """<article class="card {cls}">
  <div class="top"><span class="who">{actor}</span><span class="ago">{ago}</span>
    <span class="badge {cls}">{verdict}</span></div>
  <div class="claim">{claim}</div>
  <div class="what">{summary}</div>{issues}
</article>"""

_FEED_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent action ledger</title><style>
:root{{--bg:#0d1013;--panel:#14181d;--ink:#e9ecef;--muted:#8b939d;--line:#262c34;
--amber:#eaa53d;--ok:#46c08a;--bad:#f0524f;--mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,monospace;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.55}}
.wrap{{max-width:720px;margin:0 auto;padding:38px 20px 64px}}
.eyebrow{{font-family:var(--mono);font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:var(--muted)}}
h1{{font-family:var(--mono);font-weight:600;font-size:24px;margin:22px 0 4px}}
.stat{{font-family:var(--mono);font-size:12px;color:var(--muted);margin-bottom:24px}}.stat b{{color:var(--ink)}}
.card{{border:1px solid var(--line);border-left:3px solid var(--muted);border-radius:10px;background:var(--panel);
padding:14px 16px;margin:12px 0}}
.card.ok{{border-left-color:var(--ok)}}.card.bad{{border-left-color:var(--bad)}}.card.mix{{border-left-color:var(--amber)}}
.top{{display:flex;align-items:center;gap:10px;font-family:var(--mono);font-size:12px}}
.who{{color:var(--ink);font-weight:700}}.ago{{color:var(--muted)}}
.badge{{margin-left:auto;font-size:10px;font-weight:700;letter-spacing:.08em;padding:3px 9px;border-radius:20px}}
.badge.ok{{color:var(--ok);background:rgba(70,192,138,.10)}}.badge.bad{{color:var(--bad);background:rgba(240,82,79,.10)}}
.badge.mix{{color:var(--amber);background:rgba(234,165,61,.10)}}
.claim{{margin:9px 0 6px;font-size:14px}}.what{{font-family:var(--mono);font-size:12px;color:var(--muted)}}
.issues{{margin-top:7px;font-family:var(--mono);font-size:11px;color:var(--bad);text-transform:uppercase;letter-spacing:.06em}}
.empty{{color:var(--muted);font-family:var(--mono)}}
footer{{margin-top:28px;padding-top:14px;border-top:1px solid var(--line);font-family:var(--mono);font-size:11px;color:var(--muted)}}
</style></head><body><div class="wrap">
<div class="eyebrow">Action ledger &middot; AgentMem</div>
<h1>What your agents actually did</h1>
<div class="stat"><b>{total}</b> recorded &middot; <b>{faithful}</b> faithful &middot;
<b>{flagged}</b> flagged &middot; <b>{actors}</b> actor(s)</div>
{cards}
<footer>each entry is checked against the real diff and hash-chained to the last &middot; the agent is an untrusted witness</footer>
</div></body></html>"""
