---
name: work-evaluation
description: "Score work on value, risk, complexity and context, then route it: drop, backlog, pipeline or direct. Use on every new task, for a spontaneous idea, when ordering a backlog, or for \"is this worth doing now?\"."
---

# Work evaluation

One vector for every work decision, so items scored on different days compare.

## The vector

| Axis | Question | Scale |
|---|---|---|
| **Value** | What does the user get, and how often? | low · medium · high |
| **Risk** | What breaks, leaks, or is hard to undo if it goes wrong? | low · medium · high |
| **Complexity** | How many moving parts, repos, owners, or unknowns? | low · medium · high |
| **Context** | Is what we need to do it well available *now* (code read, decisions made, access, device, the user's attention)? | yes · partial · no |

Give each axis one line of evidence. A score without a reason is not a score.

## Routing

Triage every new task through these rules, in order; the first match wins. They read the scores above.

1. **Drop** when value is low and nothing depends on it.
2. **Backlog** when context is `no`: a side session (`idea-side-session`) with a paused, scored run.
3. **Pipeline** (`feature-pipeline`) when any of these holds:
   - it ends in a PR on a shared repo;
   - risk is medium or higher (consensus, crypto, signing, CI or release, upgrade safety);
   - complexity is medium or higher (more than one crate, repo or owner);
   - the acceptance criteria are unclear enough to need scoping;
   - it needs an independent review before it ships.
4. **Direct** otherwise: lookups, local edits, ops commands, Q&A.

If anything unknown would change the route, ask every question that could settle it (`clarify`), then
triage again. `start` runs this gate and opens the run. Say the route in one line.
A direct task escalates to the pipeline when it turns out to need a PR, hits a sensitive path, or spreads
past one file. The state machine, `stop_after`, escalate and demote are in `feature-pipeline`.

Context is the axis most often skipped. Work with full value but no context gets done badly; it
belongs in the backlog with its missing context named: say what would change the call (the missing
context, the decision it waits on, or the risk to retire first).

## Output

One line, then the evidence:

```
Value high · Risk low · Complexity medium · Context no → backlog (needs: app deep links)
- Value: …
- Risk: …
- Complexity: …
- Context: …
```

## Where it is recorded

- On a `feature-pipeline` run, as `evaluation` in its metadata
  (`{value, risk, complexity, context, decision, scored_on}`) via `run-ledger`, so paused runs
  are a scored backlog.
- In a backlog or plan, as the four axes plus the decision and date.
- In your tracker, as fields on the work item (`value`, `risk`, `complexity`, `context`,
  `decision`), so the same vector is queryable across projects.
- On a run, a route change is a `route.changed` event (`feature-pipeline.py route`).
- Re-score when the context axis changes (a backlogged item goes back through triage); keep the earlier score so the change is visible.
