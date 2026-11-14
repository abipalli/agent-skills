---
name: submit-review
description: "Submit code review findings as inline PR comments via the GitHub CLI. Takes review findings (from deep-code-review or manual analysis) and posts them as a single GitHub PR review with inline comments. Use when the user asks to \"submit review\", \"post comments\", \"submit PR feedback\", \"post review\", or \"comment on the PR\"."
---

# Submit Review

You are posting a code review on a GitHub PR. Your job is to turn review findings into precise, actionable inline PR comments and submit them as a single review.

**Prerequisites:** the GitHub CLI (`gh`), authenticated with permission to review the target PR, and network access to GitHub.

## Step 1: Determine the PR

If the PR number is not already known from context, ask which PR to submit the
review on, offering two options: the current branch's PR (auto-detect) or a
specific PR number. Use a structured question tool (such as Claude Code's
`AskUserQuestion`) when one is available; otherwise ask in plain text.

Auto-detect with:
```bash
gh pr view --json number,headRefOid -q '.number'
```

## Step 2: Gather Review Findings

If you just ran `/deep-code-review` or the user provided findings, use those directly.

Otherwise, generate findings by:
1. Get the diff: `gh pr diff <number>`
2. Read full files for context
3. Identify issues worth commenting on

**Comment quality bar:** Only submit comments that are genuinely useful. Each comment must either:
- Flag a bug, security issue, or correctness problem
- Suggest a concrete improvement with a clear reason
- Ask a clarifying question about intent

Do NOT submit comments that are:
- Style preferences already covered by formatters/linters
- Restating what the code does without adding insight
- Generic advice ("consider adding tests") without specifics

## Step 3: Draft Comments

For each finding, craft an inline comment that is **concise yet precise**:

### Comment format

Each comment must include:
- **Severity prefix** (italic, lowercase): `*issue*:`, `*suggestion*:`, or `*nit*:`
  - `*issue*:` — bugs, security problems, correctness errors, or design concerns that should be addressed
  - `*suggestion*:` — concrete improvements worth considering but not blocking
  - `*nit*:` — minor style, naming, or clarity items; take-or-leave
- **The point**: One sentence stating what's wrong or what could be better
- **Why it matters**: One sentence on the impact (skip if obvious)
- **Fix** (when applicable): A concrete code suggestion or direction — not a vague recommendation

### Writing style

- Lead with the point — no preamble ("Nice work but...", "I noticed that...")
- Use code backticks for identifiers, types, and values
- If suggesting a code change, use a GitHub suggestion block:
  ````
  ```suggestion
  corrected code here
  ```
  ````
- Keep total comment length under 5 lines when possible. Longer only when the fix requires explanation.
- One comment per issue. Do not bundle unrelated findings into a single comment.

### Examples

Good:
> *issue*: This `unwrap()` will panic if the upstream RPC returns an unexpected response. Propagate the error with `?` instead.
> ```suggestion
> let result = client.call().await?;
> ```

Good:
> *suggestion*: Is the `+ 1` intentional here? With `limit = 0` this fetches 1 item, which differs from the previous behavior of returning empty.

Good:
> *nit*: `MAX_EVICTED_STREAMS` could be `pub(crate)` for consistency with the other constants in this file.

Bad:
> I think it might be worth considering whether this could potentially cause issues in some edge cases. Maybe we should think about adding some error handling here?

## Step 4: Map Comments to Diff Positions

For each comment, determine:
1. **File path** — the file in the diff
2. **Line number** — the line in the NEW version of the file (right side of the diff)
3. **Side** — always `RIGHT` unless commenting on deleted code

Verify each file:line actually appears in the diff. GitHub only accepts inline review comments on diff positions, so if a finding refers to code outside the changed lines, find the next best inline anchor instead of moving it into the top-level review body:
- Prefer the nearest changed line in the same function or block
- Then prefer the nearest changed line in the same file
- If needed, use a changed call site, test, or related line in the diff that makes the off-diff concern actionable

When anchoring to a nearby diff line, write the comment so the target is clear (for example, "This new call still relies on `foo` returning non-null..."). If there is no honest inline anchor in the diff, skip that comment and report it after submission rather than posting a top-level review note.

## Step 5: Submit the Review

Use the `gh` CLI to submit a single review with all comments. Determine the appropriate review action from the review verdict, not just whether comments exist:

| Verdict | Action |
|---------|--------|
| Overall approval, optionally with inline non-blocking comments | `APPROVE` |
| Feedback should be posted but the PR should not be approved yet | `COMMENT` |
| No inline comments and no explicit approval request | Do not submit an empty review; tell the user there were no findings |

**Never use `REQUEST_CHANGES`** — always use `COMMENT` or `APPROVE`. `REQUEST_CHANGES` blocks the PR and should only be done manually by the reviewer in the GitHub UI.

`APPROVE` reviews may include inline comments when the review verdict is approval and the comments are non-blocking. Do not attach an additional top-level approval comment such as "LGTM" or a summary paragraph; approval is conveyed by the review event itself.

### Build the review command

Write the review to a temporary JSON file (for example `REVIEW_JSON=$(mktemp)`) and submit it via `--input` to avoid shell escaping issues:

```json
{
  "commit_id": "<HEAD SHA of the PR>",
  "event": "<APPROVE or COMMENT>",
  "body": "",
  "comments": [
    {
      "path": "path/to/file.rs",
      "line": 42,
      "side": "RIGHT",
      "body": "*issue*: Comment body here"
    }
  ]
}
```

```bash
gh api repos/{owner}/{repo}/pulls/{number}/reviews \
  --method POST \
  --input "$REVIEW_JSON"
```

The `event` field must be either `APPROVE` or `COMMENT`. Never use `REQUEST_CHANGES`.

**The `body` field must be an empty string `""`** — do not include a top-level review summary or an extra approval message. All feedback goes in inline comments only.

## Step 6: Confirm Submission

After the API call succeeds, output:
- Link to the PR
- Count of comments posted
- The review action taken

If any comments failed to post (e.g., line not in diff), report which ones and why.

## Important Guidelines

- Never submit an empty review unless the user explicitly asked you to approve the PR — if there are no findings, tell the user instead of posting
- Submit immediately without asking for confirmation — the review pipeline is automated
- Prefer fewer, higher-quality comments over many trivial ones
- Use GitHub suggestion blocks whenever a concrete code fix is possible
- Comments on deleted lines use `side=LEFT` and the old file's line number
- Multi-line comments: use `start_line` and `line` together with `start_side` and `side`
