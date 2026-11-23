#!/usr/bin/env -S python3 -I
"""Pipeline run ledger on LiteLLM workflow runs (/v1/workflows/runs), plus per-repo gates and auto-approve policy.

Environment: FP_LITELLM_URL (default http://127.0.0.1:4000), FP_LITELLM_KEY or the key in
~/.config/feature-pipeline/key, FP_WORKFLOW_TYPE (default feature-delivery).
`guard` also reads FP_GUARD_KEY_FILE (a key that can see every run, e.g. a proxy_admin_viewer
key; runs it created never count) and FP_GUARD_TRUSTED (comma-separated created_by hashes; when
set, only runs those keys created count).

Repo config: .feature-pipeline.json at the root of the repo's main checkout; optional (see load_config).

  fp.py new REPO_DIR TITLE [REQUEST] [--from RUN_ID] [--stop-after STAGE] [--route STATE]
                                     create a job for the repo containing REPO_DIR, print its run_id;
                                     --from links the task or investigation run it came from;
                                     --stop-after STAGE refuses `step.started` for later stages
                                     (scope also allows spike)
                                     --route STATE opens a direct, backlogged or dropped task;
                                     --escalate (with --from REF) marks the run as escalated from direct work
  fp.py route RUN_ID STATE [REASON]  change the run's route (pipelined|direct|backlogged|dropped), log route.changed
  fp.py list [STATUS[,STATUS]]       list jobs (pending,running,paused,completed,failed)
  fp.py show RUN_ID                  run, metadata, events, messages
  fp.py config REPO_DIR              the repo's effective config (defaults when it has no file)
  fp.py step RUN_ID STAGE EVENT [JSON]   append event, merge {stage, **JSON} into metadata
  fp.py note RUN_ID ROLE TEXT        append a message (review comments, questions, answers)
  fp.py gates RUN_ID                 run the repo's gate commands in the job worktree, record results
  fp.py approve RUN_ID               apply the repo policy to the job worktree, record approve.decided
                                     (feature-delivery runs only: no other kind can merge)
  fp.py done RUN_ID [JSON]           mark completed with output
  fp.py guard                        Claude Code PreToolUse hook: blocks `gh pr merge` unless the PR's
                                     feature-delivery run was auto-approved with auto_merge on, or a
                                     person approved it (metadata.operator_decision)
  fp.py selftest [REPO_DIR...]       policy self-check + validate those repos' configs (no network)
"""
import contextlib
import datetime
import fcntl
import getpass
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = os.environ.get("FP_LITELLM_URL", "http://127.0.0.1:4000")
TYPE = os.environ.get("FP_WORKFLOW_TYPE", "feature-delivery")
KEY_FILE = os.path.expanduser("~/.config/feature-pipeline/key")
CONFIG = ".feature-pipeline.json"
MERGEABLE = "feature-delivery"
# gh in command position (start, after ; & | ( or a newline, past VAR=x prefixes), not inside text.
MERGE = re.compile(r"(?:^|[;&|(\n])\s*(?:\w+=\S*\s+)*(?:\S*/)?gh\s+pr\s+merge\b(?:\s+([^\s'\";&|)]+))?")
REQUIRED = ("base", "lanes_dir", "branch_prefix", "gates")
# File store: one JSON per run, shaped like LiteLLM's {run, events, messages} so a UI or a
# later move to LiteLLM reads the same records.
STORE_DIR = os.path.expanduser(os.environ.get("FP_STORE_DIR", "~/.local/state/feature-pipeline/runs"))
STATUS_BY_EVENT = {"step.started": "running", "hook.waiting": "paused",
                   "hook.received": "running", "step.failed": "failed"}


def use_file_store():
    """FP_STORE=file, or FP_STORE unset and no LiteLLM key configured (FP_STORE=litellm forces LiteLLM)."""
    store = os.environ.get("FP_STORE")
    if store:
        return store == "file"
    return not (os.environ.get("FP_LITELLM_KEY") or os.path.exists(KEY_FILE))


def file_api(method, path, body=None):
    """Serve the LiteLLM routes api() uses from STORE_DIR, returning the same JSON shapes.

    POST /v1/workflows/runs, GET /v1/workflows/runs?workflow_type&status&limit,
    GET|PATCH /v1/workflows/runs/ID, GET|POST /v1/workflows/runs/ID/events|messages.
    Unlike LiteLLM, PATCH merges metadata instead of replacing it, so step() can send a delta.
    Each run file is updated under an exclusive flock and replaced atomically, so parallel
    builders can step the same run. Runs carry created_by "file:<user>" (never None), so
    guard's own-key check can't skip them.
    """
    url = urllib.parse.urlsplit(path)
    parts = url.path.strip("/").split("/")[3:]  # after v1/workflows/runs
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    os.makedirs(STORE_DIR, exist_ok=True)
    if not parts:
        if method == "POST":
            run = {"run_id": uuid.uuid4().hex, "workflow_type": body.get("workflow_type"), "status": "pending",
                   "input": body.get("input") or {}, "output": None, "metadata": body.get("metadata") or {},
                   "created_by": "file:" + getpass.getuser(), "created_at": now, "updated_at": now}
            with _run_file(run["run_id"], create=True) as rec:
                rec.update(run=run, events=[], messages=[])
            return run
        q = urllib.parse.parse_qs(url.query)
        kind, statuses = q.get("workflow_type", [None])[0], set(",".join(q.get("status", [])).split(",")) - {""}
        runs = []
        for name in os.listdir(STORE_DIR):
            if name.endswith(".json"):
                with open(os.path.join(STORE_DIR, name)) as f:
                    run = json.load(f)["run"]
                if (not kind or run["workflow_type"] == kind) and (not statuses or run["status"] in statuses):
                    runs.append(run)
        runs.sort(key=lambda r: r["created_at"], reverse=True)
        return {"runs": runs[: int(q.get("limit", ["100"])[0])]}
    run_id, sub = parts[0], (parts[1] if len(parts) > 1 else None)
    with _run_file(run_id) as rec:
        run = rec["run"]
        if sub is None and method == "GET":
            return run
        if sub is None and method == "PATCH":
            run.update({k: body[k] for k in ("status", "output") if k in body}, updated_at=now)
            run["metadata"].update(body.get("metadata") or {})
            return run
        if method == "GET":
            return {sub: rec[sub]}
        if sub == "events":
            event = {"event_id": uuid.uuid4().hex, "created_at": now, **body}
            rec["events"].append(event)
            run.update(status=STATUS_BY_EVENT.get(body.get("event_type"), run["status"]), updated_at=now)
            return event
        message = {"message_id": uuid.uuid4().hex, "created_at": now, **body}
        rec["messages"].append(message)
        return message


@contextlib.contextmanager
def _run_file(run_id, create=False):
    """Yield a run's record under an exclusive lock; write it back atomically on success."""
    if not re.fullmatch(r"[0-9a-f]{32}", run_id):
        sys.exit(f"bad run id {run_id!r}")
    path = os.path.join(STORE_DIR, run_id + ".json")
    if not create and not os.path.exists(path):
        sys.exit(f"no run {run_id} in {STORE_DIR}")
    with open(path + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rec = {}
        if not create:
            with open(path) as f:
                rec = json.load(f)
        yield rec
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(rec, f, indent=2)
        os.replace(tmp, path)


def repo_root(path):
    """Main checkout of the repo containing path, even when path is inside a linked worktree."""
    try:
        common = git(path, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    except subprocess.CalledProcessError:
        sys.exit(f"{path} is not inside a git repo")
    return os.path.dirname(common)


def load_config(root):
    """The repo's config, or defaults when it has none. A defaulted repo never auto-approves."""
    path = os.path.join(root, CONFIG)
    if not os.path.exists(path):
        try:
            base = git(root, "rev-parse", "--abbrev-ref", "origin/HEAD").strip()
        except subprocess.CalledProcessError:
            sys.exit(f"{root}: origin/HEAD is unset; run `git remote set-head origin -a` or add {CONFIG}")
        return {"base": base, "lanes_dir": f"../{os.path.basename(root)}-lanes",
                "branch_prefix": "fp/", "gates": {}, "defaulted": True}
    with open(path) as f:
        cfg = json.load(f)
    missing = [k for k in REQUIRED if k not in cfg]
    if missing:
        sys.exit(f"{path} missing: {', '.join(missing)}")
    return cfg


def api(method, path, body=None):
    if use_file_store():
        return file_api(method, path, body)
    key =os.environ.get("FP_LITELLM_KEY") or open(KEY_FILE).read().strip()
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


STAGES = ["intake", "scope", "spike", "build", "review", "approve"]
# Task routing (work-evaluation): a run is pipelined, or was moved off the pipeline. Allowed moves by current route.
ROUTES = {"pipelined": {"direct", "backlogged", "dropped"},          # direct = demote
          "direct": {"pipelined"},                                   # escalate
          "backlogged": {"pipelined", "direct", "dropped"},          # re-triaged
          "dropped": set()}


def route(run_id, to, reason="", frm=None, **extra):
    frm = frm or run_meta(run_id).get("route", "pipelined")
    if to not in ROUTES.get(frm, set()):
        sys.exit(f"run {run_id}: cannot route {frm} -> {to}")
    api("POST", f"/v1/workflows/runs/{run_id}/events",
        {"event_type": "route.changed", "step_name": run_meta(run_id).get("stage", "intake"),
         "data": {"from": frm, "to": to, "reason": reason, **extra}})
    api("PATCH", f"/v1/workflows/runs/{run_id}",
        {"metadata": {"route": to} if use_file_store() else {**run_meta(run_id), "route": to}})


def step(run_id, stage, event, data=None):
    data = data or {}
    stop = (api("GET", f"/v1/workflows/runs/{run_id}").get("metadata") or {}).get("stop_after")
    if event == "step.started" and stop in STAGES and stage in STAGES and \
            STAGES.index(stage) > max(STAGES.index(stop), STAGES.index("spike") * (stop == "scope")):
        sys.exit(f"run {run_id} stops after {stop}: stage {stage} is not allowed; wait for a human")
    api("POST", f"/v1/workflows/runs/{run_id}/events", {"event_type": event, "step_name": stage, "data": data})
    patch = {**data, "stage": stage}
    # The file store merges metadata under its lock; LiteLLM replaces it, so send the whole object.
    api("PATCH", f"/v1/workflows/runs/{run_id}",
        {"metadata": patch if use_file_store() else {**run_meta(run_id), **patch}})


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
    if cfg.get("defaulted"):
        why.append(f"no {CONFIG}: a person reviews repos without a policy")
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
    kind = api("GET", f"/v1/workflows/runs/{run_id}").get("workflow_type")
    if kind != MERGEABLE:
        sys.exit(f"run {run_id} is a {kind} run; only {MERGEABLE} runs can be approved")
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


def repo_auto_merge(repo):
    """policy.auto_merge, or False when the config is missing or unreadable (the guard fails closed)."""
    try:
        return bool(repo and load_config(repo).get("policy", {}).get("auto_merge", False))
    except (SystemExit, ValueError):
        return False


def merge_allowed(meta, auto_merge):
    """None when the run allows its PR to merge, else the reason it doesn't."""
    decided = (meta.get("operator_decision") or {}).get("decision")
    if decided == "approve":
        return None
    if decided:
        return f"the person's decision was {decided!r}"
    if (meta.get("approval") or {}).get("decision") == "auto":
        return None if auto_merge() else "approved as auto, but the repo's policy.auto_merge is off"
    return "no approval recorded: run `fp approve`, and a person must approve when it says human"


def guard(hook):
    """PreToolUse hook. Exit 2 blocks the call and shows stderr to the agent."""
    cmd = (hook.get("tool_input") or {}).get("command") or ""
    m = MERGE.search(cmd) if hook.get("tool_name") == "Bash" else None
    if not m:
        return
    pr = (m[1] or "").rstrip("/")
    pr = "" if pr.startswith("-") else pr
    cwd = os.path.realpath(hook.get("cwd") or ".")
    own = None
    if os.environ.get("FP_GUARD_KEY_FILE"):
        with open(os.environ["FP_GUARD_KEY_FILE"]) as f:
            os.environ["FP_LITELLM_KEY"] = f.read().strip()
        own = hashlib.sha256(os.environ["FP_LITELLM_KEY"].encode()).hexdigest()
    trusted = set(filter(None, os.environ.get("FP_GUARD_TRUSTED", "").split(",")))
    if trusted and use_file_store():
        sys.exit(print("merge blocked: FP_GUARD_TRUSTED is set, but the file store can't prove who wrote a run",
                       file=sys.stderr) or 2)
    try:
        runs = api("GET", "/v1/workflows/runs?" + urllib.parse.urlencode({"workflow_type": MERGEABLE, "limit": 250}))["runs"]
    except SystemExit as e:
        sys.exit(print(f"merge blocked: can't read the run ledger ({e})", file=sys.stderr) or 2)
    for r in runs:
        if r.get("created_by") == own or (trusted and r.get("created_by") not in trusted):
            continue
        meta = r.get("metadata") or {}
        meta = json.loads(meta) if isinstance(meta, str) else meta
        url = str(meta.get("pr") or "").rstrip("/")
        wt = meta.get("worktree")
        if (pr and url and (url == pr or url.endswith(f"/pull/{pr}"))) or (not pr and wt and os.path.realpath(wt) == cwd):
            why = merge_allowed(meta, lambda: repo_auto_merge(meta.get("repo")))
            if why is None:
                return
            sys.exit(print(f"merge blocked for run {r['run_id']}: {why}", file=sys.stderr) or 2)
    sys.exit(print("merge blocked: no feature-delivery run has this PR, so nothing approved it", file=sys.stderr) or 2)


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
    with tempfile.TemporaryDirectory() as t:
        git(t, "init", "-q", "-b", "trunk"); git(t, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
        git(t, "update-ref", "refs/remotes/origin/trunk", "HEAD")
        git(t, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        dflt = load_config(t)
    assert d(small, [], ok, {}, dflt) == "human" and dflt["base"] == "origin/trunk", dflt
    assert repo_auto_merge(None) is False
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
    assert merge_allowed({"approval": {"decision": "auto"}}, lambda: True) is None
    assert merge_allowed({"approval": {"decision": "auto"}}, lambda: False)
    assert merge_allowed({"approval": {"decision": "human"}}, lambda: True)
    assert merge_allowed({"approval": {"decision": "human"}, "operator_decision": {"decision": "approve"}}, lambda: False) is None
    assert merge_allowed({"approval": {"decision": "auto"}, "operator_decision": {"decision": "request_changes"}}, lambda: True)
    assert merge_allowed({}, lambda: True)
    assert merge_allowed({"operator_decision": {"decision": "approve"}}, lambda: 1 / 0) is None
    assert MERGE.search("cd x && gh pr merge https://github.com/o/r/pull/7 --squash")[1] == "https://github.com/o/r/pull/7"
    assert MERGE.search("gh pr merge --squash")[1] == "--squash" and not MERGE.search("gh pr view 7")
    assert MERGE.search("GH_TOKEN=x /usr/bin/gh pr merge 7")[1] == "7"
    assert MERGE.search("echo hi\ngh pr merge 7;")[1] == "7"
    assert not MERGE.search("printf '{\"command\":\"gh pr merge 7\"}'") and not MERGE.search("echo 'run gh pr merge'")
    checked = 0
    for repo in repos:
        c = load_config(repo_root(repo))
        if c.get("defaulted"):
            print(f"{repo}: no {CONFIG}, defaults apply (base {c['base']}, human approval)")
            continue
        checked += 1
        for rx in c.get("policy", {}).get("human_removed_lines", {}).values():
            re.compile(rx)
    selftest_file_store()
    print(f"selftest ok ({checked} repo config(s) valid)")


def selftest_file_store():
    """Round-trip a run through the file store in a temp dir: create, pause, resume, finish, list."""
    global STORE_DIR
    saved = STORE_DIR
    with tempfile.TemporaryDirectory() as STORE_DIR:
        f = file_api
        rid = f("POST", "/v1/workflows/runs", {"workflow_type": "t", "metadata": {"stage": "intake"}})["run_id"]
        assert f("GET", f"/v1/workflows/runs/{rid}")["created_by"].startswith("file:")
        for event, status in (("step.started", "running"), ("hook.waiting", "paused"), ("note", "paused"),
                              ("hook.received", "running"), ("step.failed", "failed")):
            f("POST", f"/v1/workflows/runs/{rid}/events", {"event_type": event, "step_name": "scope"})
            assert f("GET", f"/v1/workflows/runs/{rid}")["status"] == status, event
        f("PATCH", f"/v1/workflows/runs/{rid}", {"metadata": {"stage": "scope", "x": 1}})
        f("PATCH", f"/v1/workflows/runs/{rid}", {"metadata": {"y": 2}})
        assert f("GET", f"/v1/workflows/runs/{rid}")["metadata"] == {"stage": "scope", "x": 1, "y": 2}
        f("POST", f"/v1/workflows/runs/{rid}/messages", {"role": "scoper", "content": "q?"})
        f("PATCH", f"/v1/workflows/runs/{rid}", {"status": "completed", "output": {"ok": True}})
        run = f("GET", f"/v1/workflows/runs/{rid}")
        assert (run["status"], run["output"], run["metadata"]["x"]) == ("completed", {"ok": True}, 1)
        assert len(f("GET", f"/v1/workflows/runs/{rid}/events")["events"]) == 5
        assert f("GET", f"/v1/workflows/runs/{rid}/messages")["messages"][0]["content"] == "q?"
        f("POST", "/v1/workflows/runs", {"workflow_type": "other"})
        assert [r["run_id"] for r in f("GET", "/v1/workflows/runs?workflow_type=t&status=completed")["runs"]] == [rid]
        assert f("GET", "/v1/workflows/runs?workflow_type=t&status=paused")["runs"] == []
        assert len(f("GET", "/v1/workflows/runs?limit=1")["runs"]) == 1
        r2 = f("POST", "/v1/workflows/runs", {"workflow_type": "t", "metadata": {"stage": "scope", "route": "pipelined"}})["run_id"]
        route(r2, "direct", "trivial")
        route(r2, "pipelined", "touches CI")
        route(r2, "direct")
        for bad in ("backlogged", "bogus"):  # direct can only escalate
            try:
                route(r2, bad)
                raise AssertionError(bad)
            except SystemExit:
                pass
        ev = f("GET", f"/v1/workflows/runs/{r2}/events")["events"]
        assert [(e["data"]["from"], e["data"]["to"]) for e in ev if e["event_type"] == "route.changed"] == \
            [("pipelined", "direct"), ("direct", "pipelined"), ("pipelined", "direct")]
        assert f("GET", f"/v1/workflows/runs/{r2}")["metadata"]["route"] == "direct"
    STORE_DIR = saved


def main(argv):
    cmd, args = (argv[0], argv[1:]) if argv else ("help", [])
    if cmd == "new":
        source = None
        if "--from" in args:
            i = args.index("--from")
            source, args = args[i + 1], args[:i] + args[i + 2:]
        escalate = "--escalate" in args
        args = [a for a in args if a != "--escalate"]
        assert not escalate or source, "--escalate needs --from"
        stop = None
        if "--stop-after" in args:
            i = args.index("--stop-after")
            stop, args = args[i + 1], args[:i] + args[i + 2:]
            assert stop in STAGES, f"--stop-after must be one of {STAGES}"
        to = "pipelined"
        if "--route" in args:
            i = args.index("--route")
            to, args = args[i + 1], args[:i] + args[i + 2:]
            assert to in ROUTES and not (escalate and to != "pipelined"), f"--route must be one of {list(ROUTES)}"
        title = args[1]
        request = args[2] if len(args) > 2 else title
        if to == "pipelined":
            repo = repo_root(args[0])
            load_config(repo)
        else:  # direct, backlogged and dropped tasks may have no repo
            try:
                repo = repo_root(args[0])
            except SystemExit:
                repo = None
        meta = {"stage": "intake", "title": title, "repo": repo, **({"from": source} if source else {}),
                "route": to, **({"stop_after": stop} if stop else {})}
        run = api("POST", "/v1/workflows/runs", {"workflow_type": TYPE, "input": {"title": title, "request": request},
                                                  "metadata": meta})
        api("POST", f"/v1/workflows/runs/{run['run_id']}/events",
            {"event_type": "step.started", "step_name": "intake", "data": {}})
        # Every task gets a run: log its first route. An escalated run continues direct work from `source`.
        api("POST", f"/v1/workflows/runs/{run['run_id']}/events", {"event_type": "route.changed",
            "step_name": "intake", "data": {"from": "direct" if escalate else "triaged", "to": to,
                                            "reason": "escalated" if escalate else "triaged",
                                            **({"source": source} if escalate else {})}})
        print(run["run_id"])
    elif cmd == "route":
        route(args[0], args[1], " ".join(args[2:]))
    elif cmd == "list":
        q = {"workflow_type": TYPE, "limit": 100, **({"status": args[0]} if args else {})}
        for r in api("GET", "/v1/workflows/runs?" + urllib.parse.urlencode(q))["runs"]:
            m = r.get("metadata") or {}
            m = json.loads(m) if isinstance(m, str) else m
            print(f"{r['run_id']}\t{r['status']}\t{os.path.basename(m.get('repo') or '-')}\t{m.get('stage', '?')}\t{m.get('route', '-')}\t{m.get('title', '')}")
    elif cmd == "config":
        print(json.dumps(load_config(repo_root(args[0])), indent=2))
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
    elif cmd == "guard":
        try:
            guard(json.load(sys.stdin))
        except SystemExit as e:
            if e.code not in (None, 0, 2):
                sys.exit(print(f"merge blocked: guard failed ({e})", file=sys.stderr) or 2)
            raise
        except Exception as e:
            sys.exit(print(f"merge blocked: guard failed ({e!r})", file=sys.stderr) or 2)
    elif cmd == "selftest":
        selftest(args)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
