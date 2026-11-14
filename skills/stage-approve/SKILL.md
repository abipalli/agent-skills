---
name: stage-approve
description: "Pipeline stage 5: apply the repo's approval policy, open the PR, merge or hand to a person. Loaded by a pipeline conductor such as feature-pipeline."
metadata:
  calls: ["run-ledger"]
---

# stage-approve

AI review misses things a person would catch, so auto-approval exists for low
stakes only and never replaces a repo's CODEOWNERS.

## 1. Rebase and decide

```sh
git -C <worktree> fetch origin && git -C <worktree> rebase <base>
```

If the rebase changed anything, run `$FP gates RUN_ID` again. Then run `$FP approve
RUN_ID`, which records `approve.decided`:

- **exit 0 (auto):** every rule in `run-ledger`'s policy passed;
- **exit 3 (human):** the output lists the reasons.

The policy is code, not judgement. Don't override an exit 3.

## 2. Open the PR

Open it either way:

```sh
git -C <worktree> push -u origin <branch>
gh pr create --repo <github> --head <branch> --base <base without origin/> [--draft] --title ... --body ...
$FP step RUN_ID approve pr.opened '{"pr": "<url>"}'
```

- Open it as `--draft` unless the decision is auto **and** `policy.auto_merge` is
  true.
- The PR body states the problem, the approach, the alternatives considered, how
  it was verified, the review rounds, and the approval decision with its reasons.
  It does not list commits or files.
- No AI attribution: no `Co-authored-by` or "Generated with" trailers.

## 3a. Auto, with `auto_merge: true`

1. `gh pr merge <url> --squash`. Don't pass `--delete-branch`: it would switch
   branches in the main checkout.
2. `git -C <checkout> push origin --delete <branch>`
3. `git -C <checkout> worktree remove <worktree>`
4. `$FP done RUN_ID '{"pr": "<url>", "merged": true}'`

If the merge is refused (branch protection, conflicts), go to 3b with the reason.

## 3b. A person decides

Pause the run with `$FP step RUN_ID approve hook.waiting '{"approval_note": "..."}'`.
A UI that mirrors runs shows it as a decision. If you are interactive, also ask
with AskUserQuestion. Put the full case in front of them:

- the scope brief, and the `rescope_delta` if there is one;
- each spike's assumption, result and evidence;
- what changed: tasks, files, check and gate results;
- the panel's confirmed and plausible findings, non-blocking ones included;
- the policy's reasons, your recommendation and why.

The options are `approve`, `changes_requested` (with notes) and `reject`. The answer
arrives either in-session or as `metadata.operator_decision` on the run. Record it
with `hook.received`.

- **`approve`:** merge as in 3a, or leave the merge to the person when they say so.
  Then `$FP done`.
- **`changes_requested`:** send the notes to the same builder sessions, then rerun
  review.
- **`reject`:** close the PR, leave the worktree for inspection, and run `$FP done
  RUN_ID '{"rejected": true}'`.

## Record

```json
{"approve": {"status": "ok", "verdict": "approved", "summary": "", "reasoning": "",
  "approval": {"decision": "auto|human", "reasons": []},
  "decision": {"choice": "approve|changes_requested|reject", "by": "policy|human", "notes": ""},
  "pr": "", "merged": false,
  "next": "stop"}}
```
