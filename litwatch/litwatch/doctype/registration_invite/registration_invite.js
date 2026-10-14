// Copyright (c) 2026, Shahina and contributors
// For license information, please see license.txt

frappe.ui.form.on("Registration Invite", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.status !== "Active") return;
		const M = "litwatch.litwatch.doctype.registration_invite.registration_invite.";
		const call = (method, msg) =>
			frappe.call({
				method: M + method,
				args: { invite: frm.doc.name },
				freeze: true,
				callback: () => {
					frm.reload_doc();
					frappe.show_alert({ message: msg, indicator: "green" });
				},
			});
		if (frm.doc.email) {
			frm.add_custom_button(__("Send by email"), () => call("send_invite_email", __("Invite emailed")), __("Invite"));
		}
		frm.add_custom_button(
			__("Copy link"),
			() => frappe.utils.copy_to_clipboard(frm.doc.registration_link),
			__("Invite")
		);
		frm.add_custom_button(
			__("Mark sent on WhatsApp"),
			() => call("mark_sent_on_whatsapp", __("Marked as sent on WhatsApp")),
			__("Invite")
		);
		frm.add_custom_button(__("Cancel invite"), () => call("cancel_invite", __("Invite cancelled")), __("Invite"));
	},
});
