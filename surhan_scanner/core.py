import frappe

def require_scanner_access():
    roles = frappe.get_roles(frappe.session.user)

    if "System Manager" in roles:
        return True

    if "Surhan Scanner Admin" in roles:
        return True

    if "Surhan Scanner User" in roles:
        return True

    frappe.throw("Not authorized for scanner")

def get_rules(doctype):
    return frappe.get_all(
        "Surhan Scanner Rule",
        filters={"target_doctype": doctype},
        fields=["*"]
    )

def resolve_attach_field(rules, meta):
    for r in rules:
        if r.attach_field:
            return r.attach_field

    for df in meta.fields:
        if df.fieldtype in ["Attach", "Attach Image", "Table"]:
            return df.fieldname

    return None

def resolve_barcode_required(rules):
    for r in rules:
        if getattr(r, "barcode_required", 0):
            return True
    return False
