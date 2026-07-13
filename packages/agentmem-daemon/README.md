# agentmem-daemon

The local daemon that bridges Claude Code hooks to AgentMem. It receives hook events
over HTTP, runs memory-steps on the session's background worker, and hands cached
reminders back to the hooks, fast, because the hook path never waits on a model.

```bash
pip install agentmem-daemon
agentmem serve            # http://127.0.0.1:8642
```

Endpoints live under `/hook/*` (session-start, prompt, post-tool, tool-fail,
pre-compact, session-end) plus `/health`. See
[`integrations/claude_code/`](../../integrations/claude_code) for the full setup.

It's a thin FastAPI shell: the payload translation and all the real logic live in
`agentmem.integrations.claude_code` in the core package, which keeps it testable and
keeps version-specific hook details in one spot.
