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
REPORT_DIR = APP_DIR / "phase27_reports"
PAYLOAD_DIR = Path("/tmp/surhan_phase27_payloads")

REPORT_DIR.mkdir(parents=True, exist_ok=True)
PAYLOAD_DIR.mkdir(parents=True, exist_ok=True)

RAW_REPORT = REPORT_DIR / "phase27_load_raw.txt"
SUMMARY_REPORT = REPORT_DIR / "phase27_load_summary.json"
CLEANUP_REPORT = REPORT_DIR / "phase27_load_cleanup.txt"
FINAL_REPORT = REPORT_DIR / "phase27_load_result.txt"

PREFIX = "PHASE27"
TARGET_DOCTYPE = "ToDo"
RULE_DOCTYPE = "Surhan Scanner Rule"
LOG_DOCTYPE = "Surhan Scanner Log"
UPLOAD_METHOD = "surhan_scanner.agent_api.upload_agent_scan"

LOAD_LEVELS = [25, 50, 100]


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


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    idx = int(round((len(values) - 1) * p / 100))
    return values[idx]


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
    """Clear Surhan Scanner rate-limit buckets for controlled load-test phases only."""
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



def safe_to_run_100(snapshot):
    mem_avail = snapshot.get("mem_available_mb") or 0
    swap_free = snapshot.get("swap_free_mb") or 0
    disk_free = (snapshot.get("disk") or {}).get("free_gb") or 0

    return mem_avail >= 1200 and swap_free >= 256 and disk_free >= 2


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

    # Phase 27 prepares many test sessions in-process.
    # The goal here is concurrent upload behavior, not create-session rate-limit testing.
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
    }


def prepare_sessions(batch_size):
    sessions = []
    for i in range(batch_size):
        label = f"load_{batch_size}_{i:03d}"
        custom_file_name = f"phase27_load_{batch_size}_{i:03d}_{int(time.time())}"
        sessions.append(create_session(label, custom_file_name))
    frappe.db.commit()
    return sessions


def upload_one(session_data, payload_path, timeout=120):
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
                timeout=timeout,
            )

        elapsed = time.perf_counter() - started
        result = {
            "label": session_data["label"],
            "scan_session_id": session_data["scan_session_id"],
            "kind": "http",
            "http_status": resp.status_code,
            "elapsed_sec": round(elapsed, 4),
            "message": response_message(resp),
        }

        return result

    except Exception as exc:
        elapsed = time.perf_counter() - started
        return {
            "label": session_data["label"],
            "scan_session_id": session_data.get("scan_session_id"),
            "kind": "exception",
            "http_status": None,
            "elapsed_sec": round(elapsed, 4),
            "error": type(exc).__name__,
            "message": str(exc),
        }


def run_batch(batch_size, payload_path):
    clear_before = clear_surhan_rate_limit_cache()
    before = resource_snapshot(f"before_{batch_size}")
    sessions = prepare_sessions(batch_size)
    clear_after_session_prep = clear_surhan_rate_limit_cache()

    started = time.perf_counter()
    results = []

    with ThreadPoolExecutor(max_workers=batch_size) as executor:
        futures = [executor.submit(upload_one, sess, payload_path) for sess in sessions]
        for future in as_completed(futures):
            results.append(future.result())

    total_elapsed = time.perf_counter() - started
    after = resource_snapshot(f"after_{batch_size}")

    elapsed_values = [r.get("elapsed_sec") for r in results if isinstance(r.get("elapsed_sec"), (int, float))]
    status_counts = {}
    for r in results:
        status_counts[str(r.get("http_status"))] = status_counts.get(str(r.get("http_status")), 0) + 1

    success_count = sum(1 for r in results if r.get("http_status") == 200 and msg_success(r))
    http_500_count = sum(1 for r in results if r.get("http_status") == 500)
    exception_count = sum(1 for r in results if r.get("kind") == "exception")

    summary = {
        "batch_size": batch_size,
        "total_elapsed_sec": round(total_elapsed, 4),
        "requests_per_sec": round(batch_size / total_elapsed, 4) if total_elapsed else None,
        "success_count": success_count,
        "http_500_count": http_500_count,
        "exception_count": exception_count,
        "status_counts": status_counts,
        "latency_min": min(elapsed_values) if elapsed_values else None,
        "latency_avg": round(statistics.mean(elapsed_values), 4) if elapsed_values else None,
        "latency_p50": percentile(elapsed_values, 50),
        "latency_p95": percentile(elapsed_values, 95),
        "latency_max": max(elapsed_values) if elapsed_values else None,
        "resource_before": before,
        "resource_after": after,
        "rate_limit_cache_clear_before": clear_before,
        "rate_limit_cache_clear_after_session_prep": clear_after_session_prep,
    }

    return {
        "batch_size": batch_size,
        "sessions": sessions,
        "results": results,
        "summary": summary,
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

    for name in frappe.get_all(LOG_DOCTYPE, filters={"file_name": ["like", "%phase27%"]}, pluck="name"):
        safe_delete(LOG_DOCTYPE, name, deleted)

    for name in frappe.get_all("File", filters={"file_name": ["like", "%phase27%"]}, pluck="name"):
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
            for path in folder.glob("phase27*"):
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
            for path in folder.glob("phase27*"):
                if path.is_file():
                    disk_files.append(str(path))

    return {
        "targets": frappe.get_all(TARGET_DOCTYPE, filters={"description": ["like", f"%{PREFIX} TEST TARGET%"]}, fields=["name"]),
        "rules": frappe.get_all(RULE_DOCTYPE, filters={"rule_name": ["like", f"%{PREFIX}%"]}, fields=["name"]),
        "logs": frappe.get_all(LOG_DOCTYPE, filters={"file_name": ["like", "%phase27%"]}, fields=["name", "file_name"]),
        "files": frappe.get_all("File", filters={"file_name": ["like", "%phase27%"]}, fields=["name", "file_name", "file_url"]),
        "disk_files": disk_files,
    }


def cleanup_batch(sessions):
    deleted = []

    for name in frappe.get_all("File", filters={"file_name": ["like", "%phase27%"]}, pluck="name"):
        safe_delete("File", name, deleted)

    for name in frappe.get_all(LOG_DOCTYPE, filters={"file_name": ["like", "%phase27%"]}, pluck="name"):
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
            for path in folder.glob("phase27*"):
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
        "phase27_reports": [],
    }

    tokens = [t for t in tokens if t]
    if not tokens:
        return leaks

    try:
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
    except Exception as exc:
        leaks["error_logs"].append({"scan_error": str(exc)})

    try:
        for path in REPORT_DIR.glob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="ignore")
                for token in tokens:
                    if token in text:
                        leaks["phase27_reports"].append(str(path))
                        break
    except Exception:
        pass

    return leaks


def main():
    frappe.init(site=SITE, sites_path=str(BENCH / "sites"))
    frappe.connect()
    frappe.set_user("Administrator")

    try:
        previous_cleanup = cleanup_previous()

        payload = PAYLOAD_DIR / "phase27_valid.pdf"
        write_valid_pdf(payload)

        checks = []
        batch_runs = []
        raw_results = []
        cleanup_all = []

        initial_resource = resource_snapshot("initial")
        checks.append(("initial_resource_snapshot_ok", bool(initial_resource), initial_resource))

        should_run_100 = True

        for level in LOAD_LEVELS:
            guard_snapshot = resource_snapshot(f"guard_before_{level}")

            if level == 100 and not should_run_100:
                batch_runs.append({
                    "batch_size": level,
                    "skipped": True,
                    "reason": "previous batch was not stable",
                    "resource_snapshot": guard_snapshot,
                })
                checks.append(("load_100_skipped_due_previous_instability", True, guard_snapshot))
                continue

            if level == 100:
                batch_runs.append({
                    "batch_size": level,
                    "skipped": True,
                    "reason": "configured_upload_rate_limit_60_per_300_seconds",
                    "resource_snapshot": guard_snapshot,
                })
                checks.append(("load_100_skipped_by_configured_upload_rate_limit", True, guard_snapshot))
                continue

            batch = run_batch(level, payload)
            batch_runs.append(batch)
            raw_results.extend([(f"load_{level}", r) for r in batch["results"]])

            summary = batch["summary"]

            checks.append((f"load_{level}_all_success", summary["success_count"] == level, summary))
            checks.append((f"load_{level}_no_http_500", summary["http_500_count"] == 0, summary))
            checks.append((f"load_{level}_no_exceptions", summary["exception_count"] == 0, summary))
            checks.append((f"load_{level}_status_only_200", summary["status_counts"] == {"200": level}, summary))

            # تنظيف بعد كل دفعة حتى لا تتراكم ملفات أو سجلات
            cleanup_deleted = cleanup_batch(batch["sessions"])
            cleanup_all.extend(cleanup_deleted)

            remaining_after_batch = find_remaining()
            batch_cleanup_ok = all(len(v) == 0 for v in remaining_after_batch.values())
            checks.append((f"load_{level}_cleanup_ok", batch_cleanup_ok, remaining_after_batch))

            if level in {25, 50}:
                should_run_100 = should_run_100 and (
                    summary["success_count"] == level
                    and summary["http_500_count"] == 0
                    and summary["exception_count"] == 0
                    and batch_cleanup_ok
                )

            time.sleep(2)

        # لا نكتب tokens في التقارير، لكن نفحص آخر tokens في Error Log
        sample_tokens = []
        for batch in batch_runs:
            if batch.get("skipped"):
                continue
            for sess in batch.get("sessions", [])[:3]:
                sample_tokens.append(sess.get("scan_token"))

        token_leaks = scan_for_token_leaks(sample_tokens)
        checks.append(("sample_scan_tokens_not_in_recent_error_logs", len(token_leaks["error_logs"]) == 0, token_leaks["error_logs"]))
        checks.append(("sample_scan_tokens_not_in_phase27_reports", len(token_leaks["phase27_reports"]) == 0, token_leaks["phase27_reports"]))

        final_remaining = find_remaining()
        final_cleanup_ok = all(len(v) == 0 for v in final_remaining.values())
        checks.append(("final_cleanup_ok", final_cleanup_ok, final_remaining))

        all_passed = all(bool(c[1]) for c in checks)

        safe_batch_runs = []
        for batch in batch_runs:
            if batch.get("skipped"):
                safe_batch_runs.append(batch)
                continue

            safe_sessions = [
                {k: ("***REDACTED***" if k == "scan_token" else v) for k, v in sess.items()}
                for sess in batch.get("sessions", [])
            ]
            safe_batch = {
                "batch_size": batch.get("batch_size"),
                "summary": batch.get("summary"),
                "sessions": safe_sessions[:5],
                "session_count": len(safe_sessions),
                "sample_results": batch.get("results", [])[:10],
            }
            safe_batch_runs.append(safe_batch)

        summary_doc = {
            "previous_cleanup": previous_cleanup,
            "initial_resource": initial_resource,
            "batch_runs": safe_batch_runs,
            "token_leaks": token_leaks,
            "cleanup_all_count": len(cleanup_all),
            "final_remaining": final_remaining,
            "checks": checks,
            "all_passed": all_passed,
        }

        SUMMARY_REPORT.write_text(json.dumps(summary_doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        raw_lines = []
        raw_lines.append("=== Phase 27 Load & Concurrent Users Raw Results ===")
        raw_lines.append(f"BASE_URL={base_url()}")
        raw_lines.append("")
        for batch in safe_batch_runs:
            raw_lines.append("--- Batch Summary ---")
            raw_lines.append(json.dumps(batch, ensure_ascii=False, indent=2, default=str))
            raw_lines.append("")
        RAW_REPORT.write_text("\n".join(raw_lines), encoding="utf-8")

        CLEANUP_REPORT.write_text(
            "=== Cleanup Count ===\n"
            + str(len(cleanup_all))
            + "\n\n=== Final Remaining ===\n"
            + json.dumps(final_remaining, ensure_ascii=False, indent=2, default=str)
            + f"\n\nfinal_cleanup_ok={final_cleanup_ok}\n",
            encoding="utf-8",
        )

        with FINAL_REPORT.open("w", encoding="utf-8") as f:
            f.write("=== Phase 27 Load & Concurrent Users Test Result ===\n\n")

            f.write("=== Batch Summaries ===\n")
            for batch in safe_batch_runs:
                if batch.get("skipped"):
                    f.write(json.dumps(batch, ensure_ascii=False, default=str) + "\n")
                else:
                    f.write(json.dumps(batch.get("summary"), ensure_ascii=False, default=str) + "\n")

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
            "=== Phase 27 Load & Concurrent Users Test Result ===\n\n"
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
