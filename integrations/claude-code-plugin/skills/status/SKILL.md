---
name: status
description: Show what AgentMem currently remembers about this project, and whether the setup is healthy.
---

Report the state of AgentMem's memory for this project.

1. Run `agentmem doctor` and show the checklist (model/key, hooks).
2. Run `agentmem bank --tier project` for the durable, cross-session rules.
3. Run `agentmem bank` for the current session's bank.

Summarize for the user in a few lines: how many entries are active, what the standing
requirements are, and anything the doctor flagged. Keep it short.
