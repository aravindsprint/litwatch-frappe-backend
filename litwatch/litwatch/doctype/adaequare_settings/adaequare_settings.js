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
			show_client_secret(frm);
			if (frm.is_new() || !frm.doc.business) return;

			frm.add_custom_button(__("Request OTP"), () => request_otp(frm), GROUP);
			frm.add_custom_button(__("Verify OTP"), () => verify_otp(frm), GROUP);
			frm.add_custom_button(__("Resend OTP"), () => resend_otp(frm), GROUP);
			frm.add_custom_button(__("Approve connection"), () => decide(frm, "approve"), GROUP);
			frm.add_custom_button(__("Reject connection"), () => decide(frm, "reject"), GROUP);
		},
	});

	// Client Secret is a Password field (shown as dots). An eye icon under it shows / hides the saved
	// value, with a Copy button, for System Managers (litwatch.api.api_keys.get_gsp_client_secret).
	function show_client_secret(frm) {
		const field = frm.fields_dict.client_secret;
		if (!field) return;
		field.$wrapper.find(".litwatch-client-secret").remove();
		if (frm.is_new() || !frappe.user.has_role("System Manager")) return;
		litwatch_secret_toggle(
			field,
			"litwatch-client-secret",
			{ method: "litwatch.api.api_keys.get_gsp_client_secret", args: { name: frm.doc.name }, key: "client_secret" },
			[[__("Copy secret"), (s) => s]]
		);
	}
	// Eye toggle under a Password field: masked by default; the eye fetches the saved value and shows /
	// hides it. Copy buttons fetch it too, so the secret never sits in the page until asked for.
	function litwatch_secret_toggle(field, cls, fetch_secret, copies) {
		field.$wrapper.find("." + cls).remove();
		const EYE = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
		const EYE_OFF = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
		let secret = null;
		const get = async () => {
			if (secret === null) {
				const r = await frappe.call({ method: fetch_secret.method, args: fetch_secret.args });
				secret = (r.message && r.message[fetch_secret.key]) || "";
				if (!secret) frappe.show_alert({ message: __("No secret saved"), indicator: "orange" });
			}
			return secret;
		};
		const $box = $(`
			<div class="${cls}" style="margin-top: 8px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap">
				<div class="ls-secret-text" style="flex: 1; min-width: 200px; font-family: var(--font-family-monospace, monospace);
					padding: 6px 10px; background: var(--control-bg); border-radius: var(--border-radius); word-break: break-all">••••••••••••••••</div>
				<button class="btn btn-xs btn-default ls-eye" title="${__("Show")}">${EYE}</button>
			</div>`);
		let shown = false;
		$box.find(".ls-eye").on("click", async () => {
			if (!shown) {
				const s = await get();
				if (!s) return;
				$box.find(".ls-secret-text").text(s).css("user-select", "all");
			} else {
				$box.find(".ls-secret-text").text("••••••••••••••••").css("user-select", "none");
			}
			shown = !shown;
			$box.find(".ls-eye").html(shown ? EYE_OFF : EYE).attr("title", shown ? __("Hide") : __("Show"));
		});
		(copies || []).forEach(([label, make]) => {
			const $b = $(`<button class="btn btn-xs btn-default">${label}</button>`);
			$b.on("click", async () => {
				const s = await get();
				if (s) frappe.utils.copy_to_clipboard(make(s));
			});
			$box.append($b);
		});
		field.$wrapper.append($box);
	}

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
				otp_dialog(frm, values.gstin, req.name, req.otp_sent_to, req.expires_at);
			},
		});
		d.show();
	}

	async function otp_expiry(otp_request_id, expires_at) {
		// Deadline in the browser's clock: the request's expires_at measured against the server's "now",
		// so a wrong time zone or clock on the user's computer doesn't change the countdown.
		if (!expires_at) {
			const r = await frappe.db.get_value("GST OTP Request", otp_request_id, "expires_at");
			expires_at = r && r.message && r.message.expires_at;
		}
		if (!expires_at) return Date.now() + 10 * 60 * 1000;
		const left = frappe.datetime.str_to_obj(expires_at) - frappe.datetime.str_to_obj(frappe.datetime.now_datetime());
		return Date.now() + Math.max(left, 0);
	}

	function resend(frm, gstin) {
		frappe.call({
			method: "litwatch.api.gstin.resend_gstin_otp",
			args: { gstin },
			freeze: true,
			freeze_message: __("Requesting a new OTP..."),
			callback: (r) => after_request(frm, gstin, r),
		});
	}

	async function otp_dialog(frm, gstin, otp_request_id, sent_to, expires_at) {
		const deadline = await otp_expiry(otp_request_id, expires_at);
		let timer = null;

		const d = new frappe.ui.Dialog({
			title: __("Enter OTP for {0}", [gstin]),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p class="text-muted">${__("OTP sent to {0}. Request: {1}.", [
						frappe.utils.escape_html(sent_to || "-"),
						frappe.utils.escape_html(otp_request_id),
					])}</p>`,
				},
				{ fieldname: "countdown", fieldtype: "HTML" },
				{ fieldname: "otp", fieldtype: "Data", label: __("OTP"), reqd: 1 },
			],
			primary_action_label: __("Verify"),
			primary_action(values) {
				if (Date.now() >= deadline) {
					frappe.msgprint(__("This OTP has expired. Use Resend OTP to get a new one."));
					return;
				}
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
			secondary_action_label: __("Resend OTP"),
			secondary_action() {
				d.hide();
				resend(frm, gstin);
			},
		});

		const box = d.fields_dict.countdown.$wrapper;
		const tick = () => {
			const left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
			if (left <= 0) {
				clearInterval(timer);
				box.html(
					`<div class="alert alert-danger" style="margin-bottom:8px">${__(
						"OTP expired. Use Resend OTP to get a new one."
					)}</div>`
				);
				d.get_primary_btn().prop("disabled", true);
				return;
			}
			const mm = String(Math.floor(left / 60)).padStart(2, "0");
			const ss = String(left % 60).padStart(2, "0");
			const colour = left <= 60 ? "var(--red-600, #c0392b)" : left <= 180 ? "var(--orange-600, #d35400)" : "var(--text-color)";
			box.html(
				`<div style="display:flex;align-items:baseline;gap:8px;margin-bottom:8px">
					<span class="text-muted">${__("Time left")}</span>
					<span style="font-size:20px;font-weight:600;font-variant-numeric:tabular-nums;color:${colour}">${mm}:${ss}</span>
				</div>`
			);
		};
		tick();
		timer = setInterval(tick, 1000);
		d.onhide = () => clearInterval(timer);
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
