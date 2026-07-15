"""Terminal-Bench 2.0 eval: the same minimal terminal agent run twice, once bare and
once with an AgentMem session riding along. The only difference between the arms is
memory, so any pass-rate delta is attributable to it."""

from .loop import PRICES, ActionLoop, CountingProvider, Decision, is_self_hosted

__all__ = ["PRICES", "ActionLoop", "CountingProvider", "Decision", "is_self_hosted"]
