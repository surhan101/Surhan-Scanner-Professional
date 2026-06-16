import base64
import json
import os
import time
import traceback
from pathlib import Path

import frappe
import requests

SITE = "ysmo"
SITES_PATH = "sites"
APP_DIR = Path("/home/frappe/frappe-bench/apps/surhan_scanner")
REPORT_DIR = APP_DIR / "phase22_reports"
PAYLOAD_DIR = Path("/tmp/surhan_phase22_payloads")
STATE_FILE = Path("/tmp/surhan_phase22_state.json")

UPLOAD_METHOD = "surhan_scanner.agent_api.upload_agent_scan"
TARGET_DOCTYPE = "ToDo"
RULE_DOCTYPE = "Surhan Scanner Rule"
LOG_DOCTYPE = "Surhan Scanner Log"

REPORT_DIR.mkdir(parents=True, exist_ok=True)
PAYLOAD_DIR.mkdir(parents=True, exist_ok=True)

RAW_REPORT = REPORT_DIR / "phase22_upload_permutation_raw.txt"
SUMMARY_REPORT = REPORT_DIR / "phase22_upload_permutation_summary.json"
CLEANUP_REPORT = REPORT_DIR / "phase22_upload_permutation_cleanup.txt"
FINAL_REPORT = REPORT_DIR / "phase22_upload_permutation_result.txt"


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)

JPG_1X1 = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
    "2wBDAf//////////////////////////////////////////////////////////////////////////////////////"
    "wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAH/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAEFAqf/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/ASP/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/ASP/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAY/Ar//xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/IV//2gAMAwEAAgADAAAAEP/EFBQRAQAAAAAAAAAAAAAAAAAAARD/2gAIAQMBAT8QH//EFBQRAQAAAAAAAAAAAAAAAAAAARD/2gAIAQIBAT8QH//EFBABAQAAAAAAAAAAAAAAAAAAARD/2gAIAQEAAT8QH//Z"
)


def now_id():
    return time.strftime("%Y%m%d_%H%M%S")


def load_common_port():
    p = Path("/home/frappe/frappe-bench/sites/common_site_config.json")
    try:
        return json.loads(p.read_text()).get("webserver_port") or 8000
    except Exception:
        return 8000


def write_valid_pdf(path: Path, pages=1, padding_bytes=0):
    try:
        from pypdf import PdfWriter

        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=72, height=72)
        with path.open("wb") as f:
            writer.write(f)
        if padding_bytes:
            with path.open("ab") as f:
                f.write(b"\n%PHASE22_PADDING_START\n")
                f.write(b"A" * padding_bytes)
                f.write(b"\n%PHASE22_PADDING_END\n")
        return
    except Exception:
        # fallback PDF صالح بسيط
        content = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] >>
endobj
xref
0 4
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
trailer
<< /Root 1 0 R /Size 4 >>
startxref
188
%%EOF
"""
        path.write_bytes(content)


def set_if_field(doc, fieldname, value):
    try:
        if doc.meta.has_field(fieldname):
            doc.set(fieldname, value)
            return
    except Exception:
        pass

    try:
        fields = [df.fieldname for df in getattr(doc.meta, "fields", [])]
        if fieldname in fields:
            doc.set(fieldname, value)
    except Exception:
        pass


def create_target(label):
    doc = frappe.new_doc(TARGET_DOCTYPE)
    doc.description = f"PHASE22 TEST TARGET - {label}"
    doc.insert(ignore_permissions=True)
    return doc.name


def normalize_rule_file_type(file_type):
    ft = str(file_type or "Default").strip().upper()
    if ft == "PDF":
        return "PDF"
    if ft in {"JPG", "JPEG"}:
        return "JPG"
    return "Default"


def create_rule(label, file_type="PDF"):
    rule = frappe.new_doc(RULE_DOCTYPE)
    set_if_field(rule, "enabled", 1)
    set_if_field(rule, "rule_name", f"PHASE22 {label}")
    set_if_field(rule, "target_doctype", TARGET_DOCTYPE)
    set_if_field(rule, "placement_type", "Toolbar Group")
    set_if_field(rule, "upload_mode", "Attachment Only")
    set_if_field(rule, "file_type", normalize_rule_file_type(file_type))
    set_if_field(rule, "multi_page", 1)
    set_if_field(rule, "is_private", 1)
    set_if_field(rule, "folder", "Home/Attachments")
    set_if_field(rule, "resolution", 200)
    set_if_field(rule, "pixel_type", "Color")
    set_if_field(rule, "use_feeder", 0)
    set_if_field(rule, "duplex", 0)
    set_if_field(rule, "silent_scan", 0)
    set_if_field(rule, "show_preview", 0)
    set_if_field(rule, "scan_batch_mode", "Single Page")
    set_if_field(rule, "max_pages", 1)
    set_if_field(rule, "upload_strategy", "Direct Upload")
    rule.insert(ignore_permissions=True)
    return rule.name


def create_session(label, file_type="pdf"):
    from surhan_scanner.agent_api import create_scan_session

    target = create_target(label)
    rule = create_rule(label, file_type=file_type)

    session = create_scan_session(
        doctype=TARGET_DOCTYPE,
        docname=target,
        attach_field="",
        upload_mode="Attachment Only",
        rule=rule,
        is_private=1,
        folder="Home/Attachments",
        file_type=file_type,
        resolution=200,
        pixel_type="Color",
        multi_page=1,
        use_feeder=0,
        duplex=0,
        paper_source="Feeder",
        silent_scan=0,
        show_preview=0,
        scan_batch_mode="Single Page",
        max_pages=1,
        upload_strategy="Direct Upload",
        custom_file_name=f"phase22_{label}_{now_id()}",
    )

    return {
        "target": target,
        "rule": rule,
        "scan_session_id": session.get("scan_session_id"),
        "scan_token": session.get("scan_token"),
    }


def prepare_payloads():
    payloads = {}

    valid_pdf = PAYLOAD_DIR / "phase22_valid.pdf"
    write_valid_pdf(valid_pdf)
    payloads["valid_pdf"] = str(valid_pdf)

    valid_png = PAYLOAD_DIR / "phase22_valid.png"
    valid_png.write_bytes(PNG_1X1)
    payloads["valid_png"] = str(valid_png)

    valid_jpg = PAYLOAD_DIR / "phase22_valid.jpg"
    try:
        from PIL import Image
        img = Image.new("RGB", (16, 16), (255, 255, 255))
        img.save(str(valid_jpg), "JPEG")
    except Exception:
        valid_jpg.write_bytes(JPG_1X1)
    payloads["valid_jpg"] = str(valid_jpg)

    empty_pdf = PAYLOAD_DIR / "phase22_empty.pdf"
    empty_pdf.write_bytes(b"")
    payloads["empty_pdf"] = str(empty_pdf)

    corrupt_pdf = PAYLOAD_DIR / "phase22_corrupt.pdf"
    corrupt_pdf.write_bytes(b"%PDF-1.4\nthis is intentionally corrupt and has no xref\n")
    payloads["corrupt_pdf"] = str(corrupt_pdf)

    exe_file = PAYLOAD_DIR / "phase22_forbidden.exe"
    exe_file.write_bytes(b"MZ" + b"\x00" * 128)
    payloads["exe"] = str(exe_file)

    js_file = PAYLOAD_DIR / "phase22_script.js"
    js_file.write_text("alert('phase22');\n", encoding="utf-8")
    payloads["js"] = str(js_file)

    mismatch_pdf = PAYLOAD_DIR / "phase22_png_bytes_named_pdf.pdf"
    mismatch_pdf.write_bytes(PNG_1X1)
    payloads["mismatch_pdf"] = str(mismatch_pdf)

    medium_pdf = PAYLOAD_DIR / "phase22_medium_2mb.pdf"
    write_valid_pdf(medium_pdf, padding_bytes=2 * 1024 * 1024)
    payloads["medium_pdf"] = str(medium_pdf)

    return payloads


def safe_delete(doctype, name, deleted):
    if not name:
        return
    try:
        if frappe.db.exists(doctype, name):
            frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
            deleted.append((doctype, name, True))
        else:
            deleted.append((doctype, name, "already_missing"))
    except Exception as exc:
        deleted.append((doctype, name, False, str(exc)))


def cleanup_previous():
    deleted = []

    try:
        old = json.loads(STATE_FILE.read_text())
    except Exception:
        old = {}

    for case in old.get("cases", []):
        if case.get("scan_session_id"):
            for row in frappe.get_all(LOG_DOCTYPE, filters={"scan_session_id": case["scan_session_id"]}, pluck="name"):
                safe_delete(LOG_DOCTYPE, row, deleted)

    for fname in old.get("created_file_docs", []):
        safe_delete("File", fname, deleted)

    for case in old.get("cases", []):
        safe_delete(TARGET_DOCTYPE, case.get("target"), deleted)
        safe_delete(RULE_DOCTYPE, case.get("rule"), deleted)

    frappe.db.commit()
    return deleted


def delete_cache_token(token):
    try:
        import surhan_scanner.agent_api as api
        if hasattr(api, "_cache_delete"):
            api._cache_delete(token)
            return True
    except Exception:
        pass

    try:
        frappe.cache().delete_value(token)
        return True
    except Exception:
        return False


def prepare_cases():
    payloads = prepare_payloads()
    cases = []

    def add_case(label, payload_key=None, upload_filename=None, mime=None, expected="fail", token_mode="valid", file_type="pdf"):
        session = {}
        if token_mode in {"valid", "expired", "target_deleted", "rule_deleted"}:
            session = create_session(label, file_type=file_type)

            if token_mode == "expired":
                delete_cache_token(session.get("scan_token"))

            if token_mode == "target_deleted":
                safe_delete(TARGET_DOCTYPE, session.get("target"), [])

            if token_mode == "rule_deleted":
                safe_delete(RULE_DOCTYPE, session.get("rule"), [])

        case = {
            "label": label,
            "expected": expected,
            "token_mode": token_mode,
            "payload": payloads.get(payload_key) if payload_key else None,
            "upload_filename": upload_filename,
            "mime": mime,
            **session,
        }
        cases.append(case)

    add_case("missing_token", "valid_pdf", "phase22_missing_token.pdf", "application/pdf", "fail", "missing")
    add_case("fake_token", "valid_pdf", "phase22_fake_token.pdf", "application/pdf", "fail", "fake")

    add_case("valid_pdf", "valid_pdf", "phase22_valid.pdf", "application/pdf", "success", "valid", "pdf")
    add_case("png_unsupported_or_observed", "valid_png", "phase22_valid.png", "image/png", "observe", "valid", "Default")
    add_case("valid_jpg", "valid_jpg", "phase22_valid.jpg", "image/jpeg", "success", "valid", "jpg")
    add_case("arabic_filename", "valid_pdf", "مسح_تجريبي_مرحلة22.pdf", "application/pdf", "success", "valid", "pdf")
    add_case("long_filename", "valid_pdf", ("phase22_" + "x" * 120 + ".pdf"), "application/pdf", "success", "valid", "pdf")
    add_case("medium_pdf_2mb", "medium_pdf", "phase22_medium_2mb.pdf", "application/pdf", "success", "valid", "pdf")

    add_case("empty_file", "empty_pdf", "phase22_empty.pdf", "application/pdf", "fail", "valid", "pdf")
    add_case("corrupt_pdf", "corrupt_pdf", "phase22_corrupt.pdf", "application/pdf", "fail", "valid", "pdf")
    add_case("forbidden_exe", "exe", "phase22_forbidden.exe", "application/octet-stream", "fail", "valid", "pdf")
    add_case("forbidden_js", "js", "phase22_script.js", "application/javascript", "fail", "valid", "pdf")
    add_case("mime_mismatch_png_named_pdf", "mismatch_pdf", "phase22_mismatch.pdf", "application/pdf", "fail", "valid", "pdf")
    add_case("expired_token", "valid_pdf", "phase22_expired_token.pdf", "application/pdf", "fail", "expired", "pdf")
    add_case("target_deleted_before_upload", "valid_pdf", "phase22_target_deleted.pdf", "application/pdf", "fail", "target_deleted", "pdf")
    add_case("rule_deleted_after_session_observed", "valid_pdf", "phase22_rule_deleted.pdf", "application/pdf", "observe", "rule_deleted", "pdf")
    add_case("upload_without_file", None, None, None, "fail", "valid", "pdf")

    # replay: نفس التوكن مرتين
    replay_session = create_session("replay_token", file_type="pdf")
    cases.append({
        "label": "replay_first",
        "expected": "success",
        "token_mode": "valid",
        "payload": payloads["valid_pdf"],
        "upload_filename": "phase22_replay_first.pdf",
        "mime": "application/pdf",
        **replay_session,
        "_replay_group": "phase22_replay",
    })
    cases.append({
        "label": "replay_second",
        "expected": "fail",
        "token_mode": "reuse",
        "payload": payloads["valid_pdf"],
        "upload_filename": "phase22_replay_second.pdf",
        "mime": "application/pdf",
        **replay_session,
        "_replay_group": "phase22_replay",
    })

    return cases


def post_case(case, base_url):
    headers = {
        "Host": SITE,
        "Accept": "application/json",
    }

    data = {}
    if case["token_mode"] == "fake":
        data["scan_token"] = "fake-phase22-token"
    elif case["token_mode"] != "missing":
        data["scan_token"] = case.get("scan_token") or ""

    files = None
    fp = None

    try:
        if case.get("payload"):
            fp = open(case["payload"], "rb")
            files = {
                "file": (
                    case.get("upload_filename") or Path(case["payload"]).name,
                    fp,
                    case.get("mime") or "application/octet-stream",
                )
            }

        resp = requests.post(
            f"{base_url}/api/method/{UPLOAD_METHOD}",
            headers=headers,
            data=data,
            files=files,
            timeout=60,
        )

        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text[:1000]}

        msg = body.get("message") if isinstance(body, dict) else body
        if not isinstance(msg, dict):
            msg = {"raw_message": msg}

        return {
            "label": case["label"],
            "http_status": resp.status_code,
            "success": bool(msg.get("success")),
            "message": msg.get("message") or msg.get("raw_message") or "",
            "response": msg,
        }
    finally:
        if fp:
            fp.close()


def verify_and_cleanup(cases, results):
    deleted = []
    checks = []
    created_file_docs = []

    result_by_label = {r["label"]: r for r in results}

    # تحقق من ملفات وسجلات الحالات الناجحة
    for case in cases:
        r = result_by_label.get(case["label"]) or {}
        expected = case.get("expected")

        http_status = int(r.get("http_status") or 0)
        success = bool(r.get("success"))

        if expected == "success":
            ok = success and 200 <= http_status < 300
            checks.append((case["label"], "expected_success", ok, http_status, r.get("message")))
        elif expected == "fail":
            ok = (not success) and http_status in {400, 403, 404, 413}
            checks.append((case["label"], "expected_failure", ok, http_status, r.get("message")))
        else:
            checks.append((case["label"], "observed_only", True, http_status, r.get("message")))

        f = (r.get("response") or {}).get("file") or {}
        if isinstance(f, dict) and f.get("name"):
            created_file_docs.append(f["name"])

            file_exists = frappe.db.exists("File", f["name"])
            checks.append((case["label"], "file_doc_exists_after_success_response", bool(file_exists), f["name"]))

        scan_session_id = case.get("scan_session_id")
        if success and scan_session_id:
            logs = frappe.get_all(
                LOG_DOCTYPE,
                filters={"scan_session_id": scan_session_id},
                fields=["name", "status", "file_name", "file_url", "scan_session_id"],
                limit_page_length=20,
            )
            checks.append((case["label"], "scanner_log_exists", bool(logs), logs))

    # لا نسمح بأي 500 في كل الاختبارات
    for r in results:
        checks.append((r["label"], "no_http_500", r.get("http_status") != 500, r.get("http_status"), r.get("message")))

    # تنظيف logs
    for case in cases:
        if case.get("scan_session_id"):
            for row in frappe.get_all(LOG_DOCTYPE, filters={"scan_session_id": case["scan_session_id"]}, pluck="name"):
                safe_delete(LOG_DOCTYPE, row, deleted)

    # تنظيف الملفات
    for fname in created_file_docs:
        safe_delete("File", fname, deleted)

    # تنظيف targets/rules
    seen_targets = set()
    seen_rules = set()
    for case in cases:
        if case.get("target") and case["target"] not in seen_targets:
            seen_targets.add(case["target"])
            safe_delete(TARGET_DOCTYPE, case["target"], deleted)

        if case.get("rule") and case["rule"] not in seen_rules:
            seen_rules.add(case["rule"])
            safe_delete(RULE_DOCTYPE, case["rule"], deleted)

    frappe.db.commit()

    # تحقق بعد التنظيف
    remaining = {
        "todo": frappe.get_all(TARGET_DOCTYPE, filters={"description": ["like", "%PHASE22 TEST TARGET%"]}, fields=["name", "description"], limit_page_length=20),
        "rules": frappe.get_all(RULE_DOCTYPE, filters={"rule_name": ["like", "%PHASE22%"]}, fields=["name", "rule_name"], limit_page_length=20),
        "logs": [],
        "files": [],
    }

    for case in cases:
        if case.get("scan_session_id"):
            remaining["logs"].extend(frappe.get_all(LOG_DOCTYPE, filters={"scan_session_id": case["scan_session_id"]}, fields=["name", "scan_session_id"], limit_page_length=20))

    for fname in created_file_docs:
        if frappe.db.exists("File", fname):
            remaining["files"].append(fname)

    all_checks_pass = all(c[2] for c in checks)
    cleanup_ok = all(len(v) == 0 for v in remaining.values())

    return {
        "checks": checks,
        "deleted": deleted,
        "remaining": remaining,
        "created_file_docs": created_file_docs,
        "all_checks_pass": all_checks_pass,
        "cleanup_ok": cleanup_ok,
    }


def main():
    port = load_common_port()
    base_url = f"http://127.0.0.1:{port}"

    frappe.init(site=SITE, sites_path="/home/frappe/frappe-bench/sites")
    frappe.connect()
    frappe.set_user("Administrator")

    try:
        previous_cleanup = cleanup_previous()

        cases = prepare_cases()
        frappe.db.commit()

        state = {
            "site": SITE,
            "base_url": base_url,
            "cases": [
                {k: ("***REDACTED***" if k == "scan_token" and v else v) for k, v in case.items()}
                for case in cases
            ],
            "created_file_docs": [],
        }
        STATE_FILE.write_text(json.dumps({
            "site": SITE,
            "base_url": base_url,
            "cases": cases,
            "created_file_docs": [],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        results = []
        raw_lines = []
        raw_lines.append("=== Phase 22 Upload Permutation Raw Results ===")
        raw_lines.append(f"BASE_URL={base_url}")
        raw_lines.append("")

        for case in cases:
            r = post_case(case, base_url)
            results.append(r)

            raw_lines.append(f"=== {case['label']} ===")
            raw_lines.append(f"expected={case.get('expected')}")
            raw_lines.append(f"token_mode={case.get('token_mode')}")
            raw_lines.append(f"http_status={r.get('http_status')}")
            raw_lines.append(f"success={r.get('success')}")
            raw_lines.append(f"message={r.get('message')}")
            raw_lines.append(json.dumps(r.get("response"), ensure_ascii=False, indent=2))
            raw_lines.append("")

            # مهم: تأخير خفيف حتى لا نضغط السيرفر الضعيف
            time.sleep(0.25)

        verification = verify_and_cleanup(cases, results)

        STATE_FILE.write_text(json.dumps({
            "site": SITE,
            "base_url": base_url,
            "cases": cases,
            "created_file_docs": verification["created_file_docs"],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        summary = {
            "previous_cleanup": previous_cleanup,
            "results": results,
            "checks": verification["checks"],
            "remaining": verification["remaining"],
            "all_checks_pass": verification["all_checks_pass"],
            "cleanup_ok": verification["cleanup_ok"],
        }

        RAW_REPORT.write_text("\n".join(raw_lines), encoding="utf-8")
        SUMMARY_REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        CLEANUP_REPORT.write_text(
            "=== Cleanup ===\n"
            + json.dumps(verification["deleted"], ensure_ascii=False, indent=2, default=str)
            + "\n\n=== Remaining ===\n"
            + json.dumps(verification["remaining"], ensure_ascii=False, indent=2, default=str)
            + f"\n\ncleanup_ok={verification['cleanup_ok']}\n",
            encoding="utf-8",
        )

        with FINAL_REPORT.open("w", encoding="utf-8") as f:
            f.write("=== Phase 22 Upload Permutation Test Result ===\n\n")

            f.write("=== Results Summary ===\n")
            for r in results:
                f.write(
                    f"{r['label']}: http={r['http_status']} "
                    f"success={r['success']} message={r.get('message')}\n"
                )

            f.write("\n=== Checks ===\n")
            for c in verification["checks"]:
                f.write(json.dumps(c, ensure_ascii=False, default=str) + "\n")

            f.write("\n=== Cleanup ===\n")
            f.write(f"cleanup_ok={verification['cleanup_ok']}\n")

            f.write("\n=== Result ===\n")
            if verification["all_checks_pass"] and verification["cleanup_ok"]:
                f.write("PASSED\n")
            else:
                f.write("REVIEW_REQUIRED\n")

        print(FINAL_REPORT.read_text(encoding="utf-8"))

    except Exception:
        frappe.db.rollback()
        err = traceback.format_exc()
        FINAL_REPORT.write_text(
            "=== Phase 22 Upload Permutation Test Result ===\n\n"
            "=== Result ===\nREVIEW_REQUIRED\n\n"
            "=== Traceback ===\n" + err,
            encoding="utf-8",
        )
        print(FINAL_REPORT.read_text(encoding="utf-8"))
        raise
    finally:
        try:
            frappe.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    main()
