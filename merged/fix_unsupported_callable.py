#!/usr/bin/env python3
"""Unroll dynamic agent calls into literal names. No globals(), no global stmt."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path("/root/new1/new/merged")


def tuple_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Tuple):
        return [elt.id for elt in node.elts if isinstance(elt, ast.Name)]
    return []


def call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Await):
        node = node.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id
    return None


def unwrap_call(node: ast.AST) -> ast.Call | None:
    if isinstance(node, ast.Await):
        node = node.value
    return node if isinstance(node, ast.Call) else None


def module_query(tree: ast.Module) -> ast.AsyncFunctionDef:
    found = None
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "query":
            found = node
    if found is None:
        raise SystemExit("no module-level query")
    return found


def parse_query(fn: ast.AsyncFunctionDef) -> dict:
    state = None
    router = None
    floor = None
    seq = None
    fast: list[str] = []
    routes: dict[int, list[str]] = {}
    else_route: list[str] = []
    for stmt in fn.body:
        if isinstance(stmt, ast.Assign) and stmt.targets:
            t = stmt.targets[0]
            if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name):
                state = t.value.id
    try_node = None
    for stmt in fn.body:
        if isinstance(stmt, ast.Try):
            try_node = stmt
            break
    if try_node is None:
        raise SystemExit("query has no try")
    for stmt in try_node.handlers[0].body if try_node.handlers else []:
        if isinstance(stmt, ast.Return):
            floor = call_name(stmt.value)
    for stmt in try_node.body:
        if isinstance(stmt, ast.If) and isinstance(stmt.test, ast.Call):
            func = stmt.test.func
            if isinstance(func, ast.Name) and func.id == "getattr":
                ret = stmt.body[0]
                if isinstance(ret, ast.Return):
                    call = unwrap_call(ret.value)
                    if call is not None:
                        seq = call_name(call)
                        if call.args:
                            fast = tuple_names(call.args[-1])
        if isinstance(stmt, ast.Assign) and stmt.targets:
            tgt = stmt.targets[0]
            if isinstance(tgt, ast.Name) and tgt.id == "index":
                router = call_name(stmt.value)
        if not isinstance(stmt, ast.If):
            continue
        test = stmt.test
        if not (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "index"
        ):
            continue
        chain: list[ast.If] = []
        cur: ast.stmt | None = stmt
        while isinstance(cur, ast.If):
            chain.append(cur)
            if len(cur.orelse) == 1 and isinstance(cur.orelse[0], ast.If):
                cur = cur.orelse[0]
            else:
                break
        for br in chain:
            t = br.test
            if not (
                isinstance(t, ast.Compare)
                and isinstance(t.left, ast.Name)
                and t.left.id == "index"
                and t.ops
                and isinstance(t.ops[0], ast.Eq)
                and isinstance(t.comparators[0], ast.Constant)
            ):
                continue
            k = int(t.comparators[0].value)
            for inner in br.body:
                if (
                    isinstance(inner, ast.Assign)
                    and isinstance(inner.targets[0], ast.Name)
                    and inner.targets[0].id == "agents"
                ):
                    routes[k] = tuple_names(inner.value)
        last = chain[-1]
        for inner in last.orelse:
            if (
                isinstance(inner, ast.Assign)
                and isinstance(inner.targets[0], ast.Name)
                and inner.targets[0].id == "agents"
            ):
                else_route = tuple_names(inner.value)
    deco = fn.lineno
    if fn.decorator_list:
        deco = min(d.lineno for d in fn.decorator_list)
    if not routes:
        raise SystemExit("no routes")
    return {
        "state": state,
        "router": router,
        "floor": floor,
        "seq": seq,
        "fast": fast,
        "routes": routes,
        "else_route": else_route or routes[0],
        "start": deco,
        "end": fn.end_lineno,
    }


def parse_pw(fn: ast.AsyncFunctionDef) -> dict:
    remaining = None
    cutoff = None
    floor = None
    for node in fn.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "remaining"
        ):
            remaining = call_name(node.value)
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and isinstance(node.test.comparators[0], ast.Name)
            and node.test.comparators[0].id == "budget"
        ):
            cutoff = node.test.left.id
        if isinstance(node, ast.If) and node.body:
            ret = node.body[0]
            if isinstance(ret, ast.Return):
                name = call_name(ret.value)
                if name:
                    floor = name
    return {
        "remaining": remaining,
        "cutoff": cutoff,
        "floor": floor,
        "start": fn.lineno,
        "end": fn.end_lineno,
    }


def race_block(first: str, second: str, indent: str) -> str:
    return (
        f"{indent}first_out, second_out = await asyncio.gather(\n"
        f"{indent}    asyncio.wait_for({first}(query), timeout=budget),\n"
        f"{indent}    asyncio.wait_for({second}(query), timeout=budget),\n"
        f"{indent}    return_exceptions=True,\n"
        f"{indent})\n"
        f"{indent}return await _pw_parallel_two(query, first_out, second_out)\n"
    )


def render_query(info: dict, pw: dict) -> str:
    floor = info["floor"] or pw["floor"]
    fast = info["fast"] or info["routes"][0]
    else_route = info["else_route"]
    lines = [
        "@entrypoint('query')",
        "async def query(query: Query) -> Response:",
        f"    {info['state']}['started'] = time.monotonic()",
        "    try:",
        f"        remaining = {pw['remaining']}()",
        "        reserve = _PW_JUDGE_TIMEOUT_S + 6.0",
        "        budget = remaining - reserve",
        f"        if {pw['cutoff']} < budget:",
        f"            budget = {pw['cutoff']}",
        "        if budget <= 0.0:",
        f"            return {floor}(query)",
        "        if getattr(query, 'fast', False):",
    ]
    src = "\n".join(lines) + "\n"
    src += race_block(fast[0], fast[1] if len(fast) > 1 else fast[0], "            ")
    src += f"        index = {info['router']}(query)\n"
    for i, k in enumerate(sorted(info["routes"])):
        names = info["routes"][k]
        src += f"        {'if' if i == 0 else 'elif'} index == {k}:\n"
        src += race_block(names[0], names[1] if len(names) > 1 else names[0], "            ")
    src += "        else:\n"
    src += race_block(else_route[0], else_route[1] if len(else_route) > 1 else else_route[0], "            ")
    src += "    except Exception:\n"
    src += f"        return {floor}(query)\n"
    return src


def render_pw(pw: dict) -> str:
    floor = pw["floor"]
    return (
        "async def _pw_parallel_two(query: Query, first_out, second_out) -> Response:\n"
        '    """Host-pairwise pick after two named agents already ran."""\n'
        "    answers = [result for result in (first_out, second_out) if _pw_usable(result)]\n"
        "    if not answers:\n"
        f"        return {floor}(query)\n"
        "    if len(answers) == 1:\n"
        "        return answers[0]\n"
        "    try:\n"
        "        return await _pw_select(query, answers[0], answers[1])\n"
        "    except Exception:\n"
        "        return answers[0]\n"
    )


def render_seq(seq: ast.AsyncFunctionDef, names: list[str], floor: str) -> str:
    total = cutoff = min_next = None
    for node in ast.walk(seq):
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Sub)
            and isinstance(node.left, ast.Name)
            and isinstance(node.right, ast.Call)
        ):
            total = node.left.id
        if isinstance(node, ast.IfExp) and isinstance(node.test, ast.Compare):
            if isinstance(node.test.left, ast.Name):
                cutoff = node.test.left.id
        if (
            isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Name)
            and node.ops
            and isinstance(node.ops[0], ast.Lt)
            and isinstance(node.comparators[0], ast.Name)
            and node.comparators[0].id != "budget"
        ):
            min_next = node.comparators[0].id
    if not (total and cutoff and min_next and names):
        return (
            f"async def {seq.name}(query: Query, agents: tuple) -> Response:\n"
            f"    return {floor}(query)\n"
        )
    body = [
        f"async def {seq.name}(query: Query, agents: tuple) -> Response:",
        "    started = time.monotonic()",
        "    first = True",
    ]
    for name in names:
        body += [
            f"    remaining = {total} - (time.monotonic() - started)",
            "    if first:",
            f"        budget = {cutoff} if {cutoff} < remaining else remaining",
            "        first = False",
            "    else:",
            f"        if remaining < {min_next}:",
            f"            return {floor}(query)",
            "        budget = remaining - 5.0",
            "    if budget <= 0.0:",
            f"        return {floor}(query)",
            "    try:",
            f"        return await asyncio.wait_for({name}(query), timeout=budget)",
            "    except Exception:",
            "        pass",
        ]
    body.append(f"    return {floor}(query)")
    return "\n".join(body) + "\n"


def replace_span(lines: list[str], start: int, end: int, new: str) -> list[str]:
    block = new if new.endswith("\n") else new + "\n"
    return lines[: start - 1] + [block] + lines[end:]


def leftover(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            hits.append(f"L{node.lineno}:global")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "globals":
            hits.append(f"L{node.lineno}:globals()")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Subscript):
            hits.append(f"L{node.lineno}:subscript_call")
    src = path.read_text()
    if "agents[0](" in src or "agents[1](" in src:
        hits.append("agents[](")
    if "agent(query)" in src:
        hits.append("agent(query)")
    return hits


def patch_file(path: Path) -> None:
    text = path.read_text()
    tree = ast.parse(text)
    qn = module_query(tree)
    info = parse_query(qn)
    pw_fn = None
    seq_fn = None
    helpers = []
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_pw_parallel_two":
            pw_fn = node
        if info["seq"] and isinstance(node, ast.AsyncFunctionDef) and node.name == info["seq"]:
            seq_fn = node
        if isinstance(node, ast.AsyncFunctionDef):
            args = [a.arg for a in node.args.args]
            if "agent" in args and node.name not in {"query"}:
                helpers.append(node)
    if pw_fn is None:
        raise SystemExit(f"{path.name}: no _pw_parallel_two")
    pw = parse_pw(pw_fn)
    if not pw["remaining"] or not pw["cutoff"] or not pw["floor"]:
        raise SystemExit(f"{path.name}: bad pw parse {pw}")
    if not info["fast"]:
        raise SystemExit(f"{path.name}: no fast names")
    reps: list[tuple[int, int, str]] = [
        (pw["start"], pw["end"], render_pw(pw)),
        (info["start"], info["end"], render_query(info, pw)),
    ]
    if seq_fn is not None:
        reps.append(
            (
                seq_fn.lineno,
                seq_fn.end_lineno,
                render_seq(seq_fn, info["fast"], info["floor"] or pw["floor"]),
            )
        )
    for h in helpers:
        reps.append(
            (
                h.lineno,
                h.end_lineno,
                f"async def {h.name}(agent, query, budget):\n    return None\n",
            )
        )
    lines = text.splitlines(keepends=True)
    for start, end, new in sorted(reps, key=lambda r: r[0], reverse=True):
        lines = replace_span(lines, start, end, new)
    path.write_text("".join(lines))
    ast.parse(path.read_text())
    print(
        f"{path.name}: fast={info['fast'][:2]} routes={sorted(info['routes'])} "
        f"remain={pw['remaining']} leftover={leftover(path)}"
    )


def main() -> None:
    for path in sorted(ROOT.glob("uid-*.py")):
        patch_file(path)


if __name__ == "__main__":
    main()
