"""Tests for the Outcome Evaluator: the discounted-return math, parsing, and one call."""

from __future__ import annotations

import pytest
from _fakes import FakeProvider, text_response
from agentmem.policy.evaluator import StepSummary, discounted_returns, evaluate, parse_evals


def test_discounted_returns_golden() -> None:
    returns = discounted_returns([0.5, -0.2, 0.0], task_reward=1.0, gamma=0.9, horizon=6)
    assert returns == pytest.approx([1.13, 0.7, 1.0])


def test_discounted_returns_respects_horizon() -> None:
    # With horizon 0 a step sees only its own reward plus the discounted task reward.
    returns = discounted_returns([0.0, 0.0, 0.0], task_reward=1.0, gamma=0.9, horizon=0)
    assert returns == pytest.approx([0.81, 0.9, 1.0])


def test_parse_evals_extracts_array_amid_prose() -> None:
    text = 'Sure: [{"step": 1, "reward": 0.8, "label": "changed_behavior_good", "why": "turn 3"}]'
    evals = parse_evals(text)
    assert len(evals) == 1
    assert evals[0].step == 1
    assert evals[0].reward == 0.8
    assert evals[0].label == "changed_behavior_good"


def test_parse_evals_clamps_and_defaults() -> None:
    evals = parse_evals('[{"step": 2, "reward": 5.0}]')
    assert evals[0].reward == 1.0  # clamped into [-1, 1]
    assert evals[0].label == ""


def test_parse_evals_bad_input_is_empty() -> None:
    assert parse_evals("no json here") == []
    assert parse_evals("[not json]") == []


def test_evaluate_calls_the_model_once() -> None:
    provider = FakeProvider(
        phase2=[
            text_response('[{"step": 1, "reward": 0.9, "label": "prevented_repeat", "why": "x"}]')
        ]
    )
    evals = evaluate(
        provider,
        task="fix",
        trajectory="ran pytest, failed",
        task_result="pass",
        steps=[StepSummary(step=1, edits="created K-001", decision="silent")],
    )
    assert len(evals) == 1
    assert evals[0].reward == 0.9
    assert provider.seen == ["phase2"]  # exactly one call


def test_evaluate_skips_when_no_steps() -> None:
    provider = FakeProvider()
    assert evaluate(provider, task="t", trajectory="", task_result="", steps=[]) == []
    assert provider.seen == []  # never consulted the model
