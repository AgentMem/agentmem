# examples/

Runnable, copy-pasteable templates.

- **[`toy_loop.py`](./toy_loop.py)**, the whole integration in one file: read
  `pending_context()` before each turn, `observe()` after. Runs offline (no key)
  using the scripted provider; delete the `provider=` override to use a real model.

  ```bash
  python integrations/examples/toy_loop.py
  ```

## The short version: `wrap`

If you'd rather not thread the two calls through your loop yourself, `wrap` does it for
you. Your turn function takes a `memory_context` keyword; `wrap` fills it with the
pending reminder and observes whatever the turn returns.

```python
from agentmem import wrap

def take_turn(messages, *, memory_context):
    reply = call_your_agent(messages, memory_context=memory_context)
    return reply                       # or return the events to observe

agent = wrap(take_turn, task="Fix the failing auth tests",
             extract_events=lambda reply: reply.new_messages)

with agent:
    while not done:
        agent(messages)                # reads the reminder, observes the result
```

More to come alongside the integrations (a LangGraph notebook, an Agent SDK script).
