#!/usr/bin/env python3
"""Wrap every harnyx-agents-20 pack without changing its inner structure.

Fast queries keep the original single-branch router. Non-fast queries run the
index-1 and index-2 bodies in parallel, then pick with the host pairwise judge
from miner_task_scoring.py (`_score_pairwise` / `_judge_pair`).
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

SRC = Path("/root/new1/new/harnyx-agents-20-2026-09-13T03-48-54")
DST = Path("/root/new1/new/merged1")
TEMPLATE = DST / "uid-15__uid_189__artifact_808a5843-b4dc-4b7a-adf6-6630c3d47325.py"
MAX_BYTES = 1_000_000

INDEX_ALIASES = (
    ("_MODE_SHAPE_SECONDARY_AGENT", "_MODE_SHAPE_TERTIARY_AGENT"),
    ("_SHAPE_SECONDARY_AGENT", "_SHAPE_TERTIARY_AGENT"),
    ("_ANALYTICAL_FIELD_AGENT", "_BROAD_FIELD_AGENT"),
)

_PW_INDEX2_HELPER = '''
def _pw_originally_index2(query) -> bool:
    """True when the unchanged router would pick the index-2 specialist."""
    route_fn = globals()[_CANDIDATE_ROUTE_FUNCTION]
    selected = route_fn(query)
    if selected == 2:
        return True
    names = _CANDIDATE_BRANCH_CLASS_NAMES
    return bool(names) and selected == names[-1]
'''


def extract_helpers() -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    start = text.index("# Host pairwise judge")
    end = text.index("@entrypoint(\"query\")")
    helpers = text[start:end].rstrip() + "\n"
    if "def _pw_originally_index2(" not in helpers:
        helpers = helpers.rstrip() + "\n" + _PW_INDEX2_HELPER
        if not helpers.endswith("\n"):
            helpers += "\n"
    return helpers


def inject_imports(text: str) -> str:
    lines = text.splitlines(keepends=True)
    insert_at = 0
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("def ") or stripped.startswith("async def ") or stripped.startswith("class "):
            break
        if stripped.startswith("from ") or stripped.startswith("import "):
            insert_at = i + 1
    preamble = "".join(lines[:insert_at])
    extras: list[str] = []
    if re.search(r"(?m)^import asyncio\b", preamble) is None:
        extras.append("import asyncio\n")
    if re.search(r"(?m)^import json\b", preamble) is None:
        extras.append("import json\n")
    if "llm_chat" not in preamble:
        extras.append("from harnyx_miner_sdk.api import llm_chat\n")
    if not extras:
        return text
    block = "".join(extras)
    if insert_at < len(lines) and lines[insert_at].strip():
        block += "\n"
    elif insert_at >= len(lines):
        block += "\n"
    lines[insert_at:insert_at] = [block]
    return "".join(lines)


def find_module_query(tree: ast.Module) -> ast.AsyncFunctionDef:
    found: ast.AsyncFunctionDef | None = None
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "query":
            found = node
    if found is None:
        raise SystemExit("no module-level query")
    return found


def demote_original_query(text: str) -> tuple[str, bool]:
    tree = ast.parse(text)
    query_fn = find_module_query(tree)
    start = query_fn.lineno - 1
    if query_fn.decorator_list:
        start = min(dec.lineno for dec in query_fn.decorator_list) - 1
    end = query_fn.end_lineno
    lines = text.splitlines(keepends=True)
    chunk_lines = lines[start:end]
    kept: list[str] = []
    for line in chunk_lines:
        if line.lstrip().startswith("@entrypoint"):
            continue
        kept.append(line)
    chunk = "".join(kept)
    chunk, n = re.subn(
        r"(?m)^async def query\(",
        "async def _orig_query(",
        chunk,
        count=1,
    )
    if n != 1:
        raise SystemExit("failed to rename original query")
    has_context = any(
        isinstance(arg, ast.arg) and arg.arg == "context"
        for arg in query_fn.args.args
    )
    return "".join(lines[:start]) + chunk + "".join(lines[end:]), has_context


def detect_index_agents(text: str) -> tuple[str, str]:
    for first, second in INDEX_ALIASES:
        if re.search(rf"(?m)^{re.escape(first)}\s*=", text):
            return first, second
    raise SystemExit("could not detect index1/index2 agent bindings")


def make_query(has_context: bool) -> str:
    if has_context:
        sig = "async def query(query: Query, context: ContextSnapshot) -> Response:"
        orig_call = "return await _orig_query(query, context)"
        run1 = "index1(query, context)"
        run2 = "index2(query, context)"
    else:
        sig = "async def query(query: Query) -> Response:"
        orig_call = "return await _orig_query(query)"
        run1 = "index1(query)"
        run2 = "index2(query)"
    return (
        f"@entrypoint(\"query\")\n"
        f"{sig}\n"
        f"    if getattr(query, \"fast\", False):\n"
        f"        {orig_call}\n"
        f"\n"
        f"    index1 = _PW_INDEX1\n"
        f"    index2 = _PW_INDEX2\n"
        f"    first_out, second_out = await asyncio.gather(\n"
        f"        {run1},\n"
        f"        {run2},\n"
        f"        return_exceptions=True,\n"
        f"    )\n"
        f"    if _pw_originally_index2(query):\n"
        f"        first_out, second_out = second_out, first_out\n"
        f"    answers = [result for result in (first_out, second_out) if _pw_usable(result)]\n"
        f"    if not answers:\n"
        f"        return _pw_floor()\n"
        f"    if len(answers) == 1:\n"
        f"        return answers[0]\n"
        f"    try:\n"
        f"        return await _pw_select(query, answers[0], answers[1])\n"
        f"    except Exception:\n"
        f"        return answers[0]\n"
    )


def wrap_one(src_text: str, helpers: str) -> str:
    text = inject_imports(src_text)
    text, has_context = demote_original_query(text)
    index1, index2 = detect_index_agents(text)
    aliases = f"_PW_INDEX1 = {index1}\n_PW_INDEX2 = {index2}\n"
    body = text.rstrip() + "\n\n"
    body += helpers.rstrip() + "\n\n"
    body += aliases + "\n"
    body += make_query(has_context)
    if not body.endswith("\n"):
        body += "\n"
    return body


def main() -> int:
    helpers = extract_helpers()
    DST.mkdir(parents=True, exist_ok=True)
    rows: list[str] = []
    for path in sorted(SRC.glob("*.py")):
        raw = path.read_text(encoding="utf-8")
        try:
            out = wrap_one(raw, helpers)
            ast.parse(out)
        except Exception as exc:
            print(f"FAIL {path.name}: {exc}", file=sys.stderr)
            return 1
        size = len(out.encode("utf-8"))
        if size > MAX_BYTES:
            print(f"FAIL {path.name}: {size} bytes exceeds {MAX_BYTES}", file=sys.stderr)
            return 1
        dest = DST / path.name
        dest.write_text(out, encoding="utf-8")
        family = detect_index_agents(out)[0]
        rows.append(f"{path.name}\t{size}\t{family}")
        print(f"OK {path.name} {size} bytes")
    (DST / "manifest.tsv").write_text("file\tbytes\tindex1\n" + "\n".join(rows) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
