#!/usr/bin/env bash
set -u

cd ~/frappe-bench

PORT="$(python - <<'PY'
import json
from pathlib import Path
p = Path("sites/common_site_config.json")
try:
    data = json.loads(p.read_text())
    print(data.get("webserver_port") or data.get("socketio_port") or 8000)
except Exception:
    print(8000)
PY
)"

BASE="http://127.0.0.1:${PORT}"

echo "=== HTTP Guest Security Probe ==="
echo "BASE=${BASE}"
echo

probe_get() {
  local label="$1"
  local path="$2"
  echo "=== ${label} ==="
  curl -sS -i \
    -H "Host: ysmo" \
    -H "Accept: application/json" \
    "${BASE}${path}" | sed -n '1,40p'
  echo
}

probe_post() {
  local label="$1"
  local path="$2"
  local data="$3"
  echo "=== ${label} ==="
  curl -sS -i \
    -H "Host: ysmo" \
    -H "Accept: application/json" \
    -H "Content-Type: application/json" \
    -X POST \
    --data "${data}" \
    "${BASE}${path}" | sed -n '1,60p'
  echo
}

probe_get  "GET manifest no args" \
  "/api/method/surhan_scanner.agent_api.get_agent_update_manifest"

probe_post "POST report_agent_update_status empty JSON" \
  "/api/method/surhan_scanner.agent_api.report_agent_update_status" \
  '{}'

probe_post "POST agent_heartbeat empty JSON" \
  "/api/method/surhan_scanner.agent_api.agent_heartbeat" \
  '{}'

probe_post "POST upload_agent_scan empty JSON" \
  "/api/method/surhan_scanner.agent_api.upload_agent_scan" \
  '{}'
