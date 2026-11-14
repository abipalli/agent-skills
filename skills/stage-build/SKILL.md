---
name: stage-build
description: "Pipeline stage 3. Plan a scoped brief into the fewest independent tasks, give each task to a builder in its own worktree, gate every task on its success check, and merge the tasks into one lane branch for review. Loaded by a pipeline conductor such as feature-pipeline; not for direct use."
metadata:
  calls: ["run-ledger"]
---

# stage-build

You plan; builders write the code. Record the result as the `build` stage record
when every task has reported.

## 1. Plan

Split the brief into the fewest tasks that can each be built and tested on their
own. One task is fine, and usual. Each task gets:

- a `task_id` and a one-line goal;
- the files it owns (no two tasks own the same file);
- the pattern to copy and the success check, both taken from the brief;
- `depends_on`, a list of task ids.

## 2. Lane and worktrees

The run has one **lane**, a short kebab-case slug, on branch
`<branch_prefix><lane>` in `<lanes_dir>/<lane>`, created off `base`:

```sh
git -C <checkout> fetch origin
git -C <checkout> worktree add <lanes_dir>/<lane> -b <branch_prefix><lane> <base>
$FP step RUN_ID build step.started '{"lane": "<lane>", "branch": "<branch>", "worktree": "<path>"}'
```

- **One task:** it runs in the lane worktree.
- **Several tasks:** each gets its own worktree off the lane branch
  (`<lanes_dir>/<lane>-<task_id>`, branch `<branch>-<task_id>`). When a task is
  green, merge it into the lane branch. The files are disjoint, so the merge
  cannot conflict.
- Never start from a `spike/` branch. Spikes answer questions, and their code is
  not reviewed.

## 3. Dispatch

For each task whose dependencies are done, dispatch a `builder` with:

- the absolute worktree path;
- the task contract;
- the success check;
- the repo's `notes` from `.feature-pipeline.json`.

Send independent tasks at the same time. Pass the contract, not your history: the
builder starts with a fresh context on purpose. Use a stronger model only for a
task in an area the scope marked `risk: high`.

## 4. Gates before review

When a builder reports, run its success check yourself in its worktree. If it is
red, send the failure output back to the same builder session. Review does not
start while any task is red.

Once every task is merged into the lane, run `$FP gates RUN_ID`. It runs the repo's
configured gates in the lane worktree and records the results. If it fails, the
failing output goes back to the builder that owns the files.

## Record

```json
{"build": {"status": "ok", "verdict": "built", "summary": "", "reasoning": "",
  "plan": [{"task_id": "", "goal": "", "files": [], "depends_on": []}],
  "tasks": [{"task_id": "", "worktree": "", "branch": "", "base_sha": "", "head_sha": "",
             "check": "<exact command>", "check_result": "passed|failed"}],
  "next": "review"}}
```

The verdict is `built` when every check and gate passes, and `partially_built`
otherwise. Name the gap in `reasoning`.
