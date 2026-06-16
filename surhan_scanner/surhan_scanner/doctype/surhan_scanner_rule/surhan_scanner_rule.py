import frappe
from frappe import _
from frappe.model.document import Document


class SurhanScannerRule(Document):
    def validate(self):
        self.validate_target_doctype()
        self.validate_fields()
        self.validate_numeric_options()

    def validate_target_doctype(self):
        if not self.target_doctype:
            return

        if not frappe.db.exists("DocType", self.target_doctype):
            frappe.throw(
                _("Target DocType does not exist: {0}").format(self.target_doctype)
            )

    def validate_fields(self):
        if not self.target_doctype:
            return

        meta = frappe.get_meta(self.target_doctype)

        if self.placement_type == "After Field":
            if not self.target_field:
                frappe.throw(
                    _("Target Field is required when Placement Type is After Field")
                )

            if not meta.get_field(self.target_field):
                frappe.throw(
                    _("Target Field does not exist: {0}").format(self.target_field)
                )

        if self.placement_type == "All Attach Fields":
            attach_fields = [
                df.fieldname
                for df in meta.fields
                if df.fieldname and df.fieldtype in ["Attach", "Attach Image", "Table"]
            ]

            if not attach_fields:
                frappe.throw(
                    _("Target DocType has no Attach or Attach Image fields")
                )

        if self.attach_field:
            df = meta.get_field(self.attach_field)

            if not df:
                frappe.throw(
                    _("Attach Field does not exist: {0}").format(self.attach_field)
                )

            if df.fieldtype not in ["Attach", "Attach Image", "Table"]:
                frappe.throw(
                    _("Attach Field must be Attach or Attach Image")
                )

    def validate_numeric_options(self):
        if self.resolution is not None and int(self.resolution or 0) < 75:
            frappe.throw(_("Resolution must be 75 DPI or higher"))

        if self.max_pages is not None:
            max_pages = int(self.max_pages or 0)

            if max_pages < 1 or max_pages > 1000:
                frappe.throw(_("Max Pages must be between 1 and 1000"))

        if self.sort_order is not None and int(self.sort_order or 0) < 0:
            frappe.throw(_("Sort Order cannot be negative"))