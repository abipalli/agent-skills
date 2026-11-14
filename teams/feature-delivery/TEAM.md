---
schema: agentcompanies/v1
name: Feature delivery
slug: feature-delivery
description: "Takes one work item from intake to an approved PR. A conductor routes it through scoping, building in worktrees, and a multi-lane review panel; every stage is recorded on one durable run."
manager: "../../agents/conductor/AGENTS.md"
includes: ["../../agents/scoper/AGENTS.md", "../../agents/builder/AGENTS.md", "../../agents/reviewer/AGENTS.md", "../../skills/feature-pipeline/SKILL.md"]
tags: ["engineering", "delivery"]
---

The conductor runs the `feature-pipeline` skill. To build another pipeline, such as
bug triage or a dependency upgrade, write a new pipeline skill that reuses the
`stage-*` skills, and a team like this one that names it.
