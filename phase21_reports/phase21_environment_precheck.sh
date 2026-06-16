#!/usr/bin/env bash
set -u

cd ~/frappe-bench/apps/surhan_scanner || exit 1

OUT="phase21_reports/phase21_environment_precheck.txt"

{
  echo "=== Phase 21 Environment Precheck ==="
  echo

  echo "=== Date ==="
  date
  echo

  echo "=== Git Branch ==="
  git branch --show-current
  echo

  echo "=== Git Status ==="
  git status --short
  echo

  echo "=== Last Commits ==="
  git --no-pager log --oneline --decorate -10
  echo

  echo "=== Disk Usage ==="
  df -h
  echo

  echo "=== Memory ==="
  free -h || true
  echo

  echo "=== CPU ==="
  nproc || true
  uptime || true
  echo

  echo "=== Python Compile ==="
  python -m compileall -q surhan_scanner
  if [ $? -eq 0 ]; then
    echo "PYTHON_COMPILE_OK"
  else
    echo "PYTHON_COMPILE_FAILED"
  fi
  echo

  echo "=== Pycache After Compile ==="
  find surhan_scanner -type d -name "__pycache__" -print
  find surhan_scanner -type f \( -name "*.pyc" -o -name "*.pyo" \) -print
  echo

  echo "=== Agent Release Files ==="
  ls -lh surhan_scanner/public/agent/releases/SurhanScannerAgent-v1.0.2.zip
  ls -lh surhan_scanner/public/agent/update_manifest.json
  ls -lh surhan_scanner/public/agent/version.json
  echo

  echo "=== Agent Manifest ==="
  python - <<'PY'
import json
from pathlib import Path

p = Path("surhan_scanner/public/agent/update_manifest.json")
data = json.loads(p.read_text(encoding="utf-8"))

for k in [
    "latest_version",
    "package_filename",
    "package_sha256",
    "installer_type",
    "requires_admin",
    "deployment_mode",
    "package_type",
    "windows_service_installer",
]:
    print(f"{k}={data.get(k)}")
PY
  echo

  echo "=== Whitelisted API Inventory ==="
  grep -R -n "@frappe.whitelist" surhan_scanner | sed -n '1,120p'
  echo

  echo "=== Public Agent Assets ==="
  find surhan_scanner/public/agent -maxdepth 4 -type f -printf "%p | %s bytes\n" | sort
  echo

  echo "=== Report Folders ==="
  find . -maxdepth 1 -type d -name "phase*_reports" | sort
  echo

  echo "=== Result ==="
  if [ "$(git branch --show-current)" = "testing/phase-21-comprehensive-system-test-plan" ] \
     && grep -q '"latest_version": "1.0.2"' surhan_scanner/public/agent/update_manifest.json \
     && grep -q '"installer_type": "runtime_zip"' surhan_scanner/public/agent/update_manifest.json \
     && grep -q '"windows_service_installer": false' surhan_scanner/public/agent/update_manifest.json; then
    echo "PASSED"
  else
    echo "REVIEW_REQUIRED"
  fi
} > "$OUT"

# تنظيف pycache بعد compileall
find surhan_scanner -type d -name "__pycache__" -prune -exec rm -rf {} +
find surhan_scanner -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete

cat "$OUT"
