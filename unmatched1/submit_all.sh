#!/usr/bin/env bash
set -euo pipefail
PAR="${1:-8}"
ROOT="/root/new1/new/unmatched1"
LOG="$ROOT/submit_log.txt"
: > "$LOG"
cd /root/turtle/harnyx
set -a
# shellcheck disable=SC1091
source /root/turtle/harnyx/.env
set +a
export PLATFORM_BASE_URL="${PLATFORM_BASE_URL:-https://api.harnyx.ai}"

submit_one() {
  local hk="$1"
  local path="$2"
  echo "[START] $hk <- $(basename "$path")" | tee -a "$LOG"
  if out=$(uv run --package harnyx-miner harnyx-miner-submit \
      --agent-path "$path" \
      --wallet-name money \
      --hotkey-name "$hk" 2>&1); then
    echo "$out" | tee -a "$LOG"
    echo "[OK] $hk" | tee -a "$LOG"
  else
    echo "$out" | tee -a "$LOG"
    echo "[FAIL] $hk" | tee -a "$LOG" >&2
    return 1
  fi
}
export -f submit_one
export LOG

while IFS=$'\t' read -r hk path; do
  [[ -z "${hk:-}" ]] && continue
  submit_one "$hk" "$path" &
  while (( $(jobs -rp | wc -l) >= PAR )); do
    wait -n || true
  done
done < "$ROOT/submit_jobs.txt"
wait || true
python3 "$ROOT/record_submit_results.py" || true
echo "[DONE] see $ROOT/submission_history.json and $LOG"
