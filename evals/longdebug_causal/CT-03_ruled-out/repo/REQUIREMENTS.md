# Requirements

- The job pool schedules high-priority jobs before low-priority ones.
- Any lock guarding priority scheduling must be safe to use from any event loop,
  never share one lock object across loops.
- `python -m pytest` must pass.
