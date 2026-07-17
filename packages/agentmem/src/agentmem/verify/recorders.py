"""Recorders: capture the ground-truth state of things an agent acts on, beyond files.

The filesystem is one kind of ground truth (`receipt.py`). An agent also acts through APIs:
it creates git branches, commits, opens pull requests, spins up cloud resources, sends mail.
Each leaves a trace we can capture as a set of named artifacts and diff before and after a
span of work, exactly like a file diff. A `Recorder` captures that state and turns a diff
into `Change`s, which feed the same receipt as file changes, so one receipt covers
everything the agent did, not just the files.

`GitRecorder` is the concrete, offline, no-credentials instance. `ApiRecorder` is the
extension point: give it a function that lists the resources you care about, and any
cloud/mail/SaaS action becomes recordable and verifiable, without bundling a vendor SDK.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


class Change(BaseModel):
    """One artifact an agent's span of work created, changed, or removed."""

    kind: str  # file, branch, tag, commit, resource
    label: str  # what the agent would name: a path, a branch, a bucket, a message id
    verb: str  # added, modified, deleted
    detail: str = ""  # optional human context: a commit subject, a url
    reversible: bool = False


# Overreach (changed but never mentioned) only makes sense for artifacts an agent names.
# A commit is a content-addressed work product, evidence that it did something, not a thing
# it forgets to mention, so commits are never counted as overreach.
OVERREACH_KINDS = {"file", "branch", "tag", "resource"}


class Recorder(Protocol):
    """Captures the state of one kind of ground truth and diffs it into `Change`s. `name`
    keys its stored before-state; `kinds` is what it can produce, so a claim that asserts a
    recorded action leaving no trace can be told apart from one that was never watched."""

    name: str
    kinds: frozenset[str]

    def capture(self) -> Mapping[str, str]: ...

    def diff(self, before: Mapping[str, str], after: Mapping[str, str]) -> list[Change]: ...


def diff_ids(
    before: Mapping[str, str], after: Mapping[str, str]
) -> tuple[list[str], list[str], list[str]]:
    """Split two id -> fingerprint maps into added / modified / deleted ids."""
    added = sorted(k for k in after if k not in before)
    deleted = sorted(k for k in before if k not in after)
    modified = sorted(k for k in after if k in before and after[k] != before[k])
    return added, modified, deleted


class GitRecorder:
    """Capture git refs (branches, tags, HEAD) so a receipt can check an agent's
    'I made a branch / committed / tagged' against what the repository actually shows.

    Purely local: it shells out to `git`, needs no remote, no token, no network. On a
    directory that is not a git repo it captures nothing, so a receipt just shows no git
    activity rather than failing.
    """

    name = "git"
    kinds = frozenset({"branch", "tag", "commit"})

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def _git(self, *args: str) -> str:
        try:
            out = subprocess.run(  # noqa: S603
                ["git", "-C", str(self.root), *args],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return out.stdout if out.returncode == 0 else ""

    def capture(self) -> dict[str, str]:
        state: dict[str, str] = {}
        for scope, prefix in (("refs/heads", "branch"), ("refs/tags", "tag")):
            for line in self._git(
                "for-each-ref", "--format=%(refname:short) %(objectname)", scope
            ).splitlines():
                name, _, sha = line.partition(" ")
                if name:
                    state[f"{prefix}:{name}"] = sha
        head = self._git("rev-parse", "HEAD").strip()
        if head:
            state["HEAD"] = head
        return state

    def diff(self, before: Mapping[str, str], after: Mapping[str, str]) -> list[Change]:
        changes: list[Change] = []
        # New commits, exactly, from the commit graph rather than a capture window.
        b_head, a_head = before.get("HEAD"), after.get("HEAD")
        if a_head and a_head != b_head:
            rng = f"{b_head}..{a_head}" if b_head else a_head
            for line in self._git("log", "--pretty=%H %s", rng).splitlines():
                sha, _, subject = line.partition(" ")
                if sha:
                    changes.append(
                        Change(
                            kind="commit",
                            label=subject[:70] or sha[:12],
                            verb="added",
                            detail=sha[:12],
                        )
                    )
        # Branches and tags created or removed. A branch that merely moved is the commit
        # above landing on it, already reported, not a separate action to disclose.
        added, _moved, deleted = diff_ids(before, after)
        for kid in added + deleted:
            kind, _, name = kid.partition(":")
            if kind not in ("branch", "tag"):
                continue
            verb = "added" if kid in added else "deleted"
            changes.append(
                Change(
                    kind=kind,
                    label=name,
                    verb=verb,
                    reversible=(kind == "branch" and verb == "added"),
                )
            )
        return changes


class ApiRecorder:
    """Record any API resource you can list. Give it a name, a kind, and a callable that
    returns `{id: fingerprint}` for the resources you care about (buckets you own, messages
    in Sent, rows in a table); before/after diffing and verification come for free.

    This is how cloud and mail actions become auditable without bundling boto3 or a Gmail
    client: the concrete adapter is just your list function, run before and after the span.
    """

    def __init__(
        self,
        name: str,
        list_fn: Callable[[], Mapping[str, str]],
        *,
        kind: str = "resource",
        label_fn: Callable[[str], str] | None = None,
    ) -> None:
        self.name = name
        self.kinds = frozenset({kind})
        self._list = list_fn
        self.kind = kind
        self._label = label_fn or (lambda i: i)

    def capture(self) -> dict[str, str]:
        return dict(self._list())

    def diff(self, before: Mapping[str, str], after: Mapping[str, str]) -> list[Change]:
        added, modified, deleted = diff_ids(before, after)
        out: list[Change] = []
        for kid in added:
            out.append(Change(kind=self.kind, label=self._label(kid), verb="added"))
        for kid in modified:
            out.append(Change(kind=self.kind, label=self._label(kid), verb="modified"))
        for kid in deleted:
            out.append(Change(kind=self.kind, label=self._label(kid), verb="deleted"))
        return out
