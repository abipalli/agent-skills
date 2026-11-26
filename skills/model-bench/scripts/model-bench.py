#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""Standard model benchmark through a LiteLLM proxy: one harness, versioned suites, JSON results.

Environment: MODEL_BENCH_URL (LiteLLM base URL, required), MODEL_BENCH_KEY or the key in
~/.config/model-bench/key, MODEL_BENCH_RESULTS (default ~/.local/share/model-bench),
MODEL_BENCH_SSH (optional ssh target for host snapshots, or `local` to run them here), MODEL_BENCH_OLLAMA
(Ollama container name on that host, for `ollama ps`).

  model-bench.py run MODEL --build BUILD.json --suite S[,S...] [--reps N] [--phase warm|cold] [--tag T]
                    [--host-before SNAP.json]   snapshot taken elsewhere, when the run host can't see the GPU
  model-bench.py attach RESULT.json --host-after SNAP.json
  model-bench.py report RESULT.json... [--out FILE]
  model-bench.py snapshot
  model-bench.py selftest            scorer checks, no network
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import random
import re
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


HERE = Path(__file__).resolve().parent.parent
SUITES = HERE / "suites"
RESULTS = Path(os.environ.get("MODEL_BENCH_RESULTS", "~/.local/share/model-bench")).expanduser()
BUILD_FIELDS = ("model_id", "runtime", "runtime_version", "weights", "weights_hash", "quantization", "context")
SMOKE = "Reply with the single word: ready"


# MARK: HTTP

def key() -> str:
    k = os.environ.get("MODEL_BENCH_KEY")
    if k:
        return k
    path = Path("~/.config/model-bench/key").expanduser()
    if path.exists():
        return path.read_text().strip()
    sys.exit("no key: set MODEL_BENCH_KEY or write ~/.config/model-bench/key")


def base_url() -> str:
    url = os.environ.get("MODEL_BENCH_URL")
    if not url:
        sys.exit("MODEL_BENCH_URL is not set")
    return url.rstrip("/")


def post(body: dict, timeout: float = 600) -> tuple[dict, dict]:
    req = urllib.request.Request(
        f"{base_url()}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key()}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp), dict(resp.headers)


def stream(body: dict, timeout: float = 900) -> dict:
    """Streamed call; times the first token of any kind (reasoning counts) and the last."""
    body = {**body, "stream": True, "stream_options": {"include_usage": True}}
    req = urllib.request.Request(
        f"{base_url()}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key()}", "Content-Type": "application/json"},
    )
    began = time.perf_counter()
    first = first_content = None
    content, reasoning, usage, finish = [], [], {}, None
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        headers = dict(resp.headers)
        for raw in resp:
            line = raw.decode().strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            chunk = json.loads(line[5:])
            usage = chunk.get("usage") or usage
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                text = delta.get("content") or ""
                think = delta.get("reasoning_content") or ""
                now = time.perf_counter()
                if (text or think or delta.get("tool_calls")) and first is None:
                    first = now
                if text and first_content is None:
                    first_content = now
                content.append(text)
                reasoning.append(think)
                finish = choice.get("finish_reason") or finish
    end = time.perf_counter()
    return {
        "headers": headers, "content": "".join(content), "reasoning": "".join(reasoning),
        "usage": usage, "finish": finish, "total_s": end - began,
        "ttft_s": (first - began) if first else None,
        "ttfc_s": (first_content - began) if first_content else None,
        "gen_s": (end - first) if first else None,
    }


# MARK: Host snapshot

def snapshot() -> dict:
    host = os.environ.get("MODEL_BENCH_SSH")
    if not host:
        return {"note": "MODEL_BENCH_SSH unset; no host snapshot"}
    ollama = os.environ.get("MODEL_BENCH_OLLAMA")
    cmd = "; ".join(filter(None, [
        f"echo '## ollama ps'; docker exec {ollama} ollama ps" if ollama else "",
        "echo '## gpu'; nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader,nounits",
        "echo '## gpu apps'; nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader",
        "echo '## mem'; free -m",
        "echo '## load'; cat /proc/loadavg",
    ]))
    argv = ["sh", "-c", cmd] if host == "local" else ["ssh", "-o", "ConnectTimeout=10", host, cmd]
    try:
        out = subprocess.run(argv,
                             capture_output=True, text=True, timeout=60).stdout
    except subprocess.TimeoutExpired:
        return {"error": "snapshot timed out"}
    snap: dict = {"raw": out, "at": now_iso()}
    if m := re.search(r"## gpu\n(\d+), (\d+), (\d+), (\d+)", out):
        snap["gpu"] = dict(zip(("used_mib", "total_mib", "util_pct", "temp_c"), map(int, m.groups())))
    if m := re.search(r"Mem:\s+(\d+)\s+(\d+)\s+\d+\s+\d+\s+\d+\s+(\d+)\nSwap:\s+(\d+)\s+(\d+)", out):
        total, used, avail, swap_total, swap_used = map(int, m.groups())
        snap["mem"] = {"total_mb": total, "used_mb": used, "available_mb": avail,
                       "swap_total_mb": swap_total, "swap_used_mb": swap_used}
        if swap_total and swap_used / swap_total > 0.9:
            snap.setdefault("warnings", []).append(f"swap {swap_used}/{swap_total} MB")
    return snap


# MARK: Suites

def load_suite(name: str) -> dict:
    import yaml
    path = SUITES / f"{name}.yaml" if name.endswith(tuple(f".v{i}" for i in range(1, 100))) else None
    if path is None:
        versions = sorted(SUITES.glob(f"{name}.v*.yaml"), key=lambda p: int(p.stem.rsplit(".v", 1)[1]))
        if not versions:
            sys.exit(f"no suite {name!r} in {SUITES}")
        path = versions[-1]
    raw = path.read_bytes()
    suite = yaml.safe_load(raw)
    suite["_file"], suite["_sha256"] = path.name, hashlib.sha256(raw).hexdigest()
    return suite


def resolve(value):
    if isinstance(value, dict) and "fixture" in value:
        return json.loads((SUITES / "fixtures" / value["fixture"]).read_text())[value["key"]]
    return value


WORDS = ("harbour lantern ledger copper orchard meadow quarry signal canal beacon timber granite "
         "willow ferry archive pasture compass mill river cellar tower barley furnace slate").split()


def filler(seed: str, tokens: int, needle: str, at: float) -> str:
    rng = random.Random(seed)
    sentences, words = [], 0
    while words < tokens * 0.75:
        n = rng.randint(8, 16)
        s = f"Record {len(sentences) + 1}: the " + " ".join(rng.choice(WORDS) for _ in range(n)) + "."
        sentences.append(s)
        words += n + 3
    sentences.insert(int(len(sentences) * at), needle)
    return " ".join(sentences)


# MARK: Scoring

MARKDOWN = re.compile(r"(\*\*|__|`|^#{1,6}\s|^\s*[-*•]\s|^\s*\d+[.)]\s|\[[^\]]+\]\([^)]+\))", re.M)


def word_count(text: str) -> int:
    return len(re.findall(r"[\w'’]+(?:[-.,][\w'’]+)*", text))


def python_tests(text: str, entry: str, tests: list) -> bool:
    m = re.search(r"```(?:python)?\n(.*?)```", text, re.S)
    code = m.group(1) if m else text
    harness = code + f"\nimport json\nprint(json.dumps([{entry}(a) == b for a, b in {tests!r}]))\n"
    with tempfile.TemporaryDirectory() as tmp:
        try:
            out = subprocess.run([sys.executable, "-I", "-S", "-c", harness], cwd=tmp, env={},
                                 capture_output=True, text=True, timeout=10).stdout
            return all(json.loads(out.strip().splitlines()[-1]))
        except (subprocess.TimeoutExpired, ValueError, IndexError):
            return False


def check(rule: dict, text: str, tool_calls: list) -> bool:
    kind = rule["check"]
    if kind == "regex":
        return bool(re.search(rule["pattern"], text))
    if kind == "regex_absent":
        return not re.search(rule["pattern"], text)
    if kind == "min_words":
        return word_count(text) >= rule["value"]
    if kind == "max_words":
        return word_count(text) <= rule["value"]
    if kind == "no_markdown":
        return not MARKDOWN.search(text)
    if kind == "nonempty":
        return bool(text.strip())
    if kind == "no_tool":
        return not tool_calls
    if kind == "python_tests":
        return python_tests(text, rule["entry"], rule["tests"])
    raise ValueError(f"unknown check {kind}")


def schema_ok(schema: dict, args) -> bool:
    if not isinstance(args, dict):
        return False
    types = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
             "object": dict, "array": list}
    props = schema.get("properties") or {}
    if any(k not in args for k in schema.get("required") or []):
        return False
    for name, value in args.items():
        spec = props.get(name)
        if spec is None:
            continue
        want = types.get(spec.get("type"))
        if want and (not isinstance(value, want) or (want is int and isinstance(value, bool))):
            return False
        if "minimum" in spec and isinstance(value, (int, float)) and value < spec["minimum"]:
            return False
        if "maximum" in spec and isinstance(value, (int, float)) and value > spec["maximum"]:
            return False
    return True


def score_tools(case: dict, tools: list, message: dict) -> dict:
    offered = {t["function"]["name"]: t["function"].get("parameters") or {} for t in tools}
    calls = []
    for c in message.get("tool_calls") or []:
        try:
            args = json.loads(c["function"].get("arguments") or "{}")
        except ValueError:
            args = None
        calls.append((c["function"]["name"], args))
    expect = case["expect"]
    accept = expect["tool"] if isinstance(expect["tool"], list) else [expect["tool"]]
    chosen = calls[0][0] if calls else None
    invented = [n for n, _ in calls if n not in offered]
    valid = all(n in offered and schema_ok(offered[n], a) for n, a in calls)
    args = calls[0][1] if calls and isinstance(calls[0][1], dict) else {}
    args_match = all(re.search(p, str(args.get(k, ""))) for k, p in (expect.get("args") or {}).items())
    text = message.get("content") or ""
    reply_ok = not expect.get("reply") or bool(re.search(expect["reply"], text))
    right = chosen in accept
    return {"chosen": chosen, "calls": len(calls), "right_tool": right, "valid_args": valid,
            "invented": invented, "args_match": args_match, "reply_ok": reply_ok,
            "pass": right and valid and not invented and args_match and reply_ok}


def parse_strict(text: str):
    try:
        obj = json.loads(text.strip())
        return obj if isinstance(obj, dict) else None
    except ValueError:
        return None


def parse_lenient(text: str):
    s, e = text.find("{"), text.rfind("}")
    return parse_strict(text[s:e + 1]) if s != -1 and e > s else None


def score_json(case: dict, group: dict, text: str, finish: str | None) -> dict:
    strict, lenient = parse_strict(text), parse_lenient(text)
    caller_ok = (strict if group["parse"] == "strict" else lenient) is not None
    obj = strict or lenient or {}
    types = {"bool": bool, "str": str}
    shape = all(isinstance(obj.get(k), types[t]) for k, t in group["shape"].items())
    e, ok = case["expect"], True
    if "reframe" in e:
        ok &= obj.get("reframe") is e["reframe"]
        q = str(obj.get("question") or "")
        if e.get("question"):
            ok &= bool(re.search(e["question"], q))
        if e.get("question_not"):
            ok &= e["question_not"] not in q
    if "kind" in e:
        ok &= obj.get("kind") == e["kind"]
        items = obj.get("items") or []
        if "value" in e:
            ok &= bool(re.search(e["value"], str(obj.get("value", ""))))
        if "items" in e:
            ok &= len(items) == e["items"]
        if "items_min" in e:
            ok &= e["items_min"] <= len(items) <= e["items_max"]
        if "label_max" in e:
            ok &= all(len(str(i.get("label", ""))) <= e["label_max"] for i in items if isinstance(i, dict))
        for field in ("caption", "topic"):
            if f"{field}_max" in e:
                ok &= 0 < len(str(obj.get(field) or "")) <= e[f"{field}_max"]
    return {"strict": strict is not None, "lenient": lenient is not None, "caller_ok": caller_ok,
            "shape": shape, "expect_ok": bool(ok), "truncated": finish == "length",
            "pass": caller_ok and shape and bool(ok)}


# MARK: Runner

def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def request(model: str, suite: dict, messages: list, max_tokens: int, run_id: str, extra=None) -> dict:
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, **suite["sampling"],
            "metadata": {"tags": ["model-bench", f"suite:{suite['suite']}", f"run:{run_id}"]},
            **(extra or {})}
    began = time.perf_counter()
    data, headers = post(body)
    choice = data["choices"][0]
    return {"message": choice["message"], "finish": choice.get("finish_reason"),
            "usage": data.get("usage") or {}, "total_s": time.perf_counter() - began,
            "served_by": headers.get("x-litellm-model-id")}


def smoke(model: str, run_id: str) -> None:
    out = request(model, {"suite": "smoke", "sampling": {"temperature": 0, "seed": 42}},
                  [{"role": "user", "content": SMOKE}], 256, run_id)
    text = out["message"].get("content") or ""
    if not re.search(r"(?i)\bready\b", text):
        sys.exit(f"smoke failed: runtime or route broken, not scoring. reply={text[:200]!r} "
                 f"finish={out['finish']}")


def run_case(model: str, suite: dict, case: dict, rep: int, run_id: str) -> dict:
    name = suite["suite"]
    if name == "systems":
        content = case["prompt"]
        if "filler_tokens" in case:
            doc = filler(f"{name}:{case['id']}", case["filler_tokens"], case["needle"], case["needle_at"])
            content = f"{doc}\n\nQuestion: {case['prompt']}"
        nonce = f"[bench {run_id} rep {rep}]\n"
        body = {"model": model, "messages": [{"role": "user", "content": nonce + content}],
                "max_tokens": case["max_tokens"], **suite["sampling"],
                "metadata": {"tags": ["model-bench", f"suite:{name}", f"run:{run_id}"]}}
        r = stream(body)
        u = r["usage"]
        pt, ct = u.get("prompt_tokens"), u.get("completion_tokens")
        out = {
            "ttft_s": r["ttft_s"], "ttfc_s": r["ttfc_s"], "total_s": r["total_s"],
            "prompt_tokens": pt, "completion_tokens": ct, "prompt_chars": len(nonce + content),
            "prefill_tps": pt / r["ttft_s"] if pt and r["ttft_s"] else None,
            "decode_tps": (ct - 1) / r["gen_s"] if ct and r["gen_s"] and ct > 1 else None,
            "reasoning_chars": len(r["reasoning"]), "finish": r["finish"],
            "served_by": r["headers"].get("x-litellm-model-id"),
        }
        checks = [check(rule, r["content"], []) for rule in case.get("rubric") or []]
        out.update(score=sum(checks) / len(checks) if checks else None, reply=r["content"][:400])
        out["pass"] = all(checks)
        return out
    if name in ("tools", "voice"):
        tools = resolve(suite["tools"])
        msgs = [{"role": "system", "content": resolve(suite["system"])},
                {"role": "user", "content": case["prompt"]}]
        r = request(model, suite, msgs, suite["max_tokens"], run_id, {"tools": tools})
        msg = r["message"]
        if name == "tools":
            out = score_tools(case, tools, msg)
        else:
            text = msg.get("content") or ""
            checks = {rule["check"]: check(rule, text, msg.get("tool_calls") or [])
                      for rule in suite["rubric"]}
            out = {**checks, "words": word_count(text), "pass": all(checks.values())}
    elif name == "json":
        group = suite["groups"][case["group"]]
        msgs = [{"role": "system", "content": resolve(group["system"])},
                {"role": "user", "content": case["prompt"]}]
        extra = {"response_format": group["response_format"]} if "response_format" in group else None
        r = request(model, suite, msgs, group["max_tokens"], run_id, extra)
        out = score_json(case, group, r["message"].get("content") or "", r["finish"])
    elif name == "quality":
        r = request(model, suite, [{"role": "user", "content": case["prompt"]}],
                    case.get("max_tokens", suite["max_tokens"]), run_id)
        text = r["message"].get("content") or ""
        checks = [check(rule, text, r["message"].get("tool_calls") or []) for rule in case["rubric"]]
        out = {"score": sum(checks) / len(checks), "checks": checks, "pass": all(checks)}
    else:
        raise ValueError(f"unknown suite {name}")
    text = r["message"].get("content") or ""
    out.update(total_s=r["total_s"], finish=r["finish"], served_by=r["served_by"],
               completion_tokens=r["usage"].get("completion_tokens"),
               think_leak="<think>" in text, reply=text[:400])
    return out


def spread(values: list) -> dict | None:
    vals = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not vals:
        return None
    return {"median": statistics.median(vals), "min": min(vals), "max": max(vals), "n": len(vals)}


def summarize(suite: dict, cases: list) -> dict:
    reps = max(len(c["reps"]) for c in cases)
    per_rep = []
    for i in range(reps):
        row = [c["reps"][i] for c in cases if i < len(c["reps"]) and "error" not in c["reps"][i]]
        per_rep.append(sum(r.get("pass", False) for r in row) / len(cases))
    summary = {"pass_rate": spread(per_rep), "errors": sum("error" in r for c in cases for r in c["reps"])}
    flat = [r for c in cases for r in c["reps"] if "error" not in r]
    if suite["suite"] == "systems":
        for c in cases:
            ok = [r for r in c["reps"] if "error" not in r]
            summary[c["id"]] = {k: spread([r.get(k) for r in ok]) for k in
                                ("ttft_s", "decode_tps", "prefill_tps", "prompt_tokens", "total_s")}
            summary[c["id"]]["recall"] = spread([r.get("score") for r in ok])
    elif suite["suite"] == "tools":
        for k in ("right_tool", "valid_args", "args_match"):
            summary[k] = sum(bool(r.get(k)) for r in flat) / max(len(flat), 1)
        summary["invented_calls"] = sum(len(r.get("invented") or []) for r in flat)
        none = [r for c in cases if c["expect"]["tool"] is None for r in c["reps"] if "error" not in r]
        summary["no_tool_correct"] = sum(r["chosen"] is None for r in none) / max(len(none), 1)
    elif suite["suite"] == "voice":
        for k in ("no_tool", "nonempty", "max_words", "no_markdown"):
            summary[k] = sum(bool(r.get(k)) for r in flat) / max(len(flat), 1)
        summary["words"] = spread([r.get("words") for r in flat])
    elif suite["suite"] == "json":
        for k in ("caller_ok", "strict", "lenient", "shape", "expect_ok", "truncated"):
            summary[k] = sum(bool(r.get(k)) for r in flat) / max(len(flat), 1)
    elif suite["suite"] == "quality":
        summary["rubric"] = spread([statistics.mean(r["score"] for r in
                                    (c["reps"][i] for c in cases if "error" not in c["reps"][i]))
                                    for i in range(reps)])
    summary["latency_s"] = spread([r.get("total_s") for r in flat])
    summary["served_by"] = sorted({str(r.get("served_by")) for r in flat})
    return summary


def cmd_run(args) -> None:
    build = json.loads(Path(args.build).read_text())
    missing = [f for f in BUILD_FIELDS if not build.get(f)]
    if missing:
        sys.exit(f"build file lacks {missing}: no result without the exact build")
    RESULTS.mkdir(parents=True, exist_ok=True)
    for name in args.suite.split(","):
        suite = load_suite(name)
        reps = args.reps or suite["reps"]
        cases = suite["cases"]
        if args.phase == "cold":
            if suite["suite"] != "systems":
                sys.exit("--phase cold runs the systems suite only")
            cases, reps = [c for c in cases if c["id"] == "ping"], 1
        run_id = f"{dt.datetime.now():%Y%m%d-%H%M%S}-{args.model}-{suite['suite']}-{args.phase}"
        before = json.loads(Path(args.host_before).read_text()) if args.host_before else snapshot()
        if args.phase == "warm":
            smoke(args.model, run_id)
        results = [{"id": c["id"], "expect": c.get("expect"), "reps": []} for c in cases]
        for rep in range(reps):
            for case, res in zip(cases, results):
                try:
                    out = run_case(args.model, suite, case, rep, run_id)
                except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as exc:
                    out = {"error": f"{type(exc).__name__}: {exc}"[:500], "pass": False}
                res["reps"].append(out)
                flag = "ok " if out.get("pass") else ("ERR" if "error" in out else "-- ")
                print(f"{flag} {suite['suite']}/{case['id']} rep {rep + 1}/{reps}", file=sys.stderr)
        summary = summarize(suite, results)
        served = [s for s in summary["served_by"] if s != "None"]
        mismatch = [s for s in served if s != build["model_id"]]
        result = {
            "schema": "model-bench/v1", "run_id": run_id, "model": args.model, "phase": args.phase,
            "tag": args.tag, "started": before.get("at") or now_iso(), "finished": now_iso(),
            "build": build, "suite": {"name": suite["suite"], "version": suite["version"],
                                      "file": suite["_file"], "sha256": suite["_sha256"]},
            "sampling": suite["sampling"], "reps": reps, "host_before": before,
            "host_after": snapshot(), "served_by_mismatch": mismatch, "summary": summary,
            "cases": results,
        }
        path = RESULTS / f"{run_id}.json"
        path.write_text(json.dumps(result, indent=1, ensure_ascii=False))
        if mismatch:
            print(f"WARNING: served by {mismatch}, build says {build['model_id']}", file=sys.stderr)
        print(path)


# MARK: Report

def fmt(s: dict | None, digits: int = 1) -> str:
    if not s:
        return "–"
    m = f"{s['median']:.{digits}f}"
    return m if s["n"] == 1 or s["min"] == s["max"] else f"{m} [{s['min']:.{digits}f}–{s['max']:.{digits}f}]"


def pct(v) -> str:
    return "–" if v is None else f"{v * 100:.0f}%"


def cmd_report(args) -> None:
    runs: dict = {}
    for p in args.results:
        r = json.loads(Path(p).read_text())
        label = r["build"].get("label") or r["model"]
        runs.setdefault(label, {"build": r["build"]})[f"{r['suite']['name']}:{r['phase']}"] = r
    lines = ["# Model benchmark", "", "Medians over repetitions, [min–max] where they differ.", "",
             "## Builds", "", "| model | served by | runtime | weights | quant | ctx | hash |",
             "|---|---|---|---|---|---|---|"]
    for label, rs in runs.items():
        b = rs["build"]
        lines.append(f"| {label} | {b['model_id']} | {b['runtime']} {b['runtime_version']} | {b['weights']} "
                     f"| {b['quantization']} | {b['context']} | `{str(b['weights_hash'])[:12]}` |")
    lines += ["", "## Systems", "",
              "| model | cold load s | ping TTFT s | decode tok/s | prefill 2k tok/s | prefill 16k tok/s | recall 2k / 16k |",
              "|---|---|---|---|---|---|---|"]
    for label, rs in runs.items():
        w = (rs.get("systems:warm") or {}).get("summary") or {}
        c = (rs.get("systems:cold") or {}).get("summary") or {}
        cold = c.get("ping", {}).get("ttft_s")
        warm = w.get("ping", {}).get("ttft_s")
        load = f"{cold['median'] - warm['median']:.1f}" if cold and warm else "–"
        g = lambda case, k: w.get(case, {}).get(k)
        lines.append(f"| {label} | {load} | {fmt(g('ping', 'ttft_s'), 2)} | {fmt(g('decode', 'decode_tps'))} "
                     f"| {fmt(g('prefill-2k', 'prefill_tps'), 0)} | {fmt(g('prefill-16k', 'prefill_tps'), 0)} "
                     f"| {fmt(g('prefill-2k', 'recall'), 2)} / {fmt(g('prefill-16k', 'recall'), 2)} |")
    lines += ["", "## Behaviour", "",
              "| model | tools pass | right tool | valid args | invented | no-tool correct | voice pass | ≤40 words | no markdown | JSON caller-ok | strict | shape+expect | quality rubric |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for label, rs in runs.items():
        t = (rs.get("tools:warm") or {}).get("summary") or {}
        v = (rs.get("voice:warm") or {}).get("summary") or {}
        j = (rs.get("json:warm") or {}).get("summary") or {}
        q = (rs.get("quality:warm") or {}).get("summary") or {}
        pr = lambda s: fmt({k: (x * 100 if k != "n" else x) for k, x in s["pass_rate"].items()}, 0) + "%" if s.get("pass_rate") else "–"
        lines.append(f"| {label} | {pr(t)} | {pct(t.get('right_tool'))} | {pct(t.get('valid_args'))} "
                     f"| {t.get('invented_calls', '–')} | {pct(t.get('no_tool_correct'))} | {pr(v)} "
                     f"| {pct(v.get('max_words'))} | {pct(v.get('no_markdown'))} | {pct(j.get('caller_ok'))} "
                     f"| {pct(j.get('strict'))} | {pct(j.get('expect_ok'))} | {fmt(q.get('rubric'), 2)} |")
    warn = [f"- {label}: {k} served by {r['served_by_mismatch']}" for label, rs in runs.items()
            for k, r in rs.items() if k != "build" and r.get("served_by_mismatch")]
    host = [f"- {label} {k}: {', '.join(r['host_before'].get('warnings', []))}" for label, rs in runs.items()
            for k, r in rs.items() if k != "build" and r["host_before"].get("warnings")]
    if warn or host:
        lines += ["", "## Warnings", "", *warn, *host]
    text = "\n".join(lines) + "\n"
    if args.out:
        Path(args.out).write_text(text)
    print(text)


# MARK: Selftest

def cmd_attach(args) -> None:
    path = Path(args.result)
    result = json.loads(path.read_text())
    result["host_after"] = json.loads(Path(args.host_after).read_text())
    path.write_text(json.dumps(result, indent=1, ensure_ascii=False))


def cmd_selftest(_) -> None:
    import yaml
    assert word_count("It's 8,849 m tall — about 29,032 ft.") == 7
    assert MARKDOWN.search("Tips:\n- sleep") and not MARKDOWN.search("Sleep at 10 pm, keep it dark.")
    assert parse_lenient('Sure: {"reframe": false, "question": ""} done') and not parse_strict('x {"a":1}')
    tools = resolve({"fixture": "prompts.v1.json", "key": "glass_tools"})
    msg = {"tool_calls": [{"function": {"name": "resume_session", "arguments": '{"session_id": 3}'}}]}
    s = score_tools({"expect": {"tool": "resume_session", "args": {"session_id": "^3$"}}}, tools, msg)
    assert s["pass"], s
    msg = {"tool_calls": [{"function": {"name": "resume_session", "arguments": '{"session_id": "3"}'}}]}
    assert not score_tools({"expect": {"tool": "resume_session"}}, tools, msg)["valid_args"]
    msg = {"tool_calls": [{"function": {"name": "turn_on_lights", "arguments": "{}"}}]}
    assert score_tools({"expect": {"tool": None}}, tools, msg)["invented"] == ["turn_on_lights"]
    assert python_tests("```python\ndef f(s):\n    return s == s[::-1]\n```", "f", [["aba", True]])
    assert len(filler("x", 2000, "NEEDLE", 0.5).split()) > 1400
    for path in sorted(SUITES.glob("*.yaml")):
        suite = yaml.safe_load(path.read_text())
        assert path.stem == f"{suite['suite']}.v{suite['version']}", path
        assert len({c["id"] for c in suite["cases"]}) == len(suite["cases"]), path
    print("selftest ok")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("model")
    r.add_argument("--build", required=True)
    r.add_argument("--suite", default="systems,tools,voice,json,quality")
    r.add_argument("--reps", type=int)
    r.add_argument("--phase", choices=("warm", "cold"), default="warm")
    r.add_argument("--tag")
    r.add_argument("--host-before")
    at = sub.add_parser("attach")
    at.add_argument("result")
    at.add_argument("--host-after", required=True)
    rp = sub.add_parser("report")
    rp.add_argument("results", nargs="+")
    rp.add_argument("--out")
    sub.add_parser("snapshot")
    sub.add_parser("selftest")
    args = ap.parse_args()
    if args.cmd == "run":
        cmd_run(args)
    elif args.cmd == "report":
        cmd_report(args)
    elif args.cmd == "attach":
        cmd_attach(args)
    elif args.cmd == "snapshot":
        print(json.dumps(snapshot(), indent=1))
    else:
        cmd_selftest(args)


if __name__ == "__main__":
    main()
