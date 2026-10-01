#!/usr/bin/env python3
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
