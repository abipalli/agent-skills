#!/usr/bin/env python3
"""Check the repo against CONVENTIONS.md. Exit 1 on any error.

    python3 scripts/validate.py            # needs PyYAML
    python3 scripts/validate.py --format   # rewrite frontmatter into the portable style
    python3 scripts/validate.py --test     # self-check
"""
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
MODELS = ["haiku", "sonnet", "opus"]
EFFORTS = ["low", "medium", "high", "xhigh", "max"]
ACCESS = {"read-only", "worktree", "publish"}
# Things a public skill must not carry: machine paths, private hosts, real emails.
PRIVATE = [
    (re.compile(r"(?<![\w.])/(?:home|Users|srv)/\w"), "absolute home/server path"),
    (re.compile(r"\b[\w-]+\.(?:internal|lan|local)\b"), "private hostname"),
    (re.compile(r"\b[\w.+-]+@(?!example\.|users\.noreply\.github\.com)[\w-]+\.[\w.]+\b"), "email address"),
]

errors, external = [], set()


def err(path, msg):
    errors.append(f"{path.relative_to(ROOT)}: {msg}")


# Frontmatter is read by real YAML parsers (Claude Code, Codex) and by minimal ones
# (Paperclip reads `>` as a literal ">" and `[a, b]` as a string). The portable
# style below parses identically in both: maps in block style, strings plain or
# JSON-quoted on one line, lists as JSON arrays (one item per line for objects).
PLAIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._/@()+-]*")
RESERVED = {"true", "false", "yes", "no", "on", "off", "null", "~"}


def scalar(v):
    v = v.strip() if isinstance(v, str) else v
    if isinstance(v, str) and PLAIN.fullmatch(v) and v.lower() not in RESERVED \
            and not re.fullmatch(r"-?\d+(\.\d+)?", v) and not v.endswith(" "):
        return v
    return json.dumps(v, ensure_ascii=False)


def emit(obj, indent=0):
    pad, out = " " * indent, []
    for k, v in obj.items():
        if isinstance(v, dict) and v:
            out += [f"{pad}{k}:"] + emit(v, indent + 2)
        elif isinstance(v, list) and any(isinstance(i, (dict, list)) for i in v):
            out += [f"{pad}{k}: ["] + [f"{pad}  {json.dumps(i, ensure_ascii=False)}," for i in v]
            out[-1] = out[-1].rstrip(",")
            out.append(f"{pad}]")
        else:
            out.append(f"{pad}{k}: {json.dumps(v) if isinstance(v, (list, dict)) else scalar(v)}")
    return out


def split(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    return (m.group(1), text[m.end():]) if m else (None, text)


def front(path, fix=False):
    raw, body = split(path.read_text())
    if raw is None:
        err(path, "no YAML frontmatter")
        return {}
    try:
        fm = yaml.safe_load(raw) or {}
    except yaml.YAMLError as e:
        err(path, f"bad frontmatter: {e}")
        return {}
    canon = "\n".join(emit(fm))
    if raw != canon:
        if fix:
            path.write_text(f"---\n{canon}\n---\n{body}")
        else:
            err(path, "frontmatter is not in the portable style; run scripts/validate.py --format")
    return fm


def lowers(caller, callee):
    """True when calling `callee` would lower the tier `caller` set."""
    for key, order in (("model", MODELS), ("effort", EFFORTS)):
        a, b = caller.get(key), callee.get(key)
        if a in order and b in order and order.index(b) < order.index(a):
            return True
    return False


def check_skills():
    skills = {}
    for d in sorted((ROOT / "skills").iterdir()):
        md = d / "SKILL.md"
        if not md.is_file():
            err(d, "no SKILL.md")
            continue
        fm = front(md)
        skills[d.name] = fm
        if fm.get("name") != d.name:
            err(md, f"name {fm.get('name')!r} must equal the directory name")
        desc = fm.get("description") or ""
        if not desc.strip():
            err(md, "description is required")
        elif len(desc) > 1024:
            err(md, f"description is {len(desc)} characters, max 1024")
        for key, order in (("model", MODELS), ("effort", EFFORTS)):
            if key in fm and fm[key] not in order:
                err(md, f"{key} {fm[key]!r} not in {order}")
        calls = (fm.get("metadata") or {}).get("calls") or []
        if not isinstance(calls, list):
            err(md, "metadata.calls must be a list")
    for name, fm in skills.items():
        md = ROOT / "skills" / name / "SKILL.md"
        for callee in (fm.get("metadata") or {}).get("calls") or []:
            if callee not in skills:
                external.add(callee)
            elif lowers(fm, skills[callee]):
                err(md, f"calls {callee}, whose tier is lower: it would downgrade the rest of the turn")
    return skills


def check_agents(skills):
    runtime = yaml.safe_load((ROOT / ".paperclip.yaml").read_text()) or {}
    configured = (runtime.get("agents") or {}).keys()
    agents = {}
    for d in sorted((ROOT / "agents").iterdir()):
        md = d / "AGENTS.md"
        if not md.is_file():
            err(d, "no AGENTS.md")
            continue
        fm = agents[d.name] = front(md)
        for key in ("name", "description"):
            if not fm.get(key):
                err(md, f"{key} is required")
        if (fm.get("metadata") or {}).get("access") not in ACCESS:
            err(md, f"metadata.access must be one of {sorted(ACCESS)}")
        for s in fm.get("skills") or []:
            if s not in skills:
                external.add(s)
        if d.name not in configured:
            err(md, "no runtime entry under agents: in .paperclip.yaml")
    for name in configured:
        if name not in agents:
            errors.append(f".paperclip.yaml: agent {name!r} has no agents/{name}/AGENTS.md")
    return agents


def check_pipelines(skills, agents):
    for name, fm in skills.items():
        md = ROOT / "skills" / name / "SKILL.md"
        meta = fm.get("metadata") or {}
        for stage in (meta.get("pipeline") or {}).get("stages") or []:
            sid = stage.get("id", "?")
            if stage.get("agent") not in agents:
                err(md, f"stage {sid}: agent {stage.get('agent')!r} is not in agents/")
            if stage.get("skill") not in skills:
                err(md, f"stage {sid}: skill {stage.get('skill')!r} is not in skills/")
            if stage.get("skill") not in (meta.get("calls") or []):
                err(md, f"stage {sid}: {stage.get('skill')} is missing from metadata.calls")
    for md in sorted((ROOT / "teams").glob("*/TEAM.md")):
        fm = front(md)
        for ref in [fm.get("manager")] + (fm.get("includes") or []):
            if not ref or not (md.parent / ref).resolve().is_file():
                err(md, f"{ref!r} does not resolve to a file")


def format_all():
    for p in sorted([*ROOT.glob("skills/*/SKILL.md"), *ROOT.glob("agents/*/AGENTS.md"),
                     *ROOT.glob("teams/*/TEAM.md"), ROOT / "COMPANY.md"]):
        front(p, fix=True)


def check_tree():
    for p in sorted(ROOT.rglob("*")):
        if ".git" in p.parts:
            continue
        if p.is_symlink():
            err(p, "symlink: Paperclip and GitHub skill installers drop these, commit real files")
        elif p.is_file() and p.suffix in {".md", ".py", ".json", ".yaml", ".yml", ".sh", ".txt"}:
            if p.name in {"LICENSE", "NOTICE"} or p == Path(__file__).resolve():
                continue
            text = p.read_text(errors="replace")
            for rx, what in PRIVATE:
                m = rx.search(text)
                if m:
                    line = text.count("\n", 0, m.start()) + 1
                    err(p, f"line {line}: {what} {m.group(0)!r}")


def selftest():
    assert lowers({"model": "opus"}, {"model": "sonnet"})
    assert lowers({"effort": "xhigh"}, {"effort": "high"})
    assert not lowers({"model": "sonnet", "effort": "medium"}, {"model": "opus", "effort": "xhigh"})
    assert not lowers({"model": "opus"}, {})  # unset callee inherits
    assert not lowers({}, {"model": "haiku"})  # unset caller: nothing to lower
    assert PRIVATE[0][0].search("see /home/me/x") and not PRIVATE[0][0].search("a/home/b")
    assert PRIVATE[2][0].search("me@corp.com") and not PRIVATE[2][0].search("1+me@users.noreply.github.com")
    fm = {"name": "x", "description": "Does: things, then # more", "model": "opus",
          "metadata": {"calls": ["a", "b"], "pipeline": {"stages": [{"id": "s", "verdicts": ["ok"]}]}}}
    canon = "\n".join(emit(fm))
    assert yaml.safe_load(canon) == fm, canon
    assert '"Does: things, then # more"' in canon and 'calls: ["a", "b"]' in canon
    print("selftest ok")


if __name__ == "__main__":
    if "--test" in sys.argv:
        selftest()
        sys.exit(0)
    if "--format" in sys.argv:
        format_all()
    skills = check_skills()
    agents = check_agents(skills)
    check_pipelines(skills, agents)
    check_tree()
    print(f"{len(skills)} skills, {len(agents)} agents")
    if external:
        print("external skills (install separately):", ", ".join(sorted(external)))
    for e in errors:
        print("error:", e)
    sys.exit(1 if errors else 0)
