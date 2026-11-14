---
name: skill-creator
description: "Create, revise, evaluate, package, and optimize agent skills (SKILL.md for Claude Code, Codex, Cursor and other Agent Skills readers). Use whenever the user wants to create a new skill, improve an existing SKILL.md, make a skill more concise, run skill evals, compare skill versions, optimize a description for trigger accuracy, package a .skill file, or prepare a skill for a shared skills repo."
model: opus
effort: high
metadata:
  calls: []
  sources: [
    {"kind": "github-dir", "repo": "anthropics/skills", "path": "skills/skill-creator", "license": "Apache-2.0", "usage": "adapted"}
  ]
---

# Skill Creator

Use this skill to help the user create or improve skills. Start from the user's current stage: sketching an idea, editing a draft, running evals, reading feedback, optimizing the description, packaging, or committing the skill.

**Prerequisites:** Python 3 with PyYAML for the bundled scripts. Description optimization (`scripts.run_loop`) shells out to the Claude Code CLI (`claude -p`); without it, skip that step. Parallel eval runs need an agent that can start subagents; otherwise run evals serially.

Keep the process lean. If the user asks for a quick review or rewrite, do that directly. If quality is uncertain or the skill drives repeatable work, propose and run evals.

## Core Loop

1. Capture intent and constraints.
2. Draft or revise `SKILL.md`.
3. Create realistic eval prompts in `evals/evals.json`.
4. Run each eval with the skill and against a baseline.
5. Grade outputs, aggregate results, and generate the review viewer.
6. Read user feedback, improve the skill, and repeat until the user is satisfied.
7. Optionally optimize the frontmatter description, package the skill, and commit it where it lives (see "Where Skills Go").

When you maintain a todo list, include the eval and viewer work explicitly so it is not skipped.

## Communication

Match the user's technical level. Terms like "eval" and "benchmark" are usually fine; explain "JSON", "assertion", or "schema" when the user has not shown familiarity. Prefer short, practical explanations over process lectures.

## Creating Or Revising A Skill

### Capture Intent

First extract what you can from the conversation, existing files, examples, corrections, tools used, and desired outputs. Ask only for missing information that materially affects the skill.

Clarify:

- What should the skill enable?
- When should it trigger, including user phrases and nearby competing skills?
- What output format or artifact should it produce?
- What examples, edge cases, dependencies, or source files matter?
- Should this be tested with evals? Objective workflows usually should; subjective writing or taste-heavy work may rely on human review.

For an existing skill, preserve its directory name and frontmatter `name` unless the user explicitly wants a rename.

### Write `SKILL.md`

A skill directory has:

```text
skill-name/
+-- SKILL.md
+-- scripts/      # optional deterministic helpers
+-- references/   # optional docs loaded only when relevant
`-- assets/       # optional templates or source assets
```

Frontmatter must include:

- `name`: stable skill identifier, equal to the directory name.
- `description`: the primary trigger surface, at most 1024 characters. Lead with what the skill does, then the "when to use this" language: likely user phrases and near-miss contexts. Be explicit enough to avoid under-triggering.

When the skill tells the agent to load or run other skills, list them in `metadata.calls`. Set `model`/`effort` only as described in "Model and effort frontmatter" below.

Body guidance:

- Use imperative instructions.
- Explain why key steps matter instead of relying on all-caps rules.
- Keep `SKILL.md` focused. Move long schemas, domain variants, examples, and tool details into `references/`, `scripts/`, or `assets/`.
- Bundle scripts when eval transcripts show agents repeatedly inventing the same helper.
- Do not create skills for malware, unauthorized access, data exfiltration, deception, or behavior that would surprise the user given the skill description.

For large or multi-domain skills, route by variant:

```text
deploy-helper/
+-- SKILL.md
`-- references/
    +-- aws.md
    +-- gcp.md
    `-- azure.md
```

Tell the model which reference to read and when.

### Context Budget

Every installed skill costs context. Treat it as a design constraint, from the
Claude Code skill docs (code.claude.com/docs/en/skills, context-window,
plugins/measure):

- **Always on**: every session lists each skill's `name` and `description`
  (+ `when_to_use`), capped at 1,536 characters each, inside a listing budget
  of about 1% of the context window. Over budget, the least-used skills lose
  their descriptions first. Keep descriptions short, key use case first, and
  spend words on trigger phrases and near misses, not on how the skill works.
- **On invoke**: the whole body loads once and stays. Keep it under 500 lines;
  move schemas, variants, and examples to `references/` with a line saying
  when to read each. Scripts run without loading.
- **After compaction** only the first 5,000 tokens of each skill survive, so
  put must-hold rules near the top. Rules that must never break belong in
  hooks, not prose.
- **Frontmatter levers**: `disable-model-invocation: true` removes the
  description from context entirely (use it for side-effect skills a person
  starts on purpose: merge, submit, deploy); `context: fork` runs a heavy
  skill in a subagent so its work stays out of the main context;
  `paths` limits activation to matching files. For rarely used skills,
  `skillOverrides` in settings can set `name-only` or `off` (not for plugin
  skills; manage those with `/plugin disable`).
- **Measure** before and after a change: description length, body lines, and
  `/skill-doctor` or `/context` (Skills row). Benchmarks already record tokens
  per run; call out a revision that raises them.

Other agents that read `SKILL.md` have their own limits and levers; the habits
(short descriptions, lean bodies, detail in `references/`) carry over.

## Evals

Do not use `/skill-test` or a separate testing skill. Use this workflow unless the user explicitly asks to skip evals.

### Eval Set

Create 2-3 realistic prompts first. Show them to the user when useful, then save them at `evals/evals.json`:

```json
{
  "skill_name": "example-skill",
  "evals": [
    {
      "id": 1,
      "prompt": "User-like task prompt",
      "expected_output": "What success looks like",
      "files": [],
      "expectations": []
    }
  ]
}
```

Use `references/schemas.md` for full schemas. Use `expectations` consistently; grading and benchmark scripts expect that field name.

### Workspace Layout

Put results in a sibling workspace:

```text
<skill-name>-workspace/
`-- iteration-1/
    `-- eval-<id-or-name>/
        +-- eval_metadata.json
        +-- with_skill/
        `-- without_skill/ or old_skill/
```

For each eval, write `eval_metadata.json`:

```json
{
  "eval_id": 0,
  "eval_name": "descriptive-name",
  "prompt": "The eval prompt",
  "expectations": []
}
```

Use descriptive eval directory names when possible.

### Run Skill And Baseline

If independent workers or subagents are available and permitted, launch all eval runs in the same turn: every `with_skill` run plus its baseline. If not, run them inline or serially and keep the same workspace shape.

Use these baselines:

- New skill: `without_skill`.
- Existing skill: snapshot the original skill before editing and use it as `old_skill`, unless a previous iteration is the more useful comparison.

Example worker prompt:

```text
Execute this task:
- Skill path: <path-to-skill>
- Task: <eval prompt>
- Input files: <files or none>
- Save outputs to: <workspace>/iteration-<N>/<eval-name>/with_skill/outputs/
- Outputs to save: <artifacts the user cares about>
```

For baseline runs, omit the skill path for `without_skill` or point at the snapshot for `old_skill`.

### Draft Expectations While Runs Execute

Use run time to add objective expectations to `evals/evals.json` and each `eval_metadata.json`. Good expectations are verifiable and hard to satisfy accidentally. For subjective skills, prefer qualitative review instead of fake precision.

Explain briefly what the expectations check and what the viewer will show.

### Capture Timing

When worker completion notifications include `total_tokens` and `duration_ms`, immediately save them to the run's `timing.json`:

```json
{
  "total_tokens": 84852,
  "duration_ms": 23332,
  "total_duration_seconds": 23.3
}
```

This data is not recoverable later.

### Grade And Aggregate

After all runs finish:

1. Grade each run. Use `agents/grader.md` for grading instructions, or grade inline for small cases. Save `grading.json` beside `outputs/`. Its `expectations` array must contain `text`, `passed`, and `evidence`.
2. Prefer scripts for programmatically checkable expectations.
3. Aggregate:

```bash
python -m scripts.aggregate_benchmark <workspace>/iteration-N --skill-name <name>
```

4. Read `benchmark.json` and do an analyst pass. Use `agents/analyzer.md` when the results need deeper interpretation.

### Generate The Review Viewer

Always generate the eval viewer before revising based on your own judgment; the human should see outputs early.

```bash
nohup python <skill-creator-path>/eval-viewer/generate_review.py \
  <workspace>/iteration-N \
  --skill-name "my-skill" \
  --benchmark <workspace>/iteration-N/benchmark.json \
  > /dev/null 2>&1 &
VIEWER_PID=$!
```

For iteration 2+, add:

```bash
--previous-workspace <workspace>/iteration-<N-1>
```

In headless or Cowork environments, use:

```bash
python <skill-creator-path>/eval-viewer/generate_review.py \
  <workspace>/iteration-N \
  --skill-name "my-skill" \
  --benchmark <workspace>/iteration-N/benchmark.json \
  --static <workspace>/iteration-N/review.html
```

Tell the user where to review the outputs and benchmark. The viewer lets them inspect outputs, formal grades, prior outputs for later iterations, and feedback. When they are done, read `feedback.json`. Empty feedback means the run looked acceptable.

Kill the viewer server after feedback:

```bash
kill $VIEWER_PID 2>/dev/null
```

## Improving A Skill

Use feedback and transcripts to make general improvements, not eval-specific hacks.

Look for:

- Repeated user complaints or failed expectations.
- Instructions that caused wasted work or tool misuse.
- Missing scripts for repeated deterministic work.
- Weak expectations that pass bad outputs.
- Overly rigid rules that should instead explain the reason behind the behavior.

After editing, rerun evals into `iteration-<N+1>/`, generate the viewer with `--previous-workspace`, read feedback, and continue until the user is satisfied, feedback is empty, or changes stop improving results.

For rigorous A/B comparisons, read `agents/comparator.md` and `agents/analyzer.md`.

## Description Optimization

Offer description optimization after the skill behavior is in good shape.

1. Create about 20 realistic trigger eval queries: 8-10 should-trigger and 8-10 should-not-trigger. Make negatives near misses, not irrelevant prompts. Save JSON entries as:

```json
{"query": "realistic user prompt", "should_trigger": true}
```

2. Let the user review the eval set with `assets/eval_review.html`. Replace:
   - `__EVAL_DATA_PLACEHOLDER__` with the JSON array, not a quoted string.
   - `__SKILL_NAME_PLACEHOLDER__` with the skill name.
   - `__SKILL_DESCRIPTION_PLACEHOLDER__` with the current description.

3. Save the reviewed eval set, then run:

```bash
python -m scripts.run_loop \
  --eval-set <path-to-trigger-eval.json> \
  --skill-path <path-to-skill> \
  --model <model-id-powering-this-session> \
  --max-iterations 5 \
  --verbose
```

The loop evaluates trigger accuracy, proposes descriptions, uses a train/test split, and reports `best_description`. Apply it to frontmatter, then show before/after and scores.

Trigger eval prompts should be substantive. Very simple tasks may not trigger any skill because the base assistant can handle them without one.

## Packaging

If packaging is useful and the tools are available:

```bash
python -m scripts.package_skill <path/to/skill-folder>
```

Package from a writable copy if the installed skill directory is read-only. Preserve the original skill name for updates.

## Where Skills Go

- **A personal skill**: the user's own skills directory, wherever their agent reads skills from (for example a project's `.claude/skills/<name>/`, or the user-level skills directory of Claude Code, Codex or Cursor). If the user keeps one shared tree linked into several agents, write into that tree, not into a linked copy. Ask when unsure.
- **A contribution to a shared skills repo**: `skills/<slug>/SKILL.md`, with helpers in `scripts/`, `references/`, `assets/` or `evals/` beside it. If the repo has a `CONVENTIONS.md`, read it first and follow it; it overrides the general guidance here. (The agent-skills library this skill is published in has one; it covers the frontmatter, the tier rule below, `metadata.calls`, and keeping private details out.)

### Model and effort frontmatter

In Claude Code, a skill's `model`/`effort` override applies **for the rest of the turn**, not just while the skill runs, so a skill invoked by another skill can downgrade its caller. Set `model`/`effort` only on skills a person invokes directly. Leave them unset on any skill that other skills invoke, so it inherits the caller's tier. Raising the tier in a callee is safe; lowering it is not.

### Keep it portable

A skill meant for others must not carry the author's private context. Before sharing, remove names, employers, internal tools and channels, company repos and orgs, absolute paths, private hostnames and emails. Turn user-specific values (a GitHub handle, the repos to watch, a timezone) into inputs or environment variables, and state any required tool (`gh`, an MCP server, an agent-specific feature) as a prerequisite.

### Commit

If the skill lives in a git repo, stage only the skill's directory, review the diff, and commit. Push only when the user asks.

## Environment Notes

Claude.ai: no subagents, so run evals yourself one at a time, skip baselines and quantitative benchmarks, and collect qualitative feedback in conversation. Skip description optimization if `claude -p` is unavailable.

Cowork/headless: subagents may be available, but browser display may not be. Use `--static` for the eval viewer and ask the user to provide the downloaded `feedback.json`.

## Reference Files

- `agents/grader.md`: grading outputs and critiquing expectations.
- `agents/comparator.md`: blind A/B comparisons.
- `agents/analyzer.md`: benchmark and comparison analysis.
- `references/schemas.md`: expected JSON structures.
