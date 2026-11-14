# agent-skills

Skills, agent roles and pipelines for coding agents. Every skill is a plain
`SKILL.md` in the [Agent Skills](https://agentskills.io) format, so it works in
Claude Code, Codex, Cursor and anything else that reads them. The agents and teams
follow the [Agent Companies](https://github.com/paperclipai/paperclip/blob/master/docs/companies/companies-spec.md)
spec, so [Paperclip](https://github.com/paperclipai/paperclip) can import the whole
pipeline as a team.

[CONVENTIONS.md](CONVENTIONS.md) is the contract every file follows, and
`scripts/validate.py` enforces it in CI.

## What's here

### Review

| Skill | Tier | What it does |
| :--- | :--- | :--- |
| `deep-code-review` | opus / xhigh | Multi-agent review of a diff or PR: correctness first, every finding verified against the code |
| `repo-review` | opus / xhigh | Whole-repository audit with a review map and a triage of fixes |
| `re-review` | opus / high | Re-review a PR after the author pushed fixes |
| `rust-review` | inherits | Rust-specific review lane |
| `rust-best-practices` | inherits | Rust idioms handbook, adapted from Apollo GraphQL |
| `submit-review` | inherits | Post a prepared review to a GitHub PR |

### Shipping

| Skill | Tier | What it does |
| :--- | :--- | :--- |
| `pr` | opus / high | Prepare, self-review and open a pull request |
| `merge` | inherits | Squash-merge a reviewed PR |
| `github-updates` | inherits | Triage recent PR activity across a set of repos |

### Authoring

| Skill | Tier | What it does |
| :--- | :--- | :--- |
| `skill-creator` | opus / high | Create, evaluate and tune skills, adapted from Anthropic's |

### The feature pipeline

`feature-pipeline` takes one work item through intake, scope, optional spikes,
build, a review panel and an approval gate, and ends in a PR. It is built from
parts you can reuse:

```text
team  feature-delivery
├── conductor  ── runs feature-pipeline, records every stage in run-ledger
├── scoper     ── stage-intake, stage-scope, read-only stage-spike
├── builder    ── stage-build, local stage-spike, in its own worktree
└── reviewer   ── stage-review lanes: deep-code-review, ponytail-review, rust-review
```

- **State** lives on one LiteLLM workflow run per job (`run-ledger`), so a job
  survives the session and any UI that reads those runs can show and resume it.
- **Approval** is decided by code: `fp approve` applies the repo's
  `.feature-pipeline.json` policy, covering diff size, sensitive paths, review
  severities, gates and scope risk. Anything that isn't clearly low-stakes goes to
  a person.
- **New pipelines** reuse the `stage-*` skills and the four roles. Write a pipeline
  skill that declares its stages, plus a team that names it (see CONVENTIONS.md).

`ponytail-review` is external. Install it from
[ponytail](https://github.com/DietrichGebert/ponytail), or the review stage skips
that lane.

## Install

**Claude Code, Codex, Cursor:** copy or link the skills you want into your agent's
skills directory:

```sh
git clone https://github.com/abipalli/agent-skills
ln -s "$PWD/agent-skills/skills/deep-code-review" ~/.claude/skills/
```

If you keep a dotfiles repo, add this one as a submodule and link its
`skills/*` directories. Use real files, not symlinks, inside any tree that
Paperclip or a GitHub skill installer reads: both skip symlinks.

**Paperclip:**

- **Skills:** add this repo as a company skill source (Skills → Sources), with
  automatic updates on.
- **The pipeline team:** `paperclipai company import abipalli/agent-skills
  --target existing --company-id <id> --include agents,skills`. Then set the
  conductor's `FP_LITELLM_KEY` and `GH_TOKEN` inputs.

## Contributing

1. Read [CONVENTIONS.md](CONVENTIONS.md). The tier rule and `metadata.calls` matter
   most.
2. Run `python3 scripts/validate.py --test && python3 scripts/validate.py`.
3. Run a skill's `evals/` with the `skill-creator` skill when you change its
   behaviour.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
