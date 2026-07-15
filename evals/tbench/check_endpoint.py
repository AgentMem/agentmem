"""Prove a self-hosted endpoint can drive the eval before you spend GPU hours on it."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "agentmem" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentmem_evals.tbench.loop import (  # noqa: E402
    BASH_TOOL,
    DONE_TOOL,
    SYSTEM_PROMPT,
    is_self_hosted,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True, help="e.g. litellm/hosted_vllm/Qwen/Qwen3.6-27B")
    ap.add_argument("--api-base", required=True, help="e.g. http://1.2.3.4:8000/v1")
    args = ap.parse_args()

    from agentmem.llm.litellm import LiteLLMProvider

    provider = LiteLLMProvider(
        model=args.model.removeprefix("litellm/"),
        api_base=args.api_base,
        timeout=300.0,
    )

    print(f"model:    {provider.model}")
    print(f"api_base: {args.api_base}")
    print(f"priced as free: {is_self_hosted(args.model)}")

    resp = provider.complete(
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [{"type": "text", "text": "List the files in the current directory."}],
            }
        ],
        tools=[BASH_TOOL, DONE_TOOL],
        max_tokens=512,
    )

    print(f"\nstop_reason: {resp.stop_reason}")
    print(f"text:        {resp.text[:200]!r}")
    print(f"tool_calls:  {[(c.name, c.args) for c in resp.tool_calls]}")
    print(f"usage:       in={resp.usage.input_tokens} out={resp.usage.output_tokens}")

    if not resp.tool_calls:
        print(
            "\nFAIL: the model answered in prose instead of calling bash.\n"
            "The eval needs tool calls. Usually the tool-call parser is wrong for this\n"
            "model: try PARSER=qwen3_coder (or whatever the model card names) in\n"
            "serve_vllm.sh, and confirm --enable-auto-tool-choice is on."
        )
        return 1
    if resp.tool_calls[0].name != "bash" or not resp.tool_calls[0].args.get("command"):
        print("\nFAIL: got a tool call, but not a usable bash command.")
        return 1

    print("\nOK: tool calling works, the endpoint can drive the eval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
