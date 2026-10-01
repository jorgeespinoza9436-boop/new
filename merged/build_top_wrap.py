#!/usr/bin/env python3
"""Upgrade each harnyx-agents-17 combine with the top.py host-accept / pairwise shell.

Extracts the research factories from each obfuscated BUILDJ pack, maps them to
A/B/C/D from the source route, and wraps them in new1/new/top.py's gateway
failover, concurrent race, schema clamp, floor, and host pairwise judge.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SRC = Path("/root/new1/new/harnyx-agents-17-2026-09-13T03-50-45")
DST = Path("/root/new1/new/merged")
WRAP = Path("/root/new1/new/top.py")
MANIFEST = DST / "manifest.json"
MAX_BYTES = 1_000_000

VERSION_RE = re.compile(
    r"""(?:VERSION|_W\d+_VERSION)\s*=\s*['\"]([^'\"]+)['\"]"""
)


def split_wrap(text: str) -> tuple[str, str]:
    pre_mark = "\ndef _r4_fac_a():\n"
    post_mark = "\n_r4_agent_d = _r4_fac_d()\n"
    pre, rest = text.split(pre_mark, 1)
    _, post = rest.split(post_mark, 1)
    return pre, post


def source_slice(lines: list[str], node: ast.AST) -> str:
    start = node.lineno - 1
    if getattr(node, "decorator_list", None):
        start = min(d.lineno for d in node.decorator_list) - 1
    end = node.end_lineno
    return "".join(lines[start:end]).rstrip() + "\n"


def tuple_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Tuple):
        return [elt.id for elt in node.elts if isinstance(elt, ast.Name)]
    if isinstance(node, ast.Name):
        return [node.id]
    return []


def call_func_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id
    return None


def find_entrypoint(tree: ast.Module) -> ast.AsyncFunctionDef:
    found: ast.AsyncFunctionDef | None = None
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "query":
            found = node
    if found is None:
        raise SystemExit("no module-level query entrypoint")
    return found


def route_slots(query_fn: ast.AsyncFunctionDef) -> dict[str, list[str]]:
    slots: dict[str, list[str]] = {}
    for node in ast.walk(query_fn):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        names: list[str] | None = None
        key: str | None = None
        if (
            isinstance(test, ast.Call)
            and isinstance(test.func, ast.Name)
            and test.func.id == "getattr"
            and len(test.args) >= 2
            and isinstance(test.args[1], ast.Constant)
            and test.args[1].value == "fast"
        ):
            key = "fast"
        elif (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "index"
            and test.ops
            and isinstance(test.ops[0], ast.Eq)
            and test.comparators
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value in (0, 1, 2)
        ):
            key = f"i{test.comparators[0].value}"
        if key is None:
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "agents" for t in stmt.targets
            ):
                names = tuple_names(stmt.value)
            elif isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Await):
                call = stmt.value.value
                if isinstance(call, ast.Call) and len(call.args) >= 2:
                    names = tuple_names(call.args[1])
        if names:
            slots[key] = names
    if "fast" not in slots or "i0" not in slots or "i2" not in slots:
        raise SystemExit(f"incomplete route slots: {sorted(slots)}")
    return slots


def factory_map(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }


def agent_factories(tree: ast.Module, agents: list[str]) -> dict[str, str]:
    binding: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in agents:
            continue
        func = call_func_name(node.value)
        if func is None:
            raise SystemExit(f"{target.id} is not a factory() call")
        binding[target.id] = func
    missing = [name for name in agents if name not in binding]
    if missing:
        raise SystemExit(f"unbound agents: {missing}")
    return binding


def rename_factory(src: str, old: str, new: str) -> str:
    prefix = f"def {old}("
    if not src.startswith(prefix):
        raise SystemExit(f"factory {old} does not start with def")
    return f"def {new}(" + src[len(prefix) :]


def versions_of(src: str) -> list[str]:
    found: list[str] = []
    for match in VERSION_RE.finditer(src):
        value = match.group(1)
        if value not in found:
            found.append(value)
    return found


def slot_plan(slots: dict[str, list[str]]) -> dict[str, str]:
    a_name, b_name = slots["i0"][0], slots["i0"][1]
    c_name = slots["fast"][0]
    if c_name != slots["i2"][0]:
        raise SystemExit(
            f"fast lead {c_name} != index-2 lead {slots['i2'][0]}"
        )
    d_name = (
        slots["i2"][1]
        if slots["i2"][1] not in {a_name, b_name, c_name}
        else a_name
    )
    return {"a": a_name, "b": b_name, "c": c_name, "d": d_name}


def build_one(path: Path, pre: str, post: str) -> tuple[str, dict]:
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines(keepends=True)
    tree = ast.parse(raw, filename=str(path))
    slots = route_slots(find_entrypoint(tree))
    plan = slot_plan(slots)
    unique_agents = list(dict.fromkeys(plan.values()))
    bindings = agent_factories(tree, unique_agents)
    factories = factory_map(tree)
    fac_names = {slot: bindings[agent] for slot, agent in plan.items()}
    for name in fac_names.values():
        if name not in factories:
            raise SystemExit(f"{path.name}: missing factory {name}")

    pieces = [pre.rstrip(), ""]
    used: dict[str, str] = {}
    slot_meta: dict[str, dict] = {}
    for slot in ("a", "b", "c", "d"):
        old = fac_names[slot]
        new = f"_r4_fac_{slot}"
        if old in used:
            pieces.append(f"{new} = {used[old]}")
            slot_meta[slot] = {
                "factory": used[old],
                "alias_of": used[old].rsplit("_", 1)[-1],
                "source_agent": plan[slot],
                "source_factory": old,
                "versions": slot_meta[used[old].rsplit("_", 1)[-1]]["versions"],
            }
        else:
            src = rename_factory(source_slice(lines, factories[old]), old, new)
            pieces.append(src.rstrip())
            used[old] = new
            slot_meta[slot] = {
                "factory": new,
                "alias_of": None,
                "source_agent": plan[slot],
                "source_factory": old,
                "versions": versions_of(src),
            }
        pieces.append(f"_r4_agent_{slot} = {new}()")
        pieces.append("")

    pieces.append(post.lstrip("\n") if post.startswith("\n") else post)
    text = "\n".join(pieces)
    if not text.endswith("\n"):
        text += "\n"
    meta = {
        "source": path.name,
        "slots": slot_meta,
        "distinct_factories": len(used),
        "route": {key: value[:2] for key, value in slots.items()},
    }
    return text, meta


def validate(text: str, name: str) -> None:
    tree = ast.parse(text, filename=name)
    queries = [
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "query"
    ]
    if len(queries) != 1:
        raise SystemExit(f"{name}: expected 1 module-level query, got {len(queries)}")
    src = ast.get_source_segment(text, queries[0]) or ""
    for needle in ("_r4_dispatch", "_r5_select", "_r4_floor", "_r4_agent_c", "_r4_agent_a"):
        if needle not in src:
            raise SystemExit(f"{name}: entrypoint missing {needle}")
    if "_BUILDJ_TAG" in text:
        raise SystemExit(f"{name}: leftover BUILDJ tag")
    if "_r5_gateway_call" not in text:
        raise SystemExit(f"{name}: missing gateway wrap")


def main() -> None:
    DST.mkdir(parents=True, exist_ok=True)
    pre, post = split_wrap(WRAP.read_text(encoding="utf-8"))
    rows: list[dict] = []
    for path in sorted(SRC.glob("*.py")):
        text, meta = build_one(path, pre, post)
        validate(text, path.name)
        dest = DST / path.name
        dest.write_text(text, encoding="utf-8")
        size = dest.stat().st_size
        if size > MAX_BYTES:
            dest.unlink()
            raise SystemExit(f"{path.name}: {size} bytes exceeds {MAX_BYTES}")
        meta.update(
            {
                "output": dest.name,
                "lines": text.count("\n"),
                "bytes": size,
            }
        )
        rows.append(meta)
        print(
            f"wrote {dest.name}  lines={meta['lines']}  "
            f"bytes={size}  factories={meta['distinct_factories']}"
        )

    payload = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source": str(SRC),
        "wrap": str(WRAP),
        "count": len(rows),
        "four_factory": sum(1 for row in rows if row["distinct_factories"] == 4),
        "three_factory": sum(1 for row in rows if row["distinct_factories"] == 3),
        "agents": rows,
    }
    MANIFEST.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"done {len(rows)} agents -> {DST}  "
        f"4fac={payload['four_factory']} 3fac={payload['three_factory']}"
    )


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        raise
