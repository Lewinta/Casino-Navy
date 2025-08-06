frappe.ui.form.on('Payment Entry', {
    posting_date(frm){
        frm.set_value("reference_date", frm.doc.posting_date);
    },
    mode_of_payment(frm) {
        if (!frm.doc.mode_of_payment || !frm.doc.company || !frm.doc.mode_of_payment)
            return;
        const method = "casino_navy.utils.get_bank_account"
        const args = {"company": frm.doc.company, "mop": frm.doc.mode_of_payment}
        frappe.call({method, args, callback: ({message}) => {
            if (message) {
                frm.set_value("bank_account", message);
            }
        }});

    },
});