#!/usr/bin/env python3
"""Unroll validator-illegal getattr/globals/dynamic calls. Keep named races."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path("/root/new1/new/merged1")
SKIP = {
    "match_and_prepare.py",
    "record_submit_results.py",
    "build_wrap.py",
    "fix_validator_syntax.py",
}

GETATTR_OLD = """        for attr in ("raw_text", "output_text", "text"):
            value = getattr(resp, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
"""
GETATTR_NEW = """        value = getattr(resp, "raw_text", None)
        if isinstance(value, str) and value.strip():
            return value.strip()
        value = getattr(resp, "output_text", None)
        if isinstance(value, str) and value.strip():
            return value.strip()
        value = getattr(resp, "text", None)
        if isinstance(value, str) and value.strip():
            return value.strip()
"""

GLOBALS_RE = re.compile(
    r"    route_fn = globals\(\)\[_CANDIDATE_ROUTE_FUNCTION\]\n"
    r"    selected = route_fn\(query\)\n"
)
INDEX_RE = re.compile(
    r"    index1 = _PW_INDEX1\n"
    r"    index2 = _PW_INDEX2\n"
    r"    first_out, second_out = await asyncio\.gather\(\n"
    r"        index1\((query(?:, context)?)\)\,\n"
    r"        index2\(\1\),\n"
    r"        return_exceptions=True,\n"
    r"    \)\n"
)
PW_INDEX_RE = re.compile(r"^(_PW_INDEX[12]) = ([A-Za-z_][A-Za-z0-9_]*)\s*$", re.M)
ROUTE_RE = re.compile(r'^_CANDIDATE_ROUTE_FUNCTION = "([^"]+)"\s*$', re.M)
BRANCH_QUERY_RE = re.compile(
    r"    if selected == \"([^\"]+)\":\n"
    r"        branch = (_STRUCTURED_FIELD_AGENT)\n"
    r"    elif selected == \"([^\"]+)\":\n"
    r"        branch = (_ANALYTICAL_FIELD_AGENT)\n"
    r"    else:\n"
    r"        branch = (_BROAD_FIELD_AGENT)\n"
    r"    return await branch\(query\)\n"
)
BRANCH_CONTEXT_RE = re.compile(
    r"    if route_index == 0:\n"
    r"        branch = (_MODE_SHAPE_PRIMARY_AGENT)\n"
    r"    elif route_index == 1:\n"
    r"        branch = (_MODE_SHAPE_SECONDARY_AGENT)\n"
    r"    else:\n"
    r"        branch = (_MODE_SHAPE_TERTIARY_AGENT)\n"
    r"    return await branch\(query, context\)\n"
)


def leftover(text: str) -> list[str]:
    hits: list[str] = []
    if "getattr(resp, attr" in text or 'getattr(resp, attr' in text:
        hits.append("dynamic_getattr")
    if "globals()" in text:
        hits.append("globals()")
    if re.search(r"(?m)^\s*global ", text):
        hits.append("global")
    if "index1(query" in text or "index2(query" in text:
        hits.append("index_var_call")
    if "await branch(" in text:
        hits.append("branch_call")
    if "route_fn(" in text:
        hits.append("route_fn")
    return hits


def patch(path: Path) -> dict:
    text = path.read_text()
    n_getattr = text.count(GETATTR_OLD)
    if n_getattr != 1:
        raise SystemExit(f"{path.name}: getattr block count={n_getattr}")
    text = text.replace(GETATTR_OLD, GETATTR_NEW, 1)

    route = ROUTE_RE.search(text)
    if route is None:
        raise SystemExit(f"{path.name}: no _CANDIDATE_ROUTE_FUNCTION")
    route_name = route.group(1)
    text, n_glob = GLOBALS_RE.subn(f"    selected = {route_name}(query)\n", text, count=1)
    if n_glob != 1:
        raise SystemExit(f"{path.name}: globals() replace count={n_glob}")

    idx = dict(PW_INDEX_RE.findall(text))
    if "_PW_INDEX1" not in idx or "_PW_INDEX2" not in idx:
        raise SystemExit(f"{path.name}: missing _PW_INDEX bindings {idx}")
    a1, a2 = idx["_PW_INDEX1"], idx["_PW_INDEX2"]

    def index_sub(match: re.Match) -> str:
        args = match.group(1)
        return (
            f"    first_out, second_out = await asyncio.gather(\n"
            f"        {a1}({args}),\n"
            f"        {a2}({args}),\n"
            f"        return_exceptions=True,\n"
            f"    )\n"
        )

    text, n_idx = INDEX_RE.subn(index_sub, text, count=1)
    if n_idx != 1:
        raise SystemExit(f"{path.name}: index gather replace count={n_idx}")

    n_bq = n_bc = 0
    def bq(m: re.Match) -> str:
        return (
            f'    if selected == "{m.group(1)}":\n'
            f"        return await {m.group(2)}(query)\n"
            f'    if selected == "{m.group(3)}":\n'
            f"        return await {m.group(4)}(query)\n"
            f"    return await {m.group(5)}(query)\n"
        )

    def bc(m: re.Match) -> str:
        return (
            f"    if route_index == 0:\n"
            f"        return await {m.group(1)}(query, context)\n"
            f"    if route_index == 1:\n"
            f"        return await {m.group(2)}(query, context)\n"
            f"    return await {m.group(3)}(query, context)\n"
        )

    text, n_bq = BRANCH_QUERY_RE.subn(bq, text, count=1)
    text, n_bc = BRANCH_CONTEXT_RE.subn(bc, text, count=1)
    ast.parse(text)
    hits = leftover(text)
    path.write_text(text)
    return {
        "file": path.name,
        "route": route_name,
        "agents": [a1, a2],
        "branch_query": n_bq,
        "branch_context": n_bc,
        "leftover": hits,
    }


def main() -> None:
    files = sorted(
        p for p in ROOT.glob("uid-*.py") if p.name not in SKIP and p.is_file()
    )
    if not files:
        raise SystemExit("no agents")
    bad = []
    for path in files:
        info = patch(path)
        print(
            f"{info['file']} route={info['route']} "
            f"race={info['agents']} bq={info['branch_query']} "
            f"bc={info['branch_context']} leftover={info['leftover']}"
        )
        if info["leftover"]:
            bad.append(path.name)
    if bad:
        raise SystemExit(f"leftover in {bad}")
    print(f"patched {len(files)} agents")


if __name__ == "__main__":
    main()
