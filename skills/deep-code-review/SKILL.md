---
name: deep-code-review
description: "Deep multi-agent review of a diff, branch or GitHub PR: does it solve the right problem, plus parallel correctness, design, edge-case and over-engineering passes, with calibrated findings. Use for \"deep code review\", \"review this PR / diff / branch\"."
model: opus
effort: xhigh
metadata:
  calls: ["ponytail-review", "rust-review", "rust-best-practices"]
---

# Deep Code Review

Review like a senior staff engineer. Find concrete bugs, security issues,
incorrect behavior, risky rollout paths, broken contracts, and meaningful test
gaps. Also assess code quality directly: identify concrete smells that make the
changed code harder to understand, test, extend, or safely modify, even when no
current failure is proven. Ask whether the change solves the right problem, uses
an appropriate approach, and actually delivers the intended result. Turn
concrete concerns from that check into findings just like correctness, security,
or code-quality concerns. Review the writing in changed documentation and code
comments with the same care: it should be concise, natural, concrete, and easy
to read. Write all reported findings in ASD-STE100 Simplified Technical
English. Do not invent findings to look thorough.

**Prerequisites:** `git`; the GitHub CLI (`gh`), authenticated, for PR targets;
a subagent tool (such as Claude Code's Agent tool) for the parallel wave, without
which the main reviewer covers every dimension itself; and the external
`ponytail-review` skill for the over-engineering pass.

## 1. Choose the Target

If the target is unclear, ask whether to review a local diff or a GitHub PR.

For a local diff, run:

```bash
git diff origin/master...HEAD
git diff origin/master...HEAD --stat
```

If that diff is empty or `origin/master` does not exist, try
`origin/main...HEAD`, `master...HEAD`, then `main...HEAD`.

For a PR, gather:

```bash
gh pr diff <number>
gh pr view <number> --json url,title,number,headRefName,body,comments,reviews,commits
gh api repos/{owner}/{repo}/pulls/<number>/comments
```

Keep the PR URL for the final footer.

## 2. Load Review Context

Before launching review agents:

- Read the full diff and changed-file list.
- Read changed files in full, plus nearby callers, tests, schemas, config, or
  generated artifacts needed to understand behavior.
- Identify language, framework, persistence layer, deployment path, public API
  surface, and risk level.
- For PRs, summarize prior top-level comments, review bodies, and inline
  comments. Track what remains open, what appears addressed, and what should
  not be duplicated.
- For PRs, extract substantive links from the body and comments. Use available
  issue-tracker, wiki, chat, GitHub, document, browser, web, or connector tools
  to summarize linked requirements and constraints. Skip non-contextual links
  such as avatars, screenshots without discussion, CI dashboards, badges, and
  reaction media.
- For PRs, extract the problem statement from the PR body, linked tickets,
  design docs, comments, and commit messages. If the problem is only implicit,
  state the inferred problem and the uncertainty. Rewrite the problem in one
  plain sentence before judging the change.

## 3. Parallel Review Plan

Create review dimensions in two categories.

Always-run dimensions:

- **Does this solve the right problem?**: answer these questions in plain words:
  1. What user, product, or engineering problem is this change trying to fix?
  2. Is that problem real, and what evidence shows it matters?
  3. Does this change actually fix the whole problem, including the important
     paths and deployment conditions?
  4. Is this the right place and a reasonable way to fix it, or does it add
     avoidable complexity or a long-term constraint?
  Check both the overall approach and the actual changed code, boundaries,
  validation, rollout, and tests. If the change solves a non-problem, solves a
  different problem, works only for a narrow case, fixes the symptom at the
  wrong layer, adds unjustified complexity, or handles only part of the real
  need, emit a category-grouped, severity-ranked review finding even when the
  code is locally correct. Anchor it to the closest changed line or responsible
  file, explain the concrete impact, and give the smallest useful direction for
  a better fix. Group it under `Requires Review` when a human must decide
  whether the problem, approach, or solution is correct. Do not leave the
  concern only in the summary section. If the problem and approach are sound,
  report no finding for this dimension.
- **Implementation-quality alternatives**: always ask whether the same logic can
  be implemented in a cleaner, simpler, more idiomatic, or more maintainable way.
  Look for local patterns, helper APIs, framework features, standard-library
  capabilities, existing dependency features, or a well-supported new library
  that would materially reduce custom code, duplication, state space, incidental
  control flow, or future bug surface. Treat this as engineering review, not
  style review: raise a finding only when the alternative is concrete, fits the
  repository's conventions and dependency posture, and would make the changed
  behavior easier to reason about or harder to misuse. Do not suggest a new
  abstraction or dependency for cosmetic cleanup, tiny call-site wins, or churn
  that would make ownership, rollout, licensing, security, bundle size, runtime
  behavior, or maintenance risk worse. Report each material concern as a normal
  category-grouped, severity-ranked finding with a file anchor and a practical
  change direction.
- **Code-smell and cleanliness pass**: independently assess whether the changed
  code is clean, cohesive, and easy to reason about. Look for concrete smells
  such as duplicated logic, long or deeply nested functions, mixed
  responsibilities, leaky abstractions, boolean or mode-flag branching,
  stringly typed state, sentinel values, invalid states that remain
  representable, temporal coupling, surprising mutation or shared state,
  inconsistent error handling, unclear ownership, names that hide invariants,
  dead compatibility paths, comments that compensate for accidental
  complexity, or tests that mirror implementation details instead of behavior.
  This dimension is broader than proposing an alternative implementation: a
  finding may identify what is not clean and why it raises comprehension,
  testing, change, or defect risk even when there is no proven current bug or
  complete replacement design. Keep the finding specific to code introduced or
  materially worsened by the change, cite the exact construct, and give the
  smallest useful cleanup direction when one is known. Do not turn formatting,
  familiar local idioms, isolated naming taste, or speculative future reuse
  into findings.
- **Documentation and code-comment writing pass**: always review prose added or
  changed in documentation, docstrings, API docs, examples, and code comments,
  plus nearby prose whose meaning changes with the code. Check that it says only
  what the reader needs, uses short and direct sentences, sounds like a human
  teammate, and describes concrete behavior with familiar words. Flag
  repetition, throat-clearing, inflated claims, passive or indirect wording,
  comments that narrate the code instead of explaining why it exists, and vague
  generated-sounding phrases. In particular, replace stock wording such as
  "fails closed" with the actual outcome, such as "rejects the request" or
  "returns the validation error." Replace "load-bearing" with the concrete
  reason that the code or design is important, such as "other components rely
  on this check." Prefer "incoming requests," "traffic," or the specific data
  name over abstract terms such as "ingress" when those words are not required.
  Preserve exact identifiers and terms required by a
  protocol, API, standard, user interface, or established repository vocabulary;
  judge whether the prose is clear in context rather than treating examples as
  a banned-word list. Raise findings only for prose introduced or materially
  worsened by the change. When a rewrite is useful, quote only the shortest
  necessary phrase and offer concise replacement wording. If no documentation
  or comments changed, or the changed prose is already clear, return no finding
  for this dimension instead of inventing a style concern.
- **Edge-case discovery**: identify concrete scenarios that could break the
  change or prove it robust. Focus on boundary values, permission states,
  invalid inputs, retries, migrations, concurrency interleavings, backward
  compatibility, and UI state transitions. Trace only plausible scenarios from
  the actual diff and context. Report each confirmed concern as a normal
  category-grouped, severity-ranked finding with the closest useful file anchor.
  Do not create a separate final-output section for this dimension.
- **Over-engineering (ponytail) pass**: run one dedicated dimension using the
  installed `ponytail-review` skill. Read and follow its `SKILL.md` before
  reviewing. Ask of every changed line whether it needs to exist. Look for
  reinvented standard-library or existing repository helpers, unneeded
  dependencies, speculative abstractions, dead flexibility, scaffolding, and
  code or scripts that duplicate an existing framework, such as a bash harness
  next to an existing test framework. Return findings in the shared agent
  format. Deduplicate against the implementation-quality and code-smell
  dimensions: those propose a cleaner version, this one proposes deletion. If
  the skill is unavailable, say so explicitly and cover this check in the main
  reviewer rather than pretending this pass ran.
- **Rust idiom pass, when applicable**: if the diff changes Rust source or crate
  files (`.rs`, `Cargo.toml`, `Cargo.lock`, build scripts, or Rust tests), run
  one dedicated Rust idiom dimension using the `rust-review` skill when
  available. That pass should review the Rust changed lines against the base
  branch for idiomatic, cleaner, more functional Rust: stronger types and
  constructors that make invalid states unrepresentable, better ownership and
  borrowing, `Result`/`Option` flow, trait and module ergonomics,
  async/concurrency idioms, and Cargo hygiene. Keep it calibrated as review
  feedback: surface only findings that materially improve the changed Rust code
  or its API, and do not turn formatting or personal style into noise.
- **Apollo Rust best-practices pass, when applicable**: for the same Rust change
  triggers, run a separate dedicated dimension using the installed
  `rust-best-practices` skill. Do not skip this dimension because `rust-review`
  already ran; the Apollo skill adds a handbook-backed check of borrowing and
  cloning, Clippy policy, performance, error handling, tests, generics and
  dispatch, type-state opportunities, documentation, and pointer safety. Follow
  the skill's instruction to read every chapter relevant to the changed code in
  parallel before reviewing. Run targeted Cargo, Clippy, or test commands when
  they are feasible and appropriate for the repository. Treat the handbook as
  review guidance rather than an override: the repository's MSRV, lint setup,
  dependency policy, public API constraints, and established local conventions
  win when they conflict. Return category-grouped, severity-ranked findings in
  the shared agent format, and report no finding when the changed Rust already
  follows the relevant guidance. If the skill is unavailable, say so explicitly
  and continue the other review dimensions rather than pretending this pass ran.

Every always-run dimension must return a findings list in the shared agent
format below. The list can be empty. Findings from all dimensions use the same
severity, file anchor, calibration, and inline-comment rules. Do not create a
dedicated final-output section for an always-run dimension. When a dimension
finds no concern, return `No findings` to synthesis and do not add an empty
dimension report to the final output.

Agent-determined dimensions:

- Generate a short list of additional dimensions from the actual PR. The list
  should be specific, non-overlapping, and appropriate to the change.
- Consider these sample dimensions only when the PR makes them relevant:
  correctness, data integrity, API contracts, auth and trust boundaries,
  migrations, rollout safety, concurrency, UI state, accessibility,
  performance, dependency/config risk, and tests.
- Do not run sample dimensions just because they are named here. Add a dimension
  only when the changed code, linked problem statement, deployment path, or
  surrounding system gives it a concrete review question.

Use the maximum useful parallelization available. First build the complete
review-dimension set: always-run dimensions, both Rust skill passes when
applicable, all agent-determined dimensions that the actual change justifies,
and any exploratory edge-case scenarios. Do not launch the always-run reviewers
before deciding which other dimensions are needed. Before launching agents,
decide how many subagents each dimension deserves and write a brief allocation
plan: dimension name, subagent count, independent focus areas, and why that
count is useful.

Allocate subagents by the number of independent questions, not by a fixed
one-agent-per-dimension rule:

- Use 0 delegated subagents only when the main reviewer can cover the dimension
  directly or subagents are unavailable. Always-run dimensions still need to be
  covered by the main reviewer when they are not delegated.
- Use 1 subagent for a narrow dimension with one coherent review question.
- Use 2-4 subagents for a broad or risky dimension with separable concerns, such
  as API behavior versus persistence behavior, client behavior versus server
  behavior, migration correctness versus rollback safety, or high-level
  approach choice versus whether the changed code fully delivers it.
- Use more than 4 subagents for one dimension only when the PR has genuinely
  independent files, flows, platforms, or threat boundaries that would otherwise
  hide meaningful bugs.

Edge-case exploration is separate from dimension allocation. Add up to 10
exploratory agents depending on how many independent edge cases deserve
step-by-step tracing; each exploratory agent should own one concrete scenario.

The total budget is up to 30 agents across dimension subagents and exploratory
edge-case agents. Do not fill the budget with duplicate work. If the useful plan
would exceed 30 agents, prioritize "Does this solve the right problem?", the
highest-risk always-run and agent-determined dimensions, both Rust skill passes
when applicable, the code-smell and cleanliness pass, and the most plausible
independent edge cases. Merge or drop lower-risk subquestions rather than
launching overlapping agents.

After the allocation plan is set, launch all delegated subagents concurrently in
one wave across every review category: always-run dimensions,
agent-determined dimensions, both Rust skill passes when applicable, and
exploratory edge-case agents. This is a single combined dispatch, not an
always-run phase followed by a second phase for triggered dimensions. Do not
run one category and wait for it before starting another unless a later subagent
genuinely depends on an earlier result. If the tooling cannot launch the full
plan in one batch, launch the largest independent cross-category batches
available and keep mixing always-run and triggered dimensions instead of
serializing by category.

Each review agent should receive:

- The full diff or focused subset relevant to its dimension.
- Full changed-file context and any necessary surrounding code.
- Prior reviewer feedback and linked-context summaries for PRs.
- A precise focus area or exploratory thesis, including the subfocus when
  multiple subagents are assigned to the same dimension.
- For a skill-backed dimension, the exact skill name and an explicit instruction
  to read and follow its `SKILL.md` before reviewing.

Classify each retained finding into exactly one category:

- **Does not require review**: Use this only for a specific implementation
  finding that has strong evidence, is highly likely to be correct, is easy to
  fix, and does not need a human to verify the finding or select the solution.
- **Requires Review**: Use this when a human must understand the finding and
  decide whether it is accurate, whether the proposed solution is correct, or
  whether the change fixes the right problem.

If any part of the finding needs human judgment, use `Requires Review`. The
category is independent of severity and merge impact: a Critical finding can be
in either category. Keep the severity and `file:line` anchor. Split independent
concerns when they belong in different categories, and do not report the same
concern in both. `Requires Review` does not permit speculative findings; every
reported finding must still pass the calibration rules in section 5.

Agent output format:

```markdown
## <focus area>
- [Does not require review|Requires Review]
  [Critical|Warning|Suggestion] file:line - <ASD-STE100 Simplified Technical
  English that explains what the code does, the concrete consequence, and the
  smallest useful fix.>
- No findings: <briefly state what was checked>.
- Edge cases checked: <scenario and conclusion, only when relevant>.
```

Write every finding for the engineer who owns the code:

- Use ASD-STE100 Simplified Technical English. Keep exact identifiers and
  necessary technical terms.
- Use 2-4 short, complete sentences rather than a compressed report fragment.
- Start with the concrete behavior in the code. Name the relevant value, request,
  state change, or caller when that makes the sentence clearer.
- Explain what happens in a realistic case and why the author should care.
- End with the smallest useful change or question. If the fix needs design work,
  say which boundary or behavior needs to change without pretending to know the
  exact patch.
- Prefer familiar words over review jargon. For example, write "a retry can
  enqueue the event twice" instead of "this violates the idempotency invariant."
  Use a technical term only when it is the clearest precise word, and explain
  what it means in this case.
- Do not use report labels such as `Issue:`, `Impact:`, `Risk:`, or `Fix:` inside
  a finding. Do not use stiff filler such as "This introduces a material risk,"
  "wrong abstraction," or "insufficiently robust" when the actual behavior can
  be stated directly.
- Match the wording to the evidence. Say "will" for a traced failure, "can" when
  a concrete condition triggers it, and "may" only when the uncertainty is real.

Prefer:

```markdown
- [Requires Review] [Critical] src/webhooks.rs:19 - Each replica keeps its own
  cache, so the same
  retry can reach another replica and be queued again. A restart clears the
  cache too, which means customers can still receive duplicate notifications.
  Store the event ID in shared durable state and reject duplicates there.
```

Avoid:

```markdown
- [Requires Review] [Critical] src/webhooks.rs:19 - Process-local deduplication
  violates the cross-replica idempotency invariant and creates material
  duplicate-delivery risk. Fix the abstraction.
```

The "Does this solve the right problem?" reviewer must use this same finding
format. A mismatch between the real need and the proposed approach is not merely
background commentary. Report it under Critical, Warning, or Suggestion with a
file anchor, impact, and fix direction, then let synthesis deduplicate it with
other dimensions. Use Critical when the change cannot meet its core requirement
or makes the intended rollout unsafe, Warning when it leaves an important part
of the problem unsolved or fixes it at the wrong layer, and Suggestion when the
approach works but adds avoidable complexity or constraints. When the approach
is sound, state that this dimension found no issue.

For code-smell findings, retain the normal severity but do not force a
`Code smell:` label. Lead with the concrete construct and explain in natural
sentences how it makes the code harder to read, test, change, or use safely. A
code-smell finding does not need to prove an active bug. If the exact refactor is
uncertain, state the smallest cleanup direction or say which boundary needs
design attention instead of inventing a patch.

For documentation and code-comment findings, point to the exact sentence or
comment and say what makes it hard to read: unnecessary length, vague behavior,
stock generated-sounding language, needless jargon, or narration of obvious
code. Give a short natural rewrite when the intended meaning is clear. Treat
misleading documentation as a correctness or contract concern when readers
could implement or operate the system incorrectly; keep prose-only cleanup
non-blocking and do not turn personal taste into review noise.

Exploratory agents should state the failure scenario they are testing, trace the
code path with concrete inputs or interleavings, and conclude whether the risk is
valid.

### Wait for All Review Agents

After you launch the review agents, wait for every agent to finish. Use the agent
status and wait tools until no review agent is pending or running. Collect every
completed result before you write the final findings, summary, crux areas,
verdict, or final response. You can continue to read code and run checks while
agents work, but do not start final synthesis from a partial result set.

If an agent fails, is canceled, or times out, retry it when its dimension is
still useful. If a retry is not possible, review that dimension in the main
agent and state the coverage gap. Do not treat the failed agent as a completed
review. Continue to sections 4 and 5 only after each delegated dimension has a
result or the main reviewer has covered it.

## 4. Summarize and Find the Crux

Write a factual 3-6 sentence summary of what the change does, grounded in code
rather than the PR description.

In plain language, state what problem the change is trying to fix, why it matters,
whether this approach fixes it, and whether the changed code fully delivers the
approach. Call out uncertainty when the available problem statement is
incomplete. Any concern identified here must also appear as a normal finding;
do not bury it in this summary.

Identify 0-5 crux areas that deserve human attention. Use `file:line` references
and one sentence that explains why each area is essential, subtle, irreversible,
domain-sensitive, or risky. Do not repeat or summarize findings from
`Requires Review` here. If the change is mechanical, say so.

Use the relevant edge-case traces during synthesis. Put each confirmed concern
in the standard findings list. Mention a safe trace only in `What Most Needs
Human Review` when it shows that the human does not need additional
investigation. Do not create an edge-case section, and do not present an
unchecked assumption as an investigated edge case.

## 5. Synthesize and Calibrate

Combine agent results into a final review:

- Deduplicate overlapping findings.
- Assign each retained finding to exactly one review category. The main reviewer
  must verify the evidence and final category instead of trusting a subagent's
  label without review.
- Group findings by review category first: `Does not require review`, then
  `Requires Review`. Within each category, prioritize by severity: Critical,
  Warning, Suggestion.
- Keep each item ready to use as one inline review comment. Do not create
  dimension-specific findings sections.
- Rewrite retained findings after deduplication so each one reads naturally:
  concrete behavior first, realistic consequence second, and the smallest useful
  fix or question last. Keep the technical detail, but remove report shorthand,
  unexplained jargon, and sentence fragments.
- Keep correctness, security, contract, and rollout findings only when they have
  a concrete current failure mode or material risk.
- Also keep code-smell findings when they point to specific quality debt
  introduced or materially worsened by the change and explain how it makes the
  code harder to understand, test, extend, or modify safely. A current runtime
  failure is not required for this category.
- Drop or downgrade findings that are speculative, disproportionate, outside the
  PR scope, already resolved, or mainly style preference.
- Preserve useful "no finding" edge-case traces when they explain why a plausible
  concern does not need more human review.
- Preserve findings from "Does this solve the right problem?" when the problem
  does not appear real, the change solves a different problem, the fix sits at
  the wrong layer, the added complexity is not justified, or the implementation
  handles only part of the real need. These are normal review findings, not
  narrative-only observations. Put them under `Requires Review` unless the
  evidence proves a specific, easy-to-fix implementation defect that does not
  need human judgment.
- Preserve implementation-quality findings when a cleaner local pattern,
  standard API, existing dependency feature, or justified library-backed approach
  would materially reduce complexity, duplication, invalid states, or future bug
  surface without adding disproportionate dependency or migration risk.
- Preserve over-engineering (ponytail) findings when the deletion is concrete
  and safe: the code, dependency, or script can go and a named existing helper,
  standard API, or framework covers the behavior. Deduplicate them against
  implementation-quality and code-smell findings.
- Preserve Apollo Rust best-practices findings when they identify a concrete
  problem in changed Rust and fit the repository's toolchain and conventions.
  Deduplicate them against `rust-review`, code-smell, performance, test, and
  correctness findings rather than reporting the same concern twice.
- Preserve documentation and code-comment findings when changed prose is
  needlessly long, indirect, vague, jargon-heavy, generated-sounding, or merely
  narrates the code. Prefer Suggestions for readability-only cleanup, or `nit:`
  when preparing GitHub comments; use a higher severity only when inaccurate or
  ambiguous wording can cause a real implementation, API, security, or
  operational mistake. Deduplicate prose findings against correctness,
  contract, and code-smell findings.
- Preserve code-smell findings that clearly identify what is not clean even when
  the best refactor is not yet certain. Prefer Suggestions for localized
  maintainability debt and Warnings when the smell materially increases defect
  risk, hides an invariant that other code relies on, or makes safe changes
  unusually hard.
  Do not let smell findings block approval unless their impact rises to a real
  correctness, security, contract, or rollout risk.
- Record notable dropped/downgraded items in `Calibrated out` only when useful
  for reviewer trust.

Verdict:

- **Approve**: no critical issues; remaining notes are minor.
- **Request Changes**: one or more critical issues must be fixed.
- **Needs Discussion**: the main risk is architectural, product, migration, or
  ownership judgment rather than a straightforward patch, including uncertainty
  about whether the problem is real or whether the change uses the right
  approach.

## GitHub Comment Guidance

Only when findings will be posted as GitHub comments: read `references/github-comments.md` and follow it.

## Final Output

Use this shape:

```markdown
# Code Review Summary

**Verdict:** [Approve / Request Changes / Needs Discussion]
**Files reviewed:** N files, +X/-Y lines
**Review scope:** [Local diff vs <base branch> / PR #N]

## Findings

### Does not require review
1. [Critical|Warning|Suggestion] [file:line] In 2-4 ASD-STE100 Simplified
   Technical English sentences, explain what the code does, what concrete
   failure or harm follows, and the smallest useful fix.

If this category has no findings, say "No findings."

### Requires Review
1. [Critical|Warning|Suggestion] [file:line] In 2-4 ASD-STE100 Simplified
   Technical English sentences, explain what needs human judgment, what the
   concrete consequence is, and which decision or change is needed.

If this category has no findings, say "No findings."

## What This Changes
[In 3-6 factual sentences, state what changed, what problem it tries to fix,
and whether the approach delivers the intended result. Do not repeat findings
or create a dimension-specific assessment.]

## What Most Needs Human Review
[0-5 non-finding crux areas that help a human inspect the change. Do not repeat
items from Requires Review. If none exist, say "No additional areas need human
attention."]

## Prior Discussion
[PRs only. Summarize unresolved threads, addressed concerns, and linked context consulted. Omit for local diffs.]

## Calibrated Out
[Omit if empty. List dropped or downgraded concerns with a short reason.]

## Positive Notes
[Brief, only if there is something specific worth calling out.]

---
**PR:** <PR URL> <!-- omit for local diffs -->
```

## Review Principles

- Reference exact files and lines.
- Group each finding into exactly one of `Does not require review` and
  `Requires Review`. Keep severity as a separate signal.
- Write findings in ASD-STE100 Simplified Technical English. Explain the code's
  behavior and consequence in short, direct sentences, not report fragments or
  abstract labels.
- Suggest realistic fixes or ask a clear, answerable question.
- Assess code smells independently from correctness and name concrete unclean
  constructs even when they are non-blocking.
- Always assess changed documentation and code comments for concise, natural,
  plain-language writing; replace vague stock phrasing with concrete behavior
  and avoid needless jargon.
- For Rust changes, run both the `rust-review` and `rust-best-practices` skills
  and deduplicate their findings.
- Always run the `ponytail-review` over-engineering pass; ask whether each
  changed line needs to exist.
- Read surrounding code before flagging a pattern.
- Consider backward compatibility, rollout safety, migrations, and feature flags.
- Avoid duplicating prior reviewer feedback unless it remains unresolved.
