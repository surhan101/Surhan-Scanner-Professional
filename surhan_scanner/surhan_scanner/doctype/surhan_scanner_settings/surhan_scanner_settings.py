import frappe
from frappe import _
from frappe.model.document import Document


SUPPORTED_FILE_TYPES = {"pdf", "jpg", "jpeg", "png", "tif", "tiff"}


class SurhanScannerSettings(Document):
    def validate(self):
        self.set_defaults()
        self.validate_ranges()
        self.normalize_allowed_file_types()

    def set_defaults(self):
        self.scanner_engine = self.scanner_engine or "Surhan Agent"
        self.agent_url = self.agent_url or "http://127.0.0.1:8787"
        self.agent_download_url = (
            self.agent_download_url
            or "/assets/surhan_scanner/agent/releases/SurhanScannerAgent-v1.0.2.zip"
        )
        self.agent_latest_version = self.agent_latest_version or "1.0.2"
        self.agent_version_check_url = (
            self.agent_version_check_url
            or "/assets/surhan_scanner/agent/version.json"
        )

        self.agent_token_expiry_seconds = self.agent_token_expiry_seconds or 300
        self.agent_scan_timeout_seconds = self.agent_scan_timeout_seconds or 120
        self.agent_max_file_size_mb = self.agent_max_file_size_mb or 200
        self.max_upload_size_mb = self.max_upload_size_mb or 200

        self.max_concurrent_scans_per_agent = self.max_concurrent_scans_per_agent or 1
        self.upload_retry_count = self.upload_retry_count or 3
        self.upload_retry_delay_seconds = self.upload_retry_delay_seconds or 5
        self.max_scan_batch_pages = self.max_scan_batch_pages or 1000

        self.agent_allowed_file_types = (
            self.agent_allowed_file_types
            or "pdf,jpg,jpeg,png,tif,tiff"
        )

    def validate_ranges(self):
        self._validate_int_range("agent_token_expiry_seconds", 30, 900)
        self._validate_int_range("agent_scan_timeout_seconds", 30, 600)
        self._validate_int_range("agent_max_file_size_mb", 1, 200)
        self._validate_int_range("max_upload_size_mb", 1, 200)
        self._validate_int_range("max_concurrent_scans_per_agent", 1, 10)
        self._validate_int_range("upload_retry_count", 0, 10)
        self._validate_int_range("upload_retry_delay_seconds", 1, 300)
        self._validate_int_range("max_scan_batch_pages", 1, 1000)

    def normalize_allowed_file_types(self):
        value = self.agent_allowed_file_types or "pdf,jpg,jpeg,png,tif,tiff"
        file_types = []

        for item in str(value).replace("\n", ",").split(","):
            extension = item.strip().lower().lstrip(".")

            if not extension:
                continue

            if extension not in SUPPORTED_FILE_TYPES:
                frappe.throw(
                    _("Unsupported scanner file type: {0}. Supported types: {1}").format(
                        extension,
                        ", ".join(sorted(SUPPORTED_FILE_TYPES)),
                    )
                )

            if extension not in file_types:
                file_types.append(extension)

        if not file_types:
            file_types = ["pdf", "jpg", "jpeg", "png", "tif", "tiff"]

        self.agent_allowed_file_types = ",".join(file_types)

    def _validate_int_range(self, fieldname, minimum, maximum):
        value = self.get(fieldname)

        try:
            value = int(value)
        except Exception:
            frappe.throw(
                _("{0} must be a number").format(self.meta.get_label(fieldname))
            )

        if value < minimum or value > maximum:
            frappe.throw(
                _("{0} must be between {1} and {2}").format(
                    self.meta.get_label(fieldname),
                    minimum,
                    maximum,
                )
            )

        self.set(fieldname, value)