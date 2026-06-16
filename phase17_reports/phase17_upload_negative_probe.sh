#!/usr/bin/env bash
set -u

cd ~/frappe-bench

PORT="$(python - <<'PY'
import json
from pathlib import Path
p = Path("sites/common_site_config.json")
try:
    data = json.loads(p.read_text())
    print(data.get("webserver_port") or 8000)
except Exception:
    print(8000)
PY
)"

BASE="http://127.0.0.1:${PORT}"
ENDPOINT="${BASE}/api/method/surhan_scanner.agent_api.upload_agent_scan"

python - <<'PY'
import base64
import json
from pathlib import Path

sessions = json.loads(Path("/tmp/surhan_phase17_sessions.json").read_text(encoding="utf-8"))

replay = next(x for x in sessions if x["_phase17_label"] == "REPLAY")
bad_ext = next(x for x in sessions if x["_phase17_label"] == "BAD_EXTENSION")

def make_valid_pdf():
    objects = []
    def add_obj(n, content: bytes):
        objects.append((n, content))

    stream = b"BT /F1 12 Tf 72 720 Td (Surhan Scanner Phase 17 Replay Test) Tj ET"
    add_obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    add_obj(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    add_obj(3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>")
    add_obj(4, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    add_obj(5, b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))

    pdf = bytearray()
    pdf.extend(b"%PDF-1.4\n")
    offsets = [0]

    for n, content in objects:
        offsets.append(len(pdf))
        pdf.extend(f"{n} 0 obj\n".encode())
        pdf.extend(content)
        pdf.extend(b"\nendobj\n")

    xref_pos = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        pdf.extend(f"{off:010d} 00000 n \n".encode())

    pdf.extend(b"trailer\n")
    pdf.extend(f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode())
    pdf.extend(b"startxref\n")
    pdf.extend(str(xref_pos).encode())
    pdf.extend(b"\n%%EOF\n")
    return bytes(pdf)

pdf_b64 = base64.b64encode(make_valid_pdf()).decode("ascii")
exe_b64 = base64.b64encode(b"MZ fake executable content for negative security test").decode("ascii")

payloads = {
    "fake_token": {
        "scan_token": "INVALID_PHASE17_TOKEN_SHOULD_NOT_WORK",
        "filename": "fake_token.pdf",
        "file_content": pdf_b64,
    },
    "replay_first": {
        "scan_token": replay["scan_token"],
        "filename": "phase17_replay_first.pdf",
        "file_content": pdf_b64,
    },
    "replay_second": {
        "scan_token": replay["scan_token"],
        "filename": "phase17_replay_second.pdf",
        "file_content": pdf_b64,
    },
    "bad_extension": {
        "scan_token": bad_ext["scan_token"],
        "filename": "phase17_malicious.exe",
        "file_content": exe_b64,
    },
}

for name, payload in payloads.items():
    Path(f"/tmp/surhan_phase17_{name}.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

print("PHASE17_PAYLOADS_READY")
PY

probe_post() {
  local label="$1"
  local payload="$2"

  echo "=== ${label} ==="
  curl -sS -i \
    -H "Host: ysmo" \
    -H "Accept: application/json" \
    -H "Content-Type: application/json" \
    -X POST \
    --data @"${payload}" \
    "${ENDPOINT}"
  echo
}

echo "=== Phase 17 Upload Negative Security Probe ==="
echo "BASE=${BASE}"
echo

probe_post "fake_token" "/tmp/surhan_phase17_fake_token.json"
probe_post "replay_first_should_succeed" "/tmp/surhan_phase17_replay_first.json"
probe_post "replay_second_should_fail" "/tmp/surhan_phase17_replay_second.json"
probe_post "bad_extension_should_fail" "/tmp/surhan_phase17_bad_extension.json"
