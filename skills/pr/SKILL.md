---
name: pr
model: opus
effort: high
metadata:
  calls: ["deep-code-review"]
description: "Create GitHub pull requests from a fork-first workflow. Use this skill whenever the user invokes `/pr`, asks you to make changes and open a PR, says \"create a PR\", \"open a pull request\", \"push this branch to my fork\", or provides change context that should become a GitHub PR. This skill should drive the whole workflow: create or reuse the authenticated user's fork remote, sync the fork's default branch from the upstream repo, create a branch on the fork, make and verify the requested changes, push to the fork branch, and create the PR back to the upstream repository."
---

# PR

Use this skill to turn the user's change context into a GitHub pull request using
their fork as the head repository.

## Operating Model

- Treat the text after `/pr` as the context for the change to implement.
- Prefer doing the work end to end. Ask a question only when the requested change
  or target repository is genuinely ambiguous.
- Use the GitHub CLI (`gh`) and Git. Avoid browser-only PR creation unless the CLI
  is blocked.
- Keep the user's uncommitted work safe. Inspect it, preserve it, and never
  reset, discard, or silently stash changes.
- Use the repository's actual default branch. Do not assume `main`.
- Use a fork remote owned by the authenticated GitHub user. If the current remote
  already points to that fork, reuse it instead of adding a duplicate.

## Required Tools

- `git`
- Authenticated `gh` CLI with access to the target repository
- Network access to GitHub

## Workflow

### 1. Understand The Request

Identify:

- The requested code or documentation change.
- The target repository.
- Any branch name, PR title, issue number, reviewers, labels, or draft/ready
  preference the user supplied.

If the user did not provide a branch name, create one from the context using
`<type>/<ticket>-<short-kebab-slug>`, or `<type>/<short-kebab-slug>` when there
is no ticket, for example `feat/PROJ-361-session-threading` or
`docs/demo-runbook`. Infer the same type vocabulary used for Conventional Commit
titles. The slash after the type is required; do not create flat names such as
`feat-PROJ-361-session-threading` or generic agent-prefixed names such as
`codex/...` or `claude/...`. Preserve an exact branch name when the user
explicitly supplies one, and follow a stricter local repository convention when
one exists.

### 2. Inspect Repository State

Run these checks before changing branches or remotes:

```bash
git rev-parse --show-toplevel
git status --short
git branch --show-current
git remote -v
gh auth status
gh repo view --json name,nameWithOwner,defaultBranchRef,parent,isFork,owner,url
```

If the worktree is dirty:

- Decide whether the changes are part of the user's requested PR.
- If they are relevant, carry them forward carefully onto the PR branch.
- If they are unrelated or hard to classify, pause and ask which changes belong
  in the PR.

### 3. Identify Upstream And Fork

Determine the upstream repository that should receive the PR:

- If the current GitHub repo is a fork, use its `parent.nameWithOwner` as the
  upstream target.
- Otherwise, use the current repo's `nameWithOwner` as the upstream target.

Determine the authenticated GitHub user and desired fork repo:

```bash
GH_USER=$(gh api user --jq .login)
UPSTREAM_REPO=<owner/repo>
REPO_NAME=$(gh repo view "$UPSTREAM_REPO" --json name --jq .name)
DEFAULT_BRANCH=$(gh repo view "$UPSTREAM_REPO" --json defaultBranchRef --jq .defaultBranchRef.name)
FORK_REPO="$GH_USER/$REPO_NAME"
```

If the upstream repository is already owned by `GH_USER`, a separate fork is not
needed. In that case, use the existing write remote as the head remote and still
create a feature branch.

### 4. Create Or Reuse The Fork Remote

First check whether the fork exists:

```bash
gh repo view "$FORK_REPO" --json nameWithOwner,url
```

If it does not exist, create it:

```bash
gh repo fork "$UPSTREAM_REPO" --clone=false --default-branch-only
```

Find an existing local remote whose URL points at `FORK_REPO`. If one exists,
use that as `FORK_REMOTE`. Common cases are `origin`, `fork`, or the user's
login.

If no local remote points at the fork, add one. Prefer the name `fork`; if that
name is already used for a different repository, use the GitHub login or a
similarly clear name.

```bash
git remote add fork "https://github.com/$FORK_REPO.git"
FORK_REMOTE=fork
```

Avoid running `gh repo fork --remote` without `--remote-name` in an existing
clone because it can rename the current `origin` remote. If you use `--remote`,
pass an explicit remote name.

### 5. Sync The Fork Default Branch

Bring the fork's default branch up to date from upstream before branching:

```bash
gh repo sync "$FORK_REPO" --source "$UPSTREAM_REPO" --branch "$DEFAULT_BRANCH"
git fetch "$FORK_REMOTE" "$DEFAULT_BRANCH"
```

If `gh repo sync` reports that the fork default branch cannot be fast-forwarded,
stop and explain the situation. Only use `--force` after explicit user approval,
because it hard-resets the fork's default branch to upstream.

### 6. Create The PR Branch

Create the feature branch from the synced fork default branch:

```bash
git switch -c "$BRANCH_NAME" "$FORK_REMOTE/$DEFAULT_BRANCH"
git config "branch.$BRANCH_NAME.gh-merge-base" "$DEFAULT_BRANCH"
```

Before creation, verify an inferred name contains the required slash-delimited
type prefix. Examples: `fix/PROJ-410-finalization`, `chore/ci-cleanup`.

If the requested branch already exists:

- Reuse it if it clearly belongs to this task.
- Otherwise create a unique suffix or ask before overwriting anything.

If relevant dirty work was present before the branch switch, verify it carried
over cleanly with `git status --short` and `git diff`.

### 7. Make And Verify The Changes

Implement the requested change on the PR branch. Follow the repository's local
instructions, style, and test conventions.

Before committing:

```bash
git diff
git status --short
```

Run the narrowest meaningful verification first, then broader checks if the
change touches shared behavior. If tests cannot be run, record why for the PR
body and final response.

Commit only the intended files:

```bash
git add <intended-files>
git commit -m "<concise commit message>"
```

If the user already had relevant commits, do not rewrite them unless needed.

### 7.5 PR Readiness Gate

Before pushing or opening a non-draft PR, run a reviewer-minded readiness pass
over the final diff. Use `deep-code-review` as the shared home for this pass
rather than duplicating a separate checklist here.

Marking an existing draft PR ready for review counts as opening a non-draft PR:
run this gate then too, against the PR's current head at that moment, not the
diff as it existed when the draft was opened.

Apply extra scrutiny to changes that touch manifest or config schemas, remote
provisioning scripts, public/private repository filtering, sidecar or
cross-service integration, or the repository's own high-risk areas named in its
local instructions.

The gate should answer:

- Can a reviewer reproduce the promised behavior from this branch, or are any
  stacked PRs, branch images, CI artifacts, secrets, hardware, or internal tools
  still required and documented?
- If the repository publishes a filtered or sanitized public tree, do
  public-tree files, Make targets, scenarios, and docs still work after
  filtering, without leaking internal-only pipeline details?
- Do scripts fail fast for invalid flags, missing files/images/tools,
  contradictory options, unsupported platforms, and warm retries?
- Do config/schema changes keep parsers, shell helpers, Terraform/cloud-init,
  docs, and tests aligned, including defaulted and legacy syntax cases?

If the pass finds material issues, fix them before creating or marking the PR
ready. If a live infra or hardware check is impossible, state the skipped check
and residual risk in the PR body.

### 8. Push To The Fork Branch

Push the branch to the fork remote:

```bash
git push -u "$FORK_REMOTE" "$BRANCH_NAME"
```

Confirm the local branch is tracking the fork branch, not the upstream repo's
protected branch:

```bash
git status --branch --short
```

### 9. Create The Pull Request

Prepare a PR title and body from the context, commits, and verification results.
The PR title must use the Conventional Commits pattern:
`<type>[optional scope]: <description>`, for example
`fix: handle empty repository names` or
`chore(terraform): update branch protection`. Prefer `feat`, `fix`, `docs`,
`chore`, `refactor`, `test`, `build`, `ci`, `perf`, `style`, or `revert` as
the type. When the user supplies a non-conventional title, convert it while
preserving intent unless they explicitly ask for exact title wording.
Look for repository PR templates:

```bash
if test -d .github; then
  find .github -maxdepth 3 \( -iname '*pull_request_template*' -o -path '.github/PULL_REQUEST_TEMPLATE/*' \)
fi
```

Use a template when one clearly applies. Otherwise create a concise body with:

```markdown
## Summary
- <what changed>

## Verification
- <commands run, or "Not run: <reason>">

## Notes
- <risks, rollout notes, or follow-ups if relevant>
```

Create the PR from the fork branch to upstream default:

```bash
gh pr create \
  --repo "$UPSTREAM_REPO" \
  --base "$DEFAULT_BRANCH" \
  --head "$GH_USER:$BRANCH_NAME" \
  --title "$PR_TITLE" \
  --body-file "$PR_BODY_FILE"
```

Add `--draft` only when the user asked for a draft or the work is intentionally
not ready for review. If `--head "$GH_USER:$BRANCH_NAME"` is not accepted, fall
back to the pushed remote branch that `gh pr create` can see and explain the
adjustment.

### 10. Final Response

Report the outcome with:

- PR URL
- Upstream base: `<UPSTREAM_REPO>:<DEFAULT_BRANCH>`
- Fork branch: `<FORK_REPO>:<BRANCH_NAME>`
- Commit hash or short commit summary
- Verification commands and results
- Any skipped checks or follow-ups

If the PR could not be created, leave the branch and commits intact, explain the
blocker, and give the exact next command or decision needed.

## Common Edge Cases

- **Origin is already the user's fork:** use `origin` as `FORK_REMOTE`; ensure an
  upstream remote exists or use `--repo "$UPSTREAM_REPO"` explicitly for PR
  creation.
- **Current repo is the fork:** target the parent repo for the PR, sync this fork
  from the parent, and push the branch to this fork.
- **User wants a PR for existing local commits:** do not recreate the branch just
  for ceremony. Ensure the fork remote exists, sync the fork default branch,
  rebase or merge only when appropriate, push the current branch to the fork, and
  create the PR.
- **Protected upstream branch:** never push the feature branch to upstream unless
  the user explicitly asks and has permission. The default path is always the
  fork branch.
- **Sync requires force:** ask before `gh repo sync --force`; it rewrites the
  fork's default branch.
- **No changes after implementation:** do not create an empty PR. Explain that
  the repository already has the requested behavior or that the requested change
  could not be reproduced.
