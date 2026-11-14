---
name: stage-review
description: "Pipeline stage 4. A review panel runs parallel lanes over one diff: a deep correctness review, an over-engineering review, and a conventions review. A validator then dedupes the findings and checks each one against the code, giving one verdict and the severity counts the approval policy reads. Loaded by a pipeline conductor such as feature-pipeline; not for direct use."
metadata:
  calls: ["run-ledger", "deep-code-review", "ponytail-review", "rust-review"]
---

# stage-review

Reviewers are read-only. When the runtime offers a choice, run the reviewers on a
different model family than the builders, because the same family tends to miss
its own mistakes. Record the result as the `review` stage record.

## 1. Snapshot

Write the lane's diff to a file:

```sh
git -C <worktree> diff <base>...HEAD > <lanes_dir>/<run_id>-review.diff
```

Then create a detached review worktree at the lane head:

```sh
git -C <checkout> worktree add --detach <lanes_dir>/<run_id>-review <head_sha>
```

Reviewers read only there, never in a builder's worktree.

## 2. Lanes

Run the lanes in parallel. Each `reviewer` gets:

- the diff path;
- the review worktree path;
- the base and head SHAs;
- the scope brief;
- the lane's instruction.

| Lane | Instruction |
| :--- | :--- |
| `deep` | Run the `deep-code-review` skill on this diff. Also judge whether it solves the brief. |
| `ponytail` | Run the `ponytail-review` skill: what in this diff need not exist? Skip this lane if the skill isn't installed, and say so. |
| `conventions` | Check code quality and repo conventions: read the repo's CLAUDE.md, AGENTS.md or CONTRIBUTING and the nearby code, and flag drift. For a Rust diff, also run `rust-review`. |

Each lane returns its findings as JSON:

```json
[{"id": "", "lane": "", "severity": "critical|high|medium|low", "file": "", "line": 0,
  "claim": "", "evidence": "", "fix": ""}]
```

A lane that errors, or returns nothing parseable, is recorded as
`{"lane": "...", "status": "failed"}`. It still counts in the verdict.

## 3. Validator

After all the lanes return, dispatch one more `reviewer` with every lane's
findings. It must:

- merge duplicates across lanes;
- check each finding against the code at `head_sha`, marking it `confirmed`,
  `plausible` or `rejected` (with a reason);
- keep severity honest. `critical` means data loss, a security hole or a broken
  build; `high` means a real defect or a violation of the brief.

Record every surviving finding with `$FP note RUN_ID reviewer "<severity>
<file:line> <claim>"`.

## Verdict and counts

Count the confirmed and plausible findings **before anything is fixed**, and never
rewrite a round's counts afterwards:

```sh
$FP step RUN_ID review review.round '{"review": {"rounds": n, "critical": C, "high": H, "open_medium": M}}'
```

- **`clean`:** C = H = M = 0 and no lane failed. A medium that an earlier round
  answered with a deferral reason doesn't count again.
- **`changes_requested`:** anything else that ran. The conductor sends the
  findings to the builders. Each builder answers every finding with `$FP note
  RUN_ID builder "<fixed|deferred: reason> <finding>"`, then the next round
  reviews the new diff.
- **`failed`:** the validator failed, or two or more lanes failed.

Remove the review worktree when the stage ends.

## Record

```json
{"review": {"status": "ok", "verdict": "clean", "summary": "", "reasoning": "",
  "rounds": 1, "critical": 0, "high": 0, "open_medium": 0,
  "head_sha": "",
  "lanes": [{"lane": "deep", "status": "ok|failed", "finding_count": 0}],
  "findings": [{"id": "", "lanes": [], "severity": "", "validation": "", "file": "", "line": 0, "claim": "", "fix": ""}],
  "next": "approve"}}
```
