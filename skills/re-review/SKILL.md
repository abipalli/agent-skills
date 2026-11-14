---
name: re-review
model: opus
effort: high
metadata:
  calls: ["rust-review"]
description: "Re-review an existing GitHub pull request after updates. Use this skill whenever the user invokes \"/re-review\", asks whether their prior PR review comments were addressed, asks to resolve addressed comments, asks what remains before merge, or wants a concise follow-up review that reruns focused Rust review when applicable and can hand off to submit-review or merge."
---

# Re-review

Use this skill to check a PR after the author has pushed updates or replied to
review comments. Resolve your own review threads only when the fix is verified,
then report outstanding items and any new findings in a form that can feed
`/submit-review` or `/merge`.

## Operating Model

- Prefer facts from GitHub and the current code over the PR description.
- Resolve only review threads that include comments from the authenticated user
  and are clearly addressed in the current PR state.
- Do not resolve another reviewer's thread unless the user explicitly asks.
- If a thread is partially addressed, ambiguous, or answered only with intent,
  leave it unresolved and list what still needs checking.
- Keep the final answer concise and action-oriented: resolved, outstanding, new
  findings, and recommended next action.

## Required Tools

- `gh` CLI authenticated with permission to read the PR and resolve review
  threads
- `git` for branch and file context
- Network access to GitHub

## Workflow

### 1. Resolve The Target PR

If the user supplied a PR URL, PR number, or `owner/repo#number`, use it. If not,
try the current branch:

```bash
gh pr view --json number,url,title,headRefName,baseRefName,headRefOid
```

If the target is still ambiguous, ask for the exact PR.

Capture the authenticated reviewer:

```bash
gh api user --jq .login
```

### 2. Gather PR State

Fetch metadata, the latest diff, review history, and review threads:

```bash
gh pr view <selector> \
  --json number,url,title,state,isDraft,author,headRefName,baseRefName,headRefOid,commits,comments,reviews,reviewDecision,statusCheckRollup
gh pr diff <selector>
```

Fetch inline review threads with GraphQL, paginating when `hasNextPage` is true:

```bash
gh api graphql \
  -f owner=<owner> \
  -f repo=<repo> \
  -F number=<number> \
  -f query='
query($owner:String!, $repo:String!, $number:Int!) {
  repository(owner:$owner, name:$repo) {
    pullRequest(number:$number) {
      reviewThreads(first: 100) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          comments(first: 50) {
            nodes {
              id
              databaseId
              author { login }
              body
              createdAt
              url
              path
              line
              diffHunk
              outdated
            }
          }
        }
      }
    }
  }
}'
```

Identify:

- Unresolved review threads containing comments authored by the authenticated
  user.
- New commits and PR comments since the authenticated user's latest review, if
  one exists.
- Open review threads from other reviewers that may block merge. Summarize them
  but do not resolve them.

### 3. Verify Whether Prior Comments Were Addressed

For each unresolved thread containing your comment:

1. Read the current version of the referenced file and nearby code.
2. Compare the original concern, any author replies, and the current diff.
3. Classify the thread as:
   - `addressed`: the current code or reply clearly resolves the concern.
   - `outstanding`: the concern still applies.
   - `needs confirmation`: the response may be acceptable, but a human decision
     or domain context is required.
4. Record a one-sentence reason for the classification.

Only mark `addressed` threads as resolved.

Resolve a verified thread with:

```bash
gh api graphql \
  -f threadId=<thread-id> \
  -f query='
mutation($threadId:ID!) {
  resolveReviewThread(input:{threadId:$threadId}) {
    thread { id isResolved }
  }
}'
```

If resolution fails, continue the review and report the failure with the thread
URL.

### 4. Re-review New Updates

Review changes made since the authenticated user's latest review. If no previous
review by the authenticated user exists, review the whole PR diff.

If the reviewed scope includes Rust-relevant files (`.rs`, `Cargo.toml`,
`Cargo.lock`, build scripts, Rust tests, generated bindings used by changed Rust
code), run the `rust-review` skill again against the same PR, branch, commit
range, or patch before finalizing new findings. Do this even if a prior review
already included a Rust pass, because the purpose of re-review is to inspect the
current PR state after updates.

Use the Rust pass to look for fresh idiom, invariant, ownership, error-handling,
async, dependency, and Cargo findings introduced or still exposed by the current
diff. Reconcile its output with prior review threads so you do not repeat a
resolved or still-open duplicate. Fold any surviving Rust findings into
`New Findings For Submit Review` using this skill's review comment style:
`Must Fix` maps to `Critical` or `Warning` depending on merge impact;
`Suggestions` and `Nits` map to `Suggestion` unless they reveal a concrete
blocking failure mode.

Focus on:

- Whether the fixes introduced regressions or incomplete behavior.
- Whether new commits changed risk areas that were not previously reviewed.
- Whether tests were added or updated for the fixed behavior when that matters.
- Whether any remaining comments are duplicates of already-resolved concerns.

Apply the same calibration bar as `deep-code-review`: only raise issues with a
concrete failure mode, material risk, or useful clarifying question.

## Review Comment Style

When you produce findings that may be handed to `/submit-review`, write the
suggested comment text like a human reviewer would write it on GitHub. These
rules match the GitHub comment guidance in `deep-code-review`:

- Start each suggested comment with exactly one lowercase prefix:
  - `issue:` for bugs, correctness problems, security risks, broken contracts,
    missing required tests, or anything that should block/strongly delay merge.
  - `suggestion:` for non-blocking improvements that are still worth considering.
  - `nit:` for small readability, naming, or cleanup comments that are safe to
    ignore.
- Use 1-2 short paragraphs of natural prose.
- After the prefix, start from the specific behavior in the current code, then
  state the risk and the requested change.
- Do not add report-style labels after the prefix, such as "Impact:" or "Fix:".
  The prefix is enough structure; the rest should read like a normal review
  comment.
- Be clear about certainty. Use direct language for definite bugs; use "I think"
  or "Can we" for reasonable reviewer judgment calls.
- Avoid restating the whole PR context. The comment should make sense at the
  inline location and be easy for the author to act on.

Good suggested comment text:

```markdown
issue: This still lets the old value through when the retry path succeeds after
the deadline, so the caller can observe a stale result. Can we return the
timeout once the context is done instead of accepting the late retry?
```

Avoid:

```markdown
issue: stale result can be returned.
Impact: caller sees incorrect state.
Fix: return timeout after context cancellation.
```

## Output

Use this exact shape:

```markdown
# Re-review Summary

**Verdict:** [Ready to merge / Needs another review / Needs discussion]
**PR:** <title or number> - <url>

## Resolved Threads
1. <thread URL or file:line> - <what was addressed and why it was resolved>

If none were resolved, say "None."

## Outstanding Prior Comments
1. <thread URL or file:line> - <what still remains and what would address it>

If none remain, say "None."

## New Findings For Submit Review
1. [Critical|Warning|Suggestion] <file:line> - <issue, impact, and suggested
   human-readable comment text>

If there are no new findings, say "None."

## Other Open Threads
1. <reviewer/thread URL or file:line> - <brief status>

Omit this section when there are no relevant open threads from other reviewers.

## Recommended Next Action
[Run `/merge` / Run `/submit-review` with the listed findings / Ask the author
for clarification / Wait for checks]
```

## Decision Rules

- Recommend `/merge` only when your prior comments are resolved, no new findings
  remain, the PR is not a draft, and there is no obvious blocking status from
  checks or review state.
- Recommend `/submit-review` when there are new findings or unresolved prior
  comments that should be posted as review comments.
- Recommend discussion when the remaining question is product, architecture,
  migration, ownership, or reviewer judgment rather than a straightforward code
  fix.
- Do not submit review comments from this skill. Leave that to
  `submit-review`.
- Do not merge from this skill. Leave that to `merge`.
