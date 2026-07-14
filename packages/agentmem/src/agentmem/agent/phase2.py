"""Phase 2: decide whether to say anything."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..config import AgentMemConfig
from ..llm.base import LLMProvider
from ..schemas import MemoryBank, TokenUsage, render_tiered_for_agent
from .prompts import phase2_system, phase2_user_content

# Entry id like K-004 / P-011, or a project-tier PK-004 / PP-011. A bullet with no id
# is ungrounded and gets dropped.
_ID_RE = re.compile(r"\((P?[KP]-\d+)\)")
_CONTEXT_RE = re.compile(
    r"<context_for_action>(.*?)</context_for_action>", re.DOTALL | re.IGNORECASE
)
_BULLET_START = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


@dataclass
class Bullet:
    line: str  # cleaned text, still carrying its (K-004) marker(s)
    cited_ids: list[str]


@dataclass
class Phase2Result:
    bullets: list[Bullet] = field(default_factory=list)  # empty => stay silent
    usage: TokenUsage = field(default_factory=TokenUsage)
    raw: str = ""  # raw model text, kept for telemetry/replay

    @property
    def wants_intervention(self) -> bool:
        return bool(self.bullets)


def parse_phase2(text: str) -> list[Bullet]:
    """Pull grounded bullets from a Phase 2 response, or return [] for silence.

    A `<context_for_action>` block with at least one grounded bullet wins. Anything
    else is silence: an explicit `<no_intervention/>`, an empty block, ungrounded
    bullets, or junk.
    """
    match = _CONTEXT_RE.search(text)
    if not match:
        return []

    bullets: list[Bullet] = []
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Accept bulleted lines, or a bare "(K-004) ..." with no marker.
        if _BULLET_START.match(raw_line):
            line = _BULLET_START.sub("", raw_line).strip()
        elif not line.startswith("("):
            continue
        ids = _ID_RE.findall(line)
        if not ids:
            continue  # ungrounded, drop it
        bullets.append(Bullet(line=line, cited_ids=ids))

    return bullets


def run_phase2(
    provider: LLMProvider,
    config: AgentMemConfig,
    task: str,
    window: str,
    bank: MemoryBank,
    *,
    prior: str | None = None,
    project_bank: MemoryBank | None = None,
) -> Phase2Result:
    # A bank with nothing to quote can't ground a reminder, so skip the call. Dormant
    # entries don't count; they're invisible to Phase 2 either way.
    citable = bank.has_citable_entries(include_dormant=False) or (
        project_bank is not None and project_bank.has_citable_entries(include_dormant=False)
    )
    if not citable:
        return Phase2Result()

    bank_render = render_tiered_for_agent(
        bank,
        project_bank,
        include_dormant=False,
        session_cap=config.continual_session_render_cap,
        project_cap=config.continual_project_render_cap,
    )
    content = phase2_user_content(task, window, bank_render)
    if prior:
        content = f"{content}\n\n{prior}"
    resp = provider.complete(
        system=phase2_system(config.causal_enabled),
        messages=[{"role": "user", "content": content}],
        tools=None,
        max_tokens=config.max_output_tokens,
    )
    return Phase2Result(bullets=parse_phase2(resp.text), usage=resp.usage, raw=resp.text)
