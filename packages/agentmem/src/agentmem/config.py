"""Configuration."""

from __future__ import annotations

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)


class AgentMemConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTMEM_",
        env_file=".env",
        env_file_encoding="utf-8",
        toml_file="agentmem.toml",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Slot agentmem.toml in below env/.env: it's the committed baseline, overridable.
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )

    # model / provider
    # Haiku is the cheap default; the string is validated by the provider, not here.
    model: str = "claude-haiku-4-5"
    api_key: str | None = None  # None => the Anthropic SDK reads ANTHROPIC_API_KEY
    max_output_tokens: int = 1024
    request_timeout_s: float = 30.0

    # storage
    # "json" (one file per session) or a "sqlite:///path.db" URL.
    store: str = "json"
    state_dir: str = ".agentmem"

    # window (what the memory agent sees)
    window_messages: int = 8
    max_task_tokens: int = 400
    max_event_tokens: int = 500

    # bank budgets
    status_token_budget: int = 150
    entry_token_budget: int = 60
    max_knowledge: int = 30
    max_procedural: int = 30

    # causal memory: give Phase 1 the memory_link tool and render causal chains.
    causal_enabled: bool = True
    max_edges: int = 40
    max_edges_per_src: int = 2
    causal_min_confidence: float = 0.7  # only chains at/above this get rendered

    # Phase 1
    max_tool_rounds: int = 2
    max_tool_calls_per_step: int = 8

    # Phase 2 / injector
    max_bullets: int = 4
    intervention_token_budget: int = 120
    injector_cooldown_steps: int = 5  # don't re-inject an entry within this many steps

    # advantage layer (learned decisions): opt-in, needs the evaluator + some history.
    advantage_enabled: bool = False
    advantage_gate: bool = False  # one-way: may force silence, never inject
    advantage_gate_tau: float = 0.0
    advantage_min_neighbors: int = 3

    # continual memory: salience-driven active/dormant/archived lifecycle. On by
    # default; with no history yet every entry starts at salience 1.0, so it never
    # surprises a fresh bank.
    continual_enabled: bool = True
    continual_w_recency: float = 0.25
    continual_w_frequency: float = 0.15
    continual_w_importance: float = 0.35
    continual_w_reinforcement: float = 0.25

    # project-tier promotion: entries that prove durable across sessions get
    # rewritten as general rules in a smaller, longer-lived bank.
    continual_project_max: int = 40
    continual_min_sessions_lived: int = 3
    # Float bank entries relevant to the current window above the render cap, so an
    # old diagnosis of the error on screen is not dropped for a fresher generic note.
    # Off until a measured run shows recall improves (evals/repeat/recall.py).
    relevance_boost: bool = False
    continual_session_render_cap: int = 12  # per-tier caps on what Phase 1/2 see,
    continual_project_render_cap: int = 8  # highest salience first (negative transfer
    continual_playbook_render_cap: int = 3  # guardrail from too much retrieval competition)

    # triggers
    trigger_every_n: int = 3
    repeat_window: int = 6

    # privacy
    redact_secrets: bool = True  # scrub secrets from the window before the LLM sees it

    # telemetry
    telemetry: bool = True
    telemetry_path: str | None = None  # default: <state_dir>/telemetry.jsonl

    def with_overrides(self, **kwargs: object) -> AgentMemConfig:
        """Return a copy with the given (non-None) fields replaced."""
        clean = {k: v for k, v in kwargs.items() if v is not None}
        return self.model_copy(update=clean)


def default_config() -> AgentMemConfig:
    return AgentMemConfig()
