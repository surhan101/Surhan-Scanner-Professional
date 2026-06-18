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
        """Validate Surhan Scanner Rule fields.

        Supports:
        - direct Attach fields, e.g. attachment
        - table fields, e.g. attachments
        - child table attach fields, e.g. attachments.attachment_type
        """
        target_doctype = getattr(self, "target_doctype", None) or getattr(self, "scanned_doctype", None)

        if not target_doctype:
            return

        meta = frappe.get_meta(target_doctype)

        if self.placement_type == "After Field" and not self.target_field:
            frappe.throw(
                _("Target Field is required when Placement Type is After Field")
            )

        if self.target_field:
            target_df = meta.get_field(self.target_field)
            if not target_df:
                frappe.throw(
                    _("Target Field does not exist: {0}").format(self.target_field)
                )

        if self.attach_field:
            self._validate_attach_field_for_rule(meta, self.attach_field)

        barcode_field = getattr(self, "barcode_field", None)
        if barcode_field:
            barcode_df = meta.get_field(barcode_field)
            if not barcode_df:
                frappe.throw(
                    _("Barcode Field does not exist: {0}").format(barcode_field)
                )

    def _validate_attach_field_for_rule(self, meta, attach_field):
        attach_field = str(attach_field or "").strip()

        if "." in attach_field:
            table_field, child_field = attach_field.split(".", 1)
            table_field = table_field.strip()
            child_field = child_field.strip()

            table_df = meta.get_field(table_field)
            if not table_df:
                frappe.throw(
                    _("Attach Table Field does not exist: {0}").format(table_field)
                )

            if table_df.fieldtype != "Table":
                frappe.throw(
                    _("Parent field must be a Table field: {0}").format(table_field)
                )

            if not table_df.options:
                frappe.throw(
                    _("Table field has no child doctype: {0}").format(table_field)
                )

            child_meta = frappe.get_meta(table_df.options)
            child_df = child_meta.get_field(child_field)

            if not child_df:
                frappe.throw(
                    _("Child Attach Field does not exist: {0}").format(attach_field)
                )

            if child_df.fieldtype not in ["Attach", "Attach Image"]:
                frappe.throw(
                    _("Child field must be Attach or Attach Image: {0}").format(attach_field)
                )

            return

        df = meta.get_field(attach_field)
        if not df:
            frappe.throw(
                _("Attach Field does not exist: {0}").format(attach_field)
            )

        if df.fieldtype not in ["Attach", "Attach Image", "Table"]:
            frappe.throw(
                _("Attach Field must be Attach, Attach Image, or Table: {0}").format(attach_field)
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