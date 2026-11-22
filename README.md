# agent-skills

Skills, agent roles and a delivery pipeline for coding agents.

- **Skills** are plain `SKILL.md` files in the [Agent Skills](https://agentskills.io)
  format, so they work in Claude Code, Codex, Cursor and anything else that reads
  them.
- **Agents and teams** follow the
  [Agent Companies](https://github.com/paperclipai/paperclip/blob/master/docs/companies/companies-spec.md)
  spec, so [Paperclip](https://github.com/paperclipai/paperclip) can import the
  pipeline as a team.

Every file follows [CONVENTIONS.md](CONVENTIONS.md), and `scripts/validate.py`
enforces it on every push.

## Skills

Every installed skill's description stays in your agent's context all the time,
so descriptions here are capped at 300 characters. Long detail lives in
`references/` files that load only when needed. Install only the skills you use.

**Tier** is the `model` / `effort` a skill sets when you invoke it. "inherits"
marks a skill that other skills call: it runs at its caller's tier (see
[Tiers](CONVENTIONS.md#tiers)).

### Review

| Skill | Tier | Use it to |
| :--- | :--- | :--- |
| [`deep-code-review`](skills/deep-code-review/SKILL.md) | opus / xhigh | review a diff, branch or PR in depth, with parallel passes and calibrated findings |
| [`repo-review`](skills/repo-review/SKILL.md) | opus / xhigh | audit a whole repository and triage the fixes |
| [`re-review`](skills/re-review/SKILL.md) | opus / high | check a PR's updates against your earlier review |
| [`rust-review`](skills/rust-review/SKILL.md) | inherits | add a Rust idiom lane to a review |
| [`rust-best-practices`](skills/rust-best-practices/SKILL.md) | inherits | write or refactor idiomatic Rust (adapted from Apollo GraphQL) |
| [`submit-review`](skills/submit-review/SKILL.md) | inherits | post findings as one PR review, after you approve the exact draft |

### Shipping

| Skill | Tier | Use it to |
| :--- | :--- | :--- |
| [`pr`](skills/pr/SKILL.md) | sonnet / medium | make a change and open a PR from your fork |
| [`merge`](skills/merge/SKILL.md) | inherits | approve and squash-merge a PR |
| [`github-updates`](skills/github-updates/SKILL.md) | inherits | brief the PRs that need you across your repos |

### Authoring

| Skill | Tier | Use it to |
| :--- | :--- | :--- |
| [`skill-creator`](skills/skill-creator/SKILL.md) | opus / high | create, evaluate and tune skills (adapted from Anthropic's) |

### The feature pipeline

[`feature-pipeline`](skills/feature-pipeline/SKILL.md) takes one work item through
intake, scope, optional spikes, build, a review panel and an approval gate, and
ends in a PR. It is assembled from parts you can reuse:

```text
team feature-delivery
├── conductor ─ runs feature-pipeline, records every stage with run-ledger
├── scoper    ─ stage-intake, stage-scope, read-only stage-spike
├── builder   ─ stage-build, local stage-spike, each in its own worktree
└── reviewer  ─ stage-review lanes: deep-code-review, ponytail-review, rust-review
```

| Skill | Tier | Role |
| :--- | :--- | :--- |
| [`feature-pipeline`](skills/feature-pipeline/SKILL.md) | sonnet / medium | the conductor: plans, routes, records |
| [`run-ledger`](skills/run-ledger/SKILL.md) | inherits | run state, repo gates and the approval policy (`scripts/fp.py`) |
| `stage-intake` … `stage-approve` | inherit | one skill per stage |

- **State.** Each job is one [LiteLLM](https://github.com/BerriAI/litellm)
  workflow run. The job survives the session, and any UI that reads those runs can
  show it and resume it. You need a LiteLLM proxy with workflow runs (v1.81+);
  see [`run-ledger`](skills/run-ledger/SKILL.md#prerequisites).
- **Per-repo config.** A `.feature-pipeline.json` at the repo root sets the gates
  (test, lint) and the approval policy. See
  [`run-ledger`](skills/run-ledger/SKILL.md#repo-config).
- **Approval.** Code decides it, not the model. `fp approve` applies the repo's
  policy: diff size, sensitive paths, review severities, gates and scope risk.
  Anything not clearly low-stakes goes to a person. Nothing merges on its own
  unless the repo sets `policy.auto_merge`.
- **New pipelines.** Reuse the `stage-*` skills and the four agent roles: write a
  pipeline skill that declares its stages, and a team that names it. See
  [Teams and pipelines](CONVENTIONS.md#teams-and-pipelines).

### Running a company

[`teams/company-core`](teams/company-core/TEAM.md) is the standing roster for a
company run by agents, for example in Paperclip:

| Agent | Does |
| :--- | :--- |
| [`chief-of-staff`](agents/chief-of-staff/AGENTS.md) | takes each delegated task, plans it, assigns the parts, follows up, and brings decisions to a person |
| [`researcher`](agents/researcher/AGENTS.md) | researches and drafts from public material on low-cost models; never sees personal data |
| [`conductor`](agents/conductor/AGENTS.md) | runs the feature pipeline for code changes |

Code goes to the conductor, research to the researcher, and anything that spends,
sends or commits goes to a person. In `.paperclip.yaml` every agent has its
heartbeat timer off and wakes when it is assigned work, so an idle company costs
nothing.

### Vendored skill packs

Third-party packs live under `vendor/` as git submodules pinned to a known
commit, so an upstream change arrives only as a reviewed submodule bump.

| Pack | License | Recommended skills |
| :--- | :--- | :--- |
| [ponytail](https://github.com/DietrichGebert/ponytail) | MIT | `ponytail` (always-on minimal-code ruleset), `ponytail-review` (the review panel's over-engineering lane), `ponytail-debt` |
| [caveman](https://github.com/JuliusBrussee/caveman) | Apache-2.0 | `caveman` (terse output), `caveman-commit`, `caveman-compress` |
| [gh-stack](https://github.com/github/gh-stack) | MIT | `gh-stack` (stacked PRs) |

Each pack ships more skills than these. Link only the ones you want, since every
linked skill adds its description to your context.

## Install

### Claude Code, Codex, Cursor

Clone with submodules, then link the skills you want into your agent's skills
directory:

```sh
git clone --recurse-submodules https://github.com/abipalli/agent-skills
cd agent-skills
for s in deep-code-review rust-review submit-review; do
  ln -s "$PWD/skills/$s" ~/.claude/skills/$s      # Codex: ~/.codex/skills, Cursor: ~/.cursor/skills
done
ln -s "$PWD/vendor/ponytail/skills/ponytail-review" ~/.claude/skills/ponytail-review
```

A callee skill must be installed next to the skill that calls it. For example,
`deep-code-review` uses `rust-review` and `ponytail-review`. The `metadata.calls`
list in each `SKILL.md` names what a skill needs.

To keep it in a dotfiles repo, add this repo as a submodule and link from there.
Update it with `git submodule update --remote`.

### Paperclip

- **Skills:** add `https://github.com/abipalli/agent-skills` as a company skill
  source (Skills → Sources), with automatic updates on. Paperclip skips submodules,
  so add a vendored pack's own repo as a separate source if you want it.
- **The pipeline team:**

  ```sh
  paperclipai company import abipalli/agent-skills --target existing \
    --company-id <id> --include agents,skills --dry-run   # drop --dry-run to apply
  ```

  Then give the conductor its `FP_LITELLM_KEY` and `GH_TOKEN` inputs. Model and
  effort per role come from [`.paperclip.yaml`](.paperclip.yaml).

## Contributing

1. Read [CONVENTIONS.md](CONVENTIONS.md). The rules that matter most:
   - descriptions of at most 300 characters;
   - the tier rule;
   - `metadata.calls`;
   - no private paths, hosts or emails.
2. Run the checks:

   ```sh
   pip install pyyaml
   python3 scripts/validate.py --test && python3 scripts/validate.py
   ```

   `--format` rewrites frontmatter into the portable style the validator requires.
3. If you change a skill's behaviour, run its `evals/` with
   [`skill-creator`](skills/skill-creator/SKILL.md).

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Vendored packs keep their
own licenses.
