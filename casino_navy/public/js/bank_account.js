frappe.ui.form.on("Bank Account", {
    refresh(frm){
        frm.trigger("set_queries");
    },
    set_queries(frm) {
        frm.set_query("custom_reserves_account", function() {
            return {
                filters: {
                    "company": frm.doc.company,
                    "is_group": 0,
                }
            };
        });
    }
});