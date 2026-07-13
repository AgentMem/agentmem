# examples/

Runnable, copy-pasteable templates.

- **[`toy_loop.py`](./toy_loop.py)** — the whole integration in one file: read
  `pending_context()` before each turn, `observe()` after. Runs offline (no key)
  using the scripted provider; delete the `provider=` override to use a real model.

  ```bash
  python integrations/examples/toy_loop.py
  ```

More to come alongside the integrations (a LangGraph notebook, an Agent SDK script).
