#!/usr/bin/env python3
"""Match merged1 agents to registered SN67 hotkeys with no latest submission."""
from __future__ import annotations

import csv
import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/root/new1/new/merged1")
WALLET = "money"
NETUID = 67
SEED = 202609140638
QUERY_TAG_PREFIX = "merged1"
HARNYX_ROOT = Path("/root/turtle/harnyx")
SKIP_SCRIPT_NAMES = {
    "match_and_prepare.py",
    "record_submit_results.py",
    "build_wrap.py",
}

# Live SN67 registrations from taostats metagraph (coldkey 5GYRZNMp...,
# 2026-09-14T06:38Z) that have no Harnyx latest_submission.
REGISTERED_UNSUBMITTED = [
    {
        "hotkey_name": "hk-67-21",
        "hotkey_address": "5Fuy17yC3JYga3cZhta2ceGwkDBRsg87mhcvnK6Lin19ESsK",
        "subnet_uid": 99,
    },
    {
        "hotkey_name": "hk-67-22",
        "hotkey_address": "5CtDxfrph8mvH48Pvbjbvvj3m1prBAPEzCNdaLhepgstfNFW",
        "subnet_uid": 139,
    },
    {
        "hotkey_name": "hk-67-24",
        "hotkey_address": "5DPeLLKL4qKXL9rKH1Pzb8q5j35HM3eLWnHMVSfXYfPXVUeN",
        "subnet_uid": 8,
    },
    {
        "hotkey_name": "hk-67-25",
        "hotkey_address": "5EFWj4UjDg7o7yJhv9WAGC7AhfAHj6oED8VYdJW9qZ342w6E",
        "subnet_uid": 89,
    },
    {
        "hotkey_name": "hk-67-26",
        "hotkey_address": "5CGD4DPXwqvVBvVbWFaT9JfXRmmQCpDao9P3VEL4RzSuRUhs",
        "subnet_uid": 49,
    },
    {
        "hotkey_name": "hk-67-27",
        "hotkey_address": "5Gk3KZBrLN9MpZYMy5zhEf2m5EAEHwo1wQWZvrgbF78zjU8n",
        "subnet_uid": 93,
    },
    {
        "hotkey_name": "hk-67-28",
        "hotkey_address": "5Dk3SEN97iQzkjsQks55PB2JoNAnU9FiCdWw4dWXShdjX6M1",
        "subnet_uid": 121,
    },
]

LLM_PROVIDERS = (
    "openrouter",
    "chutes",
    "ai_gateway",
    "fireworks",
    "together",
    "anthropic",
    "groq",
)
SEARCH_PROVIDERS = (
    "parallel",
    "tavily",
    "desearch",
    "firecrawl",
    "exa",
    "serper",
    "brave",
)
MODEL_RE = re.compile(
    r"""(?x)
    ['"](
        (?:z-ai|zai|deepseek|openai|anthropic|google|meta-llama|qwen|mistralai|x-ai|moonshotai)
        /[A-Za-z0-9._-]+
    )['"]
    """
)
UID_RE = re.compile(r"(?:uid[_-]|u)(\d+)", re.I)


def agent_uids(filename: str) -> list[str]:
    found: list[str] = []
    for u in UID_RE.findall(filename):
        if u not in found:
            found.append(u)
    return found


def primary_agent_uid(filename: str) -> str:
    found = agent_uids(filename)
    return found[0] if found else ""


def extract_providers(path: Path) -> dict:
    text = path.read_text(errors="ignore")
    llm: set[str] = set()
    search: set[str] = set()
    for name in LLM_PROVIDERS:
        if re.search(rf"""['"]{re.escape(name)}['"]""", text):
            llm.add(name)
    for name in SEARCH_PROVIDERS:
        if re.search(rf"""['"]{re.escape(name)}['"]""", text):
            search.add(name)
    models = sorted(set(MODEL_RE.findall(text)))
    return {
        "llm_providers": sorted(llm),
        "search_providers": sorted(search),
        "models": models,
    }


def write_submit_script() -> None:
    script = ROOT / "submit_all.sh"
    script.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
PAR="${{1:-8}}"
ROOT="{ROOT}"
LOG="$ROOT/submit_log.txt"
: > "$LOG"
cd {HARNYX_ROOT}
set -a
# shellcheck disable=SC1091
source {HARNYX_ROOT}/.env
set +a
export PLATFORM_BASE_URL="${{PLATFORM_BASE_URL:-https://api.harnyx.ai}}"

submit_one() {{
  local hk="$1"
  local path="$2"
  echo "[START] $hk <- $(basename "$path")" | tee -a "$LOG"
  if out=$(uv run --package harnyx-miner harnyx-miner-submit \\
      --agent-path "$path" \\
      --wallet-name money \\
      --hotkey-name "$hk" 2>&1); then
    echo "$out" | tee -a "$LOG"
    echo "[OK] $hk" | tee -a "$LOG"
  else
    echo "$out" | tee -a "$LOG"
    echo "[FAIL] $hk" | tee -a "$LOG" >&2
    return 1
  fi
}}
export -f submit_one
export LOG

while IFS=$'\\t' read -r hk path; do
  [[ -z "${{hk:-}}" ]] && continue
  submit_one "$hk" "$path" &
  while (( $(jobs -rp | wc -l) >= PAR )); do
    wait -n || true
  done
done < "$ROOT/submit_jobs.txt"
wait || true
python3 "$ROOT/record_submit_results.py" || true
echo "[DONE] see $ROOT/submission_history.json and $LOG"
"""
    )
    script.chmod(0o755)
    (ROOT / "SUBMIT_COMMAND.txt").write_text(f"bash {ROOT}/submit_all.sh 8\n")
    recorder = ROOT / "record_submit_results.py"
    recorder.write_text(
        r'''#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
hist_path = ROOT / "submission_history.json"
log_path = ROOT / "submit_log.txt"
hist = json.loads(hist_path.read_text())
log = log_path.read_text() if log_path.exists() else ""

ok = set(re.findall(r"^\[OK\] (hk-67-\d+)\s*$", log, re.M))
fail = set(re.findall(r"^\[FAIL\] (hk-67-\d+)\s*$", log, re.M))
payloads = {}
for m in re.finditer(r'\{\s*"uid".*?\}', log, re.S):
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        continue
    uid = data.get("uid")
    if uid is not None:
        payloads[int(uid)] = data

now = datetime.now(timezone.utc).isoformat()
for row in hist.get("matches", []):
    hk = row["hotkey_name"]
    uid = row.get("subnet_uid")
    if hk in ok:
        row["status"] = "submitted"
        row["submitted_at"] = now
        if uid is not None and int(uid) in payloads:
            row["submit_result"] = payloads[int(uid)]
            row["submitted_at"] = payloads[int(uid)].get("submitted_at", now)
            row["artifact_id"] = payloads[int(uid)].get("artifact_id")
            row["content_hash"] = payloads[int(uid)].get("content_hash")
            if payloads[int(uid)].get("uid") is not None:
                row["subnet_uid"] = payloads[int(uid)]["uid"]
    elif hk in fail:
        row["status"] = "failed"
        row["failed_at"] = now
hist["recorded_at"] = now
hist_path.write_text(json.dumps(hist, indent=2) + "\n")
print("recorded", len(ok), "ok", len(fail), "fail")
'''
    )
    recorder.chmod(0o755)


def main() -> None:
    now = datetime.now(timezone.utc).isoformat()
    rng = random.Random(SEED)
    agents = sorted(
        p
        for p in ROOT.glob("*.py")
        if p.name not in SKIP_SCRIPT_NAMES and p.is_file()
    )
    if not agents:
        raise SystemExit(f"no agent .py files in {ROOT}")

    hotkeys = list(REGISTERED_UNSUBMITTED)
    leftover_agents = list(agents)
    leftover_hks = list(hotkeys)
    rng.shuffle(leftover_agents)
    rng.shuffle(leftover_hks)
    selected = leftover_agents[: len(leftover_hks)]
    unused_agents = [p.name for p in leftover_agents[len(leftover_hks) :]]

    matches: list[dict] = []
    used: set[str] = set()
    for agent in selected:
        skip_uids = {int(u) for u in agent_uids(agent.name) if u.isdigit()}
        chosen = None
        for hk in leftover_hks:
            if hk["hotkey_name"] in used:
                continue
            if hk["subnet_uid"] in skip_uids:
                continue
            chosen = hk
            break
        if chosen is None:
            for hk in leftover_hks:
                if hk["hotkey_name"] not in used:
                    chosen = hk
                    break
        if chosen is None:
            raise SystemExit(f"no hotkey left for {agent.name}")
        used.add(chosen["hotkey_name"])
        stamp = datetime.now(timezone.utc).isoformat()
        hk_num = chosen["hotkey_name"].replace("hk-67-", "")
        providers = extract_providers(agent)
        matches.append(
            {
                "hotkey_name": chosen["hotkey_name"],
                "hotkey_address": chosen["hotkey_address"],
                "subnet_uid": chosen["subnet_uid"],
                "wallet_name": WALLET,
                "agent_filename": agent.name,
                "agent_name": agent.name,
                "agent_path": str(agent),
                "agent_uid": primary_agent_uid(agent.name),
                "agent_uids": agent_uids(agent.name),
                "llm_providers": providers["llm_providers"],
                "search_providers": providers["search_providers"],
                "models": providers["models"],
                "providers": providers,
                "query_tag": f"{QUERY_TAG_PREFIX}-hk67{hk_num}",
                "matched_at": stamp,
                "date": stamp,
                "status": "prepared",
            }
        )

    matches.sort(key=lambda m: int(m["hotkey_name"].split("-")[-1]))
    file_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    history = {
        "batch": "new1-new-merged1",
        "created_at": now,
        "wallet_name": WALLET,
        "netuid": NETUID,
        "match_seed": SEED,
        "match_mode": "registered_unsubmitted_random",
        "agent_dir": str(ROOT),
        "source": "https://taostats.io/subnets/67/metagraph coldkey=5GYRZNMpLdJPyvzrDLLARRTwHSpZUwfCEAirXwWiAx4A9X9s",
        "unsubmitted_source": "http://127.0.0.1:5189/api/my-agents",
        "agent_count": len(agents),
        "registered_unsubmitted_count": len(hotkeys),
        "matched_count": len(matches),
        "unused_agent_count": len(unused_agents),
        "matches": matches,
        "unused_agents": unused_agents,
        "registered_unsubmitted": hotkeys,
    }
    (ROOT / "submission_history.json").write_text(json.dumps(history, indent=2) + "\n")
    (ROOT / f"submission_history_{file_stamp}.json").write_text(
        json.dumps(history, indent=2) + "\n"
    )
    (ROOT / "submit_jobs.txt").write_text(
        "".join(f"{m['hotkey_name']}\t{m['agent_path']}\n" for m in matches)
    )
    (ROOT / "hotkey_map.json").write_text(json.dumps(matches, indent=2) + "\n")
    tsv = ROOT / "hotkey_map.tsv"
    with tsv.open("w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(
            [
                "hotkey_name",
                "hotkey_address",
                "subnet_uid",
                "agent_filename",
                "agent_name",
                "agent_uid",
                "llm_providers",
                "search_providers",
                "models",
                "query_tag",
                "matched_at",
                "date",
                "status",
            ]
        )
        for m in matches:
            w.writerow(
                [
                    m["hotkey_name"],
                    m["hotkey_address"],
                    m["subnet_uid"],
                    m["agent_filename"],
                    m["agent_name"],
                    m["agent_uid"],
                    ",".join(m["llm_providers"]),
                    ",".join(m["search_providers"]),
                    ",".join(m["models"]),
                    m["query_tag"],
                    m["matched_at"],
                    m["date"],
                    m["status"],
                ]
            )
    write_submit_script()
    print(
        f"agents={len(agents)} registered_unsubmitted={len(hotkeys)} "
        f"matched={len(matches)} unused_agents={len(unused_agents)}"
    )
    for m in matches:
        print(
            f"  {m['hotkey_name']} uid={m['subnet_uid']} {m['hotkey_address']} "
            f"<- {m['agent_filename']} llm={m['llm_providers']} search={m['search_providers']}"
        )
    print(f"submit: bash {ROOT}/submit_all.sh 8")


if __name__ == "__main__":
    main()
