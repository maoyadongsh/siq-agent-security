#!/usr/bin/env python3
"""Validate the research task ledger; --write refreshes its Markdown projection."""

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "docs/open-source-research-tasks-20260908.json"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def derived(ledger):
    tasks = ledger["tasks"]
    return {"workstreams": len(ledger["workstreams"]), "tasks": len(tasks),
            "status_counts": dict(Counter(t["status"] for t in tasks)),
            "kind_counts": dict(Counter(t["kind"] for t in tasks))}


def stream_status(items):
    states = {t["status"] for t in items}
    if states == {"todo"}:
        return "todo"
    if states <= {"done", "not_applicable"}:
        return "done"
    return "blocked" if "blocked" in states else "in_progress"


def validate(ledger, *, check_derived=True):
    require(ledger["schema_version"] == "siq-research-open-source-tasks/v1", "unsupported schema")
    source_path = (ROOT / ledger["source_document"]).resolve()
    require(source_path.is_relative_to(ROOT), "source document escapes repository")
    source = source_path.read_bytes()
    require(hashlib.sha256(source).hexdigest() == ledger["source_document_sha256"], "source document digest mismatch")
    source_text = source.decode()
    source_streams = set(re.findall(r"^\| (O-\d+) \|", source_text, re.MULTILINE))
    source_sections = set(re.findall(r"^## (\d+)\.", source_text, re.MULTILINE))
    tasks = ledger["tasks"]
    ids = [t["id"] for t in tasks]
    require(len(ids) == len(set(ids)), "duplicate task ID")
    by_id = {t["id"]: t for t in tasks}
    streams = [s["id"] for s in ledger["workstreams"]]
    require(len(streams) == len(set(streams)) and set(streams) == source_streams, "source workstream coverage mismatch")
    decisions = [d["id"] for d in ledger["decision_dependencies"]]
    require(len(decisions) == len(set(decisions)), "duplicate decision ID")
    for decision in ledger["decision_dependencies"]:
        require(decision["first_consumer"] in by_id, "unknown decision consumer")
    for task in tasks:
        id = task["id"]
        require(re.fullmatch(r"O-\d{2}\.\d{2}", id), f"invalid task ID: {id}")
        require(task["workstream_id"] == id.split(".")[0] and task["workstream_id"] in streams, f"invalid workstream: {id}")
        require(task["status"] in ledger["status_definitions"], f"unknown status: {id}")
        require(task["kind"] in ledger["kind_definitions"], f"unknown kind: {id}")
        require(task["priority"] in ("P0", "P1", "P2"), f"invalid priority: {id}")
        for field in ("title", "owner_role", "source_sections", "planned_outputs", "work", "acceptance", "planned_validation", "evidence_required"):
            require(task.get(field), f"missing {field}: {id}")
        require(all(s.split(".")[0] in source_sections for s in task["source_sections"]), f"unknown source section: {id}")
        require(set(task["depends_on"]) <= by_id.keys(), f"unknown dependency: {id}")
        require(set(task["decision_dependencies"]) <= set(decisions), f"unknown decision: {id}")
        require(isinstance(task["validation"], list) and isinstance(task["evidence"], list), f"invalid actual evidence lists: {id}")
        if task["status"] == "done":
            require(task["kind"] != "recurring", f"recurring task cannot be permanently done: {id}")
            require(task["validation"] and task["evidence"] and task["completed_at"], f"done without actual evidence: {id}")
            datetime.fromisoformat(task["completed_at"].replace("Z", "+00:00"))
            require(all(by_id[dep]["status"] in ("done", "not_applicable") for dep in task["depends_on"]), f"done before dependencies: {id}")
        if task["status"] == "blocked":
            require(task["blocker"], f"blocked without reason: {id}")
        if task["status"] == "not_applicable":
            require(task["kind"] in ("conditional", "external_manual"), f"inapplicable status outside supported scope: {id}")
            require(task["evidence"] and task.get("not_applicable_reason"), f"inapplicable without evidence and reason: {id}")
        if task["kind"] == "conditional":
            require(task["condition"], f"conditional task without condition: {id}")
        if task["kind"] == "recurring":
            require(task["recurrence"], f"recurring task without schedule: {id}")
    check_graph({id: by_id[id]["depends_on"] for id in ids})
    for stream in ledger["workstreams"]:
        children = [t for t in tasks if t["workstream_id"] == stream["id"]]
        require(children and stream["task_ids"] == [t["id"] for t in children], f"stream children mismatch: {stream['id']}")
        if check_derived:
            require(stream["status"] == stream_status(children), f"stale stream status: {stream['id']}")
    coverage = ledger["source_coverage"]
    require(len(coverage) == len(source_sections) and {c["section"] for c in coverage} == source_sections, "source section coverage mismatch")
    for row in coverage:
        expected = ids if row["section"] == "11" else [t["id"] for t in tasks if any(s.split(".")[0] == row["section"] for s in t["source_sections"])]
        require(row["task_ids"] == expected and expected, f"section task mapping mismatch: {row['section']}")
    gates = ledger["acceptance_gates"]
    gate_ids = [g["id"] for g in gates]
    require(len(gate_ids) == len(set(gate_ids)), "duplicate acceptance gate ID")
    for gate in gates:
        require(gate["tasks"] and set(gate["tasks"]) <= by_id.keys(), "invalid gate tasks")
        require(set(gate.get("depends_on_gates", [])) <= set(gate_ids), "unknown gate dependency")
        require(gate["state"] in ("not_met", "met"), "invalid gate state")
        if gate["state"] == "met":
            require(all(by_id[id]["status"] in ("done", "not_applicable") for id in gate["tasks"]), "gate met before tasks")
            require(all(next(g for g in gates if g["id"] == dep)["state"] == "met" for dep in gate.get("depends_on_gates", [])), "gate met before prior gates")
    check_graph({g["id"]: g.get("depends_on_gates", []) for g in gates})
    if check_derived:
        require(ledger["summary"] == derived(ledger), "stale summary")


def check_graph(graph):
    active, visited = set(), set()

    def visit(id):
        require(id not in active, f"dependency cycle at {id}")
        if id in visited:
            return
        active.add(id)
        for dep in graph[id]:
            visit(dep)
        active.remove(id)
        visited.add(id)

    for id in graph:
        visit(id)


def render(ledger):
    summary = ledger["summary"]
    lines = ["# 研究开源开发任务台账", "",
             "[方案原文](open-source-research-plan-20260908.md) · [机器可读台账](open-source-research-tasks-20260908.json)", "",
             f"原文 {summary['workstreams']} 个阶段已拆分为 **{summary['tasks']} 项执行任务**，覆盖全部 12 节。",
             "当前状态：" + "；".join(f"`{key}` {value} 项" for key, value in summary["status_counts"].items()) + "。任务登记不等于工程实施或外部发布完成。", "",
             "## 基线与执行规则", "",
             f"- 登记基线：`{ledger['recording_head_sha']}`；登记分支：`{ledger['recording_branch']}`。",
             f"- V5 运行源码：`{ledger['frozen_v5_runtime_sha']}`；原文档提交独立保留。",
             f"- 研究 submission SHA：`{ledger['research_submission_sha'] or '尚未确定'}`。",
             f"- 方案 SHA256：`{ledger['source_document_sha256']}`。", ""]
    lines += ["- " + rule for rule in ledger["global_rules"]]
    lines += ["", "维护方式：修改 JSON 中的任务状态和实际证据后，运行以下命令生成阅读版并校验；不可手改 Markdown 造成漂移。", "",
              "```bash", "python3 scripts/check_research_task_ledger.py --write", "python3 scripts/check_research_task_ledger.py", "```", "",
              "状态：" + "；".join(f"`{key}`：{value}" for key, value in ledger["status_definitions"].items()) + "。", "",
              "## 待决策事项", "", "这些是执行时要核实的事实或操作范围，不是本次落盘需逐项批准的清单。已有有效授权继续适用。", "",
              "| ID | 事项 | 建议责任角色 | 适用规则 |", "| --- | --- | --- | --- |"]
    lines += [f"| {d['id']} | {d['title']} | {d['owner_role']} | {d['rule']} |" for d in ledger["decision_dependencies"]]
    lines += ["", "## 阶段总览", "", "| 阶段 | 原文任务 | 建议排期 | 子任务数 | 状态 |", "| --- | --- | --- | --- | --- |"]
    lines += [f"| {s['id']} | {s['title']} | {s['phase']} | {len(s['task_ids'])} | {s['status']} |" for s in ledger["workstreams"]]
    lines += ["", "排期从方案获采纳且负责人落实后起算，不是实际交付日期承诺。", "", "## 验收里程碑", "",
              "| 门禁 | 达成条件 | 必需任务 | 前置门禁 | 当前 |", "| --- | --- | --- | --- | --- |"]
    lines += [f"| {g['id']} | {g['title']} | {', '.join(g['tasks'])} | {', '.join(g.get('depends_on_gates', [])) or '无'} | {g['state']} |" for g in ledger["acceptance_gates"]]
    lines += ["", "G-01～G-03 为首轮研究发行；G-04 为外部复现；G-05 为传播/社区；G-06 为论文材料可提交。真实投稿/接收由 O-17.03/04 另行记录，持续维护按期跟踪。", "", "## 全量任务", ""]
    for stream in ledger["workstreams"]:
        lines += [f"### {stream['id']} · {stream['title']}", "", f"原文排期：{stream['phase']}。输出路径是计划位置，实际完成以证据为准。", ""]
        for task in ledger["tasks"]:
            if task["workstream_id"] != stream["id"]:
                continue
            lines += [f"#### {task['id']} · {task['title']}", "",
                      f"- 状态：`{task['status']}`；优先级：`{task['priority']}`；类型：`{task['kind']}`；责任角色：`{task['owner_role']}`；负责人：{task['assignee'] or '未指派'}。",
                      "- 原文依据：" + "、".join("§" + s for s in task["source_sections"]) + "。",
                      "- 完成依赖：" + (", ".join(task["depends_on"]) or "无") + "；待决策依赖：" + (", ".join(task["decision_dependencies"]) or "无") + "。",
                      "- 计划产物：" + "；".join("`" + p + "`" for p in task["planned_outputs"]) + "。"]
            for key, label in (("condition", "条件"), ("recurrence", "周期"), ("blocker", "实际阻塞"), ("completed_at", "完成时间")):
                if task.get(key):
                    lines.append(f"- {label}：{task[key]}。")
            lines += ["", "实施内容：", ""] + [f"{i}. {step}" for i, step in enumerate(task["work"], 1)]
            lines += ["", "验收标准（逐项在实际验证记录中说明结果）：", ""] + ["- " + step for step in task["acceptance"]]
            lines += ["", "计划验证：", ""]
            for method in task["planned_validation"]:
                lines.append("- " + method["method"] + "：" + "；".join(method["checks"]) + "。" + method["expected"])
            lines += ["", "实际验证：`" + json.dumps(task["validation"], ensure_ascii=False) + "`。",
                      "实际证据：`" + json.dumps(task["evidence"], ensure_ascii=False) + "`。", ""]
    lines += ["## 原文覆盖矩阵", "", "| 原文节 | 对应任务 |", "| --- | --- |"]
    lines += [f"| §{c['section']} | {', '.join(c['task_ids'])} |" for c in ledger["source_coverage"]]
    lines += ["", "## 执行入口", "",
              "实施开始时先刷新 O-01.01，再开展 O-01.02、O-02.01/02、O-03.01、O-06.01、O-07.01、O-08.01 的准备。某个外部事项等待确认时，继续无依赖的本地准备；不能跨过未满足依赖发布结果。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=DEFAULT)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    ledger = json.loads(args.ledger.read_text())
    validate(ledger, check_derived=not args.write)
    if args.write:
        ledger["summary"] = derived(ledger)
        for stream in ledger["workstreams"]:
            stream["status"] = stream_status([t for t in ledger["tasks"] if t["workstream_id"] == stream["id"]])
        validate(ledger)
        args.ledger.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n")
        args.ledger.with_suffix(".md").write_text(render(ledger))
    else:
        require(args.ledger.with_suffix(".md").read_text() == render(ledger), "Markdown projection drift; run --write")
    print(json.dumps({"result": "passed", **ledger["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
