---
schema: agentcompanies/v1
name: Agent Skills
slug: agent-skills
description: "A library of agent skills, roles and pipelines. Import its agents and skills into an existing company, or start a new company from the feature-delivery team."
version: 0.1.0
license: Apache-2.0
authors: [
  {"name": "abipalli"}
]
homepage: "https://github.com/abipalli/agent-skills"
requirements:
  secrets: ["FP_LITELLM_KEY", "GH_TOKEN"]
---

This package is a library rather than a company. Most people import it into an
existing company with `--target existing --include agents,skills`. See README.md.
