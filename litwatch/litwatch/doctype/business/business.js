// Copyright (c) 2026, Shahina and contributors
// For license information, please see license.txt

// Approve / Reject a business created by a GST User while "Require business approval" is on.

frappe.ui.form.on("Business", {
	refresh(frm) {
		if (frm.is_new()) return;
		const status = frm.doc.approval_status || "Approved";
		if (status === "Pending") {
			frm.dashboard.set_headline(__("This business is waiting for approval."), "orange");
		} else if (status === "Rejected") {
			frm.dashboard.set_headline(__("Rejected: {0}", [frm.doc.approval_note || "-"]), "red");
		}
		if (status !== "Approved") {
			frm.add_custom_button(
				__("Approve"),
				() =>
					frappe.call({
						method: "litwatch.api.approvals.approve_business",
						args: { businessId: frm.doc.name },
						freeze: true,
						callback: () => {
							frm.reload_doc();
							frappe.show_alert({ message: __("Business approved"), indicator: "green" });
						},
					}),
				__("Approval")
			);
		}
		if (status === "Pending") {
			frm.add_custom_button(
				__("Reject"),
				() =>
					frappe.prompt(
						{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
						(v) =>
							frappe.call({
								method: "litwatch.api.approvals.reject_business",
								args: { businessId: frm.doc.name, reason: v.reason },
								freeze: true,
								callback: () => {
									frm.reload_doc();
									frappe.show_alert({ message: __("Business rejected"), indicator: "orange" });
								},
							}),
						__("Reject business"),
						__("Reject")
					),
				__("Approval")
			);
		}
	},
});
