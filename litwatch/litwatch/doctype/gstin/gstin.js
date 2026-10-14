// Copyright (c) 2026, Shahina and contributors
// For license information, please see license.txt

// Approve / Reject a connection that is Awaiting verification (consent_status "verifying").

(() => {
	const GROUP = __("GST Portal");

	frappe.ui.form.on("GSTIN", {
		refresh(frm) {
			if (frm.is_new()) return;
			if (frm.doc.consent_status === "verifying") {
				frm.dashboard.set_headline(
					__("OTP verified: this connection is waiting for approval."),
					"orange"
				);
				frm.add_custom_button(__("Approve connection"), () => approve(frm), GROUP);
				frm.add_custom_button(__("Reject connection"), () => reject(frm), GROUP);
			}
		},
	});

	function approve(frm) {
		frappe.confirm(__("Approve the GST portal connection of {0}?", [frm.doc.name]), () =>
			frappe.call({
				method: "litwatch.api.gstin.approve_gstin_connection",
				args: { gstin: frm.doc.name },
				freeze: true,
				callback: (r) => {
					frm.reload_doc();
					frappe.show_alert({
						message: __("{0} connected until {1}", [frm.doc.name, (r.message || {}).validUntil || "-"]),
						indicator: "green",
					});
				},
			})
		);
	}

	function reject(frm) {
		frappe.prompt(
			{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
			(values) =>
				frappe.call({
					method: "litwatch.api.gstin.reject_gstin_connection",
					args: { gstin: frm.doc.name, reason: values.reason },
					freeze: true,
					callback: () => {
						frm.reload_doc();
						frappe.show_alert({ message: __("{0} rejected", [frm.doc.name]), indicator: "orange" });
					},
				}),
			__("Reject GSTIN connection"),
			__("Reject")
		);
	}
})();
