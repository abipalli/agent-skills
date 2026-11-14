#!/usr/bin/env -S python3 -I
"""Pipeline run ledger on LiteLLM workflow runs (/v1/workflows/runs), plus per-repo gates and auto-approve policy.

Environment: FP_LITELLM_URL (default http://127.0.0.1:4000), FP_LITELLM_KEY or the key in
~/.config/feature-pipeline/key, FP_WORKFLOW_TYPE (default feature-delivery).

Repo config: .feature-pipeline.json at the root of the repo's main checkout.

  fp.py new REPO_DIR TITLE [REQUEST] create a job for the repo containing REPO_DIR, print its run_id
  fp.py list [STATUS[,STATUS]]       list jobs (pending,running,paused,completed,failed)
  fp.py show RUN_ID                  run, metadata, events, messages
  fp.py step RUN_ID STAGE EVENT [JSON]   append event, merge {stage, **JSON} into metadata
  fp.py note RUN_ID ROLE TEXT        append a message (review comments, questions, answers)
  fp.py gates RUN_ID                 run the repo's gate commands in the job worktree, record results
  fp.py approve RUN_ID               apply the repo policy to the job worktree, record approve.decided
  fp.py done RUN_ID [JSON]           mark completed with output
  fp.py selftest [REPO_DIR...]       policy self-check + validate those repos' configs (no network)
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("FP_LITELLM_URL", "http://127.0.0.1:4000")
TYPE = os.environ.get("FP_WORKFLOW_TYPE", "feature-delivery")
KEY_FILE = os.path.expanduser("~/.config/feature-pipeline/key")
CONFIG = ".feature-pipeline.json"
REQUIRED = ("base", "lanes_dir", "branch_prefix", "gates")


def repo_root(path):
    """Main checkout of the repo containing path, even when path is inside a linked worktree."""
    try:
        common = git(path, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    except subprocess.CalledProcessError:
        sys.exit(f"{path} is not inside a git repo")
    return os.path.dirname(common)


def load_config(root):
    path = os.path.join(root, CONFIG)
    if not os.path.exists(path):
        sys.exit(f"no {CONFIG} at {root}")
    with open(path) as f:
        cfg = json.load(f)
    missing = [k for k in REQUIRED if k not in cfg]
    if missing:
        sys.exit(f"{path} missing: {', '.join(missing)}")
    return cfg


def api(method, path, body=None):
    key = os.environ.get("FP_LITELLM_KEY") or open(KEY_FILE).read().strip()
    req = urllib.request.Request(
        BASE + path, method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path}: {e.code} {e.read().decode()[:500]}")


def run_meta(run_id):
    meta = api("GET", f"/v1/workflows/runs/{run_id}").get("metadata") or {}
    return json.loads(meta) if isinstance(meta, str) else meta


def job(run_id):
    meta = run_meta(run_id)
    if "repo" not in meta or "worktree" not in meta:
        sys.exit(f"run {run_id} has no repo/worktree in metadata yet")
    return meta, load_config(meta["repo"])


def step(run_id, stage, event, data=None):
    data = data or {}
    api("POST", f"/v1/workflows/runs/{run_id}/events", {"event_type": event, "step_name": stage, "data": data})
    api("PATCH", f"/v1/workflows/runs/{run_id}", {"metadata": {**run_meta(run_id), **data, "stage": stage}})


def decide(numstat, removed, review, gates, cfg, dirty=False, scope=None):
    """numstat: [(added, deleted, path)] with None for binary; removed: '-' diff lines;
    scope: the scope stage record (risk, sensitive_areas, verdict, spikes)."""
    pol = cfg.get("policy", {})
    max_lines, max_files, max_rounds = pol.get("max_lines", 300), pol.get("max_files", 10), pol.get("max_rounds", 3)
    why = []
    scope = scope or {}
    if scope.get("risk") != "low":
        why.append(f"scope risk is {scope.get('risk', 'not recorded')}, auto needs low")
    if scope.get("sensitive_areas"):
        why.append("sensitive areas: " + ", ".join(scope["sensitive_areas"]))
    if scope.get("verdict") == "rescoped":
        why.append("rescoped: a human confirms the smaller slice")
    if any(s.get("class") == "side_effects" for s in scope.get("spikes", [])):
        why.append("a spike had side effects")
    paths = [p for _, _, p in numstat]
    if not paths:
        why.append("empty diff")
    if dirty:
        why.append("uncommitted changes in worktree")
    if review.get("critical", 1) or review.get("high", 1):
        why.append(f"review: {review.get('critical', '?')} critical / {review.get('high', '?')} high")
    if review.get("open_medium", 1):
        why.append(f"review: {review.get('open_medium', '?')} medium neither fixed nor deferred with a reason")
    if review.get("rounds", max_rounds + 1) > max_rounds:
        why.append(f"review took {review.get('rounds', '?')} rounds (cap {max_rounds})")
    bad = [g for g in cfg["gates"] if gates.get(g) != "pass"]
    if bad:
        why.append("gates not passing: " + ", ".join(bad))
    for label, pats in pol.get("human_paths", {}).items():
        if hit := sorted({p for p in paths if any(s in p for s in pats)}):
            why.append(f"{label}: " + ", ".join(hit))
    for label, rx in pol.get("human_removed_lines", {}).items():
        if hit := sorted({m.group(0) for line in removed for m in [re.search(rx, line)] if m}):
            why.append(f"{label}: " + ", ".join(hit))
    if CONFIG in paths:
        why.append(f"changes the pipeline's own config ({CONFIG})")
    if any(a is None for a, _, _ in numstat):
        why.append("binary files in diff")
    size = sum((a or 0) + (d or 0) for a, d, _ in numstat)
    if size > max_lines or len(paths) > max_files:
        why.append(f"diff {size} lines / {len(paths)} files (cap {max_lines} / {max_files})")
    return {
        "decision": "human" if why else "auto",
        "reasons": why or ["all auto-approve rules passed"],
        "stats": {"lines": size, "files": len(paths)},
    }


def git(wt, *args):
    return subprocess.run(["git", "-C", wt, *args], check=True, capture_output=True, text=True).stdout


def run_gates(run_id):
    meta, cfg = job(run_id)
    results = {}
    for name, cmd in cfg["gates"].items():
        p = subprocess.run(cmd, shell=True, cwd=meta["worktree"], capture_output=True, text=True)
        results[name] = "pass" if p.returncode == 0 else "fail"
        print(f"== {name}: {results[name]} ({cmd})")
        if p.returncode:
            print((p.stdout + p.stderr)[-3000:])
    step(run_id, meta.get("stage", "build"), "gates.ran", {"gates": results})
    return all(v == "pass" for v in results.values())


def approve(run_id):
    meta, cfg = job(run_id)
    wt, base = meta["worktree"], cfg["base"]
    numstat = []
    for line in git(wt, "diff", "--numstat", f"{base}...HEAD").splitlines():
        a, d, p = line.split("\t", 2)
        numstat.append((None if a == "-" else int(a), None if d == "-" else int(d), p))
    removed = [l for l in git(wt, "diff", "-U0", f"{base}...HEAD").splitlines()
               if l.startswith("-") and not l.startswith("---")]
    result = decide(numstat, removed, meta.get("review", {}), meta.get("gates", {}), cfg,
                    dirty=bool(git(wt, "status", "--porcelain").strip()), scope=meta.get("scope"))
    step(run_id, "approve", "approve.decided", {"approval": result})
    return result


def selftest(repos):
    cfg = {
        "gates": {"check": "true", "test": "true"},
        "policy": {
            "human_paths": {"swift": ["apps/ios/"], "trust": ["auth/", "Cargo.toml"]},
            "human_removed_lines": {"wire": r'serde\(|"(event_name|api_version)"'},
        },
    }
    ok = {"rounds": 1, "critical": 0, "high": 0, "open_medium": 0}
    gates = {"check": "pass", "test": "pass"}
    small = [(10, 2, "src/ics.rs")]
    low = {"risk": "low", "verdict": "proceed", "sensitive_areas": [], "spikes": []}
    d = lambda *a, **k: decide(*a, **{"scope": low, **k})["decision"]
    assert d(small, [], ok, gates, cfg) == "auto"
    assert d([], [], ok, gates, cfg) == "human"
    assert d(small, [], ok, gates, cfg, dirty=True) == "human"
    assert d(small, [], {**ok, "high": 1}, gates, cfg) == "human"
    assert d(small, [], {**ok, "open_medium": 2}, gates, cfg) == "human"
    assert d(small, [], {**ok, "rounds": 4}, gates, cfg) == "human"
    assert d(small, [], {}, gates, cfg) == "human"
    assert d(small, [], ok, {**gates, "test": "fail"}, cfg) == "human"
    assert d(small, [], ok, {"check": "pass"}, cfg) == "human"
    for p in ("apps/ios/App.swift", "crates/auth/src/lib.rs", "crates/ai/Cargo.toml"):
        assert d([(1, 1, p)], [], ok, gates, cfg) == "human", p
    assert d(small, ['-    #[serde(rename = "x")]'], ok, gates, cfg) == "human"
    assert d(small, ['-    const K: &str = "event_name";'], ok, gates, cfg) == "human"
    assert d(small, ["-    let event_names = 1;"], ok, gates, cfg) == "auto"
    assert d(small, [], ok, gates, cfg, scope={}) == "human"
    assert d(small, [], ok, gates, cfg, scope={**low, "risk": "medium"}) == "human"
    assert d(small, [], ok, gates, cfg, scope={**low, "sensitive_areas": ["auth"]}) == "human"
    assert d(small, [], ok, gates, cfg, scope={**low, "verdict": "rescoped"}) == "human"
    assert d(small, [], ok, gates, cfg, scope={**low, "spikes": [{"class": "side_effects"}]}) == "human"
    assert d([(None, None, "docs/x.png")], [], ok, gates, cfg) == "human"
    assert d([(300, 1, "src/ics.rs")], [], ok, gates, cfg) == "human"
    assert d([(1, 0, f"docs/f{i}.md") for i in range(11)], [], ok, gates, cfg) == "human"
    assert d([(400, 0, "src/a.rs")], [], ok, gates, {**cfg, "policy": {"max_lines": 500}}) == "auto"
    assert d([(1, 1, CONFIG)], [], ok, gates, cfg) == "human"
    for repo in repos:
        c = load_config(repo_root(repo))
        for rx in c.get("policy", {}).get("human_removed_lines", {}).values():
            re.compile(rx)
    print(f"selftest ok ({len(repos)} repo config(s) valid)")


def main(argv):
    cmd, args = (argv[0], argv[1:]) if argv else ("help", [])
    if cmd == "new":
        repo, title = repo_root(args[0]), args[1]
        request = args[2] if len(args) > 2 else title
        load_config(repo)
        run = api("POST", "/v1/workflows/runs", {"workflow_type": TYPE, "input": {"title": title, "request": request},
                                                  "metadata": {"stage": "intake", "title": title, "repo": repo}})
        api("POST", f"/v1/workflows/runs/{run['run_id']}/events",
            {"event_type": "step.started", "step_name": "intake", "data": {}})
        print(run["run_id"])
    elif cmd == "list":
        q = {"workflow_type": TYPE, "limit": 100, **({"status": args[0]} if args else {})}
        for r in api("GET", "/v1/workflows/runs?" + urllib.parse.urlencode(q))["runs"]:
            m = r.get("metadata") or {}
            m = json.loads(m) if isinstance(m, str) else m
            print(f"{r['run_id']}\t{r['status']}\t{os.path.basename(m.get('repo', '?'))}\t{m.get('stage', '?')}\t{m.get('title', '')}")
    elif cmd == "show":
        rid = args[0]
        print(json.dumps({"run": api("GET", f"/v1/workflows/runs/{rid}"),
                          "events": api("GET", f"/v1/workflows/runs/{rid}/events"),
                          "messages": api("GET", f"/v1/workflows/runs/{rid}/messages")}, indent=2))
    elif cmd == "step":
        step(args[0], args[1], args[2], json.loads(args[3]) if len(args) > 3 else None)
    elif cmd == "note":
        api("POST", f"/v1/workflows/runs/{args[0]}/messages", {"role": args[1], "content": args[2]})
    elif cmd == "gates":
        sys.exit(0 if run_gates(args[0]) else 1)
    elif cmd == "approve":
        result = approve(args[0])
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["decision"] == "auto" else 3)
    elif cmd == "done":
        api("PATCH", f"/v1/workflows/runs/{args[0]}",
            {"status": "completed", "output": json.loads(args[1]) if len(args) > 1 else {}})
    elif cmd == "selftest":
        selftest(args)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
