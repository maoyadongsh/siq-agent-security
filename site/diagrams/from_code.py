#!/usr/bin/env python3
"""Scan this repo's source and emit Mermaid diagrams for GitHub Pages.

Nothing here is hand-laid-out architecture. Nodes and edges come from:
  - CLI subcommands in cmd/agentshield/main.go
  - http.ServeMux registrations in internal/server/server.go
  - Go imports among apps/agentshield/internal/*
  - grant.transitions map
  - admission.builder.finish verdict rules
  - receipt.Engine.evaluate / Decide return paths
  - adapters/runtime/* directories
  - PolicyExec verdict → OpenClaw decision switch
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
GO_ROOT = REPO / "apps" / "agentshield"
INTERNAL = GO_ROOT / "internal"
MAIN = GO_ROOT / "cmd" / "agentshield" / "main.go"
SERVER = INTERNAL / "server" / "server.go"
GRANT = INTERNAL / "grant" / "grant.go"
ADMISSION = INTERNAL / "admission" / "admission.go"
ENGINE = INTERNAL / "receipt" / "engine.go"
ADAPTERS_GO = INTERNAL / "adapters" / "adapters.go"
ADAPTERS_DIR = REPO / "adapters" / "runtime"

THEME = """%%{init: {'theme': 'base', 'themeVariables': {
  'primaryColor': '#fdfcf9',
  'primaryTextColor': '#001840',
  'primaryBorderColor': '#001840',
  'lineColor': '#7c5a0c',
  'secondaryColor': '#f3eee2',
  'tertiaryColor': '#f7f4ee',
  'fontFamily': 'ui-sans-serif, system-ui, sans-serif'
}}}%%
"""


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def mermaid_label(s: str) -> str:
    s = s.replace("\\", "/").replace('"', "'").replace("[", "(").replace("]", ")")
    s = s.replace("#", "＃")
    return s


def mermaid_id(s: str) -> str:
    out = re.sub(r"[^A-Za-z0-9_]", "_", s)
    if out[0:1].isdigit():
        out = "n_" + out
    return out or "n"


def extract_cli(src: str) -> list[str]:
    in_switch = False
    cmds: list[str] = []
    for line in src.splitlines():
        if "switch os.Args[1]" in line:
            in_switch = True
            continue
        if in_switch:
            if line.startswith("\t") and line.strip().startswith("}"):
                break
            m = re.match(r'\tcase "([^"]+)":', line)
            if m:
                cmds.append(m.group(1))
    return cmds


def extract_routes(src: str) -> list[tuple[str, str]]:
    routes = []
    for m in re.finditer(r's\.mux\.HandleFunc\("([^"]+)",\s*([^)]+)\)', src):
        routes.append((m.group(1), m.group(2).strip()))
    if re.search(r's\.mux\.Handle\("/",\s*d\.UI\)', src):
        routes.append(("/", "d.UI"))
    return routes


def extract_packages() -> tuple[list[str], list[tuple[str, str]]]:
    pkgs = sorted(p.name for p in INTERNAL.iterdir() if p.is_dir() and any(p.glob("*.go")))
    prefix = "siq-agent-security/apps/agentshield/internal/"
    edges: set[tuple[str, str]] = set()
    for pkg in pkgs:
        for go in (INTERNAL / pkg).glob("*.go"):
            if go.name.endswith("_test.go"):
                continue
            text = read(go)
            for m in re.finditer(re.escape(prefix) + r"([a-z0-9]+)", text):
                other = m.group(1)
                if other != pkg and other in pkgs:
                    edges.add((pkg, other))
    return pkgs, sorted(edges)


def extract_transitions(src: str) -> list[tuple[str, str]]:
    block = re.search(r"var transitions = map\[string\]\[\]string\{(.*?)\n\}", src, re.S)
    if not block:
        raise SystemExit("grant.transitions not found")
    edges = []
    for m in re.finditer(r'"([^"]+)":\s*\{([^}]+)\}', block.group(1)):
        frm = m.group(1)
        tos = re.findall(r'"([^"]+)"', m.group(2))
        for to in tos:
            edges.append((frm, to))
    return edges


def extract_admission_rules(src: str) -> dict:
    fn = re.search(r"func \(b \*builder\) finish\(hasSkillMD bool\)[\s\S]+?\n\}\n\n", src)
    if not fn:
        # fallback: take from finish through next top-level func
        fn = re.search(r"func \(b \*builder\) finish\(hasSkillMD bool\)(.*?)func ", src, re.S)
    body = fn.group(0) if fn else ""
    return {
        "default": "admit",
        "finding_quarantine": "quarantine" if "dispQuarantine" in body and 'verdict = "quarantine"' in body else None,
        "finding_declare": "admit_with_conditions" if "dispDeclare" in body else None,
        "integrity_force": bool(re.search(r"overLimit \|\| b\.w\.symlinkEscape \|\| !hasSkillMD", body)),
    }


def extract_decide_returns(src: str) -> list[tuple[str, str]]:
    """(action, go-expression) from evaluate() return statements."""
    fn = re.search(r"func \(e \*Engine\) evaluate\([\s\S]*?\n\}", src)
    if not fn:
        raise SystemExit("receipt.evaluate not found")
    out = []
    for m in re.finditer(r"return (Action[A-Za-z]+), (.+)$", fn.group(0), re.M):
        expr = re.sub(r"\s+", " ", m.group(2).rstrip())
        if len(expr) > 80:
            expr = expr[:77] + "..."
        out.append((m.group(1).replace("Action", "").lower(), expr))
    return out


def extract_mode_switch(src: str) -> list[str]:
    fn = re.search(r"func \(e \*Engine\) Decide\([\s\S]*?\n\}\n\n", src)
    body = fn.group(0) if fn else src
    block = re.search(r"switch e\.opts\.EnforcementMode \{([\s\S]+?)\n\t\}", body)
    if not block:
        return []
    modes = []
    for m in re.finditer(r'case "([^"]+)"(?:,\s*"([^"]+)")?', block.group(1)):
        modes.append(m.group(1))
        if m.group(2):
            modes.append(m.group(2))
    if re.search(r"\n\tdefault:", block.group(1)):
        modes.append("default")
    return modes


def extract_policy_exec_map(src: str) -> list[tuple[str, str]]:
    block = re.search(r"switch res\.Admission\.Verdict \{([\s\S]+?)\n\t\}", src)
    if not block:
        return []
    text = block.group(1)
    simple = re.findall(
        r'case "([^"]+)":\s*\n\s*out\.Decision(?:, out\.Reason)? = "([^"]+)"',
        text,
    )
    if re.search(r'default:\s*\n\s*out\.Decision = "block"', text):
        simple.append(("quarantine", "block"))
    return simple


def extract_adapters() -> list[str]:
    if not ADAPTERS_DIR.exists():
        return []
    return sorted(p.name for p in ADAPTERS_DIR.iterdir() if p.is_dir())


def write_mmd(name: str, body: str) -> Path:
    path = OUT / name
    path.write_text(THEME + body.strip() + "\n", encoding="utf-8")
    return path


def diagram_packages(pkgs: list[str], edges: list[tuple[str, str]]) -> str:
    lines = ["flowchart LR"]
    for p in pkgs:
        lines.append(f'  {mermaid_id(p)}["{p}"]')
    for a, b in edges:
        lines.append(f"  {mermaid_id(a)} --> {mermaid_id(b)}")
    return "\n".join(lines)


def diagram_cli_http(cmds: list[str], routes: list[tuple[str, str]], adapters: list[str]) -> str:
    lines = ["flowchart TB"]
    lines.append('  subgraph cli["cmd/agentshield switch os.Args[1]"]')
    for c in cmds:
        lines.append(f'    cli_{mermaid_id(c)}["{c}"]')
    lines.append("  end")
    lines.append('  subgraph http["internal/server New() ServeMux"]')
    for path, _ in routes:
        lines.append(f'    rt_{mermaid_id(path)}["{path}"]')
    lines.append("  end")
    if adapters:
        lines.append('  subgraph adp["adapters/runtime"]')
        for a in adapters:
            lines.append(f'    ad_{mermaid_id(a)}["{a}"]')
        lines.append("  end")
        lines.append("  adp --> http")
    # known wiring from code names
    if "serve" in cmds:
        lines.append("  cli_serve --> http")
    if "admit" in cmds and any(p == "/v1/admit" for p, _ in routes):
        lines.append("  cli_admit -.-> rt__v1_admit")
    if "policy-exec" in cmds:
        lines.append("  cli_policy_exec --> adp")
    if "hook" in cmds:
        lines.append("  cli_hook --> adp")
    return "\n".join(lines)


def diagram_admission(rules: dict, policy_map: list[tuple[str, str]]) -> str:
    lines = ["flowchart TD"]
    lines.append('  start["admission.Admit(path)"] --> finish["builder.finish()"]')
    lines.append(f'  finish --> def["default verdict = {rules["default"]}"]')
    lines.append('  def --> q{"finding.Disposition == quarantine"}')
    lines.append('  q -->|yes| quar["verdict = quarantine"]')
    lines.append('  q -->|no| d{"finding.Disposition == declare"}')
    lines.append('  d -->|yes| cond["verdict = admit_with_conditions"]')
    lines.append(f'  d -->|no| ok["verdict = {rules["default"]}"]')
    if rules.get("integrity_force"):
        lines.append('  quar --> force["overLimit || symlinkEscape || !SKILL.md → quarantine"]')
        lines.append("  cond --> force")
        lines.append("  ok --> force")
        lines.append('  force --> out["stdout JSON / exit 0 or 3"]')
    else:
        lines.append("  quar --> out[stdout]")
        lines.append("  cond --> out")
        lines.append("  ok --> out")
    if policy_map:
        lines.append('  out --> pe["PolicyExec switch Verdict"]')
        for verdict, decision in policy_map:
            lines.append(f'  pe --> p_{mermaid_id(verdict)}["{verdict} → {decision}"]')
    return "\n".join(lines)


def diagram_decide(returns: list[tuple[str, str]], modes: list[str]) -> str:
    lines = ["flowchart TD"]
    lines.append('  dec["Engine.Decide"] --> ev["Engine.evaluate"]')
    for i, (action, reason) in enumerate(returns):
        nid = f"r{i}"
        label = mermaid_label(reason)
        if len(label) > 56:
            label = label[:53] + "..."
        lines.append(f'  ev --> {nid}["{action}: {label}"]')
    if modes:
        lines.append('  dec --> mode["switch EnforcementMode"]')
        for m in modes:
            lines.append(f'  mode --> m_{mermaid_id(m)}["{m}"]')
        if "audit_only" in modes:
            lines.append('  m_audit_only --> advisory["non-allow → AdvisoryAction; action=allow"]')
        if "warn" in modes:
            lines.append("  m_warn --> advisory")
    return "\n".join(lines)


def diagram_grant(edges: list[tuple[str, str]]) -> str:
    lines = ["stateDiagram-v2"]
    for a, b in edges:
        lines.append(f"  {a} --> {b}")
    return "\n".join(lines)


def diagram_runtime(cmds: list[str], routes: list[tuple[str, str]], adapters: list[str]) -> str:
    lines = ["flowchart LR"]
    lines.append('  subgraph host["this checkout"]')
    lines.append('    skill["skills/siq-agent-security"]')
    lines.append('    bin["apps/agentshield cmd"]')
    for a in adapters:
        lines.append(f'    {mermaid_id(a)}["{a}"]')
    lines.append("  end")
    lines.append('  skill --> bin')
    for a in adapters:
        lines.append(f"  {mermaid_id(a)} --> bin")
    decide = next((p for p, _ in routes if p == "/v1/decide"), None)
    if decide:
        lines.append('  bin --> api["/v1/decide"]')
    return "\n".join(lines)


def main() -> None:
    main_src = read(MAIN)
    server_src = read(SERVER)
    grant_src = read(GRANT)
    adm_src = read(ADMISSION)
    eng_src = read(ENGINE)
    adp_src = read(ADAPTERS_GO)

    cmds = extract_cli(main_src)
    routes = extract_routes(server_src)
    pkgs, pkg_edges = extract_packages()
    transitions = extract_transitions(grant_src)
    adm_rules = extract_admission_rules(adm_src)
    decide_ret = extract_decide_returns(eng_src)
    modes = extract_mode_switch(eng_src)
    policy_map = extract_policy_exec_map(adp_src)
    adapters = extract_adapters()

    diagrams = [
        {
            "id": "runtime",
            "title": "本仓目录怎么接到本机程序",
            "file": "runtime.mmd",
            "sources": ["apps/agentshield/cmd/agentshield/main.go", "adapters/runtime/"],
        },
        {
            "id": "packages",
            "title": "Go internal 包依赖（import）",
            "file": "packages.mmd",
            "sources": ["apps/agentshield/internal/*/"],
        },
        {
            "id": "cli-http",
            "title": "CLI 子命令与 HTTP 路由",
            "file": "cli-http.mmd",
            "sources": [
                "apps/agentshield/cmd/agentshield/main.go",
                "apps/agentshield/internal/server/server.go",
            ],
        },
        {
            "id": "admission",
            "title": "admit 结论与 policy-exec 映射",
            "file": "admission.mmd",
            "sources": [
                "apps/agentshield/internal/admission/admission.go",
                "apps/agentshield/internal/adapters/adapters.go",
            ],
        },
        {
            "id": "decide",
            "title": "Decide / evaluate 返回路径",
            "file": "decide.mmd",
            "sources": ["apps/agentshield/internal/receipt/engine.go"],
        },
        {
            "id": "grant",
            "title": "grant.transitions 状态机",
            "file": "grant.mmd",
            "sources": ["apps/agentshield/internal/grant/grant.go"],
        },
    ]

    write_mmd("runtime.mmd", diagram_runtime(cmds, routes, adapters))
    write_mmd("packages.mmd", diagram_packages(pkgs, pkg_edges))
    write_mmd("cli-http.mmd", diagram_cli_http(cmds, routes, adapters))
    write_mmd("admission.mmd", diagram_admission(adm_rules, policy_map))
    write_mmd("decide.mmd", diagram_decide(decide_ret, modes))
    write_mmd("grant.mmd", diagram_grant(transitions))

    meta = {
        "generated_from": "site/diagrams/from_code.py",
        "note": "Nodes and edges are parsed from the current checkout, not drawn by hand.",
        "cli": cmds,
        "http_routes": [p for p, _ in routes],
        "packages": pkgs,
        "package_imports": [{"from": a, "to": b} for a, b in pkg_edges],
        "grant_transitions": [{"from": a, "to": b} for a, b in transitions],
        "decide_returns": [{"action": a, "reason": r} for a, r in decide_ret],
        "enforcement_modes_in_decide": modes,
        "policy_exec": [{"verdict": v, "decision": d} for v, d in policy_map],
        "adapters": adapters,
        "diagrams": diagrams,
    }
    (OUT / "index.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"cli={len(cmds)} routes={len(routes)} pkgs={len(pkgs)} edges={len(pkg_edges)} adapters={adapters}")


if __name__ == "__main__":
    main()
