frappe.ui.form.on("User", {
    refresh(frm){
        frm.trigger("add_custom_buttons");
    },
    add_custom_buttons(frm){
        if (frappe.session.user == frm.doc.name || !frappe.user.has_role("System Manager"))
            return

        if (frappe.session.user === 'Administrator') {
            frm.add_custom_button(__("Login as user"), () => {
                frappe.call({
                    method: "casino_navy.casino_navy.controllers.user.impersonate",
                    args: { "user": frm.doc.name },
                    freeze: true,
                    freeze_message: "Impersonating...",
                    callback: (data) => {
                        if(!data || !data.message)
                            return 
                        else {
                            localStorage.setItem('impersonated', frappe.session.user_fullname);
                            frappe.assets.clear_local_storage();
                            location.reload();
                        }
                    }
                });
            });
        }
    }
});