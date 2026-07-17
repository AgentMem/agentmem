---
name: setup
description: First-time AgentMem setup. Check the memory engine, help set an API key, and verify everything is ready. Friendly for people who do not write code.
---

Walk the user through setting up AgentMem for the first time. Be warm and plain-spoken;
assume they may not know what a terminal, PATH, or API key is. Do the checks yourself and
translate the results. Keep the whole thing to a handful of short lines.

## 1. Check the engine

Run:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/agentmem-engine" doctor
```

Read the checklist it prints:

- **`[ok] model/key`** means the engine is installed and can reach the model. Good.
- **`[!!] model/key`** with a "no API key" style message means the engine runs but has no
  key yet. Go to step 2.
- If the command itself fails to run, the engine is not fetched yet. The plugin will fetch
  it automatically the first time a hook fires, as long as `uv` or Python is on the
  machine. For a faster, permanent install, suggest they run this once in a terminal:
  ```bash
  uv tool install agentmem-core
  ```
  (If they do not have `uv`, point them to https://agentmem.xyz/start. Do not make them
  feel stuck; the plugin still works on demand without this step, just a little slower the
  first time each session.)

## 2. The API key, explained simply

AgentMem's memory step calls Anthropic's API to decide what is worth remembering, so it
needs an **Anthropic API key**. This is separate from a Claude Pro or Max subscription.
Tell them plainly:

- If they already have a key (starts with `sk-ant-`), the cleanest place is an environment
  variable named `ANTHROPIC_API_KEY`. Offer the one line they can paste into their terminal
  profile, and explain it in one sentence.
- If they do not have one, point them to https://console.anthropic.com to create a key, and
  reassure them the memory step is small and cheap (it stays silent most turns).

Never ask them to paste the key into the chat, and never write the key into a file that
gets committed. If they want it stored for this project only, the safe spot is the `env`
block of `.claude/settings.local.json` (which is git-ignored), not `settings.json`.

## 3. Confirm

Run `doctor` once more and confirm the `model/key` line is now `[ok]`. Then tell them what
happens next, in their words: from the next session on, AgentMem quietly keeps track of
what matters on this project, and hands a short, grounded reminder back to Claude when it
would actually help. They can run `/agentmem:status` any time to see what it remembers.
