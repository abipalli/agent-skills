---
name: repo-review
model: opus
effort: xhigh
description: "Deep whole-repository review for architecture, correctness, security, concurrency, operations, data integrity, tests, and maintainability. Use when the user asks to \"review this repo\", \"deep repo review\", \"audit this codebase\", \"analyze this project\", or invokes \"repo-review\". For PRs, branch diffs, commits, or patches, prefer the focused code-review skills instead."
---

# Repo Review

Use this skill for a deep review of an entire repository, not a single diff. The goal is to find real defects and systemic risks, prioritize them, and only change code when the user asked for fixes or clearly wants the review to include remediation.

**Prerequisites:** `git` and ripgrep (`rg`). Parallel node reviews need a subagent tool (such as Claude Code's Agent tool); without one, review the nodes in sequence.

## Operating Principles

- Start review-first. Do not edit code during discovery or finding validation unless the user explicitly requested fixes.
- Preserve user work. Check `git status --short --branch` before edits, and do not revert unrelated changes.
- Favor evidence over breadth theater. Review the meaningful systems, entrypoints, data flows, and risky edges; do not claim every generated, vendored, or mechanical file was deeply reviewed.
- Calibrate severity by actual impact and reachability. A finding needs a plausible failure mode, affected users or operators, and a concrete fix.
- Keep findings compact and actionable. Lead with issues, then residual risk and verification.
- Parallelize independent reads and reviews when available and safe. Use subagents only when the environment permits delegation and the user request allows it.

## Fast Start

Run discovery commands first, preferably in parallel:

```bash
git status --short --branch
git log --oneline -20
rg --files -g '!**/.git/**' -g '!**/node_modules/**' -g '!**/vendor/**' -g '!**/dist/**' -g '!**/build/**' -g '!**/.next/**'
```

Then inspect the files that reveal shape and risk:

- Project manifests and build files: `package.json`, `Cargo.toml`, `go.mod`, `pyproject.toml`, `pom.xml`, `Makefile`, Docker and CI files.
- Entrypoints and routing: servers, CLIs, workers, cron jobs, API routes, middleware.
- Trust boundaries: auth, permissions, request parsing, webhooks, file uploads, external integrations.
- State and persistence: database schema, migrations, ORM models, queues, caches, distributed locks.
- Tests and observability: critical test suites, logging, metrics, tracing, alerting, runbooks.

Use [references/review-playbook.md](references/review-playbook.md) when you need the detailed checklist or a worker prompt template.

## Review Map

Create a lightweight dependency-aware review map before deep reading. Group by reviewable concern, not by individual file.

Each node should include:

- `id`: short name such as `api-auth`, `billing-state`, or `worker-retries`
- `files`: key files or directories
- `focus`: two to five review dimensions
- `depends_on`: only true prerequisites, not loosely related areas

Prefer a shallow map with many independent nodes. Useful default nodes are:

- Architecture and module boundaries
- Public API, routing, and authz/authn
- Data model, migrations, and persistence invariants
- Background jobs, queues, async, and concurrency
- External integrations, retries, timeouts, and idempotency
- Configuration, secrets, deployment, and observability
- Critical tests, fixtures, and coverage gaps

Share the map briefly when the review is large or long-running. For small repositories, keep it internal and move quickly.

## Execution

Review high-risk nodes first: public entrypoints, auth, data mutation, async workers, migrations, and external calls. For each node:

1. Read enough surrounding code to understand the intended invariant.
2. Trace source-to-sink paths for user input, state changes, permissions, and failures.
3. Check tests that should catch the issue before filing a finding.
4. Validate that the finding is reachable in the current architecture.
5. Record findings with exact file and line references.

If parallel subagents are appropriate, give each one a bounded node, relevant files, known dependencies, and the finding quality bar from the reference playbook. Avoid duplicate reviewers over the same files unless one is doing a distinct specialty pass such as security or concurrency.

## Finding Quality Bar

Report a finding only when it meets most of these:

- It identifies a specific bug, vulnerability, operational risk, or maintainability trap.
- It explains the impact in concrete terms.
- It cites exact code locations and the path that makes the issue reachable.
- It proposes a practical fix or decision needed from a human.
- It is not merely style, formatting, preference, or a linter concern.

Use this format:

```markdown
### [Severity] Short Title

- **Location:** `path/to/file.ext:123`
- **Impact:** What can go wrong and who is affected.
- **Evidence:** The code path, invariant violation, exploit path, or operational scenario.
- **Fix:** Minimal practical remediation.
```

Severity guide:

- `Critical`: likely data loss, account compromise, remote code execution, severe auth bypass, or outage trigger.
- `High`: reachable security gap, corrupt state, major reliability failure, or broken core workflow.
- `Medium`: real bug or operational risk with narrower blast radius or workaround.
- `Low`: useful improvement tied to a concrete risk.

## Output

For a short review, answer directly with findings first:

```markdown
## Findings
[ordered by severity]

## Residual Risk
[important areas not fully reviewed or requiring runtime context]

## Verification
[commands run, tests inspected, and anything not run]
```

For a long review, create or update `REPO_REVIEW.md` in the repo root unless the user provided another path. Keep it current as nodes finish:

```markdown
# Repository Review: <repo>

**Status:** In Progress
**Scope:** <what was reviewed>

## Review Map
<nodes and dependencies>

## Findings
<findings ordered by severity, with node attribution>

## Cross-Cutting Assessment
- Systemic patterns
- Trust-boundary posture
- Data-integrity risks
- Operational and observability gaps
- Test coverage gaps

## Remediation Plan
- Confident fixes
- Needs human decision
- Suggested verification
```

In the final answer, summarize the highest-risk findings, where the full review lives, and what verification was run.

## Remediation

Apply fixes only when requested or when the user asked for a review-and-fix workflow.

Before editing:

1. Re-check `git status --short`.
2. Triage findings into `confident fix`, `risky fix`, and `needs human`.
3. Make the smallest correct changes for confident fixes.
4. Leave risky fixes as recommendations unless the user approves the direction.
5. Run targeted tests or static checks that match the touched code.
6. Update `REPO_REVIEW.md` with what changed, what remains, and any verification gaps.

When fixing in parallel, split work by disjoint files or modules and make ownership explicit. Never let two workers edit the same file unless one has already finished and the change has been reviewed.
