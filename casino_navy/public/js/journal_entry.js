frappe.ui.form.on("Journal Entry", {
    refresh(frm){
        frm.trigger("add_custom_buttons");
    },
    add_custom_buttons(frm){
        if (!frm.doc.reference_type || !frm.doc.reference_name) 
            return 
        
    
        frm.add_custom_button(__("View Transaction"), ()=> {
            frappe.set_route("Form", frm.doc.reference_type, frm.doc.reference_name);
        }, __("View"));
    },
});

frappe.ui.form.on("Journal Entry Account", {
    account(frm, cdt, cdn){
        const row = locals[cdt][cdn];
        if (!row.account) return;
        const method = "casino_navy.utils.get_bank_account"
        const args = {"company": frm.doc.company, "account": row.account}
        frappe.call({method, args, callback: ({message}) => {
            if (message) {
                frappe.model.set_value(cdt, cdn, "bank_account", message);
            }
        }});
    }
});