# How AgentMem forgets

An agent that works the same project for weeks accumulates memory faster than it can
use it. Old facts and new ones compete for room in a bounded context, and the stale
ones start crowding out what matters. AgentMem's answer is not to delete, storage is
cheap and a deleted lesson is gone for good, but to let memory fade, and to fade the
right things.

## Salience

Every entry carries a salience score in `[0, 1]`, blended from four signals:

- **Recency**, how many sessions since it was last touched (half-life of five sessions).
- **Frequency**, how often it actually gets injected into a reminder.
- **Importance**, what its tag is worth on its own: a `policy` or `task` requirement
  outweighs a one-off `attempt`.
- **Reinforcement**, whether the reminders that cited it changed the agent's behavior
  for the better, graded by the Outcome Evaluator. Without the evaluator this term is
  zero and the other three still work.

## Three states, never deleted

Salience sorts each entry into a lifecycle:

| State | Salience | Behavior |
|---|---|---|
| `active` | ≥ 0.5 | Rendered to the memory agent as usual. |
| `dormant` | 0.2-0.5 | Hidden from intervention, still searchable, revived the moment it's saved again. |
| `archived` | < 0.2 | Moved to cold storage, out of the working bank. |

Capacity pressure demotes the lowest-salience entry instead of deleting it. Entries
tagged `policy` or `task` have a floor that keeps them `active` through decay alone,
the guard against forgetting a hard requirement just because it hasn't come up lately.

## Consolidation

At natural breakpoints (before a transcript is compacted, and when a session ends),
two passes keep the bank from sprawling:

- **Merge** folds a near-duplicate pair into one entry.
- **Fusion** turns a cluster of repeated attempts on the same file into a single
  abstract rule, keeping the originals dormant as evidence.

## Tiers

What proves durable graduates. An entry that has lived several sessions and earned
positive reinforcement gets rewritten as a general rule and promoted into a smaller,
longer-lived **project** bank that outranks any single session's memory. A future
tier, the user **playbook**, holds hand-approved style and policy rules across
projects.

## Why this shape

The design follows a simple rule of thumb: keep everything, surface little, and let
usefulness decide what stays close. Forgetting here is a ranking problem, not a
deletion one, which is exactly what lets a long-running agent stay sharp without
either drowning in its own history or losing the lesson it will need next month.
