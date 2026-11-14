# GitHub Comment Guidance

When asked to prepare or submit GitHub comments, make them easy to apply:

- Treat `Does not require review` and `Requires Review` as report-grouping
  metadata. Do not add these category labels to an inline comment body.
- Prefer one finding per inline comment on the closest changed line.
- Include a GitHub suggestion block in inline comments whenever the fix can be
  expressed as an exact replacement for the commented changed line range.
- Use file comments for issues that belong outside the changed lines.
- Keep comments calibrated and actionable; do not post broad restatements of the
  final review.
- Do not include suggestion blocks for approximate fixes, multi-file changes,
  generated files, formatting-only churn, or patches that require unstated
  context.

Write GitHub comments like a senior human reviewer, not like a generated report:

- Write all findings in ASD-STE100 Simplified Technical English. Keep exact
  identifiers and necessary technical terms.
- Start each GitHub-ready comment with exactly one lowercase prefix:
  - `issue:` for bugs, correctness problems, security risks, broken contracts,
    missing required tests, or anything that should block/strongly delay merge.
  - `suggestion:` for non-blocking improvements that are still worth considering.
  - `nit:` for small readability, naming, or cleanup comments that are safe to
    ignore.
- Use natural prose in 1-2 short paragraphs.
- After the prefix, lead with the concrete code behavior, then explain the risk
  and the smallest useful ask.
- Do not add report-style labels after the prefix, such as "Impact:" or "Fix:".
  The prefix is enough structure; the rest should read like a normal review
  comment.
- Avoid stiff phrasing like "This causes a material risk" when a more direct
  sentence works: "If this path retries after the context is canceled, the caller
  can wait forever."
- Phrase requests as collaborative review comments: "Can we...", "I think this
  needs...", or "This looks like it can..." when that matches the certainty.
  Be direct for definite bugs.
- Include enough context that the author understands why the line matters
  without reading the full final review.

Suggestion blocks should be minimal, compile-ready, and limited to the lines the
inline comment is attached to. Put the reasoning outside the block and only the
replacement code inside it:

````markdown
issue: The fallback needs to preserve the caller's explicit timeout; otherwise
slow requests silently switch back to the default.

```suggestion
timeout = options.timeout ?? DEFAULT_TIMEOUT
```
````

Good comment shape:

```markdown
issue: This returns success even when the write fails, so callers will advance
the checkpoint and skip retrying the batch. Can we return the write error here
instead?
```

Avoid this shape in GitHub comments:

```markdown
issue: write errors are ignored.
Impact: data loss.
Fix: return the error.
```
