#!/usr/bin/env python3
"""Offline, read-only path lifecycle analysis for the frozen B0 scouting receipts.

The input root is deliberately supplied at runtime.  No prompts, repository
contents, model output, or validator details are written to the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def load_json(path: Path):
    return json.loads(path.read_text())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_rows(root: Path):
    rows = []
    for result_root in sorted(root.glob("private-results/full-initial-20260713-g2-*")):
        for summary in sorted(result_root.glob("*/run_summary.json")):
            row = load_json(summary)
            row["_dir"] = str(summary.parent)
            rows.append(row)
    if len(rows) != 70:
        raise SystemExit(f"expected 70 frozen runs, found {len(rows)}")
    return rows


def task_map(root: Path):
    return {x["task_id"]: x for x in load_json(root / "tasks/PRIVATE_TASK_DEFINITIONS.json")}


def compile_record(row):
    p = Path(row["_dir"]) / "b0_compile.json"
    return load_json(p) if p.exists() else {}


def provenance(comp):
    return {x["path"]: x for x in comp.get("routing_decision", {}).get("candidate_provenance", [])}


def ledger(comp):
    return {x["path"]: x for x in comp.get("file_decision_ledger", {}).get("records", [])}


def category(comp, path):
    rd = comp.get("routing_decision", {})
    for key, label in (("primary_paths", "PRIMARY"), ("verification_paths", "VERIFY"), ("support_paths", "SUPPORT")):
        if path in rd.get(key, []):
            return label
    for key, label in (("primary_files", "PRIMARY"), ("verification_files", "VERIFY"), ("support_files", "SUPPORT")):
        if any(x.get("path") == path for x in comp.get(key, []) if isinstance(x, dict)):
            return label
    return None


def trace(row, task):
    comp = compile_record(row)
    prov = provenance(comp)
    led = ledger(comp)
    selected = {x.get("path"): x for x in comp.get("selected", []) if isinstance(x, dict) and x.get("path")}
    required = [p for p in task.get("allowed_mutation_paths", []) if "*" not in p]
    read = set(row.get("read_paths", []))
    edited = set(row.get("files_edited", []))
    traces = []
    for path in required:
        l = led.get(path, {})
        p = prov.get(path, {})
        s = selected.get(path, {})
        generated = bool(l.get("candidate") or p)
        admitted = path in selected
        if not generated:
            loss = "required_path_not_generated" if path in led else "required_path_not_in_inventory"
        elif not admitted:
            loss = "required_path_filtered"
        elif path not in read:
            loss = "agent_ignored_correct_path"
        else:
            loss = None
        traces.append({
            "task_id": row["task_id"], "required_path": path,
            "present_in_inventory": path in led,
            "generated_as_candidate": generated,
            "candidate_generator": p.get("provenance", l.get("candidate_projection_reason")),
            "candidate_evidence": p.get("matched_signals", l.get("matched_prompt_terms", [])),
            "score_components": s.get("score_deltas", l.get("score_deltas", {})),
            "total_score": p.get("score", s.get("score", l.get("raw_score"))),
            "rank": p.get("rank"), "filter_result": l.get("skip_reason") or ("eligible" if l.get("eligible", generated) else "ineligible"),
            "packet_admitted": admitted, "packet_category": category(comp, path),
            "packet_position": list(selected).index(path) if admitted else None,
            "read_by_agent": path in read, "edited_by_agent": path in edited,
            "discovered_later": path in row.get("unsupplied_required_paths", []) and path in read,
            "point_of_loss": loss,
            "root_cause": loss or ("agent_ignored_correct_path" if path not in edited else "none_observed"),
        })
    supplied_unused = []
    for path in row.get("supplied_unused_paths", []):
        s = selected.get(path, {})
        p = prov.get(path, {})
        l = led.get(path, {})
        supplied_unused.append({
            "task_id": row["task_id"], "supplied_path": path,
            "generator": p.get("provenance", l.get("candidate_projection_reason")),
            "evidence": p.get("matched_signals", l.get("matched_prompt_terms", [])),
            "score": p.get("score", s.get("score", l.get("raw_score"))),
            "rank": p.get("rank"), "category": category(comp, path),
            "reason_admitted": s.get("reason") or l.get("why_promoted"),
            "read_by_agent": path in read,
            "unused_reason": "not_read_in_receipt",
            "cost_effect": "proxy_only_packet_or_exploration_exposure",
            "should_have_been_suppressed": False,
        })
    return traces, supplied_unused


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    tasks = task_map(args.root)
    rows = [r for r in run_rows(args.root) if r["arm"] == "B0"]
    traces, unused = [], []
    for row in rows:
        t, u = trace(row, tasks[row["task_id"]]); traces.extend(t); unused.extend(u)
    by_task = {r["task_id"]: r for r in rows}
    required_total = len(traces)
    generated = sum(x["generated_as_candidate"] for x in traces)
    admitted = sum(x["packet_admitted"] for x in traces)
    read_required = sum(x["read_by_agent"] for x in traces)
    out = {
        "schema_version": "b0-path-lifecycle-forensics.v1",
        "source": {"root_sha256": sha(args.root / "private-results/PRIVATE_FULL_SCOUTING_RESULTS.json"), "run_count": len(rows), "arm": "B0"},
        "metrics": {
            "tasks": len(rows), "required_paths": required_total,
            "candidate_recall": generated / required_total if required_total else None,
            "packet_required_recall": admitted / required_total if required_total else None,
            "read_required_recall": read_required / required_total if required_total else None,
            "supplied_paths": sum(len(r.get("selected_paths", [])) for r in rows),
            "supplied_unused_paths": len(unused),
            "path_precision_proxy": sum(len(r.get("supplied_used_paths", [])) for r in rows) / max(1, sum(len(r.get("selected_paths", [])) for r in rows)),
            "packet_waste": len(unused) / max(1, sum(len(r.get("selected_paths", [])) for r in rows)),
            "expansion_tasks": sum(bool(r.get("unsupplied_required_paths")) for r in rows),
        },
        "root_cause_counts": Counter(x["root_cause"] for x in traces),
        "task_class_summary": {}, "required_path_traces": traces, "unused_path_admission": unused,
    }
    classes = defaultdict(lambda: {"B0": [], "STANDARD": []})
    for r in run_rows(args.root): classes[r["task_class"]][r["arm"]].append(r)
    for cls, arms in classes.items():
        out["task_class_summary"][cls] = {a: {"tasks": len(v), "success": sum(x.get("hidden_validator_passed", False) for x in v), "tokens": sum(x.get("total_tokens", 0) for x in v), "requests": sum(x.get("requests", 0) for x in v), "searches": sum(x.get("searches", 0) for x in v), "reads": sum(len(x.get("read_paths", [])) for x in v)} for a, v in arms.items()}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
