"""The four tools the memory agent uses to edit the bank.

The agent emits tool calls instead of rewriting the bank as free text, which keeps
edits structured and auditable. This module holds the tool schemas and the parsed
`ToolCall`; applying a call to the bank lives in bank.apply_tool_calls.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

UPDATE_STATUS = "memory_update_status"
SAVE_KNOWLEDGE = "memory_save_knowledge"
SAVE_PROCEDURAL = "memory_save_procedural"
DELETE = "memory_delete"
LINK = "memory_link"

MEMORY_TOOL_NAMES = frozenset({UPDATE_STATUS, SAVE_KNOWLEDGE, SAVE_PROCEDURAL, DELETE, LINK})

# Anthropic tool-use format. `id` is optional on the save tools: omit it to create,
# pass an existing id to update in place. The system allocates ids, so an `id` here
# only ever names one the model was already shown.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": UPDATE_STATUS,
        "description": (
            "Replace your private status notes (progress, open issues, risks). "
            "These are never shown to the action agent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
        },
    },
    {
        "name": SAVE_KNOWLEDGE,
        "description": (
            "Save or update a stable fact: a requirement, environment fact, path, "
            "config, or verified finding. One fact per call, telegraphic."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Existing id to update (e.g. 'K-003'); omit to create a new entry.",
                },
                "tag": {"type": "string", "enum": ["env", "path", "task", "policy", "other"]},
                "content": {"type": "string"},
            },
            "required": ["tag", "content"],
        },
    },
    {
        "name": SAVE_PROCEDURAL,
        "description": (
            "Record an attempt and its outcome, or a diagnosis: a command that "
            "failed and why, a fix that worked, a ruled-out hypothesis, a perf note."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Existing id to update; omit to create."},
                "tag": {
                    "type": "string",
                    "enum": ["attempt", "fix", "diagnosis", "bug", "perf", "other"],
                },
                "content": {"type": "string"},
            },
            "required": ["tag", "content"],
        },
    },
    {
        "name": DELETE,
        "description": "Delete an outdated or incorrect entry by id.",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
]

# The 5th tool, offered only when causal memory is on. Kept separate so the base
# behavior is unchanged when it's off.
MEMORY_LINK_SCHEMA: dict[str, Any] = {
    "name": LINK,
    "description": (
        "Create or remove a causal/logical edge between two existing entries. Only "
        "link when you observed the evidence in the trajectory; write causes as rules, "
        "not logs."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "src": {"type": "string", "description": "Source entry id, usually P-*."},
            "dst": {"type": "string", "description": "Target entry id (P-* or K-*)."},
            "rel": {
                "type": "string",
                "enum": ["caused_by", "fixed_by", "rules_out", "blocks", "verifies", "supersedes"],
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence_step": {"type": "integer"},
            "remove": {"type": "boolean", "default": False},
        },
        "required": ["src", "dst", "rel", "confidence", "evidence_step"],
    },
}


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    block_id: str | None = None  # Anthropic tool_use id, echoed back in the result turn

    def is_memory_tool(self) -> bool:
        return self.name in MEMORY_TOOL_NAMES
