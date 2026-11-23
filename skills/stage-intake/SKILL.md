---
name: stage-intake
description: "Pipeline stage 1: turn a work item into a brief and open its run. Loaded by a pipeline conductor such as feature-pipeline."
metadata:
  calls: ["run-ledger"]
---

# stage-intake

Dispatch to `scoper` with the raw input and the instructions below. Record what it
returns as the `intake` stage record.

## Open the run

If you know the target repo, run `$FP new <repo-dir> "<short title>" "<the request
verbatim>"` before you dispatch. Add `--stop-after <stage>` when the caller wants the run to stop
early, and `--from <ref> --escalate` when direct work is moving onto the pipeline. If you don't, let the scoper find the repo first,
then open the run. Report the RUN_ID to the user.

## Fetch (read-only)

Use whatever access the runtime has. When a source can't be read, say which one
and why; don't guess its content.

- **Free text:** the request as given.
- **GitHub issue or PR:** `gh issue view` / `gh pr view` with comments, plus any
  linked issues.
- **Jira key or URL:** the issue, its acceptance criteria, comments, linked issues
  and parent epic, through an Atlassian MCP server if one is connected.
- **Chat permalink** (Slack and similar): the whole thread, through the matching
  MCP server.

Then find the target repo's local main checkout. If more than one checkout
matches, list them and ask; do not guess. The repo must have
`.feature-pipeline.json` (see `run-ledger`).

## Record

```json
{"intake": {"status": "ok", "verdict": "ok", "summary": "", "reasoning": "",
  "source": {"kind": "text|github|jira|chat", "ref": "", "url": ""},
  "title": "",
  "ask": "The request in the requester's own words, quoted.",
  "acceptance_criteria": [],
  "context_links": [],
  "repo": {"name": "", "checkout": "", "base": ""},
  "requester": "",
  "next": "scope"}}
```

The verdict is `failed` when the source can't be read, for example because of
missing access or an MCP server that isn't connected. Say which.
