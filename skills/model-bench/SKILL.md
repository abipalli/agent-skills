---
name: model-bench
description: "Benchmark a model through LiteLLM the same way every time: systems, tool calling, voice rules, strict JSON and rubric spot checks, with the exact build recorded. Use for \"benchmark this model\", \"compare models\", \"should X replace Y\"."
metadata:
  calls: []
---

# model-bench

One harness for every model. `scripts/model-bench.py` calls a model **by its LiteLLM name**,
runs the versioned suites in `suites/`, and writes one JSON result per suite run, plus a
markdown report across runs. Run it with `uv run --script` (it declares `pyyaml` inline).

```sh
MB=<this skill's directory>/scripts/model-bench.py
$MB selftest                                          # scorers, no network
$MB snapshot                                          # host state: ollama ps, GPU, RAM, swap
$MB run MODEL --build build.json --phase cold --suite systems
$MB run MODEL --build build.json                      # warm: all five suites
$MB report $RESULTS/*.json --out report.md
```

Environment: `MODEL_BENCH_URL`, `MODEL_BENCH_KEY` (or `~/.config/model-bench/key`),
`MODEL_BENCH_RESULTS` (default `~/.local/share/model-bench`), and optionally
`MODEL_BENCH_SSH` and `MODEL_BENCH_OLLAMA` for host snapshots.

## Rules of the method

1. **Record the build or don't run.** `build.json` must name `model_id` (LiteLLM's
   `model_info.id`), `runtime`, `runtime_version`, `weights`, `weights_hash` (Ollama digest or
   file SHA-256), `quantization` and `context`. Add the route's own parameters (thinking,
   reasoning effort) under `params`, and a short `label` for the report. Every response's
   `x-litellm-model-id` is checked against `model_id`. A fallback to another model is flagged,
   never averaged in.
2. **Measure models as deployed.** The harness sends only the prompt, sampling and
   `max_tokens`. Thinking, reasoning effort and `num_ctx` belong to the route. To compare
   settings, make two routes and two build files.
3. **Same exam for everyone.** Suites are frozen: changing a case means a new
   `<suite>.v<N+1>.yaml`. Results carry the suite's version and SHA-256. Compare only results with
   the same suite hash. Prompts and tool schemas come verbatim from production
   (`suites/fixtures/`), copied by extraction, not retyped.
4. **Smoke before score.** A warm run first checks a trivial prompt. If it fails, the run
   aborts with "runtime broken" instead of scoring the model zero.
5. **Cold and warm are separate runs.** For cold, the model must not be loaded: unload it, check
   with `snapshot`, then `--phase cold`. Cold load ≈ cold `ping` TTFT minus warm `ping` TTFT.
   Never unload a resident production model without the owner's go-ahead, and reload it and
   confirm it is back when done.
6. **Repetitions, median and spread.** At least 3 repetitions, interleaved (every case's rep 1,
   then rep 2...). The report shows the median with [min–max]. Fixed temperature and seed come
   from the suite. Seeds don't make GPU decoding deterministic, so spread is still expected.
7. **Defeat caches where they would lie.** Systems prompts start with a per-request nonce, so a
   prefix cache never serves a repetition. Prefill rates use each model's own token count, and the
   result also keeps `prompt_chars`, because tokenizers differ.
8. **Rubrics, not impressions.** Every quality point is a deterministic check (regex, word
   limits, executed unit tests). No judge model, which would be one more model to benchmark.
9. **The machine is part of the result.** A host snapshot is saved before and after each run.
   Swap above 90% or a co-resident model is flagged in the report.
10. **Score structured output the way its caller parses it.** The JSON suite records strict and
    lenient parses, and `caller_ok` uses the caller's own rule.

## Adding a model

1. Make it reachable as a LiteLLM route whose name starts with `local-` if it runs locally: the
   PII guard treats every other name as egress and would mask or rewrite the benchmark prompts.
2. Write its `build.json` (see rule 1).
3. Run cold, then warm, then `report` with the baselines' latest results for the same suite
   hashes.

## Suites

| Suite | Measures | Scored by |
|---|---|---|
| `systems` | TTFT, decode tok/s, prefill tok/s at about 2k and 16k tokens, long-context recall | streamed timings, regex recall |
| `tools` | right tool, schema-valid arguments, no invented tools, no tool when none is needed | first-turn `tool_calls` vs `expect` |
| `voice` | at most 40 words, plain text, no tool on chat questions | word count, markdown regex |
| `json` | reframer (lenient, 800 tokens) and card (strict, `json_object`, 300 tokens) | parse, shape, expected values |
| `quality` | arithmetic, ordering, extraction, summary fidelity, format, honesty, code | rubric checks, executed tests |
