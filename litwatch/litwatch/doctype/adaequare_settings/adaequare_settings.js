// Copyright (c) 2026, Shahina and contributors
// For license information, please see license.txt

// GST Portal buttons: request / verify / resend the portal OTP for one of this
// Business's GSTINs, using the same APIs as the LitWatch frontend
// (litwatch.api.gstin.connect_gstin / verify_gstin_otp / resend_gstin_otp).
// A verified OTP is saved into the OTP field of this record and the GSTIN waits
// for approval ("verifying"); Approve / Reject connection finish the flow
// (litwatch.api.gstin.approve_gstin_connection / reject_gstin_connection).

(() => {
	const GROUP = __("GST Portal");

	frappe.ui.form.on("Adaequare Settings", {
		refresh(frm) {
			if (frm.is_new() || !frm.doc.business) return;

			frm.add_custom_button(__("Request OTP"), () => request_otp(frm), GROUP);
			frm.add_custom_button(__("Verify OTP"), () => verify_otp(frm), GROUP);
			frm.add_custom_button(__("Resend OTP"), () => resend_otp(frm), GROUP);
			frm.add_custom_button(__("Approve connection"), () => decide(frm, "approve"), GROUP);
			frm.add_custom_button(__("Reject connection"), () => decide(frm, "reject"), GROUP);
		},
	});

	async function business_gstins(frm) {
		const rows = await frappe.db.get_list("GSTIN", {
			filters: { business_id: frm.doc.business },
			fields: ["name", "portal_user_id", "consent_status"],
			order_by: "creation asc",
			limit: 0,
		});
		if (!rows.length) {
			frappe.msgprint(
				__("Business {0} has no GSTIN. Add one to the Business first.", [frm.doc.business])
			);
		}
		return rows;
	}

	function gstin_field(rows) {
		return {
			fieldname: "gstin",
			fieldtype: "Select",
			label: __("GSTIN"),
			reqd: 1,
			options: rows.map((r) => r.name).join("\n"),
			default: rows[0] && rows[0].name,
			description: __("GSTINs of this Business"),
		};
	}

	async function latest_pending_request(gstin) {
		const rows = await frappe.db.get_list("GST OTP Request", {
			filters: { gstin, status: "pending" },
			fields: ["name", "otp_sent_to", "expires_at"],
			order_by: "creation desc",
			limit: 1,
		});
		return rows[0];
	}

	function status_message(gstin, res) {
		if (res.consent === "active") {
			return __("{0} is connected. Consent valid until {1}.", [gstin, res.validUntil || "-"]);
		}
		return __("{0} is now Awaiting verification. Approve or reject the connection (GST Portal → Approve connection).", [gstin]);
	}

	function after_request(frm, gstin, r) {
		const res = r.message || {};
		frm.reload_doc();
		if (!res.otpRequired) {
			frappe.msgprint({
				title: __("No OTP needed"),
				indicator: "green",
				message: __("The GST portal session for {0} is already active.", [gstin]) + " " + status_message(gstin, res),
			});
			return;
		}
		frappe.show_alert({ message: __("OTP sent to {0}", [res.otpSentTo || "-"]), indicator: "green" });
		otp_dialog(frm, gstin, res.otpRequestId, res.otpSentTo);
	}

	async function request_otp(frm) {
		const rows = await business_gstins(frm);
		if (!rows.length) return;

		const d = new frappe.ui.Dialog({
			title: __("Request GST portal OTP"),
			fields: [
				gstin_field(rows),
				{
					fieldname: "portal_user_id",
					fieldtype: "Data",
					label: __("GST Portal Username"),
					reqd: 1,
					default: rows[0].portal_user_id,
				},
			],
			primary_action_label: __("Request OTP"),
			primary_action(values) {
				d.hide();
				frappe.call({
					method: "litwatch.api.gstin.connect_gstin",
					args: { gstin: values.gstin, portalUserId: values.portal_user_id },
					freeze: true,
					freeze_message: __("Requesting OTP from the GST portal..."),
					callback: (r) => after_request(frm, values.gstin, r),
				});
			},
		});
		d.fields_dict.gstin.$input.on("change", () => {
			const row = rows.find((x) => x.name === d.get_value("gstin"));
			d.set_value("portal_user_id", (row && row.portal_user_id) || "");
		});
		d.show();
	}

	async function resend_otp(frm) {
		const rows = await business_gstins(frm);
		if (!rows.length) return;

		const d = new frappe.ui.Dialog({
			title: __("Resend GST portal OTP"),
			fields: [gstin_field(rows)],
			primary_action_label: __("Resend OTP"),
			primary_action(values) {
				d.hide();
				frappe.call({
					method: "litwatch.api.gstin.resend_gstin_otp",
					args: { gstin: values.gstin },
					freeze: true,
					freeze_message: __("Requesting a new OTP..."),
					callback: (r) => after_request(frm, values.gstin, r),
				});
			},
		});
		d.show();
	}

	async function verify_otp(frm) {
		const rows = await business_gstins(frm);
		if (!rows.length) return;

		const d = new frappe.ui.Dialog({
			title: __("Verify GST portal OTP"),
			fields: [gstin_field(rows)],
			primary_action_label: __("Next"),
			async primary_action(values) {
				const req = await latest_pending_request(values.gstin);
				if (!req) {
					frappe.msgprint(__("No pending OTP request for {0}. Use Request OTP first.", [values.gstin]));
					return;
				}
				d.hide();
				otp_dialog(frm, values.gstin, req.name, req.otp_sent_to);
			},
		});
		d.show();
	}

	function otp_dialog(frm, gstin, otp_request_id, sent_to) {
		const d = new frappe.ui.Dialog({
			title: __("Enter OTP for {0}", [gstin]),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p class="text-muted">${__("OTP sent to {0}. Request: {1}. It is valid for 10 minutes.", [
						frappe.utils.escape_html(sent_to || "-"),
						frappe.utils.escape_html(otp_request_id),
					])}</p>`,
				},
				{ fieldname: "otp", fieldtype: "Data", label: __("OTP"), reqd: 1 },
			],
			primary_action_label: __("Verify"),
			primary_action(values) {
				const otp = String(values.otp || "").trim();
				if (!/^\d+$/.test(otp)) {
					frappe.msgprint(__("OTP must be a number"));
					return;
				}
				d.hide();
				frappe.call({
					method: "litwatch.api.gstin.verify_gstin_otp",
					args: { gstin, otpRequestId: otp_request_id, otp },
					freeze: true,
					freeze_message: __("Verifying OTP with the GST portal..."),
					callback: (r) => {
						const res = r.message || {};
						frm.reload_doc();
						frappe.msgprint({
							title: __("OTP verified"),
							indicator: "green",
							message: status_message(gstin, res) + " " + __("The OTP is saved in this record."),
						});
					},
				});
			},
		});
		d.show();
	}

	async function decide(frm, action) {
		const rows = (await business_gstins(frm)).filter((r) => r.consent_status === "verifying");
		if (!rows.length) {
			frappe.msgprint(__("No GSTIN of this Business is waiting for verification."));
			return;
		}
		const fields = [gstin_field(rows)];
		if (action === "reject") {
			fields.push({ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 });
		}
		const d = new frappe.ui.Dialog({
			title: action === "approve" ? __("Approve GSTIN connection") : __("Reject GSTIN connection"),
			fields,
			primary_action_label: action === "approve" ? __("Approve") : __("Reject"),
			primary_action(values) {
				d.hide();
				frappe.call({
					method:
						action === "approve"
							? "litwatch.api.gstin.approve_gstin_connection"
							: "litwatch.api.gstin.reject_gstin_connection",
					args: action === "approve" ? { gstin: values.gstin } : { gstin: values.gstin, reason: values.reason },
					freeze: true,
					callback: (r) => {
						const res = r.message || {};
						frm.reload_doc();
						frappe.show_alert({
							message:
								action === "approve"
									? __("{0} connected until {1}", [values.gstin, res.validUntil || "-"])
									: __("{0} rejected; it is back to {1}", [values.gstin, res.consent]),
							indicator: action === "approve" ? "green" : "orange",
						});
					},
				});
			},
		});
		d.show();
	}
})();
