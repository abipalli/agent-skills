---
name: stage-scope
description: "Pipeline stage 2. A read-only, high-reasoning scoping verdict on one work item: need_more_information, spike, defer, rescoped or proceed. It is judged against a four-part implementation-brief bar and an explicit list of load-bearing assumptions. Loaded by a pipeline conductor such as feature-pipeline; not for direct use."
metadata:
  calls: ["run-ledger"]
---

# stage-scope

Send the intake record to the **same** `scoper` session. The scoper reads the code
it needs, read-only, and returns the verdict. Record it as the `scope` stage record.

## Look for overlap first

Before deciding, check whether other work already owns these files or this goal:

- open worktrees: `git -C <checkout> worktree list`
- open PRs: `gh pr list --repo <github>`
- every `scope_sources` entry in `.feature-pipeline.json`
- other open pipeline runs for this repo: `$FP list`

If another lane, PR, plan or run owns the work, the verdict is `defer`, with
`align_with` naming that work.

## The bar for `proceed`

The brief must answer all four:

1. **What** to change: the observable behaviour after the change.
2. **Where** to look: files, modules or entry points, confirmed in the code.
3. **What pattern to copy:** an existing implementation of something similar.
4. **How success is checked:** the tests or commands that prove it.

A brief also rests on assumptions about the world outside the code:

- which configuration is live in an environment;
- which version a client talks to;
- whether a key, role or permission exists;
- whether an approach works at all.

List each assumption the plan depends on. If one is wrong, the build fails late,
after real work or real side effects.

## Verdicts

- **`proceed`:** all four are answered from the item plus the code, and no
  load-bearing assumption is untested.
- **`rescoped`:** the ask is valid but the wrong size or shape: too big for one
  change, or it hides a prerequisite. Give the smallest coherent slice that ships
  value, and put the rest in `deferred_remainder`.
- **`spike`:** the brief is otherwise clear, but one or more assumptions can only
  be settled by an experiment. List them as `spikes`; `stage-spike` runs them.
- **`need_more_information`:** a gap only a person can close. Each question offers
  options and a recommendation.
- **`defer`:** the work should not happen now. It is blocked by another change, a
  duplicate, already done, or out of scope for this repo. Name the blocker in
  `blocked_by`, or the overlapping work in `align_with`.

### Spike or ask?

Ask a person when they can answer faster or more reliably than an experiment: an
owner's intent, a policy, which credential to use, whether a cost is acceptable.

Spike when the answer lives in the system and anyone's memory of it may be stale:
what a service actually enforces, what a client actually parses, whether a flow
actually works end to end. A claim from a ticket or a chat that the plan depends
on ("X isn't enabled there yet") is a spike, not a fact.

### Writing spikes

Keep each spike to one question and the cheapest experiment that answers it.
Prefer, in order:

1. a read-only probe;
2. a local run;
3. a run against shared or paid infrastructure.

Use the third only when nothing cheaper answers the question, and say why in
`why_not_cheaper`. Allow at most 3 spikes. If more are needed, the work is not
understood yet, so the verdict is `need_more_information`.

A rerun of scope after the spike stage cannot return `spike`.

## Record

```json
{"scope": {"status": "ok", "verdict": "proceed", "summary": "", "reasoning": "",
  "brief": {"what": "", "where": [], "pattern": "", "success_check": []},
  "assumptions": [{"assumption": "", "tested": "yes|no|n/a", "evidence": ""}],
  "risk": "low|medium|high",
  "sensitive_areas": [],
  "questions": [{"question": "", "options": [], "recommendation": ""}],
  "spikes": [
    {"spike_id": "", "assumption": "", "why_it_matters": "",
     "experiment": "", "class": "read_only|local|side_effects",
     "why_not_cheaper": "", "timebox_minutes": 30,
     "pass_signal": "", "fail_signal": "", "if_pass": "", "if_fail": ""}
  ],
  "rescope_delta": "",
  "deferred_remainder": [],
  "blocked_by": "",
  "align_with": "",
  "next": "build"}}
```

- `sensitive_areas` lists anything touching security, auth, money, data
  migrations, public APIs, CI or dependencies. Auto-approval refuses any run where
  this list is not empty.
- `if_pass` and `if_fail` say what the brief or verdict becomes for each result,
  so the rerun after spikes is mechanical.
- `risk` must be `low` for auto-approval. When in doubt, pick the higher risk.
