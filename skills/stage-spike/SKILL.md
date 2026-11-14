---
name: stage-spike
description: "Pipeline stage 2b. Run the scoper's spikes (one-off probes, prototypes or proofs of concept that test the assumptions a brief rests on) in throwaway worktrees, with a human approval for anything with side effects, and record what they showed. Loaded by a pipeline conductor such as feature-pipeline; not for direct use."
metadata:
  calls: ["run-ledger"]
---

# stage-spike

This stage runs only after scope returns `spike`. Record the results as the `spike`
stage record, then rerun scope with them.

A spike turns a guess into evidence before anyone builds on it. Examples: "is this
check enforced in that environment?", "does this SDK version parse that service's
responses?", "does the deploy work with separate keys per role?". A spike answers
one question and is then thrown away. Its result goes into the brief; its code
never lands.

## 1. Sort each spike by class

The scope record gives each spike a `class`. Check it against the experiment,
because the class decides who runs the spike and whether a person must approve it
first. When unsure, take the stricter class.

| Class | What it does | Runner | Approval |
| :--- | :--- | :--- | :--- |
| `read_only` | reads code, docs, service state or API answers; sends nothing | `scoper` | none |
| `local` | writes or runs code on this machine: a script, a test, a local environment | `builder` in a throwaway worktree | none |
| `side_effects` | spends money or touches anything shared: cloud resources, shared environments, posts, pushes | `builder`, once approved | a person first |

Before a `side_effects` spike starts, ask a person. Interactively, use
AskUserQuestion; otherwise pause the run with `hook.waiting`. The question says:

- what the spike creates or sends;
- what it costs;
- how it is cleaned up;
- the cheaper alternative, if there is one.

The options are `run`, `skip` (recorded as not run) and `run cheaper` (with notes).
Without a `run`, the spike does not run.

## 2. Throwaway worktrees

A `local` or `side_effects` spike gets its own worktree off the base branch:

```sh
git -C <checkout> worktree add <lanes_dir>/<run_id>-spike-<spike_id> -b spike/<run_id>/<spike_id> <base>
```

- The builder works only there and never pushes. It commits only if the spike
  needs a commit to run.
- Nothing from a spike worktree feeds the build stage. Builders start again from
  the base branch, so spike shortcuts cannot leak into the PR.
- When the spike reports, record its result, then remove the worktree and branch
  (`git worktree remove --force`, then `git branch -D`). Keep them only if a person
  asked to, and list them in `cleanup`.
- Tear down any cloud resource a spike created in this same stage, and record the
  teardown. A spike that cannot clean up stops the run for a person.

## 3. Dispatch

Send independent spikes at the same time. Each request carries only the spike's
contract:

- the assumption;
- the experiment;
- the pass and fail signals;
- the timebox;
- the worktree path.

The runner reports one JSON block:

```json
{"spike_id": "", "result": "pass|fail|inconclusive", "observed": "", "evidence": [], "minutes": 0}
```

Prefer a probe whose result cannot be an artifact of the probe itself. A simulated
write is not the write: a dry-run call can fail or succeed for reasons the real
operation would not. When a probe could mislead that way, use a local run instead.

A spike that hits its timebox stops and reports `inconclusive` with what it saw. It
does not keep digging. The point is a cheap answer, and an expensive one belongs in
the scoped work or with a person.

## 4. Hand back to scope

Send all the results to the **same** scoper session and rerun scope. The rerun
must pick `proceed`, `rescoped`, `need_more_information` or `defer`. It may not
return `spike` again: one round only, so a run cannot loop on spikes. An
`inconclusive` result becomes a `need_more_information` question or a `defer`,
not a second spike.

## Record

```json
{"spike": {"status": "ok", "verdict": "validated", "summary": "", "reasoning": "",
  "spikes": [
    {"spike_id": "", "assumption": "", "class": "read_only|local|side_effects",
     "runner": "scoper|builder", "approval": "not_needed|approved|skipped",
     "worktree": "", "result": "pass|fail|inconclusive|not_run",
     "observed": "", "evidence": [], "minutes": 0}
  ],
  "cleanup": [{"what": "worktree|branch|cloud", "ref": "", "done": true}],
  "next": "scope"}}
```

Verdicts:

- `validated`: every spike reported pass or fail.
- `partially_validated`: any spike is `inconclusive` or `not_run`. Name those in
  `reasoning`.
- `failed`: the stage could not run.

Also copy each spike's `class` into `scope.spikes`, so `fp approve` can see whether
any spike had side effects.
