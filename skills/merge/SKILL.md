---
name: merge
description: "Approve and merge a GitHub pull request with no additional review comments. Use this skill whenever the user invokes `/merge`, says \"approve and merge\", \"merge this PR\", \"approve the PR without comments\", or asks for a GitHub PR to be approved and merged as a single workflow. This skill should always use GitHub's squash-and-merge flow: identify the target PR, submit an approval review with an empty body, and squash-merge or enable squash auto-merge without posting extra commentary on the PR."
---

# Merge

Use this skill to approve a GitHub pull request without adding review comments,
then squash-merge it through GitHub.

## Operating Model

- Treat `/merge` as explicit permission to approve and merge the target PR.
- Do not perform a fresh code review unless the user explicitly asks for one.
- Use the GitHub CLI (`gh`) and GitHub's branch protection rules. Do not bypass
  protections with admin privileges unless the user explicitly requests it.
- Keep the PR clean: never add a top-level approval comment such as "LGTM" or a
  summary paragraph. Approval is conveyed by the review event itself.
- Always use squash-and-merge. Do not use merge commits or rebase merges, and do
  not ask the user to choose a merge method.
- Ask a question only when the target PR is genuinely ambiguous.

## Required Tools

- `gh` CLI authenticated with permission to review and merge the target PR
- `git` when resolving the current branch's PR
- Network access to GitHub

## Workflow

### 1. Resolve The Target PR

If the user supplied a PR URL, PR number, or `owner/repo#number`, use it. If they
only invoked `/merge`, resolve the PR from the current branch:

```bash
gh pr view --json number,url,title,state,isDraft,headRefName,baseRefName
```

If this fails because there is no PR for the current branch, ask the user which
PR to merge. If multiple repositories or PRs are plausible, ask for the exact
target instead of guessing.

### 2. Inspect Merge Readiness

Fetch enough metadata to avoid surprising the user:

```bash
gh pr view <selector> \
  --json number,url,title,state,isDraft,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup,headRefOid,headRefName,baseRefName
```

Stop and report clearly if the PR is closed, already merged, or still a draft.
If checks are failing or GitHub reports conflicts, do not approve-and-merge;
explain the blocker in the final response.

Pending required checks are different from failures. If GitHub will not merge
immediately only because required checks are pending, enable auto-merge after
approval instead of polling indefinitely.

### 3. Require Squash Merge

Always merge with `--squash`. This keeps `/merge` predictable and avoids changing
the repository history style from one invocation to the next.

Check that squash merge is allowed:

```bash
gh repo view --json squashMergeAllowed
```

If squash merge is not allowed for the repository, stop and report that blocker.
Do not fall back to `--merge` or `--rebase`.

### 4. Approve With No Comment

Submit an approval review with an empty body:

```bash
gh pr review <selector> --approve
```

Do not pass `--body`. If you need to use the API instead, send `"body": ""`.

If GitHub rejects the approval because the authenticated user authored the PR or
has already approved it, do not invent a workaround comment. Continue to the
merge step only if GitHub permits the merge, and tell the user exactly what
happened.

### 5. Merge

Use a non-interactive squash merge command:

```bash
gh pr merge <selector> --squash
```

If GitHub refuses immediate merge only because required checks are still pending,
enable squash auto-merge:

```bash
gh pr merge <selector> --squash --auto
```

Do not pass `--delete-branch`. Branch cleanup is outside this skill's scope
because it adds an extra operation and can fail independently of the merge.

Do not use `--admin` unless the user explicitly asked to bypass branch
protection.

### 6. Confirm The Result

Return a concise final response with:

- PR title or number and link
- Whether approval was submitted, skipped because already present, or rejected
  by GitHub
- Whether the PR was merged immediately or auto-merge was enabled
- Squash merge was used
- That branch deletion was not attempted

Keep the response factual and short. Do not paste command transcripts unless the
user asks for them.
