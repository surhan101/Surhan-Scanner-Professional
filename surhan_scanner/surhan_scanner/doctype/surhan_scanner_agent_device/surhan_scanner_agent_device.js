frappe.ui.form.on("Surhan Scanner Agent Device", {
    refresh(frm) {
        frm.set_df_property("agent_id", "read_only", frm.doc.__islocal ? 0 : 1);
    }
});
