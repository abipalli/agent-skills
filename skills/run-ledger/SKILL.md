---
name: run-ledger
description: "Durable pipeline state on LiteLLM workflow runs (scripts/feature-pipeline.py): record stages, run repo gates, apply the auto-approve policy. Loaded by pipeline skills; use directly for \"pipeline status\", \"show run <id>\"."
metadata:
  calls: []
---

# run-ledger

`scripts/feature-pipeline.py`, next to this file, is the only way to read or write a run. It uses
Python's standard library only.

```sh
FP=<this skill's directory>/scripts/feature-pipeline.py
$FP new <repo-dir> "<title>" "<request>" [--from RUN_ID] [--stop-after <stage>] [--route direct|backlogged|dropped]
                                           # → RUN_ID; --from links a task or investigation;
                                           # --stop-after makes step.started refuse later stages;
                                           # --escalate (needs --from) marks direct work moving onto the pipeline
$FP route RUN_ID <state> "<reason>"        # pipelined|direct|backlogged|dropped; logs route.changed
$FP list [paused|running|completed|...]    # RUN_ID  status  repo  stage  title
$FP show RUN_ID                            # run, metadata, events, messages
$FP step RUN_ID <stage> <event> '<json>'   # append an event; merge the JSON into metadata
$FP note RUN_ID <role> "<text>"            # a message: question, answer, review finding
$FP gates RUN_ID                           # run the repo's gates in the run's worktree
$FP approve RUN_ID                         # repo policy → exit 0 auto, exit 3 human
$FP done RUN_ID '<json output>'            # mark completed
$FP config <repo-dir>                      # effective repo config (defaults when no file)
$FP selftest [repo-dir...]                 # policy self-check plus repo config check, no network
```

## Run kinds

`FP_WORKFLOW_TYPE` picks the kind; the default is `feature-delivery`.

| Kind | Opened by | Ends with |
| :--- | :--- | :--- |
| `feature-delivery` | a pipeline conductor | a PR, through `fp approve`. The only kind that can merge. |
| `investigation` | a scoper, for an open-ended question or proof of concept | `fp done` with the finding and a recommendation. Its code never lands. |
| `task` | the owner's assistant, handing work off | the company lead closes it with a report. It holds no code. |

- `fp approve` refuses every kind except `feature-delivery`.
- Investigations follow `stage-spike`'s classes: anything with side effects
  waits for a person.
- A good investigation result is carried forward by a new `feature-delivery` run
  opened with `--from` that links back to it. The investigation run itself never
  becomes one.
- Add a kind only when its end state, its gate or its readers differ. Put the
  topic, repo or agent in metadata instead.

## Merge guard

`fp guard` is a Claude Code `PreToolUse` hook for `Bash`. It blocks `gh pr merge`
unless the PR's feature-delivery run allows it:

- `metadata.operator_decision.decision` is `approve`; or
- `fp approve` said `auto` and the repo's `policy.auto_merge` is true.

It finds the run by the PR URL or number in the command. Without one, it uses
the run whose worktree is the current directory. It also blocks when it can't
reach the ledger.

```json
{"hooks": {"PreToolUse": [{"matcher": "Bash",
  "hooks": [{"type": "command", "command": "<this skill's directory>/scripts/feature-pipeline.py guard"}]}]}}
```

It stops mistakes and a conductor that drifts from the rules. It can't stop an
agent that writes a fake decision with the same key, so keep branch protection
on the base branch.

## Prerequisites

Nothing by default: with no LiteLLM key configured, runs are JSON files under
`~/.local/state/feature-pipeline/runs` (`FP_STORE_DIR`). To share runs with a UI,
use LiteLLM instead (`FP_STORE=litellm` forces it):

- A LiteLLM proxy (v1.81 or later) with workflow runs. Set `FP_LITELLM_URL`;
  the default is `http://127.0.0.1:4000`.
- A virtual key in `FP_LITELLM_KEY` or `~/.config/feature-pipeline/key`. The key
  only needs the workflow-run routes. LiteLLM shows a run only to the key that
  created it, unless the key belongs to an admin user, so a UI that should see
  every client's runs needs such a key.
- Optionally, `.feature-pipeline.json` in the target repo (see "Repo config").

## Events

Event names drive the run's status. Any other name is logged without changing it.

| Event | Run status | Use it when |
| :--- | :--- | :--- |
| `step.started` | running | a stage begins |
| `step.completed` | (unchanged) | a stage finishes; carries its record |
| `hook.waiting` | paused | the run waits for a human: a question, an approval |
| `hook.received` | running | the human answered; carries the answer |
| `step.failed` | failed | a stage could not run |

A paused run is the human inbox. A UI that mirrors runs can show it as a decision,
for example the Paperclip bridge. Writing the answer back is two steps: append
`hook.received`, and set `metadata.operator_decision` to
`{decision, note, via, at}`. A conductor resuming a paused run reads that field
first.

Routing state lives in metadata and events, so it can be queried:

- `metadata.route`: `pipelined` (set by `new`), `direct`, `backlogged` or `dropped`. `fp list` shows it.
- `metadata.stop_after`: a stage id; `step.started` refuses any later stage (`scope` also allows `spike`).
- `route.changed` event, data `{from, to, reason}`, written by `fp route` and by `new` (from `triaged`). With `new --escalate` it also
  carries `source`, the `--from` reference. `fp route` refuses moves the state machine in
  `feature-pipeline` does not allow.

## Stage records

When a stage finishes, merge one record under the stage's id:

```sh
$FP step RUN_ID scope step.completed '{"scope": {
  "status": "ok", "verdict": "proceed",
  "summary": "One or two plain sentences: what this stage decided.",
  "reasoning": "Why, with the evidence it rests on.",
  "agent": {"name": "scoper", "model": "opus"},
  ...stage-specific fields...,
  "next": "build"}}'
```

- `status` is `ok` or `failed`. A `failed` record needs a `reasoning` that says
  what broke.
- `verdict` is one of the stage's verdicts. `next` is the stage to route to, or
  `stop`.
- Stage-specific fields sit next to these, and each stage skill defines its own.
- A stage that reruns overwrites its record; the event history keeps every round.

`fp approve` reads these metadata keys, so stages must write them exactly:

- `scope.{risk, sensitive_areas, verdict, spikes}`
- `review.{rounds, critical, high, open_medium}`
- `gates`, which `fp gates` writes for you
- `worktree`

## Repo config

Optional. Without it, `feature-pipeline.py` uses defaults: base = the remote's default branch (`origin/HEAD`), `lanes_dir`
`../<repo>-lanes`, `branch_prefix` `fp/`, no gates, and every approval goes to a
person. `$FP config <repo-dir>` prints the effective values; stages read them there.

`.feature-pipeline.json` lives at the root of the repo's **main checkout**. `feature-pipeline.py`
always reads it from there, never from the branch being approved, so a change
cannot loosen its own rules. A diff that touches it always goes to a human.

```json
{
  "github": "owner/name",
  "base": "origin/main",
  "lanes_dir": "../name-lanes",
  "branch_prefix": "fp/",
  "gates": {"test": "cargo test --workspace", "lint": "cargo clippy -- -D warnings"},
  "scope_sources": ["docs/plans/*.md"],
  "notes": "Repo rules a builder must follow.",
  "policy": {
    "max_lines": 300, "max_files": 10, "max_rounds": 3,
    "auto_merge": false,
    "human_paths": {"ci": [".github/"], "deps": ["Cargo.toml", "package.json"]},
    "human_removed_lines": {"public api": "^-\\s*pub fn"}
  }
}
```

- A file must set `base`, `lanes_dir`, `branch_prefix` and `gates`. `lanes_dir` is
  relative to the main checkout.
- Policy defaults: 300 lines, 10 files, 3 review rounds, `auto_merge: false`, and
  no path rules.

Auto-approve needs all of the following. Anything else goes to a human, and
`fp approve` lists the reasons.

- **Scope:** `risk` is low, there are no sensitive areas, the verdict was not
  `rescoped`, and no spike had side effects.
- **Review:** no critical or high findings, and every medium finding is either
  fixed or deferred with a reason, all within `max_rounds`.
- **Gates:** every gate passes.
- **Diff:** no human path hit, no matching removed line, no binary files, within
  the size caps, and the worktree is clean.

Even when `fp approve` says auto, the change only merges without a person if
`auto_merge` is true. Otherwise auto means "ready for review".
