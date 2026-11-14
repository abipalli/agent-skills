# Conventions

This repo is a library of **skills**, **agents** and **teams** that compose into
pipelines. It follows two open formats, so the same files work everywhere:

- [Agent Skills](https://agentskills.io) for `skills/<slug>/SKILL.md`: Claude Code,
  Codex, Cursor and anything else that reads `SKILL.md`.
- [Agent Companies](https://github.com/paperclipai/paperclip/blob/master/docs/companies/companies-spec.md)
  (`agentcompanies/v1`) for `agents/` and `teams/`, so Paperclip can import them.

`scripts/validate.py` enforces everything marked **must** below. CI runs it on every
push.

## Layout

```text
skills/<slug>/SKILL.md        a method: what to do and how
skills/<slug>/{scripts,references,assets,evals}/   optional, next to the skill that uses them
agents/<slug>/AGENTS.md       a role: who does it, with which skills, under which limits
teams/<slug>/TEAM.md          a composition: a manager agent plus the agents and skills it runs
.paperclip.yaml               runtime per agent (adapter, model, effort) for Paperclip
```

Skills, agents and teams are flat directories named by slug. Nothing nests: a
pipeline's stage skills live in `skills/` like any other skill, so other pipelines
can reuse them.

## Skills

```yaml
---
name: deep-code-review
model: opus
effort: xhigh
description: "What it does, then when to use it: the trigger phrases a user would type."
metadata:
  calls: ["rust-review", "ponytail-review"]
  sources: [
    {"kind": "github-dir", "repo": "owner/name", "path": "skills/foo", "license": "Apache-2.0", "usage": "adapted"}
  ]
---
```

- **`name`** must equal the directory name.
- **`description`** is required, at most 1024 characters.
- **`model` / `effort`**: entry points only, see "Tiers".
- **`metadata.sources`**: upstream provenance, when the skill is adapted.

**Frontmatter style is part of the contract.** Real YAML parsers (Claude Code,
Codex) and minimal ones read these files. Paperclip's reads a `>` folded string as
a literal `>`, and `[a, b]` as one string. In the portable style, both kinds read
the same:

- maps in block style;
- strings plain, or double-quoted on one line;
- lists as JSON arrays.

`scripts/validate.py --format` rewrites any frontmatter into this style, and plain
`validate.py` rejects anything else. Write frontmatter however you like and run
`--format`.

- **`description`** decides when the skill triggers. Lead with what it does, then the
  phrases that should trigger it. Don't use the description to summarise the body.
- **`metadata.calls`** must list every skill the body tells the agent to load or run,
  including skills from outside this repo (`ponytail-review`, say). The validator
  checks the calls inside this repo; calls to outside skills are reported as
  external.
- **No absolute paths, hostnames or personal details** anywhere in a skill. Refer to
  files next to the skill by relative path (`scripts/fp.py`), and to user
  configuration through environment variables.

### Tiers

Claude Code applies a skill's `model` and `effort` to **the rest of the turn**, not
only while the skill runs. A cheap callee therefore downgrades the expensive caller
that invoked it. The rule:

> Set `model` and `effort` only on skills a person invokes directly. A skill that
> other skills invoke leaves them unset and inherits its caller's tier. A callee may
> **raise** the tier but must never **lower** it.

The validator checks every `calls` edge. If both ends set a tier, the callee's must
be at least the caller's:

- model order: `haiku` < `sonnet` < `opus`
- effort order: `low` < `medium` < `high` < `xhigh` < `max`

| Tier | Use for |
| :--- | :--- |
| `opus` / `xhigh` | acceptance gates: the review that decides whether code ships |
| `opus` / `high` | judgement-heavy authoring: PRs, re-reviews, skill design |
| `sonnet` / `medium` | orchestration that delegates its hard parts to stronger callees |
| unset | callees |

## Agents

An agent is a role. `AGENTS.md` follows the Agent Companies spec. The frontmatter
says who the agent is and which skills it may use; the body is its standing
instructions.

```yaml
---
name: Reviewer
title: Code reviewer
description: Reviews one diff for one review lane. Report-only.
reportsTo: conductor
skills: ["deep-code-review", "rust-review"]
metadata:
  access: read-only     # read-only | worktree | publish
---
```

- `skills` must resolve to `skills/<slug>/` or be listed as external in the
  validator's report.
- `metadata.access` must be set:
  - `read-only`: reads code and tickets, never writes.
  - `worktree`: writes and commits inside the worktree it was handed. Never pushes.
  - `publish`: may push and open PRs. Only the conductor gets this, and only after a
    human approves.
- `reportsTo` is the slug of another agent, or `null`.
- **Runtime belongs in `.paperclip.yaml`, not in `AGENTS.md`.** That covers the
  adapter, model and effort. The spec keeps vendor config out of the portable
  package. Every agent must have an entry there. Write `.paperclip.yaml` in block
  style only.

## Teams and pipelines

A pipeline is a team: a **conductor** agent that runs a pipeline skill, plus the
agents the stages dispatch to. `TEAM.md` is the composition; the pipeline skill
declares its stages:

```yaml
metadata:
  calls: ["stage-intake", "stage-scope", "..."]
  pipeline:
    stages: [
      {"id": "scope", "agent": "scoper", "skill": "stage-scope", "verdicts": ["need_more_information", "spike", "defer", "rescoped", "proceed"]},
      {"id": "build", "agent": "builder", "skill": "stage-build", "verdicts": ["built", "partially_built", "failed"]}
    ]
```

Every stage's `agent` and `skill` must resolve. To add a stage, write its skill, add
one line, and route its verdicts in the pipeline skill's body. To build a different
pipeline, such as bug triage, reuse the stage skills and agents in a new pipeline
skill and team.

Run state does not live in any of these files. A pipeline records each stage as
events on one durable run (see `run-ledger`), so any UI can show and resume it.
