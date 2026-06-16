import json
import time
import traceback
from pathlib import Path

import frappe
import requests

SITE = "ysmo"
BENCH = Path("/home/frappe/frappe-bench")
APP_DIR = BENCH / "apps/surhan_scanner"
REPORT_DIR = APP_DIR / "phase23_reports"

REPORT_DIR.mkdir(parents=True, exist_ok=True)

RAW_REPORT = REPORT_DIR / "phase23_agent_connectivity_raw.txt"
SUMMARY_REPORT = REPORT_DIR / "phase23_agent_connectivity_summary.json"
FINAL_REPORT = REPORT_DIR / "phase23_agent_connectivity_result.txt"
CLEANUP_REPORT = REPORT_DIR / "phase23_agent_connectivity_cleanup.txt"

TARGET_DOCTYPE = "ToDo"
RULE_DOCTYPE = "Surhan Scanner Rule"
LOG_DOCTYPE = "Surhan Scanner Log"
AGENT_DEVICE_DOCTYPE = "Surhan Scanner Agent Device"

PREFIX = "PHASE23"


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


def create_session(label):
    from surhan_scanner.agent_api import create_scan_session

    target = create_target(label)
    rule = create_rule(label, file_type="PDF")

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
        custom_file_name=f"phase23_{label}_{int(time.time())}",
    )

    return {
        "label": label,
        "target": target,
        "rule": rule,
        "scan_session_id": session.get("scan_session_id"),
        "scan_token": session.get("scan_token"),
    }


def response_message(resp):
    try:
        data = resp.json()
    except Exception:
        return {"raw": resp.text[:1000]}

    if isinstance(data, dict) and isinstance(data.get("message"), dict):
        return data["message"]

    return data


def http_get(method, params=None):
    resp = requests.get(
        f"{base_url()}/api/method/{method}",
        headers=headers(),
        params=params or {},
        timeout=60,
    )
    return {
        "http_status": resp.status_code,
        "message": response_message(resp),
    }


def http_post(method, data=None):
    resp = requests.post(
        f"{base_url()}/api/method/{method}",
        headers=headers(),
        data=data or {},
        timeout=60,
    )
    return {
        "http_status": resp.status_code,
        "message": response_message(resp),
    }


def ok_no_500(result):
    return int(result.get("http_status") or 0) != 500


def msg_success(result):
    msg = result.get("message")
    return isinstance(msg, dict) and bool(msg.get("success"))


def msg_text(result):
    msg = result.get("message")
    if isinstance(msg, dict):
        return str(msg.get("message") or msg)
    return str(msg)


def cleanup_previous():
    deleted = []

    def safe_delete(dt, name):
        try:
            if name and frappe.db.exists(dt, name):
                frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
                deleted.append((dt, name, True))
        except Exception as exc:
            deleted.append((dt, name, False, str(exc)))

    for name in frappe.get_all(LOG_DOCTYPE, filters={"scan_session_id": ["like", f"%{PREFIX}%"]}, pluck="name"):
        safe_delete(LOG_DOCTYPE, name)

    for name in frappe.get_all(TARGET_DOCTYPE, filters={"description": ["like", f"%{PREFIX} TEST TARGET%"]}, pluck="name"):
        safe_delete(TARGET_DOCTYPE, name)

    for name in frappe.get_all(RULE_DOCTYPE, filters={"rule_name": ["like", f"%{PREFIX}%"]}, pluck="name"):
        safe_delete(RULE_DOCTYPE, name)

    # تنظيف Agent Devices التي تنشأ من الاختبار إن وجدت
    fields = [df.fieldname for df in frappe.get_meta(AGENT_DEVICE_DOCTYPE).fields]
    possible_fields = ["agent_id", "device_id", "machine_name", "hostname", "computer_name"]

    for field in possible_fields:
        if field in fields:
            try:
                for name in frappe.get_all(
                    AGENT_DEVICE_DOCTYPE,
                    filters={field: ["like", f"%{PREFIX}%"]},
                    pluck="name",
                ):
                    safe_delete(AGENT_DEVICE_DOCTYPE, name)
            except Exception:
                pass

    frappe.db.commit()
    return deleted


def safe_direct_call(label, fn, *args, **kwargs):
    try:
        data = fn(*args, **kwargs)
        return {
            "label": label,
            "success": True,
            "data": data,
        }
    except Exception as exc:
        return {
            "label": label,
            "success": False,
            "error": str(exc),
            "traceback_tail": "\n".join(traceback.format_exc().splitlines()[-30:]),
        }


def main():
    frappe.init(site=SITE, sites_path=str(BENCH / "sites"))
    frappe.connect()
    frappe.set_user("Administrator")

    try:
        previous_cleanup = cleanup_previous()

        sessions = {
            "manifest": create_session("manifest"),
            "heartbeat": create_session("heartbeat"),
            "update_status": create_session("update_status"),
        }
        frappe.db.commit()

        results = []
        checks = []

        manifest_method = "surhan_scanner.agent_api.get_agent_update_manifest"
        heartbeat_method = "surhan_scanner.agent_api.agent_heartbeat"
        status_method = "surhan_scanner.agent_api.report_agent_update_status"

        # 1. Manifest tests
        r = http_get(manifest_method)
        results.append(("manifest_missing_token", r))
        checks.append(("manifest_missing_token_403", r["http_status"] == 403, r))

        r = http_get(manifest_method, {"scan_token": "fake-phase23-token"})
        results.append(("manifest_fake_token", r))
        checks.append(("manifest_fake_token_403", r["http_status"] == 403, r))

        r = http_get(manifest_method, {"scan_token": sessions["manifest"]["scan_token"]})
        results.append(("manifest_valid_token", r))
        checks.append(("manifest_valid_token_success", r["http_status"] == 200 and msg_success(r), r))
        checks.append(("manifest_has_version_1_0_2", "1.0.2" in json.dumps(r.get("message"), ensure_ascii=False), r))
        checks.append(("manifest_runtime_zip", "runtime_zip" in json.dumps(r.get("message"), ensure_ascii=False), r))

        # 2. Heartbeat tests
        r = http_post(heartbeat_method)
        results.append(("heartbeat_missing_token", r))
        checks.append(("heartbeat_missing_token_403", r["http_status"] == 403, r))

        r = http_post(heartbeat_method, {"scan_token": "fake-phase23-token"})
        results.append(("heartbeat_fake_token", r))
        checks.append(("heartbeat_fake_token_403", r["http_status"] == 403, r))

        heartbeat_data = {
            "scan_token": sessions["heartbeat"]["scan_token"],
            "agent_id": f"{PREFIX}-AGENT-001",
            "device_id": f"{PREFIX}-DEVICE-001",
            "machine_name": f"{PREFIX}-MACHINE",
            "hostname": f"{PREFIX}-HOST",
            "computer_name": f"{PREFIX}-COMPUTER",
            "username": "phase23_user",
            "agent_version": "1.0.2",
            "status": "Online",
            "scanner_count": "1",
            "scanners": json.dumps([
                {
                    "name": f"{PREFIX}-SCANNER-01",
                    "model": "Virtual Scanner",
                    "status": "Ready",
                    "duplex": True,
                }
            ]),
        }
        r = http_post(heartbeat_method, heartbeat_data)
        results.append(("heartbeat_valid_token", r))
        checks.append(("heartbeat_valid_no_500", ok_no_500(r), r))
        checks.append(("heartbeat_valid_expected_success_or_safe_client_error", r["http_status"] in {200, 400, 403}, r))

        # 3. Update status tests
        r = http_post(status_method)
        results.append(("update_status_empty", r))
        checks.append(("update_status_empty_400", r["http_status"] == 400, r))

        r = http_post(status_method, {"scan_token": "fake-phase23-token", "status": "Installed"})
        results.append(("update_status_fake_token", r))
        checks.append(("update_status_fake_token_403", r["http_status"] == 403, r))

        accepted_status = None
        candidate_statuses = ["Installed", "Downloaded", "Failed", "Available", "Up To Date", "Update Available", "Error"]
        status_attempts = []

        for st in candidate_statuses:
            sess = create_session(f"update_status_{st}")
            frappe.db.commit()
            r = http_post(status_method, {
                "scan_token": sess["scan_token"],
                "status": st,
                "agent_id": f"{PREFIX}-AGENT-001",
                "device_id": f"{PREFIX}-DEVICE-001",
                "agent_version": "1.0.2",
                "message": f"Phase23 status test {st}",
            })
            status_attempts.append((st, r))
            results.append((f"update_status_valid_candidate_{st}", r))
            checks.append((f"update_status_{st}_no_500", ok_no_500(r), r))

            if r["http_status"] == 200 and msg_success(r):
                accepted_status = st
                break

        checks.append(("update_status_has_one_valid_status", accepted_status is not None, status_attempts))

        # 4. Direct authenticated monitoring APIs
        import surhan_scanner.agent_api as api

        direct_calls = []
        for fn_name in [
            "get_agent_monitoring_status",
            "get_agent_dashboard_data",
            "mark_stale_agents_offline",
        ]:
            if hasattr(api, fn_name):
                direct_calls.append(safe_direct_call(fn_name, getattr(api, fn_name)))

        checks.append(("direct_monitoring_calls_no_crash", all(x["success"] for x in direct_calls), direct_calls))

        # 5. No HTTP 500 globally
        for label, r in results:
            checks.append((f"{label}_no_http_500", ok_no_500(r), r))

        # 6. Cleanup
        cleanup_deleted = cleanup_previous()

        remaining = {
            "targets": frappe.get_all(TARGET_DOCTYPE, filters={"description": ["like", f"%{PREFIX} TEST TARGET%"]}, fields=["name", "description"]),
            "rules": frappe.get_all(RULE_DOCTYPE, filters={"rule_name": ["like", f"%{PREFIX}%"]}, fields=["name", "rule_name"]),
            "logs": frappe.get_all(LOG_DOCTYPE, filters={"scan_session_id": ["like", f"%{PREFIX}%"]}, fields=["name", "scan_session_id"]),
        }

        fields = [df.fieldname for df in frappe.get_meta(AGENT_DEVICE_DOCTYPE).fields]
        remaining_devices = []
        for field in ["agent_id", "device_id", "machine_name", "hostname", "computer_name"]:
            if field in fields:
                try:
                    remaining_devices.extend(frappe.get_all(
                        AGENT_DEVICE_DOCTYPE,
                        filters={field: ["like", f"%{PREFIX}%"]},
                        fields=["name"],
                    ))
                except Exception:
                    pass
        remaining["agent_devices"] = remaining_devices

        cleanup_ok = all(len(v) == 0 for v in remaining.values())
        checks.append(("cleanup_ok", cleanup_ok, remaining))

        all_passed = all(bool(c[1]) for c in checks)

        summary = {
            "previous_cleanup": previous_cleanup,
            "sessions": {k: {kk: ("***REDACTED***" if kk == "scan_token" else vv) for kk, vv in v.items()} for k, v in sessions.items()},
            "results": results,
            "accepted_update_status": accepted_status,
            "direct_calls": direct_calls,
            "cleanup_deleted": cleanup_deleted,
            "remaining": remaining,
            "checks": checks,
            "all_passed": all_passed,
            "cleanup_ok": cleanup_ok,
        }

        SUMMARY_REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        raw_lines = []
        raw_lines.append("=== Phase 23 Agent Connectivity Raw Results ===")
        raw_lines.append(f"BASE_URL={base_url()}")
        raw_lines.append("")
        for label, r in results:
            raw_lines.append(f"--- {label} ---")
            raw_lines.append(json.dumps(r, ensure_ascii=False, indent=2, default=str))
            raw_lines.append("")
        raw_lines.append("--- Direct Calls ---")
        raw_lines.append(json.dumps(direct_calls, ensure_ascii=False, indent=2, default=str))
        RAW_REPORT.write_text("\n".join(raw_lines), encoding="utf-8")

        CLEANUP_REPORT.write_text(
            "=== Cleanup Deleted ===\n"
            + json.dumps(cleanup_deleted, ensure_ascii=False, indent=2, default=str)
            + "\n\n=== Remaining ===\n"
            + json.dumps(remaining, ensure_ascii=False, indent=2, default=str)
            + f"\n\ncleanup_ok={cleanup_ok}\n",
            encoding="utf-8",
        )

        with FINAL_REPORT.open("w", encoding="utf-8") as f:
            f.write("=== Phase 23 Agent Connectivity Test Result ===\n\n")

            f.write("=== HTTP Results ===\n")
            for label, r in results:
                f.write(f"{label}: http={r['http_status']} message={msg_text(r)}\n")

            f.write("\n=== Accepted Update Status ===\n")
            f.write(f"{accepted_status}\n")

            f.write("\n=== Direct Monitoring Calls ===\n")
            for item in direct_calls:
                f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")

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
            "=== Phase 23 Agent Connectivity Test Result ===\n\n"
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
