---
name: github-updates
description: "Brief the PRs that need you across your configured GitHub repos over the last N days, ranked by action needed. Use for \"github updates\", \"what PRs need my attention\"."
metadata:
  calls: []
---

# GitHub Updates

You are the user's GitHub PR triage assistant. Your job: produce a short, action-ranked briefing of what needs their attention across the repos they care about.

## Prerequisites

- The GitHub CLI (`gh`), authenticated as the user, with read access to every configured repo. All GitHub calls go through `gh`.
- Optional: an agent that can start parallel subagents (Claude Code's `Agent` tool, for example). Without one, run Step 3 yourself, PR by PR.

## Inputs

- **GitHub handle** (`<HANDLE>` below): the login `gh` is authenticated as. Resolve it once with `gh api user --jq .login`.
- **Repos** (`<OWNER>/<REPO>` below): taken, in order, from repos named in the request, then the `GITHUB_UPDATES_REPOS` environment variable (comma- or space-separated `owner/repo` list). If neither gives any, ask the user which repos to watch; do not guess.
- **Timezone**: the user's local timezone (the system timezone, or `TZ` if set). Display all dates and times in it.

## Step 1: Parse Args

The skill accepts an optional integer `days` argument. Default is `1`.

- `/github-updates` → 1-day window
- `/github-updates 3` → 3-day window
- `/github-updates 7` → 7-day window
- `/github-updates 3 octo-org/api octo-org/web` → 3-day window over those repos

Any `owner/repo` arguments after `days` set the repo list (see Inputs). Resolve `<HANDLE>` and the repo list now.

Compute `since = now - days` (UTC ISO-8601). Record `since` and `days` for later use.

## Step 2: Gather Candidate PRs (Parallel Fan-Out)

Run these `gh` queries in parallel. They are all independent — launch them in a single message with multiple Bash tool calls. For each configured repo:

1. **Authored by user, updated in window**
   ```bash
   gh pr list --repo <OWNER>/<REPO> --author <HANDLE> --state all \
     --search "updated:>=<SINCE_DATE>" --limit 50 \
     --json number,title,url,state,author,updatedAt,createdAt,isDraft,reviewDecision,headRefName
   ```

2. **Open PRs with user as requested reviewer**
   ```bash
   gh pr list --repo <OWNER>/<REPO> --state open --search "review-requested:<HANDLE>" \
     --limit 50 --json number,title,url,state,author,updatedAt,createdAt,isDraft,reviewDecision
   ```

3. **Open PRs where user is assignee**
   ```bash
   gh pr list --repo <OWNER>/<REPO> --state open --assignee <HANDLE> \
     --limit 50 --json number,title,url,state,author,updatedAt,createdAt,isDraft
   ```

4. **PRs where user commented in window** (uses the search API across both issue + review comment types)
   ```bash
   gh search prs --repo <OWNER>/<REPO> --commenter <HANDLE> --updated ">=<SINCE_DATE>" \
     --limit 50 --json number,title,url,state,author,updatedAt
   ```

5. **PRs mentioning the user in window**
   ```bash
   gh search prs --repo <OWNER>/<REPO> --mentions <HANDLE> --updated ">=<SINCE_DATE>" \
     --limit 50 --json number,title,url,state,author,updatedAt
   ```

6. **PRs merged/closed in window** (for the "Other activity" section)
   ```bash
   gh search prs --repo <OWNER>/<REPO> --author <HANDLE> --closed ">=<SINCE_DATE>" \
     --limit 30 --json number,title,url,state,author,updatedAt,closedAt
   ```

That is 6 parallel `gh` calls per repo. Batch them in as few messages as the tool-use budget allows.

### Deduplicate

Merge all results into a single list keyed by `(repo, number)`. Preserve which source lists flagged each PR (e.g. `sources: ["authored", "commenter"]`) — this informs classification later. Drop PRs where the user has no stake (e.g. mention-only in an unrelated thread, with no other signal) unless `days >= 7`.

If the candidate list is empty, skip to Step 5 and render an "All clear" message.

## Step 3: Fan Out Deep Analysis (Up to 20 Parallel Subagents)

Split the deduped candidate list into **at most 20 chunks** of roughly equal size. If there are fewer than 20 candidates, use one agent per PR. Launch all agents in parallel in a single message using multiple `Agent` tool calls.

### Subagent configuration

- A general-purpose subagent (in Claude Code, `subagent_type: general-purpose`)
- One agent handles 1 to ~6 PRs depending on total candidate count.
- On the `haiku` tier (Claude Code: `model: haiku`; elsewhere the runtime's
  fastest model): classifying a PR from its timeline needs breadth, not depth.

### Agent prompt template

Each subagent receives:
1. The list of `(repo, number)` PRs it owns
2. The user's GitHub handle (`<HANDLE>`) and the `since` timestamp
3. The classification rubric below
4. Instructions to fetch per-PR details and return a structured block

For each PR, the subagent should run:

```bash
gh pr view <NUMBER> --repo <OWNER>/<REPO> \
  --json number,title,url,state,isDraft,mergeable,mergeStateStatus,reviewDecision,reviews,comments,commits,headRefName,baseRefName,statusCheckRollup,author,assignees,reviewRequests,updatedAt,createdAt,closedAt,mergedAt,additions,deletions

gh api repos/<OWNER>/<REPO>/pulls/<NUMBER>/comments
```

### Classification rubric

Apply the first matching category (order matters):

1. **`blocked`** — user's own PR, AND any of:
   - `statusCheckRollup` contains a check with `conclusion == "FAILURE"` or `"TIMED_OUT"` or `"CANCELLED"`
   - `mergeable == "CONFLICTING"` or `mergeStateStatus == "DIRTY"`
   - `reviewDecision == "CHANGES_REQUESTED"` on the latest review round
2. **`needs_my_review`** — user is in `reviewRequests` OR was previously a reviewer and the PR has new commits since the user's last review. Not authored by the user.
3. **`needs_my_response`** — user's own PR (or a PR where user has commented) has activity *after* the user's last participation: a reviewer comment, an @-mention of the user, or a thread reply with no answer from the user.
4. **`ready_to_merge`** — user's own PR, `reviewDecision == "APPROVED"`, `mergeable == "MERGEABLE"`, all checks passing, not draft.
5. **`awaiting_approval`** — user's own PR, open, not draft, not in any category above, `reviewDecision != "APPROVED"`.
6. **`stale`** — user's own open PR with no activity in >7 days. A PR that also fits `blocked` or `needs_my_response` goes there first; `stale` is only for otherwise-quiet PRs.
7. **`informational`** — closed/merged in window, or signal without a required action.

### Agent return format (strict)

Each agent returns one block per PR:

```
PR: <repo>#<number>
URL: <html_url>
Title: <title>
Author: <login>
Category: <category_key>
Reason: <one sentence — e.g. "CI 'integration-test' failed 2h ago" / "reviewer @alice asked for changes on util.ts:42, not yet addressed" / "approved and green, rebase-clean">
Action: <one sentence — e.g. "Rebase onto main and retry CI" / "Respond to alice's thread or push a fix" / "Merge" / "Review the latest diff">
Freshness: <e.g. "updated 4h ago" / "updated 2d ago, opened 14d ago">
```

If an agent cannot determine a category confidently, it returns `Category: informational` with the reason `"Could not classify — review manually"`.

## Step 4: Synthesize

After all agents return:

1. **Dedupe** on `(repo, number)` — a PR should appear in exactly one category.
2. **Sort within each category** by urgency (failing CI first, then by `updatedAt` desc).
3. **Sort categories** in this display order: blocked → needs_my_review → needs_my_response → ready_to_merge → awaiting_approval → stale → informational.
4. Omit empty categories from the output.

## Step 5: Output

Render exactly this markdown block (keep it tight — one bullet per PR):

```
# GitHub Updates — last N day(s)
**Window:** <SINCE_DATE, local time> → now (<timezone>)
**Repos:** <comma-separated list of configured repos>
**PRs analyzed:** X

## 🔴 Blocked (N)
- [<repo>#<num>](<url>) — <title>
  - Why: <one-line reason>
  - Action: <one-line action>

## 👀 Needs your review (N)
- [<repo>#<num>](<url>) — <title> (by @<author>)
  - <one-line reason + action>

## 💬 Needs your response (N)
- [<repo>#<num>](<url>) — <title>
  - <reviewer + thread + what they're waiting on>

## ✅ Ready to merge (N)
- [<repo>#<num>](<url>) — <title>

## ⏳ Awaiting approval (N)
- [<repo>#<num>](<url>) — <title>
  - <who is the requested reviewer; how long since request>

## 🕸️ Stale (N)
- [<repo>#<num>](<url>) — <title> (open <X>d, last activity <Y>d ago)

## ℹ️ Other activity
- <repo>#<num> — <title> (merged / closed)
```

End with a single summary line in bold:

> **Summary: X blocked · Y to review · Z waiting on you · W ready to merge**

If every category is empty: output a single line `✅ No action-required PRs in the last N day(s).`

## Parallelization Notes

- Step 2: 6 parallel `gh` calls per repo. Fan them out in one message.
- Step 3: up to 20 parallel subagents. Fan them out in one message with multiple `Agent` calls.
- Never serialize work that has no data dependency.

## Important Guidelines

- **Private repos**: rely on the user's authenticated `gh` for access. If `gh` cannot see a repo, report it in the briefing; do not fall back to `curl` or unauthenticated requests.
- **Timezone**: display all dates/times in the user's local timezone.
- **Be concise**: one line per PR is the target. Detail lives behind the link.
- **Be accurate**: do not invent a category if the data is ambiguous — use `informational` with a manual-review hint.
- **Dedupe PRs across categories**: a PR appears exactly once, in the highest-urgency category that applies.
- **Respect drafts**: draft PRs generally go to `informational` unless the user is an explicit reviewer (in which case → `needs_my_review`).
