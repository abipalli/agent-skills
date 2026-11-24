---
name: stage-build
description: "Pipeline stage 3: plan tasks, delegate each to a builder in a worktree, gate on checks. Loaded by a pipeline conductor such as feature-pipeline."
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
- `depends_on`, a list of task ids;
- `interfaces`: what the task produces for later tasks (exact names and types)
  and what it consumes from earlier ones. Builders see only their own task, so a
  name agreed here is the only way parallel tasks meet at merge;
- `review_focus`: up to 5 inputs or failures the brief implies that no check
  exercises yet, most likely first. The owning task adds a test for each, and the
  list goes to the reviewers.

Map every `acceptance_criteria` entry from intake to the task and test that
cover it, in `coverage`. A criterion with no task is a planning gap: rescope or
add a task before dispatching.

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
- the repo's `notes` from `.feature-pipeline.json`;
- the comment rule: match the file's comment style and sibling names; a comment says only what the
  code can't (no copied config values, no restating the code, no rationale, which goes in the PR body).
  Paste in `~/.agents/rules/code-comments.md` instead when it exists.

Send independent tasks at the same time. Pass the contract, not your history: the
builder starts with a fresh context on purpose. Use a stronger model only for a
task in an area the scope marked `risk: high`.

A builder may stop early. On `needs_context`, answer its question in the same
session. If it asks again, re-dispatch on a stronger tier or split the task. On
`done_with_concerns`, read the concerns before gating; they go to the reviewers.

## 4. Gates before review

When a builder reports, run its success check yourself in its worktree. If it is
red, send the failure output back to the same builder session. Review does not
start while any task is red.

- **The check must be able to fail.** For a behaviour change or a bug fix, the
  builder runs the new test before implementing and reports the failing line as
  `red`. A check that never went red is not evidence; send it back.
- **Cap the fix loop.** If the same check is red twice, the builder states the
  root cause and its evidence before the next attempt, and changes one thing at a
  time. After 3 failed fixes, stop the task as `partially_built`: the problem is
  in the brief or the design, so it goes back to scope, not another round.

Once every task is merged into the lane, run `$FP gates RUN_ID`. It runs the repo's
configured gates in the lane worktree and records the results. If it fails, the
failing output goes back to the builder that owns the files.

## Record

```json
{"build": {"status": "ok", "verdict": "built", "summary": "", "reasoning": "",
  "plan": [{"task_id": "", "goal": "", "files": [], "depends_on": [],
            "interfaces": {"produces": [], "consumes": []}, "review_focus": []}],
  "coverage": [{"criterion": "", "task_id": "", "test": ""}],
  "tasks": [{"task_id": "", "worktree": "", "branch": "", "base_sha": "", "head_sha": "",
             "status": "done|done_with_concerns|needs_context|blocked",
             "red": "<failing line before the change>",
             "check": "<exact command>", "check_result": "passed|failed"}],
  "next": "review"}}
```

The verdict is `built` when every check and gate passes, and `partially_built`
otherwise. Name the gap in `reasoning`.
