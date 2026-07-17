"""An agent's account verified against the repository, rendered as a flight-recorder report
in markdown or HTML."""

from __future__ import annotations

import html
from pathlib import Path

from pydantic import BaseModel

from . import grounding


class AccountReport(BaseModel):
    """What an agent said it did, split by what the repository can confirm."""

    account: str
    repo_name: str
    verified: list[str]
    contradicted: list[str]

    @property
    def grounded(self) -> bool:
        return bool(self.verified)

    @property
    def status(self) -> str:
        if self.verified and not self.contradicted:
            return "VERIFIED"
        if self.contradicted and not self.verified:
            return "CONTRADICTED"
        return "MIXED"

    def to_markdown(self) -> str:
        lines = [
            "# Agent-run flight recorder",
            "",
            f"Repo `{self.repo_name}`. The account below is checked against the checkout,",
            "not the agent's word. Each named artifact is verified or contradicted.",
            "",
            f"**Status: {self.status}**  ({len(self.verified)} verified, "
            f"{len(self.contradicted)} contradicted)",
            "",
            "> " + self.account.strip().replace("\n", "\n> "),
            "",
            "| claim | verdict |",
            "|---|---|",
        ]
        for c in self.contradicted:
            lines.append(f"| `{c}` | contradicted, not in the checkout |")
        for c in self.verified:
            lines.append(f"| `{c}` | verified, present |")
        return "\n".join(lines) + "\n"

    def to_html(self) -> str:
        return _HTML.format(
            repo=html.escape(self.repo_name),
            status=self.status,
            status_class="bad"
            if self.status == "CONTRADICTED"
            else ("ok" if self.status == "VERIFIED" else "mix"),
            n_ok=len(self.verified),
            n_bad=len(self.contradicted),
            account=html.escape(self.account.strip()),
            rows="\n".join(
                [
                    _ROW.format(
                        cls="bad", glyph="&times;", claim=html.escape(c), chip="contradicted"
                    )
                    for c in self.contradicted
                ]
                + [
                    _ROW.format(cls="ok", glyph="&check;", claim=html.escape(c), chip="verified")
                    for c in self.verified
                ]
            ),
        )


def verify_account(account: str, repo: Path) -> AccountReport:
    """Check an account's claims against a repository checkout."""
    g = grounding.score(account, repo)
    return AccountReport(
        account=account,
        repo_name=repo.name or str(repo),
        verified=g["real"],
        contradicted=g["invented"],
    )


_ROW = (
    '<div class="row {cls}"><span class="g">{glyph}</span>'
    '<span class="claim">{claim}</span><span class="chip {cls}">{chip}</span></div>'
)

_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flight recorder &middot; {repo}</title><style>
:root{{--bg:#0d1013;--panel:#14181d;--ink:#e9ecef;--muted:#8b939d;--line:#262c34;
--amber:#eaa53d;--ok:#46c08a;--bad:#f0524f;--mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,monospace;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.6}}
.wrap{{max-width:820px;margin:0 auto;padding:40px 22px 64px}}
.eyebrow{{font-family:var(--mono);font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:var(--muted)}}
.rec{{display:inline-flex;align-items:center;gap:8px}}.dot{{width:8px;height:8px;border-radius:50%;background:var(--bad)}}
h1{{font-family:var(--mono);font-weight:600;font-size:26px;margin:26px 0 6px}}
.meta{{font-family:var(--mono);font-size:12px;color:var(--muted)}}.meta b{{color:var(--ink)}}
.badge{{display:inline-block;font-family:var(--mono);font-size:12px;font-weight:700;letter-spacing:.1em;
padding:5px 11px;border-radius:6px;margin:14px 0}}
.badge.bad{{color:var(--bad);background:rgba(240,82,79,.10)}}.badge.ok{{color:var(--ok);background:rgba(70,192,138,.10)}}
.badge.mix{{color:var(--amber);background:rgba(234,165,61,.10)}}
.stmt{{padding:15px 17px;border:1px solid var(--line);border-left:3px solid var(--muted);border-radius:8px;
background:var(--panel);font-size:14px;white-space:pre-wrap;margin:12px 0 20px}}
.ledger{{border:1px solid var(--line);border-radius:10px;overflow:hidden}}
.row{{display:grid;grid-template-columns:20px 1fr auto;gap:12px;align-items:center;padding:11px 15px;border-top:1px solid var(--line)}}
.row:first-child{{border-top:none}}.g{{font-family:var(--mono);font-weight:700;text-align:center}}
.claim{{font-family:var(--mono);font-size:13px;word-break:break-all}}
.row.bad .g{{color:var(--bad)}}.row.ok .g{{color:var(--ok)}}
.row.bad .claim{{text-decoration:line-through;text-decoration-color:rgba(240,82,79,.55)}}
.chip{{font-family:var(--mono);font-size:10px;letter-spacing:.06em;text-transform:uppercase;font-weight:700;
padding:4px 9px;border-radius:20px;white-space:nowrap}}.chip.bad{{color:var(--bad);background:rgba(240,82,79,.10)}}
.chip.ok{{color:var(--ok);background:rgba(70,192,138,.10)}}
footer{{margin-top:30px;padding-top:16px;border-top:1px solid var(--line);font-family:var(--mono);font-size:11px;color:var(--muted)}}
</style></head><body><div class="wrap">
<div class="eyebrow rec"><span class="dot"></span>&nbsp;Flight recorder &middot; AgentMem</div>
<h1>What the agent said it did</h1>
<div class="meta">repo <b>{repo}</b> &middot; checked against the checkout, not the agent's word</div>
<span class="badge {status_class}">{status} &middot; {n_ok} verified, {n_bad} contradicted</span>
<div class="stmt">{account}</div>
<div class="ledger">
{rows}
</div>
<footer>the agent is an untrusted witness &middot; git decides &middot; the model never grades itself</footer>
</div></body></html>"""
