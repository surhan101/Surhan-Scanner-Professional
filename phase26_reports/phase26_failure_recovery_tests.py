import json
import subprocess
import time
import traceback
from pathlib import Path

import frappe
import requests

SITE = "ysmo"
BENCH = Path("/home/frappe/frappe-bench")
APP_DIR = BENCH / "apps/surhan_scanner"
REPORT_DIR = APP_DIR / "phase26_reports"
PAYLOAD_DIR = Path("/tmp/surhan_phase26_payloads")

REPORT_DIR.mkdir(parents=True, exist_ok=True)
PAYLOAD_DIR.mkdir(parents=True, exist_ok=True)

RAW_REPORT = REPORT_DIR / "phase26_failure_recovery_raw.txt"
SUMMARY_REPORT = REPORT_DIR / "phase26_failure_recovery_summary.json"
CLEANUP_REPORT = REPORT_DIR / "phase26_failure_recovery_cleanup.txt"
FINAL_REPORT = REPORT_DIR / "phase26_failure_recovery_result.txt"

PREFIX = "PHASE26"
TARGET_DOCTYPE = "ToDo"
RULE_DOCTYPE = "Surhan Scanner Rule"
LOG_DOCTYPE = "Surhan Scanner Log"
UPLOAD_METHOD = "surhan_scanner.agent_api.upload_agent_scan"


def get_port():
    try:
        return json.loads((BENCH / "sites/common_site_config.json").read_text()).get("webserver_port") or 8000
    except Exception:
        return 8000


def base_url():
    return f"http://127.0.0.1:{get_port()}"


def headers():
    return {
        "Host": SITE,
        "Accept": "application/json",
    }


def response_message(resp):
    try:
        data = resp.json()
    except Exception:
        return {"raw": resp.text[:1000]}

    if isinstance(data, dict) and isinstance(data.get("message"), dict):
        return data["message"]

    return data


def msg_success(result):
    msg = result.get("message")
    return isinstance(msg, dict) and bool(msg.get("success"))


def msg_text(result):
    msg = result.get("message")
    if isinstance(msg, dict):
        return str(msg.get("message") or msg)
    return str(msg)


def no_500(result):
    return int(result.get("http_status") or 0) != 500


def http_get(method, params=None, timeout=60):
    try:
        resp = requests.get(
            f"{base_url()}/api/method/{method}",
            headers=headers(),
            params=params or {},
            timeout=timeout,
        )
        return {
            "kind": "http",
            "http_status": resp.status_code,
            "message": response_message(resp),
        }
    except Exception as exc:
        return {
            "kind": "exception",
            "http_status": None,
            "error": type(exc).__name__,
            "message": str(exc),
        }


def http_post(method, data=None, files=None, timeout=60):
    try:
        resp = requests.post(
            f"{base_url()}/api/method/{method}",
            headers=headers(),
            data=data or {},
            files=files,
            timeout=timeout,
        )
        return {
            "kind": "http",
            "http_status": resp.status_code,
            "message": response_message(resp),
        }
    except Exception as exc:
        return {
            "kind": "exception",
            "http_status": None,
            "error": type(exc).__name__,
            "message": str(exc),
        }


def set_if_field(doc, fieldname, value):
    try:
        if doc.meta.has_field(fieldname):
            doc.set(fieldname, value)
            return
    except Exception:
        pass

    try:
        if fieldname in [df.fieldname for df in getattr(doc.meta, "fields", [])]:
            doc.set(fieldname, value)
    except Exception:
        pass


def normalize_rule_file_type(file_type):
    ft = str(file_type or "Default").strip().upper()
    if ft == "PDF":
        return "PDF"
    if ft in {"JPG", "JPEG"}:
        return "JPG"
    return "Default"


def write_valid_pdf(path: Path):
    try:
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        with path.open("wb") as f:
            writer.write(f)
    except Exception:
        path.write_bytes(
            b"""%PDF-1.4
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
        )


def write_corrupt_pdf(path: Path):
    path.write_bytes(b"%PDF-1.4\n% corrupted phase26 file without eof\n")


def create_target(label):
    doc = frappe.new_doc(TARGET_DOCTYPE)
    doc.description = f"{PREFIX} TEST TARGET - {label}"
    doc.insert(ignore_permissions=True)
    return doc.name


def create_rule(label, file_type="PDF"):
    rule = frappe.new_doc(RULE_DOCTYPE)

    set_if_field(rule, "enabled", 1)
    set_if_field(rule, "rule_name", f"{PREFIX} {label}")
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


def create_session(label, custom_file_name=None):
    from surhan_scanner.agent_api import create_scan_session

    target = create_target(label)
    rule = create_rule(label)

    session = create_scan_session(
        doctype=TARGET_DOCTYPE,
        docname=target,
        attach_field="",
        upload_mode="Attachment Only",
        rule=rule,
        is_private=1,
        folder="Home/Attachments",
        file_type="pdf",
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
        custom_file_name=custom_file_name or f"phase26_{label}_{int(time.time())}",
    )

    return {
        "label": label,
        "target": target,
        "rule": rule,
        "scan_session_id": session.get("scan_session_id"),
        "scan_token": session.get("scan_token"),
    }


def upload_file(scan_token, path, upload_filename, mime_type="application/pdf"):
    with open(path, "rb") as fp:
        files = {
            "file": (upload_filename, fp, mime_type)
        }
        return http_post(
            UPLOAD_METHOD,
            data={"scan_token": scan_token},
            files=files,
            timeout=90,
        )


def safe_delete(dt, name, deleted):
    try:
        if name and frappe.db.exists(dt, name):
            frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
            deleted.append((dt, name, True))
        elif name:
            deleted.append((dt, name, "already_missing"))
    except Exception as exc:
        deleted.append((dt, name, False, str(exc)))


def cleanup_previous():
    deleted = []

    for name in frappe.get_all(LOG_DOCTYPE, filters={"file_name": ["like", "%phase26%"]}, pluck="name"):
        safe_delete(LOG_DOCTYPE, name, deleted)

    for name in frappe.get_all("File", filters={"file_name": ["like", "%phase26%"]}, pluck="name"):
        safe_delete("File", name, deleted)

    for name in frappe.get_all(TARGET_DOCTYPE, filters={"description": ["like", f"%{PREFIX} TEST TARGET%"]}, pluck="name"):
        safe_delete(TARGET_DOCTYPE, name, deleted)

    for name in frappe.get_all(RULE_DOCTYPE, filters={"rule_name": ["like", f"%{PREFIX}%"]}, pluck="name"):
        safe_delete(RULE_DOCTYPE, name, deleted)

    for folder in [
        BENCH / "sites" / SITE / "private" / "files",
        BENCH / "sites" / SITE / "public" / "files",
    ]:
        if folder.exists():
            for path in folder.glob("phase26*"):
                try:
                    if path.is_file():
                        path.unlink()
                        deleted.append(("disk_file", str(path), True))
                except Exception as exc:
                    deleted.append(("disk_file", str(path), False, str(exc)))

    frappe.db.commit()
    return deleted


def find_remaining():
    private_dir = BENCH / "sites" / SITE / "private" / "files"
    public_dir = BENCH / "sites" / SITE / "public" / "files"

    disk_files = []
    for folder in [private_dir, public_dir]:
        if folder.exists():
            for path in folder.glob("phase26*"):
                if path.is_file():
                    disk_files.append(str(path))

    return {
        "targets": frappe.get_all(TARGET_DOCTYPE, filters={"description": ["like", f"%{PREFIX} TEST TARGET%"]}, fields=["name", "description"]),
        "rules": frappe.get_all(RULE_DOCTYPE, filters={"rule_name": ["like", f"%{PREFIX}%"]}, fields=["name", "rule_name"]),
        "logs": frappe.get_all(LOG_DOCTYPE, filters={"file_name": ["like", "%phase26%"]}, fields=["name", "file_name", "scan_session_id"]),
        "files": frappe.get_all("File", filters={"file_name": ["like", "%phase26%"]}, fields=["name", "file_name", "file_url"]),
        "disk_files": disk_files,
    }


def scan_for_secret_leak(secret):
    leaks = {
        "error_logs": [],
        "phase26_reports": [],
    }

    if not secret:
        return leaks

    try:
        rows = frappe.get_all(
            "Error Log",
            fields=["name", "creation", "method", "error"],
            order_by="creation desc",
            limit_page_length=80,
        )
        for row in rows:
            blob = json.dumps(row, ensure_ascii=False, default=str)
            if secret in blob:
                leaks["error_logs"].append({
                    "name": row.get("name"),
                    "creation": str(row.get("creation")),
                    "method": row.get("method"),
                })
    except Exception as exc:
        leaks["error_logs"].append({"scan_error": str(exc)})

    try:
        for path in REPORT_DIR.glob("*"):
            if path.is_file():
                try:
                    if secret in path.read_text(encoding="utf-8", errors="ignore"):
                        leaks["phase26_reports"].append(str(path))
                except Exception:
                    pass
    except Exception:
        pass

    return leaks


def run_shell(label, cmd, timeout=60):
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(BENCH),
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return {
            "label": label,
            "returncode": proc.returncode,
            "stdout_tail": "\n".join(proc.stdout.splitlines()[-80:]),
            "stderr_tail": "\n".join(proc.stderr.splitlines()[-80:]),
        }
    except Exception as exc:
        return {
            "label": label,
            "error": type(exc).__name__,
            "message": str(exc),
        }


def simulate_closed_port():
    try:
        requests.get("http://127.0.0.1:65531", timeout=2)
        return {
            "kind": "unexpected_success",
            "ok": False,
        }
    except Exception as exc:
        return {
            "kind": "expected_network_failure",
            "ok": True,
            "error": type(exc).__name__,
            "message": str(exc)[:300],
        }


def main():
    frappe.init(site=SITE, sites_path=str(BENCH / "sites"))
    frappe.connect()
    frappe.set_user("Administrator")

    try:
        previous_cleanup = cleanup_previous()

        valid_pdf = PAYLOAD_DIR / "phase26_valid.pdf"
        corrupt_pdf = PAYLOAD_DIR / "phase26_corrupt.pdf"
        write_valid_pdf(valid_pdf)
        write_corrupt_pdf(corrupt_pdf)

        results = []
        checks = []
        sessions = []

        # 1) Runtime checks: DB, cache, workers/doctor as non-destructive checks
        try:
            db_ping = frappe.db.sql("select 1 as ok", as_dict=True)
            checks.append(("db_ping_ok", bool(db_ping and db_ping[0].get("ok") == 1), db_ping))
        except Exception as exc:
            checks.append(("db_ping_ok", False, str(exc)))

        try:
            cache_obj = frappe.cache()
            cache_obj.set_value("phase26_cache_ping", "ok", expires_in_sec=60)
            cache_value = cache_obj.get_value("phase26_cache_ping")
            checks.append(("cache_ping_ok", cache_value in {"ok", b"ok"}, str(cache_value)))
        except Exception as exc:
            checks.append(("cache_ping_ok", False, str(exc)))

        doctor = run_shell("bench_doctor", "bench doctor", timeout=90)
        results.append(("bench_doctor", doctor))
        checks.append(("bench_doctor_no_exception", "error" not in doctor, doctor))

        worker_ps = run_shell("worker_process_scan", "ps -ef | grep -E 'frappe.*worker|rq:worker|bench worker' | grep -v grep || true")
        results.append(("worker_process_scan", worker_ps))
        checks.append(("worker_scan_no_exception", "error" not in worker_ps, worker_ps))

        # 2) Simulated network failure to closed local port
        net_fail = simulate_closed_port()
        results.append(("simulated_closed_port_network_failure", net_fail))
        checks.append(("simulated_closed_port_expected_failure", bool(net_fail.get("ok")), net_fail))

        # 3) Invalid API route must not 500
        r = http_get("surhan_scanner.agent_api.__phase26_missing_method__")
        results.append(("invalid_api_route", r))
        checks.append(("invalid_api_route_not_500", no_500(r), r))
        checks.append(("invalid_api_route_safe_status_or_exception", r.get("kind") == "exception" or r.get("http_status") in {400, 403, 404, 417}, r))

        # 4) Upload without file
        sess = create_session("upload_without_file")
        sessions.append(sess)
        frappe.db.commit()
        r = http_post(UPLOAD_METHOD, data={"scan_token": sess["scan_token"]})
        results.append(("upload_without_file", r))
        checks.append(("upload_without_file_400", r.get("http_status") == 400 and not msg_success(r), r))
        checks.append(("upload_without_file_no_500", no_500(r), r))

        # 5) Target deleted before upload
        sess = create_session("target_deleted_before_upload")
        sessions.append(sess)
        frappe.db.commit()
        safe_delete(TARGET_DOCTYPE, sess["target"], [])
        frappe.db.commit()
        r = upload_file(sess["scan_token"], valid_pdf, "phase26_target_deleted.pdf")
        results.append(("target_deleted_before_upload", r))
        checks.append(("target_deleted_before_upload_403", r.get("http_status") == 403 and not msg_success(r), r))
        checks.append(("target_deleted_before_upload_no_500", no_500(r), r))

        # 6) Rule deleted before upload
        sess = create_session("rule_deleted_before_upload")
        sessions.append(sess)
        frappe.db.commit()
        safe_delete(RULE_DOCTYPE, sess["rule"], [])
        frappe.db.commit()
        r = upload_file(sess["scan_token"], valid_pdf, "phase26_rule_deleted.pdf")
        results.append(("rule_deleted_before_upload", r))
        checks.append(("rule_deleted_before_upload_403", r.get("http_status") == 403 and not msg_success(r), r))
        checks.append(("rule_deleted_before_upload_no_500", no_500(r), r))

        # 7) Corrupt PDF must be 400, not 500
        sess = create_session("corrupt_pdf_recovery")
        sessions.append(sess)
        frappe.db.commit()
        r = upload_file(sess["scan_token"], corrupt_pdf, "phase26_corrupt.pdf")
        results.append(("corrupt_pdf_recovery", r))
        checks.append(("corrupt_pdf_400", r.get("http_status") == 400 and not msg_success(r), r))
        checks.append(("corrupt_pdf_no_500", no_500(r), r))

        # 8) Replay token: first success, second forbidden
        sess = create_session("replay_recovery")
        sessions.append(sess)
        frappe.db.commit()
        r1 = upload_file(sess["scan_token"], valid_pdf, "phase26_replay_first.pdf")
        r2 = upload_file(sess["scan_token"], valid_pdf, "phase26_replay_second.pdf")
        results.append(("replay_first", r1))
        results.append(("replay_second", r2))
        checks.append(("replay_first_success", r1.get("http_status") == 200 and msg_success(r1), r1))
        checks.append(("replay_second_rejected", r2.get("http_status") == 403 and not msg_success(r2), r2))
        checks.append(("replay_no_500", no_500(r1) and no_500(r2), {"first": r1, "second": r2}))

        # 9) Manifest/heartbeat/update status with invalid token after runtime failure scenarios
        guest_failure_tests = [
            ("manifest_invalid_token_after_failures", "GET", "surhan_scanner.agent_api.get_agent_update_manifest", {"scan_token": "phase26-invalid-token"}),
            ("heartbeat_invalid_token_after_failures", "POST", "surhan_scanner.agent_api.agent_heartbeat", {"scan_token": "phase26-invalid-token"}),
            ("update_status_invalid_token_after_failures", "POST", "surhan_scanner.agent_api.report_agent_update_status", {"scan_token": "phase26-invalid-token", "status": "Installed"}),
        ]

        for label, method, endpoint, data in guest_failure_tests:
            if method == "GET":
                r = http_get(endpoint, data)
            else:
                r = http_post(endpoint, data)
            results.append((label, r))
            checks.append((f"{label}_403", r.get("http_status") == 403 and not msg_success(r), r))
            checks.append((f"{label}_no_500", no_500(r), r))

        # 10) Token leak scan for the replay token
        token_leaks = scan_for_secret_leak(sessions[-1]["scan_token"] if sessions else "")
        checks.append(("scan_token_not_in_recent_error_logs", len(token_leaks["error_logs"]) == 0, token_leaks["error_logs"]))
        checks.append(("scan_token_not_in_phase26_reports", len(token_leaks["phase26_reports"]) == 0, token_leaks["phase26_reports"]))

        # 11) Cleanup
        deleted = []

        for name in frappe.get_all("File", filters={"file_name": ["like", "%phase26%"]}, pluck="name"):
            safe_delete("File", name, deleted)

        for name in frappe.get_all(LOG_DOCTYPE, filters={"file_name": ["like", "%phase26%"]}, pluck="name"):
            safe_delete(LOG_DOCTYPE, name, deleted)

        for sess in sessions:
            safe_delete(TARGET_DOCTYPE, sess.get("target"), deleted)
            safe_delete(RULE_DOCTYPE, sess.get("rule"), deleted)

        frappe.db.commit()

        for folder in [
            BENCH / "sites" / SITE / "private" / "files",
            BENCH / "sites" / SITE / "public" / "files",
        ]:
            if folder.exists():
                for path in folder.glob("phase26*"):
                    try:
                        if path.is_file():
                            path.unlink()
                            deleted.append(("disk_file", str(path), True))
                    except Exception as exc:
                        deleted.append(("disk_file", str(path), False, str(exc)))

        remaining = find_remaining()
        cleanup_ok = all(len(v) == 0 for v in remaining.values())
        checks.append(("cleanup_ok", cleanup_ok, remaining))

        all_passed = all(bool(c[1]) for c in checks)

        safe_sessions = [
            {k: ("***REDACTED***" if k == "scan_token" else v) for k, v in sess.items()}
            for sess in sessions
        ]

        summary = {
            "previous_cleanup": previous_cleanup,
            "sessions": safe_sessions,
            "results": results,
            "token_leaks": token_leaks,
            "deleted": deleted,
            "remaining": remaining,
            "checks": checks,
            "cleanup_ok": cleanup_ok,
            "all_passed": all_passed,
        }

        SUMMARY_REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        raw_lines = []
        raw_lines.append("=== Phase 26 Failure & Recovery Raw Results ===")
        raw_lines.append(f"BASE_URL={base_url()}")
        raw_lines.append("")
        for label, r in results:
            raw_lines.append(f"--- {label} ---")
            raw_lines.append(json.dumps(r, ensure_ascii=False, indent=2, default=str))
            raw_lines.append("")
        RAW_REPORT.write_text("\n".join(raw_lines), encoding="utf-8")

        CLEANUP_REPORT.write_text(
            "=== Deleted ===\n"
            + json.dumps(deleted, ensure_ascii=False, indent=2, default=str)
            + "\n\n=== Remaining ===\n"
            + json.dumps(remaining, ensure_ascii=False, indent=2, default=str)
            + f"\n\ncleanup_ok={cleanup_ok}\n",
            encoding="utf-8",
        )

        with FINAL_REPORT.open("w", encoding="utf-8") as f:
            f.write("=== Phase 26 Failure & Recovery Test Result ===\n\n")

            f.write("=== Results ===\n")
            for label, r in results:
                if isinstance(r, dict) and "http_status" in r:
                    f.write(f"{label}: http={r.get('http_status')} message={msg_text(r)}\n")
                else:
                    f.write(f"{label}: {json.dumps(r, ensure_ascii=False, default=str)}\n")

            f.write("\n=== Token Leakage ===\n")
            f.write(json.dumps(token_leaks, ensure_ascii=False, default=str) + "\n")

            f.write("\n=== Checks ===\n")
            for c in checks:
                f.write(json.dumps(c, ensure_ascii=False, default=str) + "\n")

            f.write("\n=== Cleanup ===\n")
            f.write(f"cleanup_ok={cleanup_ok}\n")

            f.write("\n=== Result ===\n")
            f.write("PASSED\n" if all_passed else "REVIEW_REQUIRED\n")

        print(FINAL_REPORT.read_text(encoding="utf-8"))

    except Exception:
        frappe.db.rollback()
        err = traceback.format_exc()
        FINAL_REPORT.write_text(
            "=== Phase 26 Failure & Recovery Test Result ===\n\n"
            "=== Result ===\nREVIEW_REQUIRED\n\n"
            "=== Traceback ===\n"
            + err,
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
