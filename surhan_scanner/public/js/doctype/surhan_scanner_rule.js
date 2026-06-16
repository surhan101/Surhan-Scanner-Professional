frappe.ui.form.on("Surhan Scanner Rule", {
    refresh: function (frm) {
        frm.trigger("load_doctype_fields");
    },

    target_doctype: function (frm) {
        frm.set_value("target_field", "");
        frm.set_value("attach_field", "");
        frm.trigger("load_doctype_fields");
    },

    load_doctype_fields: function (frm) {
        if (!frm.doc.target_doctype) {
            return;
        }

        frappe.call({
            method: "surhan_scanner.api.get_doctype_fields",
            args: {
                doctype: frm.doc.target_doctype
            },
            callback: function (r) {
                const data = r.message || {};
                const all_fields = data.all_fields || [];
                const attach_fields = data.attach_fields || [];
                const barcode_fields = data.barcode_fields || [];

                const all_options = [""].concat(
                    all_fields.map(function (df) {
                        return df.fieldname;
                    })
                );

                const attach_options = [""].concat(
                    attach_fields.map(function (df) {
                        return df.fieldname;
                    })
                );

                const barcode_options = [""].concat(
                    barcode_fields.map(function (df) {
                        return df.fieldname;
                    })
                );

                frm.set_df_property("target_field", "options", all_options.join("\n"));
                frm.set_df_property("attach_field", "options", attach_options.join("\n"));

                if (frm.fields_dict.barcode_field) {
                    frm.set_df_property("barcode_field", "options", barcode_options.join("\n"));
                }
            }
        });
    }
});
