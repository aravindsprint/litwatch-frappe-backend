// Copyright (c) 2026, Shahina and contributors
// For license information, please see license.txt

frappe.ui.form.on("LitWatch Lead", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (!frm.doc.user) {
			frm.add_custom_button(__("Convert to User"), () => {
				if (!frm.doc.email) {
					frappe.msgprint(__("Add the Email ID first."));
					return;
				}
				frappe.confirm(
					__("Create a LitWatch account for {0} and send the account email?", [frm.doc.email]),
					() =>
						frappe.call({
							method: "litwatch.onboarding.convert_lead",
							args: { lead: frm.doc.name },
							freeze: true,
							callback: (r) => {
								frm.reload_doc();
								frappe.show_alert({ message: __("Account created: {0}", [r.message.user]), indicator: "green" });
							},
						})
				);
			});
			frm.add_custom_button(__("Registration invite"), () => {
				frappe.new_doc("Registration Invite", {
					lead: frm.doc.name,
					email: frm.doc.email,
					whatsapp_number: frm.doc.whatsapp_number,
					invitee_name: frm.doc.full_name,
				});
			});
		} else {
			frm.dashboard.set_headline(__("Converted to User {0}", [frm.doc.user]), "green");
		}
	},
});
