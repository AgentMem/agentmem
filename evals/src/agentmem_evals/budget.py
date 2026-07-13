"""A hard USD cap so a live eval can't run away.

Prices are approximate and per million tokens; update them from the current pricing
page before trusting a live estimate. Offline runs spend nothing (scripted providers
report zero tokens), so the cap only ever bites on real API runs.
"""

from __future__ import annotations

# (input $/Mtok, output $/Mtok). Rough placeholders; verify before a real run.
_PRICES: dict[str, tuple[float, float]] = {
    "haiku": (1.0, 5.0),
    "sonnet": (3.0, 15.0),
    "opus": (15.0, 75.0),
}


class BudgetExceeded(RuntimeError):
    pass


def _rate(model: str) -> tuple[float, float]:
    m = model.lower()
    for key, price in _PRICES.items():
        if key in m:
            return price
    return _PRICES["sonnet"]  # unknown model: assume mid-tier rather than free


class UsdBudget:
    def __init__(self, cap_usd: float | None = None) -> None:
        self.cap = cap_usd
        self.spent = 0.0

    def charge(self, model: str, tokens_in: int, tokens_out: int) -> None:
        in_rate, out_rate = _rate(model)
        self.spent += (tokens_in * in_rate + tokens_out * out_rate) / 1_000_000
        if self.cap is not None and self.spent > self.cap:
            raise BudgetExceeded(f"spent ${self.spent:.2f}, cap ${self.cap:.2f}")

    @property
    def remaining(self) -> float:
        return float("inf") if self.cap is None else max(0.0, self.cap - self.spent)
