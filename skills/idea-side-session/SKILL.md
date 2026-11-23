---
name: idea-side-session
model: sonnet
effort: low
description: "Take a spontaneous idea into its own side session and the feature pipeline: score it, open a run, run a question register into scope, and leave it backlogged or ready to build. Use for \"would be nice to…\", \"what if…\", \"open a side session for it\"."
metadata:
  calls: ["work-evaluation", "run-ledger", "stage-intake", "stage-scope", "feature-pipeline"]
---

# Idea side session

A front end to `feature-pipeline` for ideas that arrive mid-task. The main session keeps its
thread; each idea gets its own herdr tab and its own pipeline run, so it can be resumed, shown in
Paperclip, and built later with `feature-pipeline` from where it stopped.

## 1. Catch it

Restate the idea in one sentence and score it with `work-evaluation`. Tell the user it is going
to a side session and carry on with the main task.

## 2. Open the run (stage-intake)

Load `run-ledger`, then follow `stage-intake` with the idea as free text: `$FP new <repo-dir>
"<title>" "<the user's words, verbatim>"`. Record the `work-evaluation` vector on the run:

```sh
$FP step RUN_ID intake step.completed '{"intake": {...}, "evaluation": {"value": "", "risk": "",
  "complexity": "", "context": "", "decision": "", "scored_on": ""}}'
```

An idea with no repo yet cannot open a pipelined run. Record it
as a plan doc (`docs/plans/<idea>.md`) or a Machina `work_item` with the same vector, and say so.

## 3. Side session and brief

One herdr tab per idea, in the workspace of the repo it belongs to:

```
herdr tab create --workspace <ws> --cwd <scratch dir> --label "<idea>" --no-focus
herdr agent start <name> --kind claude --pane <pane> -- --model haiku
```

A folder Claude Code has not seen asks the user to trust it; let the user answer. Write
`brief.md` there from the intake record (with `design-brief` when the idea is a product
experience): context, the proposed experience, constraints and house rules. The side agent does
not share the main conversation, so the brief must stand alone.

## 4. Question register (lightweight pre-pass to scope)

Prompt the side agent to walk through the brief as a skeptical reviewer and write `register.md`:
a table of scope and feature questions (ID, area, question, why it matters, options, suggested
default, phase it blocks, who decides), assumptions that may be wrong, and the smallest useful
first slice. Attach it to the run: `$FP note RUN_ID scoper "<path to register.md>"`.

## 5. Scope (stage-scope, main session as scoper)

Read the register as the scoper would, then follow `stage-scope`:

- correct rows that rest on a wrong assumption, merge duplicates, and promote the question that
  changes the design;
- accept defaults that need no one; the rest become the record's `questions`, each with options
  and a recommendation;
- the register's assumptions become `assumptions`; ones only the system can settle become
  `spikes`;
- its first slice is the `rescoped` brief, the rest `deferred_remainder`.

Return the stage's verdict. `need_more_information` goes to the user (AskUserQuestion, or
`hook.waiting` so it shows in the Paperclip inbox); rerun scope with the answers.

## 6. Backlog or build

- **`defer`**, or a `work-evaluation` decision of backlog: pause the run with `hook.waiting`,
  naming the missing context, and record it with `$FP route RUN_ID backlogged "<missing context>"`.
  The run is the backlog entry.
- **`proceed`** or **`rescoped`** with context available now: hand the run to `feature-pipeline`
  ("resume job RUN_ID"), which builds, reviews and stops at approval.

## 7. Evaluate prescriptive against descriptive

After approval (or after a build outside the pipeline), compare the plan (prescriptive: the scope
brief and decisions) with what exists (descriptive: the code, deployed config, observed
behaviour). Record it on the run:

```sh
$FP step RUN_ID retro step.completed '{"retro": {"realizations": [], "drift": [],
  "learnings": [], "rescored": {}}}'
```

- **Realizations:** where the build taught something the plan did not know.
- **Drift:** where plan and build disagree, and which one is right.
- **Learnings:** facts that hold beyond this idea. Re-score related backlog runs with
  `work-evaluation` where they change the context axis.

## 8. Report

Tell the user the verdict, the run id, where the idea is recorded, and what needs them next.
Close the herdr tab when the run is paused, handed to the pipeline, or done.
