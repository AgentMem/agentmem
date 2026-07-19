"""Plans and per-team entitlements: what a team may store before it has to upgrade."""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

# Each plan caps how many receipts a team may keep. None means unlimited.
PLANS: dict[str, dict[str, int | None]] = {
    "free": {"max_receipts": 500},
    "pro": {"max_receipts": None},
    "enterprise": {"max_receipts": None},
}
DEFAULT_PLAN = "free"


class PlanStore:
    """Which plan each team is on, seeded from the environment and updated by billing."""

    def __init__(self, base: Path | str) -> None:
        self.path = Path(base) / "plans.json"

    def _load(self) -> dict[str, str]:
        seed = {}
        raw = os.environ.get("AGENTMEM_HUB_PLANS")
        if raw:
            try:
                seed = {str(t): str(p) for t, p in json.loads(raw).items()}
            except ValueError:
                seed = {}
        if self.path.exists():
            with contextlib.suppress(ValueError):
                seed.update({str(t): str(p) for t, p in json.loads(self.path.read_text()).items()})
        return seed

    def plan_for(self, team: str) -> str:
        plan = self._load().get(team, DEFAULT_PLAN)
        return plan if plan in PLANS else DEFAULT_PLAN

    def set_plan(self, team: str, plan: str) -> None:
        if plan not in PLANS:
            plan = DEFAULT_PLAN
        current = self._load()
        current[team] = plan
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(current, indent=2))

    def limit_for(self, team: str) -> int | None:
        return PLANS[self.plan_for(team)]["max_receipts"]
