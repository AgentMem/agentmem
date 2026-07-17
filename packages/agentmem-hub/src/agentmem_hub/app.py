"""The multi-tenant team feed: ingest pushed receipts, gate each team by a bearer key, and
serve the shared timeline as JSON and a web page that keeps the key out of the URL."""

from __future__ import annotations

import os
from pathlib import Path

from agentmem.verify import ActionReceipt
from agentmem.verify.ledger import Ledger
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from . import __version__
from .auth import key_ok, load_keys
from .store import TeamEntry, TeamLedger


class Push(BaseModel):
    receipt: ActionReceipt
    contributor: str = "agent"


def _entry_json(entry: TeamEntry) -> dict:
    r = entry.receipt
    return {
        "receipt_id": r.receipt_id,
        "actor": r.actor,
        "contributor": entry.contributor,
        "verdict": r.verdict,
        "issues": r.issues,
        "claim": r.claim,
        "summary": Ledger._one_line(r),
        "created_at": r.created_at,
        "received_at": entry.received_at,
        "team_hash": entry.hash,
    }


def create_app(base: Path | str | None = None, keys: dict[str, set[str]] | None = None) -> FastAPI:
    base = Path(base or os.environ.get("AGENTMEM_HUB_DATA", ".agentmem-hub"))
    resolved_keys = keys if keys is not None else load_keys()
    ledger = TeamLedger(base)
    app = FastAPI(title="AgentMem hub", version=__version__)

    def require_key(team: str, authorization: str | None = Header(default=None)) -> None:
        presented = (authorization or "").removeprefix("Bearer ").strip()
        if not key_ok(resolved_keys, team, presented):
            raise HTTPException(status_code=401, detail="invalid or missing team key")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    @app.post("/teams/{team}/receipts", dependencies=[Depends(require_key)])
    def ingest(team: str, push: Push) -> dict:
        try:
            entry = ledger.append(team, push.receipt, push.contributor)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "stored": entry is not None,  # False means it was already there (idempotent)
            "team_hash": entry.hash if entry else ledger.head_hash(team),
        }

    @app.get("/teams/{team}/receipts", dependencies=[Depends(require_key)])
    def feed_json(
        team: str,
        actor: str | None = None,
        verdict: str | None = None,
        contributor: str | None = None,
        limit: int | None = None,
    ) -> dict:
        entries = ledger.entries(
            team, actor=actor, verdict=verdict, contributor=contributor, limit=limit
        )
        return {"summary": ledger.summary(team), "entries": [_entry_json(e) for e in entries]}

    @app.get("/teams/{team}/verify", dependencies=[Depends(require_key)])
    def verify(team: str) -> dict:
        problems = ledger.verify(team)
        return {"intact": not problems, "problems": problems}

    @app.get("/teams/{team}/export", dependencies=[Depends(require_key)])
    def export(team: str, format: str = "json") -> object:
        records = [
            {
                "timestamp": e.receipt.created_at,
                "actor": e.receipt.actor,
                "contributor": e.contributor,
                "action": e.receipt.claim,
                "outcome": e.receipt.verdict,
                "issues": ";".join(e.receipt.issues),
                "artifacts": "; ".join(
                    [*e.receipt.added, *e.receipt.modified, *e.receipt.deleted]
                    + [c.label for c in e.receipt.changes]
                ),
                "receipt_id": e.receipt.receipt_id,
                "receipt_hash": e.receipt.hash,
            }
            for e in reversed(ledger.entries(team))  # oldest first, an audit log reads forward
        ]
        if format == "csv":
            import csv
            import io

            fields = list(records[0].keys()) if records else ["timestamp", "actor", "action"]
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=fields)
            writer.writeheader()
            writer.writerows(records)
            return Response(buffer.getvalue(), media_type="text/csv")
        return {"format": "agentmem-audit-log/1", "records": records}

    @app.get("/teams/{team}", response_class=HTMLResponse)
    def feed_page(team: str) -> HTMLResponse:
        # A shell only: no receipts, no key. The page asks for the key in the browser and
        # fetches the JSON with it, so nothing sensitive is ever in this URL or the logs.
        return HTMLResponse(_FEED_HTML.replace("__TEAM__", team))

    @app.exception_handler(401)
    async def _unauthorized(_request, exc):  # type: ignore[no-untyped-def]  # noqa: ANN001
        return JSONResponse(status_code=401, content={"detail": "invalid or missing team key"})

    return app


_FEED_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Team feed &middot; __TEAM__</title><style>
:root{--bg:#0d1013;--panel:#14181d;--ink:#e9ecef;--muted:#8b939d;--line:#262c34;
--amber:#eaa53d;--ok:#46c08a;--bad:#f0524f;--mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,monospace;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.55}
.wrap{max-width:720px;margin:0 auto;padding:34px 20px 64px}
.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:var(--muted)}
h1{font-family:var(--mono);font-weight:600;font-size:23px;margin:20px 0 4px}
.stat{font-family:var(--mono);font-size:12px;color:var(--muted);margin-bottom:18px}.stat b{color:var(--ink)}
.gate{display:flex;gap:8px;margin:14px 0 22px}
input{flex:1;background:var(--panel);border:1px solid var(--line);border-radius:8px;color:var(--ink);
font-family:var(--mono);font-size:13px;padding:9px 11px}
button{background:#2f6bff;border:0;color:#fff;border-radius:8px;font-weight:600;padding:9px 16px;cursor:pointer}
.card{border:1px solid var(--line);border-left:3px solid var(--muted);border-radius:10px;background:var(--panel);
padding:13px 15px;margin:11px 0}
.card.ok{border-left-color:var(--ok)}.card.bad{border-left-color:var(--bad)}.card.mix{border-left-color:var(--amber)}
.top{display:flex;align-items:center;gap:9px;font-family:var(--mono);font-size:12px}
.who{color:var(--ink);font-weight:700}.by{color:var(--muted)}.ago{color:var(--muted)}
.badge{margin-left:auto;font-size:10px;font-weight:700;letter-spacing:.08em;padding:3px 9px;border-radius:20px}
.badge.ok{color:var(--ok);background:rgba(70,192,138,.10)}.badge.bad{color:var(--bad);background:rgba(240,82,79,.10)}
.badge.mix{color:var(--amber);background:rgba(234,165,61,.10)}
.claim{margin:8px 0 5px;font-size:14px}.what{font-family:var(--mono);font-size:12px;color:var(--muted)}
.issues{margin-top:6px;font-family:var(--mono);font-size:11px;color:var(--bad);text-transform:uppercase;letter-spacing:.06em}
.msg{color:var(--muted);font-family:var(--mono);font-size:12px}
footer{margin-top:26px;padding-top:14px;border-top:1px solid var(--line);font-family:var(--mono);font-size:11px;color:var(--muted)}
</style></head><body><div class="wrap">
<div class="eyebrow">Team feed &middot; AgentMem</div>
<h1>What __TEAM__ actually did</h1>
<div class="stat" id="stat"></div>
<div class="gate"><input id="key" type="password" placeholder="team key" autocomplete="off">
<button id="go">Open feed</button></div>
<div id="feed"><p class="msg">Enter your team key to load the feed.</p></div>
<footer>each entry is checked against the real diff and chained to the last &middot; the agent is an untrusted witness</footer>
</div>
<script>
const team = "__TEAM__";
const cls = v => v === "FAITHFUL" ? "ok" : (v === "MIXED" ? "mix" : "bad");
const esc = s => (s||"").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
async function load(){
  const key = document.getElementById("key").value || sessionStorage.getItem("am_key_"+team) || "";
  if(!key){ return; }
  sessionStorage.setItem("am_key_"+team, key);
  const feed = document.getElementById("feed");
  feed.innerHTML = '<p class="msg">Loading...</p>';
  let res;
  try { res = await fetch("/teams/"+encodeURIComponent(team)+"/receipts", {headers:{Authorization:"Bearer "+key}}); }
  catch(e){ feed.innerHTML = '<p class="msg">Could not reach the hub.</p>'; return; }
  if(res.status === 401){ feed.innerHTML = '<p class="msg">That key was not accepted.</p>'; return; }
  const data = await res.json();
  const s = data.summary || {};
  document.getElementById("stat").innerHTML =
    "<b>"+(s.total||0)+"</b> recorded &middot; <b>"+(s.faithful||0)+"</b> faithful &middot; <b>"+(s.flagged||0)+
    "</b> flagged &middot; <b>"+((s.contributors||[]).length)+"</b> contributor(s)";
  const cards = (data.entries||[]).map(e => {
    const c = cls(e.verdict);
    const issues = (e.issues && e.issues.length) ? '<div class="issues">'+esc(e.issues.join(", "))+'</div>' : "";
    return '<article class="card '+c+'"><div class="top"><span class="who">'+esc(e.actor)+
      '</span><span class="by">via '+esc(e.contributor)+'</span><span class="ago">'+esc(e.received_at)+
      '</span><span class="badge '+c+'">'+esc(e.verdict)+'</span></div><div class="claim">'+esc(e.claim)+
      '</div><div class="what">'+esc(e.summary)+'</div>'+issues+'</article>';
  }).join("");
  feed.innerHTML = cards || '<p class="msg">No receipts yet.</p>';
}
document.getElementById("go").addEventListener("click", load);
document.getElementById("key").addEventListener("keydown", e => { if(e.key === "Enter") load(); });
if(sessionStorage.getItem("am_key_"+team)) load();
</script>
</body></html>"""
