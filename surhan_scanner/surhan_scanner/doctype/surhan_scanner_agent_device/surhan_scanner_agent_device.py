# Copyright (c) 2026, Surhan
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint


class SurhanScannerAgentDevice(Document):
    def validate(self):
        allowed_statuses = {"Online", "Offline", "Warning", "Blocked"}
        if self.status and self.status not in allowed_statuses:
            frappe.throw("Invalid Agent status")

        if self.agent_id:
            self.agent_id = str(self.agent_id).strip().replace("/", "_").replace("\\", "_")[:120]

        self.total_heartbeats = max(cint(self.total_heartbeats), 0)
        self.total_scans = max(cint(self.total_scans), 0)
