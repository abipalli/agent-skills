# Evals

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
