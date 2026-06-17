import json
import os
import statistics
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import shutil

import frappe
import requests

SITE = "ysmo"
BENCH = Path("/home/frappe/frappe-bench")
APP_DIR = BENCH / "apps/surhan_scanner"
REPORT_DIR = APP_DIR / "phase28_reports"
PAYLOAD_DIR = Path("/tmp/surhan_phase28_payloads")

REPORT_DIR.mkdir(parents=True, exist_ok=True)
PAYLOAD_DIR.mkdir(parents=True, exist_ok=True)

RAW_REPORT = REPORT_DIR / "phase28_data_integrity_raw.txt"
SUMMARY_REPORT = REPORT_DIR / "phase28_data_integrity_summary.json"
CLEANUP_REPORT = REPORT_DIR / "phase28_data_integrity_cleanup.txt"
FINAL_REPORT = REPORT_DIR / "phase28_data_integrity_result.txt"

PREFIX = "PHASE28"
TARGET_DOCTYPE = "ToDo"
RULE_DOCTYPE = "Surhan Scanner Rule"
LOG_DOCTYPE = "Surhan Scanner Log"
UPLOAD_METHOD = "surhan_scanner.agent_api.upload_agent_scan"

BATCH_SIZE = 30


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


def no_500(result):
    return int(result.get("http_status") or 0) != 500



def refresh_db_read_transaction():
    """End the current DB transaction so this process can see HTTP-worker commits.

    Important:
    Do not call frappe.clear_cache() here because scan sessions/tokens may be cache-backed.
    Clearing cache after session preparation can invalidate tokens before upload.
    """
    try:
        frappe.db.commit()
    except Exception:
        try:
            frappe.db.rollback()
        except Exception:
            pass



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


def resource_snapshot(label):
    mem = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            mem[key] = int(value.strip().split()[0]) // 1024
    except Exception:
        pass

    try:
        loadavg = Path("/proc/loadavg").read_text().strip()
    except Exception:
        loadavg = ""

    try:
        disk = shutil.disk_usage(str(BENCH))
        disk_info = {
            "total_gb": round(disk.total / 1024**3, 2),
            "used_gb": round(disk.used / 1024**3, 2),
            "free_gb": round(disk.free / 1024**3, 2),
        }
    except Exception as exc:
        disk_info = {"error": str(exc)}

    return {
        "label": label,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mem_available_mb": mem.get("MemAvailable"),
        "mem_free_mb": mem.get("MemFree"),
        "swap_free_mb": mem.get("SwapFree"),
        "swap_total_mb": mem.get("SwapTotal"),
        "loadavg": loadavg,
        "cpu_count": os.cpu_count(),
        "disk": disk_info,
    }


def clear_surhan_rate_limit_cache():
    patterns = [
        "surhan_scanner:rate_limit:*",
        "*surhan_scanner:rate_limit:*",
    ]

    cache = frappe.cache()
    deleted = []

    for pattern in patterns:
        try:
            cache.delete_keys(pattern)
            deleted.append({"pattern": pattern, "method": "delete_keys"})
            continue
        except Exception:
            pass

        try:
            keys = cache.get_keys(pattern)
            for key in keys or []:
                try:
                    cache.delete_value(key)
                except Exception:
                    try:
                        cache.delete_value(key.decode() if isinstance(key, bytes) else str(key))
                    except Exception:
                        pass

            deleted.append({
                "pattern": pattern,
                "method": "get_keys_delete_value",
                "count": len(keys or []),
            })
        except Exception as exc:
            deleted.append({
                "pattern": pattern,
                "error": str(exc),
            })

    return deleted


def write_valid_pdf(path: Path, marker: str):
    try:
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        with path.open("wb") as f:
            writer.write(f)

        with path.open("ab") as f:
            f.write(("\n%" + marker + "\n").encode("utf-8"))
    except Exception:
        path.write_bytes(
            (
                "%PDF-1.4\n"
                "1 0 obj\n"
                "<< /Type /Catalog /Pages 2 0 R >>\n"
                "endobj\n"
                "2 0 obj\n"
                "<< /Type /Pages /Kids [3 0 R] /Count 1 >>\n"
                "endobj\n"
                "3 0 obj\n"
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] >>\n"
                "endobj\n"
                "xref\n"
                "0 4\n"
                "0000000000 65535 f \n"
                "0000000009 00000 n \n"
                "0000000058 00000 n \n"
                "0000000115 00000 n \n"
                "trailer\n"
                "<< /Root 1 0 R /Size 4 >>\n"
                "startxref\n"
                "188\n"
                "%%EOF\n"
                f"%{marker}\n"
            ).encode("utf-8")
        )


def normalize_rule_file_type(file_type):
    ft = str(file_type or "Default").strip().upper()
    if ft == "PDF":
        return "PDF"
    if ft in {"JPG", "JPEG"}:
        return "JPG"
    return "Default"


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


def create_session(label, custom_file_name):
    import surhan_scanner.agent_api as agent_api

    # Controlled test preparation only.
    # Phase 28 validates data integrity after pressure; rate-limit was already verified.
    agent_api._enforce_create_scan_session_rate_limit = lambda: None
    create_scan_session = agent_api.create_scan_session

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
        custom_file_name=custom_file_name,
    )

    return {
        "label": label,
        "target": target,
        "rule": rule,
        "scan_session_id": session.get("scan_session_id"),
        "scan_token": session.get("scan_token"),
        "custom_file_name": custom_file_name,
    }


def prepare_sessions_and_payloads(batch_size):
    sessions = []
    payloads = {}

    for i in range(batch_size):
        label = f"integrity_{i:03d}"
        custom_file_name = f"phase28_integrity_{i:03d}_{int(time.time())}"
        payload = PAYLOAD_DIR / f"phase28_integrity_{i:03d}.pdf"
        write_valid_pdf(payload, f"PHASE28_INTEGRITY_{i:03d}")

        sessions.append(create_session(label, custom_file_name))
        payloads[label] = payload

    frappe.db.commit()
    return sessions, payloads


def upload_one(session_data, payload_path):
    started = time.perf_counter()

    try:
        with open(payload_path, "rb") as fp:
            files = {
                "file": (f"{session_data['label']}.pdf", fp, "application/pdf")
            }
            resp = requests.post(
                f"{base_url()}/api/method/{UPLOAD_METHOD}",
                headers=headers(),
                data={"scan_token": session_data["scan_token"]},
                files=files,
                timeout=120,
            )

        elapsed = time.perf_counter() - started
        return {
            "label": session_data["label"],
            "scan_session_id": session_data["scan_session_id"],
            "target": session_data["target"],
            "rule": session_data["rule"],
            "kind": "http",
            "http_status": resp.status_code,
            "elapsed_sec": round(elapsed, 4),
            "message": response_message(resp),
        }

    except Exception as exc:
        elapsed = time.perf_counter() - started
        return {
            "label": session_data["label"],
            "scan_session_id": session_data.get("scan_session_id"),
            "target": session_data.get("target"),
            "rule": session_data.get("rule"),
            "kind": "exception",
            "http_status": None,
            "elapsed_sec": round(elapsed, 4),
            "error": type(exc).__name__,
            "message": str(exc),
        }


def file_url_to_disk_path(file_url):
    if not file_url:
        return None

    if file_url.startswith("/private/files/"):
        return BENCH / "sites" / SITE / "private" / "files" / Path(file_url).name

    if file_url.startswith("/files/"):
        return BENCH / "sites" / SITE / "public" / "files" / Path(file_url).name

    return None


def get_file_doc(name):
    if not name or not frappe.db.exists("File", name):
        return None

    return frappe.get_doc("File", name).as_dict()


def get_logs_by_session(scan_session_id):
    # Read only fields that actually exist in Surhan Scanner Log.
    # Some installations do not have target_doctype / target_docname fields.
    meta = frappe.get_meta(LOG_DOCTYPE)
    existing = {
        df.fieldname
        for df in getattr(meta, "fields", [])
        if getattr(df, "fieldname", None)
    }

    wanted = ["name", "status", "file_name", "file_url", "scan_session_id", "target_doctype", "target_docname"]
    fields = [field for field in wanted if field == "name" or field in existing]

    return frappe.get_all(
        LOG_DOCTYPE,
        filters={"scan_session_id": scan_session_id},
        fields=fields,
        limit_page_length=50,
    )


def run_pressure_uploads(sessions, payloads):
    clear_before = clear_surhan_rate_limit_cache()
    before = resource_snapshot("before_pressure_upload")

    started = time.perf_counter()
    results = []

    with ThreadPoolExecutor(max_workers=len(sessions)) as executor:
        futures = [
            executor.submit(upload_one, sess, payloads[sess["label"]])
            for sess in sessions
        ]
        for future in as_completed(futures):
            results.append(future.result())

    elapsed = time.perf_counter() - started
    after = resource_snapshot("after_pressure_upload")

    elapsed_values = [r.get("elapsed_sec") for r in results if isinstance(r.get("elapsed_sec"), (int, float))]
    status_counts = {}
    for r in results:
        status_counts[str(r.get("http_status"))] = status_counts.get(str(r.get("http_status")), 0) + 1

    summary = {
        "batch_size": len(sessions),
        "total_elapsed_sec": round(elapsed, 4),
        "requests_per_sec": round(len(sessions) / elapsed, 4) if elapsed else None,
        "success_count": sum(1 for r in results if r.get("http_status") == 200 and msg_success(r)),
        "http_500_count": sum(1 for r in results if r.get("http_status") == 500),
        "exception_count": sum(1 for r in results if r.get("kind") == "exception"),
        "status_counts": status_counts,
        "latency_min": min(elapsed_values) if elapsed_values else None,
        "latency_avg": round(statistics.mean(elapsed_values), 4) if elapsed_values else None,
        "latency_max": max(elapsed_values) if elapsed_values else None,
        "resource_before": before,
        "resource_after": after,
        "rate_limit_cache_clear_before": clear_before,
    }

    return results, summary


def validate_integrity(results, session_map):
    checks = []
    file_urls = []
    file_names = []
    file_docs = []
    log_names = []

    for r in results:
        label = r.get("label")
        sess = session_map.get(label) or {}
        msg = r.get("message") if isinstance(r.get("message"), dict) else {}
        file_info = msg.get("file") if isinstance(msg, dict) else {}
        file_doc = get_file_doc(file_info.get("name") if isinstance(file_info, dict) else None)
        logs = get_logs_by_session(r.get("scan_session_id"))

        checks.append((f"{label}_upload_success", r.get("http_status") == 200 and msg_success(r), r))
        checks.append((f"{label}_no_http_500", no_500(r), r))

        checks.append((f"{label}_file_info_present", bool(file_info and file_info.get("name") and file_info.get("file_url")), file_info))
        checks.append((f"{label}_file_doc_exists", bool(file_doc), file_doc))

        if file_info:
            file_urls.append(file_info.get("file_url"))
            file_names.append(file_info.get("file_name"))

        if file_doc:
            file_docs.append(file_doc.get("name"))
            checks.append((f"{label}_file_private", int(file_doc.get("is_private") or 0) == 1, file_doc.get("is_private")))
            checks.append((f"{label}_file_url_private", str(file_doc.get("file_url") or "").startswith("/private/files/"), file_doc.get("file_url")))
            checks.append((f"{label}_attached_to_correct_target", file_doc.get("attached_to_doctype") == TARGET_DOCTYPE and file_doc.get("attached_to_name") == sess.get("target"), {
                "attached_to_doctype": file_doc.get("attached_to_doctype"),
                "attached_to_name": file_doc.get("attached_to_name"),
                "expected_target": sess.get("target"),
            }))

            disk_path = file_url_to_disk_path(file_doc.get("file_url"))
            disk_exists = bool(disk_path and disk_path.exists())
            checks.append((f"{label}_disk_file_exists", disk_exists, str(disk_path) if disk_path else None))

            if disk_exists:
                disk_size = disk_path.stat().st_size
                db_size = int(file_doc.get("file_size") or 0)
                checks.append((f"{label}_disk_size_close_to_db_size", abs(disk_size - db_size) <= 16, {
                    "disk_size": disk_size,
                    "db_size": db_size,
                }))

        checks.append((f"{label}_scan_log_exists_once", len(logs) == 1, logs))
        if logs:
            log_names.extend([x.get("name") for x in logs])
            log = logs[0]
            checks.append((f"{label}_scan_log_success", str(log.get("status")).lower() == "success", log))
            checks.append((f"{label}_scan_log_url_matches_file", bool(file_doc and log.get("file_url") == file_doc.get("file_url")), {
                "log_file_url": log.get("file_url"),
                "file_doc_url": file_doc.get("file_url") if file_doc else None,
            }))

    checks.append(("all_file_urls_unique", len(file_urls) == len(set(file_urls)) == len(results), {
        "count": len(file_urls),
        "unique": len(set(file_urls)),
    }))
    checks.append(("all_file_docs_unique", len(file_docs) == len(set(file_docs)) == len(results), {
        "count": len(file_docs),
        "unique": len(set(file_docs)),
    }))
    checks.append(("all_scan_logs_unique", len(log_names) == len(set(log_names)) == len(results), {
        "count": len(log_names),
        "unique": len(set(log_names)),
    }))

    return checks


def phase_counts():
    return {
        "targets": frappe.db.count(TARGET_DOCTYPE, {"description": ["like", f"%{PREFIX} TEST TARGET%"]}),
        "rules": frappe.db.count(RULE_DOCTYPE, {"rule_name": ["like", f"%{PREFIX}%"]}),
        "logs": frappe.db.count(LOG_DOCTYPE, {"file_name": ["like", "%phase28%"]}),
        "files": frappe.db.count("File", {"file_name": ["like", "%phase28%"]}),
    }


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

    for name in frappe.get_all(LOG_DOCTYPE, filters={"file_name": ["like", "%phase28%"]}, pluck="name"):
        safe_delete(LOG_DOCTYPE, name, deleted)

    for name in frappe.get_all("File", filters={"file_name": ["like", "%phase28%"]}, pluck="name"):
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
            for path in folder.glob("phase28*"):
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
            for path in folder.glob("phase28*"):
                if path.is_file():
                    disk_files.append(str(path))

    return {
        "targets": frappe.get_all(TARGET_DOCTYPE, filters={"description": ["like", f"%{PREFIX} TEST TARGET%"]}, fields=["name"]),
        "rules": frappe.get_all(RULE_DOCTYPE, filters={"rule_name": ["like", f"%{PREFIX}%"]}, fields=["name"]),
        "logs": frappe.get_all(LOG_DOCTYPE, filters={"file_name": ["like", "%phase28%"]}, fields=["name", "file_name", "file_url"]),
        "files": frappe.get_all("File", filters={"file_name": ["like", "%phase28%"]}, fields=["name", "file_name", "file_url"]),
        "disk_files": disk_files,
    }


def cleanup_all(sessions):
    deleted = []

    for name in frappe.get_all("File", filters={"file_name": ["like", "%phase28%"]}, pluck="name"):
        safe_delete("File", name, deleted)

    for name in frappe.get_all(LOG_DOCTYPE, filters={"file_name": ["like", "%phase28%"]}, pluck="name"):
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
            for path in folder.glob("phase28*"):
                try:
                    if path.is_file():
                        path.unlink()
                        deleted.append(("disk_file", str(path), True))
                except Exception as exc:
                    deleted.append(("disk_file", str(path), False, str(exc)))

    return deleted


def scan_for_token_leaks(tokens):
    leaks = {
        "error_logs": [],
        "phase28_reports": [],
    }

    tokens = [t for t in tokens if t]
    if not tokens:
        return leaks

    rows = frappe.get_all(
        "Error Log",
        fields=["name", "creation", "method", "error"],
        order_by="creation desc",
        limit_page_length=100,
    )

    for row in rows:
        blob = json.dumps(row, ensure_ascii=False, default=str)
        for token in tokens:
            if token in blob:
                leaks["error_logs"].append({
                    "name": row.get("name"),
                    "creation": str(row.get("creation")),
                    "method": row.get("method"),
                })
                break

    for path in REPORT_DIR.glob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in tokens:
                if token in text:
                    leaks["phase28_reports"].append(str(path))
                    break

    return leaks


def main():
    frappe.init(site=SITE, sites_path=str(BENCH / "sites"))
    frappe.connect()
    frappe.set_user("Administrator")

    try:
        previous_cleanup = cleanup_previous()
        refresh_db_read_transaction()

        checks = []
        initial_counts = phase_counts()
        checks.append(("initial_phase_counts_zero", all(v == 0 for v in initial_counts.values()), initial_counts))

        clear_cache_result = clear_surhan_rate_limit_cache()
        sessions, payloads = prepare_sessions_and_payloads(BATCH_SIZE)
        session_map = {s["label"]: s for s in sessions}
        refresh_db_read_transaction()

        after_prepare_counts = phase_counts()
        checks.append(("after_prepare_targets_count", after_prepare_counts["targets"] == BATCH_SIZE, after_prepare_counts))
        checks.append(("after_prepare_rules_count", after_prepare_counts["rules"] == BATCH_SIZE, after_prepare_counts))
        checks.append(("after_prepare_no_files_yet", after_prepare_counts["files"] == 0, after_prepare_counts))
        checks.append(("after_prepare_no_logs_yet", after_prepare_counts["logs"] == 0, after_prepare_counts))

        results, pressure_summary = run_pressure_uploads(sessions, payloads)
        refresh_db_read_transaction()

        checks.append(("pressure_success_count", pressure_summary["success_count"] == BATCH_SIZE, pressure_summary))
        checks.append(("pressure_no_http_500", pressure_summary["http_500_count"] == 0, pressure_summary))
        checks.append(("pressure_no_exceptions", pressure_summary["exception_count"] == 0, pressure_summary))
        checks.append(("pressure_status_only_200", pressure_summary["status_counts"] == {"200": BATCH_SIZE}, pressure_summary))

        after_upload_counts = phase_counts()
        checks.append(("after_upload_files_count", after_upload_counts["files"] == BATCH_SIZE, after_upload_counts))
        checks.append(("after_upload_logs_count", after_upload_counts["logs"] == BATCH_SIZE, after_upload_counts))
        checks.append(("after_upload_targets_count", after_upload_counts["targets"] == BATCH_SIZE, after_upload_counts))
        checks.append(("after_upload_rules_count", after_upload_counts["rules"] == BATCH_SIZE, after_upload_counts))

        refresh_db_read_transaction()
        integrity_checks = validate_integrity(results, session_map)
        checks.extend(integrity_checks)

        sample_tokens = [s.get("scan_token") for s in sessions[:5]]
        token_leaks = scan_for_token_leaks(sample_tokens)
        checks.append(("sample_scan_tokens_not_in_recent_error_logs", len(token_leaks["error_logs"]) == 0, token_leaks["error_logs"]))
        checks.append(("sample_scan_tokens_not_in_phase28_reports", len(token_leaks["phase28_reports"]) == 0, token_leaks["phase28_reports"]))

        refresh_db_read_transaction()
        deleted = cleanup_all(sessions)
        refresh_db_read_transaction()

        final_remaining = find_remaining()
        final_cleanup_ok = all(len(v) == 0 for v in final_remaining.values())
        final_counts = phase_counts()

        checks.append(("final_cleanup_ok", final_cleanup_ok, final_remaining))
        checks.append(("final_phase_counts_zero", all(v == 0 for v in final_counts.values()), final_counts))

        all_passed = all(bool(c[1]) for c in checks)

        safe_sessions = [
            {k: ("***REDACTED***" if k == "scan_token" else v) for k, v in sess.items()}
            for sess in sessions
        ]

        safe_results = []
        for r in results:
            safe_results.append(r)

        summary_doc = {
            "previous_cleanup": previous_cleanup,
            "clear_cache_result": clear_cache_result,
            "batch_size": BATCH_SIZE,
            "initial_counts": initial_counts,
            "after_prepare_counts": after_prepare_counts,
            "pressure_summary": pressure_summary,
            "after_upload_counts": after_upload_counts,
            "safe_sessions_sample": safe_sessions[:5],
            "results_sample": safe_results[:10],
            "token_leaks": token_leaks,
            "deleted_count": len(deleted),
            "final_remaining": final_remaining,
            "final_counts": final_counts,
            "checks": checks,
            "all_passed": all_passed,
        }

        SUMMARY_REPORT.write_text(json.dumps(summary_doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        raw_lines = []
        raw_lines.append("=== Phase 28 Data Integrity After Pressure Raw Results ===")
        raw_lines.append(f"BASE_URL={base_url()}")
        raw_lines.append("")
        raw_lines.append("=== Pressure Summary ===")
        raw_lines.append(json.dumps(pressure_summary, ensure_ascii=False, indent=2, default=str))
        raw_lines.append("")
        raw_lines.append("=== Upload Results Sample ===")
        raw_lines.append(json.dumps(safe_results[:20], ensure_ascii=False, indent=2, default=str))
        RAW_REPORT.write_text("\n".join(raw_lines), encoding="utf-8")

        CLEANUP_REPORT.write_text(
            "=== Deleted Count ===\n"
            + str(len(deleted))
            + "\n\n=== Final Remaining ===\n"
            + json.dumps(final_remaining, ensure_ascii=False, indent=2, default=str)
            + "\n\n=== Final Counts ===\n"
            + json.dumps(final_counts, ensure_ascii=False, indent=2, default=str)
            + f"\n\nfinal_cleanup_ok={final_cleanup_ok}\n",
            encoding="utf-8",
        )

        with FINAL_REPORT.open("w", encoding="utf-8") as f:
            f.write("=== Phase 28 Data Integrity After Pressure & Cleanup Test Result ===\n\n")

            f.write("=== Counts ===\n")
            f.write(f"initial_counts={json.dumps(initial_counts, ensure_ascii=False, default=str)}\n")
            f.write(f"after_prepare_counts={json.dumps(after_prepare_counts, ensure_ascii=False, default=str)}\n")
            f.write(f"after_upload_counts={json.dumps(after_upload_counts, ensure_ascii=False, default=str)}\n")
            f.write(f"final_counts={json.dumps(final_counts, ensure_ascii=False, default=str)}\n")

            f.write("\n=== Pressure Summary ===\n")
            f.write(json.dumps(pressure_summary, ensure_ascii=False, default=str) + "\n")

            f.write("\n=== Token Leakage ===\n")
            f.write(json.dumps(token_leaks, ensure_ascii=False, default=str) + "\n")

            f.write("\n=== Checks ===\n")
            for c in checks:
                f.write(json.dumps(c, ensure_ascii=False, default=str) + "\n")

            f.write("\n=== Cleanup ===\n")
            f.write(f"final_cleanup_ok={final_cleanup_ok}\n")

            f.write("\n=== Result ===\n")
            f.write("PASSED\n" if all_passed else "REVIEW_REQUIRED\n")

        print(FINAL_REPORT.read_text(encoding="utf-8"))

    except Exception:
        frappe.db.rollback()
        err = traceback.format_exc()
        FINAL_REPORT.write_text(
            "=== Phase 28 Data Integrity After Pressure & Cleanup Test Result ===\n\n"
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
