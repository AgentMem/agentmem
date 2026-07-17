"""Verify an agent's account of a span of work against the real diff, and hold a
hash-chained, reversible receipt of it."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from . import grounding
from .recorders import EVIDENCE_KINDS, Change, Recorder

# Directories that are never part of an agent's real work product, so we neither snapshot
# nor diff them. Keeps the before-state small and the diff about code, not noise.
_IGNORE_DIRS = {
    ".git",
    ".agentmem",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".idea",
    ".vscode",
    "dist",
    "build",
    ".next",
    "out",
}

# Files that legitimately change without being mentioned (lockfiles, caches, editor cruft).
# They are still tracked for undo, but a change to one is not counted as overreach.
_INCIDENTAL_NAMES = {
    "uv.lock",
    "poetry.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "cargo.lock",
    "pipfile.lock",
    "composer.lock",
    "gemfile.lock",
    ".ds_store",
}
_INCIDENTAL_SUFFIX = {".pyc", ".pyo", ".lock", ".log", ".tmp", ".swp"}

# Content bytes are copied into the before-store so undo can put a file back. Above this
# size we record the hash but not the bytes: the change is seen, just not reversible.
_MAX_BLOB = 4_000_000

# Words that turn a plain claim into an assertion of success. A failing check under one of
# these is a silent failure; a failing check without one is just a failure the receipt notes.
_SUCCESS = re.compile(
    r"\b(pass(?:es|ed|ing)?|green|works?|working|fixed|fixes|succe\w*|done|"
    r"no (?:errors?|failures?)|all (?:good|tests? pass))\b",
    re.I,
)

# A claim that asserts a git action. If git was recorded and none of these left a trace,
# the agent is describing work it did not do.
_GIT_CLAIM = re.compile(
    r"\b(commit(?:s|ted|ting)?|push(?:es|ed|ing)?|branch(?:es|ed)?|tag(?:s|ged)?|"
    r"merg(?:e|es|ed|ing)|pull request|opened a pr|\bpr\b)\b",
    re.I,
)


def _rel_parts(root: Path, p: Path) -> tuple[str, ...]:
    return p.relative_to(root).parts


def _iter_files(root: Path):  # type: ignore[no-untyped-def]
    for p in root.rglob("*"):
        if not p.is_file() or p.is_symlink():
            continue
        if set(_rel_parts(root, p)) & _IGNORE_DIRS:
            continue
        yield p


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _incidental(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    return name in _INCIDENTAL_NAMES or any(name.endswith(s) for s in _INCIDENTAL_SUFFIX)


@dataclass
class Snapshot:
    """The file state under a root, path -> (sha256, size); with a `store`, the bytes too, so undo can restore them."""

    root: Path
    files: dict[str, tuple[str, int]]
    store: Path | None = None

    @classmethod
    def capture(cls, root: Path, store: Path | None = None) -> Snapshot:
        root = root.resolve()
        files: dict[str, tuple[str, int]] = {}
        blobs = None
        if store is not None:
            blobs = store / "blobs"
            blobs.mkdir(parents=True, exist_ok=True)
        for p in _iter_files(root):
            try:
                data = p.read_bytes()
            except OSError:
                continue
            rel = p.relative_to(root).as_posix()
            sha = _sha(data)
            files[rel] = (sha, len(data))
            if blobs is not None and len(data) <= _MAX_BLOB:
                blob = blobs / sha
                if not blob.exists():
                    blob.write_bytes(data)
        snap = cls(root=root, files=files, store=store)
        if store is not None:
            snap.save(store / "manifest.json")
        return snap

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"root": str(self.root), "files": self.files}, indent=2))

    @classmethod
    def load(cls, store: Path) -> Snapshot:
        data = json.loads((store / "manifest.json").read_text())
        files = {k: (v[0], v[1]) for k, v in data["files"].items()}
        return cls(root=Path(data["root"]), files=files, store=store)

    def blob(self, sha: str) -> bytes | None:
        if self.store is None:
            return None
        p = self.store / "blobs" / sha
        return p.read_bytes() if p.exists() else None


@dataclass
class Effect:
    """The real change between two snapshots: what an agent's span of work actually did."""

    added: list[str]
    modified: list[str]
    deleted: list[str]

    @property
    def changed(self) -> list[str]:
        return sorted(self.added + self.modified + self.deleted)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.modified or self.deleted)

    @classmethod
    def between(cls, before: Snapshot, after: Snapshot) -> Effect:
        b, a = before.files, after.files
        added = [p for p in a if p not in b]
        deleted = [p for p in b if p not in a]
        modified = [p for p in a if p in b and a[p][0] != b[p][0]]
        return cls(sorted(added), sorted(modified), sorted(deleted))


class Check(BaseModel):
    """A command the agent's work was gated on, and whether it actually passed."""

    name: str
    ok: bool
    detail: str = ""


class ActionReceipt(BaseModel):
    """A verified, reversible account of one span; `verdict`/`issues` derive from the stored facts, `hash` chains it to the last."""

    receipt_id: str
    created_at: str
    actor: str
    repo_name: str
    claim: str
    added: list[str]
    modified: list[str]
    deleted: list[str]
    verified: list[str]
    fabricated: list[str]
    overreach: list[str]
    incidental: list[str]
    changes: list[Change] = []
    checks: list[Check]
    reversible: bool
    prev_hash: str
    hash: str

    @property
    def failed_checks(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    @property
    def silent_failure(self) -> bool:
        return bool(self.failed_checks) and bool(_SUCCESS.search(self.claim))

    @property
    def issues(self) -> list[str]:
        out = []
        if self.fabricated:
            out.append("fabrication")
        if self.overreach:
            out.append("overreach")
        if self.silent_failure:
            out.append("silent-failure")
        return out

    @property
    def verdict(self) -> str:
        issues = self.issues
        if not issues:
            return "FAITHFUL"
        if len(issues) > 1:
            return "MIXED"
        return {
            "fabrication": "FABRICATED",
            "overreach": "OVERREACH",
            "silent-failure": "SILENT_FAILURE",
        }[issues[0]]

    def payload(self) -> dict[str, object]:
        """The raw facts the hash is computed over. Derived fields are left out on purpose,
        so recomputing them can never change the chain."""
        return {
            "receipt_id": self.receipt_id,
            "created_at": self.created_at,
            "actor": self.actor,
            "repo_name": self.repo_name,
            "claim": self.claim,
            "added": self.added,
            "modified": self.modified,
            "deleted": self.deleted,
            "changes": [c.model_dump() for c in self.changes],
            "checks": [c.model_dump() for c in self.checks],
            "prev_hash": self.prev_hash,
        }

    def compute_hash(self) -> str:
        blob = json.dumps(self.payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()

    def tampered(self) -> bool:
        return self.hash != self.compute_hash()

    def to_markdown(self) -> str:
        lines = [
            "# Agent action receipt",
            "",
            f"Repo `{self.repo_name}`. The claim below is checked against the real diff,",
            "not the agent's word.",
            "",
            f"**Verdict: {self.verdict}**",
            "",
            "> " + self.claim.strip().replace("\n", "\n> "),
            "",
            "| what actually changed | vs the claim |",
            "|---|---|",
        ]
        for c in self.fabricated:
            lines.append(f"| `{c}` | claimed, but not in the diff |")
        for c in self.overreach:
            lines.append(f"| `{c}` | changed, never mentioned |")
        for c in self.verified:
            lines.append(f"| `{c}` | claimed and done |")
        for c in self.incidental:
            lines.append(f"| `{c}` | changed, incidental |")
        for chk in self.failed_checks:
            lines.append(f"| check `{chk.name}` | claimed to pass, failed |")
        if self.changes:
            lines += ["", "beyond files:"]
            for ch in self.changes:
                extra = f" ({ch.detail})" if ch.detail else ""
                lines.append(f"- {ch.verb} {ch.kind} `{ch.label}`{extra}")
        lines += [
            "",
            f"changed {len(self.added)} added, {len(self.modified)} modified, "
            f"{len(self.deleted)} deleted - "
            f"{'reversible' if self.reversible else 'partly reversible'} "
            f"- receipt `{self.receipt_id}`",
        ]
        return "\n".join(lines) + "\n"

    def to_html(self) -> str:
        import html as _html

        def row(cls: str, glyph: str, claim: str, chip: str) -> str:
            return _ROW.format(cls=cls, glyph=glyph, claim=_html.escape(claim), chip=chip)

        rows = (
            [row("bad", "&times;", c, "claimed, not done") for c in self.fabricated]
            + [row("warn", "&plus;", c, "undisclosed") for c in self.overreach]
            + [row("ok", "&check;", c, "claimed and done") for c in self.verified]
            + [
                row("bad", "&times;", f"check: {chk.name}", "claimed pass, failed")
                for chk in self.failed_checks
            ]
            + [row("dim", "&middot;", c, "incidental") for c in self.incidental]
        )
        cls = "ok" if self.verdict == "FAITHFUL" else ("mix" if self.verdict == "MIXED" else "bad")
        return _RECEIPT_HTML.format(
            repo=_html.escape(self.repo_name),
            verdict=self.verdict,
            verdict_class=cls,
            claim=_html.escape(self.claim.strip()),
            rows="\n".join(rows),
            n_add=len(self.added),
            n_mod=len(self.modified),
            n_del=len(self.deleted),
            rev="reversible" if self.reversible else "partly reversible",
            rid=self.receipt_id,
            hashline=self.hash[:16],
        )


def _match(token: str, changed: list[str]) -> str | None:
    """The changed path a claimed token refers to, or None. A token matches a change when
    it is the same path, a suffix of it, or the same file name."""
    t = token.lower().lstrip("./")
    base = t.rsplit("/", 1)[-1]
    for c in changed:
        cl = c.lower()
        if cl == t or cl.endswith("/" + t) or cl.rsplit("/", 1)[-1] == base:
            return c
    return None


def build_receipt(
    claim: str,
    effect: Effect,
    *,
    repo_name: str,
    changes: list[Change] | None = None,
    recorded_kinds: set[str] | None = None,
    checks: list[Check] | None = None,
    reversible: bool = True,
    actor: str = "agent",
    receipt_id: str | None = None,
    created_at: str | None = None,
    prev_hash: str = "",
) -> ActionReceipt:
    """Split a claim against the real diff (files plus recorder `changes`) into verified / fabricated / overreach, and seal it."""
    changes = changes or []
    recorded_kinds = recorded_kinds or set()
    checks = checks or []
    changed = effect.changed
    claimed = grounding.path_candidates(claim)

    verified: list[str] = []
    fabricated: list[str] = []
    matched: set[str] = set()
    for tok in claimed:
        hit = _match(tok, changed)
        if hit:
            if tok not in verified:
                verified.append(tok)
            matched.add(hit)
        elif tok not in fabricated:
            fabricated.append(tok)

    overreach: list[str] = []
    incidental: list[str] = []
    for c in changed:
        if c in matched:
            continue
        (incidental if _incidental(c) else overreach).append(c)

    # Fold in the non-file changes. A commit is evidence the agent did work, never an
    # overreach; a named artifact (branch, tag, resource) is verified when the claim
    # mentions it and overreach when it does not.
    low_claim = claim.lower()
    for ch in changes:
        if ch.kind == "commit":
            continue
        # A change is mentioned if the claim names its label or any part of it: an email's
        # label is "subject -> recipient", and a claim usually names one, not the whole thing.
        segments = [ch.label, *(s.strip() for s in re.split(r" -> | → ", ch.label))]
        mentioned = any(seg and seg.lower() in low_claim for seg in segments)
        if mentioned:
            verified.append(f"{ch.kind} {ch.label}")
        elif ch.kind not in EVIDENCE_KINDS:
            overreach.append(f"{ch.kind} {ch.label} ({ch.verb})")

    # A git action asserted in the claim that left no trace at all.
    git_kinds = {"commit", "branch", "tag"}
    if (
        recorded_kinds & git_kinds
        and _GIT_CLAIM.search(claim)
        and not any(ch.kind in git_kinds for ch in changes)
    ):
        fabricated.append("a claimed git action that left no commit, branch, or tag")

    receipt = ActionReceipt(
        receipt_id=receipt_id or uuid.uuid4().hex[:12],
        created_at=created_at or datetime.now(UTC).isoformat(timespec="seconds"),
        actor=actor,
        repo_name=repo_name,
        claim=claim,
        added=effect.added,
        modified=effect.modified,
        deleted=effect.deleted,
        verified=verified,
        fabricated=fabricated,
        overreach=overreach,
        incidental=incidental,
        changes=changes,
        checks=checks,
        reversible=reversible,
        prev_hash=prev_hash,
        hash="",
    )
    receipt.hash = receipt.compute_hash()
    return receipt


def verify_run(
    before: Snapshot,
    after: Snapshot,
    claim: str,
    *,
    changes: list[Change] | None = None,
    recorded_kinds: set[str] | None = None,
    checks: list[Check] | None = None,
    repo_name: str | None = None,
    receipt_id: str | None = None,
    prev_hash: str = "",
    actor: str = "agent",
) -> ActionReceipt:
    """Compare two snapshots, verify the claim against the diff (plus recorder `changes`), and return a receipt."""
    effect = Effect.between(before, after)
    reversible = all(
        before.blob(before.files[p][0]) is not None for p in effect.modified + effect.deleted
    )
    return build_receipt(
        claim,
        effect,
        repo_name=repo_name or before.root.name or str(before.root),
        changes=changes,
        recorded_kinds=recorded_kinds,
        checks=checks,
        reversible=reversible,
        actor=actor,
        receipt_id=receipt_id,
        prev_hash=prev_hash,
    )


class ReceiptStore:
    """The on-disk, append-only, hash-chained home for receipts: begin freezes the ground truth, end verifies and seals, undo restores."""

    def __init__(self, base: Path) -> None:
        self.dir = Path(base) / "receipts"

    def _slot(self, receipt_id: str) -> Path:
        return self.dir / receipt_id

    def begin(
        self, root: Path, recorders: Sequence[Recorder] = (), receipt_id: str | None = None
    ) -> str:
        receipt_id = receipt_id or uuid.uuid4().hex[:12]
        slot = self._slot(receipt_id)
        Snapshot.capture(Path(root), store=slot / "before")
        states = {r.name: dict(r.capture()) for r in recorders}
        (slot / "before" / "recorders.json").write_text(json.dumps(states))
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "CURRENT").write_text(receipt_id)
        return receipt_id

    def head_hash(self) -> str:
        chain = self.dir / "chain.jsonl"
        if not chain.exists():
            return ""
        lines = [ln for ln in chain.read_text().splitlines() if ln.strip()]
        return json.loads(lines[-1])["hash"] if lines else ""

    def latest_id(self) -> str | None:
        cur = self.dir / "CURRENT"
        return cur.read_text().strip() if cur.exists() else None

    def recorded_names(self, receipt_id: str) -> set[str]:
        """Which recorders were active at `begin`, so `end` can re-create them."""
        path = self._slot(receipt_id) / "before" / "recorders.json"
        if not path.exists():
            return set()
        return set(json.loads(path.read_text()).keys())

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Serialize appends so several actors writing to one ledger cannot fork the chain.
        Uses an advisory file lock where the platform has one, and is a no-op otherwise."""
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            import fcntl
        except ImportError:
            yield
            return
        with (self.dir / ".lock").open("w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def end(
        self,
        receipt_id: str,
        claim: str,
        root: Path | None = None,
        recorders: Sequence[Recorder] = (),
        checks: list[Check] | None = None,
        actor: str = "agent",
    ) -> ActionReceipt:
        slot = self._slot(receipt_id)
        before = Snapshot.load(slot / "before")
        after = Snapshot.capture(Path(root) if root is not None else before.root, store=None)
        before_states: dict[str, dict[str, str]] = {}
        recorder_json = slot / "before" / "recorders.json"
        if recorder_json.exists():
            before_states = json.loads(recorder_json.read_text())
        changes: list[Change] = []
        recorded_kinds: set[str] = set()
        for r in recorders:
            recorded_kinds |= set(r.kinds)
            changes.extend(r.diff(before_states.get(r.name, {}), dict(r.capture())))
        receipt = verify_run(
            before,
            after,
            claim,
            changes=changes,
            recorded_kinds=recorded_kinds,
            checks=checks,
            receipt_id=receipt_id,
            actor=actor,
        )
        # Read the head, seal against it, and append, all under the lock, so a second actor
        # ending at the same moment chains after this one instead of forking beside it.
        with self._locked():
            receipt.prev_hash = self.head_hash()
            receipt.hash = receipt.compute_hash()
            (slot / "receipt.json").write_text(receipt.model_dump_json(indent=2))
            with (self.dir / "chain.jsonl").open("a") as handle:
                handle.write(
                    json.dumps(
                        {
                            "id": receipt_id,
                            "actor": receipt.actor,
                            "hash": receipt.hash,
                            "prev_hash": receipt.prev_hash,
                            "created_at": receipt.created_at,
                            "verdict": receipt.verdict,
                        }
                    )
                    + "\n"
                )
        return receipt

    def load(self, receipt_id: str) -> ActionReceipt:
        return ActionReceipt.model_validate_json(
            (self._slot(receipt_id) / "receipt.json").read_text()
        )

    def undo(self, receipt_id: str, root: Path | None = None) -> UndoResult:
        before = Snapshot.load(self._slot(receipt_id) / "before")
        return undo(self.load(receipt_id), before, Path(root) if root is not None else before.root)

    def verify_chain(self) -> list[str]:
        """Walk the chain and report any break: a receipt whose facts no longer hash to
        its seal, or a link whose prev_hash does not point at the receipt before it."""
        chain = self.dir / "chain.jsonl"
        if not chain.exists():
            return []
        problems: list[str] = []
        prev = ""
        for ln in chain.read_text().splitlines():
            if not ln.strip():
                continue
            row = json.loads(ln)
            receipt = self.load(row["id"])
            if receipt.tampered():
                problems.append(f"{row['id']}: contents were edited after sealing")
            if receipt.prev_hash != prev:
                problems.append(f"{row['id']}: chain broken, prev_hash does not match")
            prev = receipt.hash
        return problems


@dataclass
class UndoResult:
    restored: list[str]
    removed: list[str]
    skipped: list[str]


def undo(receipt: ActionReceipt, before: Snapshot, root: Path) -> UndoResult:
    """Restore the tree to before the span: modified/deleted files from stored bytes, added ones removed, too-big ones skipped."""
    root = root.resolve()
    restored, removed, skipped = [], [], []
    for rel in receipt.modified + receipt.deleted:
        sha = before.files.get(rel, ("", 0))[0]
        data = before.blob(sha) if sha else None
        if data is None:
            skipped.append(rel)
            continue
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        restored.append(rel)
    for rel in receipt.added:
        target = root / rel
        if target.exists():
            target.unlink()
            removed.append(rel)
    return UndoResult(sorted(restored), sorted(removed), sorted(skipped))


_ROW = (
    '<div class="row {cls}"><span class="g">{glyph}</span>'
    '<span class="claim">{claim}</span><span class="chip {cls}">{chip}</span></div>'
)

_RECEIPT_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Action receipt &middot; {repo}</title><style>
:root{{--bg:#0d1013;--panel:#14181d;--ink:#e9ecef;--muted:#8b939d;--line:#262c34;
--amber:#eaa53d;--ok:#46c08a;--bad:#f0524f;--mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,monospace;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.6}}
.wrap{{max-width:820px;margin:0 auto;padding:40px 22px 64px}}
.eyebrow{{font-family:var(--mono);font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:var(--muted)}}
.rec{{display:inline-flex;align-items:center;gap:8px}}.dot{{width:8px;height:8px;border-radius:50%;background:var(--amber)}}
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
.row.bad .g{{color:var(--bad)}}.row.ok .g{{color:var(--ok)}}.row.warn .g{{color:var(--amber)}}.row.dim .g,.row.dim .claim{{color:var(--muted)}}
.row.bad .claim{{text-decoration:line-through;text-decoration-color:rgba(240,82,79,.55)}}
.chip{{font-family:var(--mono);font-size:10px;letter-spacing:.06em;text-transform:uppercase;font-weight:700;
padding:4px 9px;border-radius:20px;white-space:nowrap}}.chip.bad{{color:var(--bad);background:rgba(240,82,79,.10)}}
.chip.ok{{color:var(--ok);background:rgba(70,192,138,.10)}}.chip.warn{{color:var(--amber);background:rgba(234,165,61,.10)}}
.chip.dim{{color:var(--muted);background:rgba(139,147,157,.10)}}
footer{{margin-top:30px;padding-top:16px;border-top:1px solid var(--line);font-family:var(--mono);font-size:11px;color:var(--muted)}}
</style></head><body><div class="wrap">
<div class="eyebrow rec"><span class="dot"></span>&nbsp;Action receipt &middot; AgentMem</div>
<h1>What the agent actually did</h1>
<div class="meta">repo <b>{repo}</b> &middot; the claim is checked against the real diff, not the agent's word</div>
<span class="badge {verdict_class}">{verdict}</span>
<div class="stmt">{claim}</div>
<div class="ledger">
{rows}
</div>
<footer>{n_add} added &middot; {n_mod} modified &middot; {n_del} deleted &middot; {rev} &middot; receipt {rid} &middot; seal {hashline}</footer>
</div></body></html>"""
