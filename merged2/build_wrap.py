#!/usr/bin/env python3
"""Wrap every harnyx-agents-17 pack without changing its inner structure.

Fast queries keep the original sequential runner. Non-fast queries run the
first two routed agents in parallel, then pick with the host pairwise judge
from miner_task_scoring.py (`_score_pairwise` / `_judge_pair`).
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

SRC = Path("/root/new1/new/harnyx-agents-17-2026-09-13T03-50-45")
DST = Path("/root/new1/new/merged2")
TEMPLATE = Path("/root/new1/new/merged1/uid-97__uid_97__artifact_b6f9e8e7-ce8f-436c-bd4e-34006bbebed4.py")
MAX_BYTES = 1_000_000


def extract_helpers() -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    start = text.index("# Host pairwise judge")
    end = text.index("def _pw_floor()")
    helpers = text[start:end].rstrip() + "\n"
    if helpers.count("return await llm_chat(") != 1:
        raise SystemExit("template judge chat is not a single llm_chat call")
    return helpers


def inject_json(text: str) -> str:
    if re.search(r"(?m)^import json\b", text):
        return text
    if re.search(r"(?m)^import time\b", text):
        return text.replace("import time\n", "import time\nimport json\n", 1)
    if re.search(r"(?m)^import asyncio\b", text):
        return text.replace("import asyncio\n", "import asyncio\nimport json\n", 1)
    raise SystemExit("could not inject json import")


def find_module_query(tree: ast.Module) -> ast.AsyncFunctionDef:
    found: ast.AsyncFunctionDef | None = None
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "query":
            found = node
    if found is None:
        raise SystemExit("no module-level query")
    return found


def float_helpers(tree: ast.Module, text: str) -> tuple[str, str]:
    elapsed = None
    remaining = None
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.returns is None:
            continue
        if ast.unparse(node.returns) != "float":
            continue
        seg = ast.get_source_segment(text, node) or ""
        if "started" in seg and "monotonic" in seg:
            elapsed = node.name
        elif elapsed and elapsed in seg:
            remaining = node.name
            break
    if not elapsed or not remaining:
        raise SystemExit("could not detect elapsed/remaining helpers")
    return elapsed, remaining


def sequential_symbols(tree: ast.Module, text: str, seq_name: str) -> tuple[str, str]:
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == seq_name:
            seg = ast.get_source_segment(text, node) or ""
            wall = re.search(r"remaining = (_\w+) - \(time\.monotonic\(\) - started\)", seg)
            first = re.search(r"budget = (_\w+) if \1 < remaining else remaining", seg)
            if wall is None or first is None:
                raise SystemExit(f"could not read budgets from {seq_name}")
            return wall.group(1), first.group(1)
    raise SystemExit(f"missing sequential runner {seq_name}")


def orig_llm_name(text: str) -> str:
    match = re.search(r"^(_\w+) = _hsapi\.llm_chat$", text, re.M)
    if match is None:
        raise SystemExit("could not find saved original llm_chat")
    return match.group(1)


def detect_slots(text: str) -> dict[str, str]:
    tree = ast.parse(text)
    query = find_module_query(tree)
    src = ast.get_source_segment(text, query) or ""
    nonfast = re.search(r"return await (_\w+)\(query, agents\)", src)
    fast = re.search(r"return await (_\w+)\(query, \(", src)
    floor = re.search(r"except Exception:\n        return (_\w+)\(query\)", src)
    if not nonfast or not fast or not floor:
        raise SystemExit("could not detect query runners")
    _, remaining = float_helpers(tree, text)
    _wall, first_budget = sequential_symbols(tree, text, fast.group(1))
    return {
        "nonfast": nonfast.group(1),
        "sequential": fast.group(1),
        "floor": floor.group(1),
        "remaining": remaining,
        "first_budget": first_budget,
        "orig_llm": orig_llm_name(text),
    }


def make_parallel(slots: dict[str, str]) -> str:
    return (
        "\n"
        "async def _pw_parallel_two(query: Query, agents: tuple) -> Response:\n"
        '    """Run the first two routed agents together, then host-pairwise pick."""\n'
        "    if len(agents) < 2:\n"
        f"        return await {slots['sequential']}(query, agents)\n"
        f"    remaining = {slots['remaining']}()\n"
        "    reserve = _PW_JUDGE_TIMEOUT_S + 6.0\n"
        "    budget = remaining - reserve\n"
        f"    if {slots['first_budget']} < budget:\n"
        f"        budget = {slots['first_budget']}\n"
        "    if budget <= 0.0:\n"
        f"        return {slots['floor']}(query)\n"
        "    first_out, second_out = await asyncio.gather(\n"
        "        asyncio.wait_for(agents[0](query), timeout=budget),\n"
        "        asyncio.wait_for(agents[1](query), timeout=budget),\n"
        "        return_exceptions=True,\n"
        "    )\n"
        "    answers = [result for result in (first_out, second_out) if _pw_usable(result)]\n"
        "    if not answers:\n"
        f"        return {slots['floor']}(query)\n"
        "    if len(answers) == 1:\n"
        "        return answers[0]\n"
        "    try:\n"
        "        return await _pw_select(query, answers[0], answers[1])\n"
        "    except Exception:\n"
        "        return answers[0]\n"
    )


def wrap_one(src_text: str, helpers: str) -> tuple[str, dict[str, str]]:
    slots = detect_slots(src_text)
    text = inject_json(src_text)
    old = f"        return await {slots['nonfast']}(query, agents)\n"
    if text.count(old) != 1:
        raise SystemExit(f"expected 1 non-fast runner, got {text.count(old)}")
    text = text.replace(old, "        return await _pw_parallel_two(query, agents)\n", 1)
    judge = helpers.replace("return await llm_chat(", f"return await {slots['orig_llm']}(", 1)
    out = text.rstrip() + "\n\n" + judge + make_parallel(slots)
    if not out.endswith("\n"):
        out += "\n"
    return out, slots


def validate(out: str, slots: dict[str, str]) -> None:
    tree = ast.parse(out)
    names = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    needed = {
        "query",
        "_pw_parallel_two",
        "_pw_select",
        "_pw_judge_pair",
        "_pw_judge_chat",
        slots["sequential"],
        slots["floor"],
    }
    missing = sorted(needed - names)
    if missing:
        raise SystemExit(f"missing names: {missing}")
    query_fn = find_module_query(tree)
    src_query = ast.get_source_segment(out, query_fn) or ""
    if f"{slots['sequential']}(query, (" not in src_query:
        raise SystemExit("fast path lost sequential runner")
    if "_pw_parallel_two(query, agents)" not in src_query:
        raise SystemExit("non-fast path did not switch to parallel judge")
    if f"return await {slots['orig_llm']}(" not in out:
        raise SystemExit("judge does not use original llm_chat")


def main() -> int:
    helpers = extract_helpers()
    DST.mkdir(parents=True, exist_ok=True)
    rows: list[str] = []
    for path in sorted(SRC.glob("*.py")):
        raw = path.read_text(encoding="utf-8")
        try:
            out, slots = wrap_one(raw, helpers)
            validate(out, slots)
        except Exception as exc:
            print(f"FAIL {path.name}: {exc}", file=sys.stderr)
            return 1
        size = len(out.encode("utf-8"))
        if size > MAX_BYTES:
            print(f"FAIL {path.name}: {size} bytes exceeds {MAX_BYTES}", file=sys.stderr)
            return 1
        dest = DST / path.name
        dest.write_text(out, encoding="utf-8")
        rows.append(
            f"{path.name}\t{size}\t{slots['sequential']}\t{slots['nonfast']}\t{slots['orig_llm']}"
        )
        print(f"OK {path.name} {size} bytes seq={slots['sequential']} was={slots['nonfast']}")
    (DST / "manifest.tsv").write_text(
        "file\tbytes\tsequential\tnonfast_was\torig_llm\n" + "\n".join(rows) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
