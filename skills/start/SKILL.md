---
name: start
model: sonnet
effort: low
description: "Gate every new task: triage it with work-evaluation's routing rules, open its run, and say which route it takes (dropped, direct, backlogged, pipelined) and where a pipelined run stops. Use for \"/start <task>\" and at the start of any new task."
metadata:
  calls: ["work-evaluation", "run-ledger", "feature-pipeline"]
---

# start

The entry gate. One task in, one route out, one run recorded. Load `run-ledger` for `$FP`.

## 1. Triage

Score the task with `work-evaluation` and apply its routing rules. If anything that would change the
route is unknown, enter **clarify**: ask every question that could settle the route, together, with
AskUserQuestion (up to four per call), then triage again with the answers.

## 2. Open the run

Every task gets a run, so `fp list` shows all routes.

| Route | Command | Then |
| :--- | :--- | :--- |
| `pipelined` | `$FP new <repo-dir> "<title>" "<request verbatim>" [--stop-after scope\|build\|review\|approve]` | follow `feature-pipeline` |
| `direct` | `$FP new <dir> "<title>" "<request>" --route direct` | do the work; `$FP done RUN_ID '{"result": "…"}'` |
| `backlogged` | `$FP new <dir> "<title>" "<request>" --route backlogged`, then `$FP step RUN_ID intake hook.waiting '{"needs": "<missing context>"}'` | stop; the paused run is the backlog entry |
| `dropped` | `$FP new <dir> "<title>" "<request>" --route dropped` | `$FP done RUN_ID '{"reason": "…"}'` |

Record the score on the run: `$FP step RUN_ID intake step.completed '{"evaluation": {...}}'`.
Pass `--stop-after` when the user names a gate ("just scope it"); the conductor stops there and waits.

## 3. Say the gate

One line: `Gate: <route> (<why>)`, plus `stops after <stage>` for a pipelined run and the run id.
Example: `Gate: pipelined (CI change, risk medium), stops after scope. Run 3f2a…`

## Mid-flight

- **Escalate** a direct task that needs a PR, hits a sensitive path, or spreads past one file:
  `$FP new <repo-dir> "<title>" "<work done so far>" --from <direct RUN_ID> --escalate`, then
  `$FP done <direct RUN_ID> '{"escalated_to": "<new RUN_ID>"}'`. Say the new gate line.
- **Re-triage** a backlogged run when its context axis changes: re-score, then `$FP route RUN_ID <state>`.
