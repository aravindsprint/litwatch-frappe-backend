// GSTIN list: colour each connection status; filter on "verifying" to see what waits for approval.
frappe.listview_settings["GSTIN"] = {
	add_fields: ["consent_status"],
	get_indicator(doc) {
		const map = {
			inactive: [__("Not set up"), "gray"],
			ready: [__("Ready to connect"), "blue"],
			pending: [__("OTP sent"), "yellow"],
			verifying: [__("Awaiting verification"), "orange"],
			active: [__("Connected"), "green"],
			expired: [__("Expired"), "red"],
		};
		const [label, color] = map[doc.consent_status || "inactive"] || [doc.consent_status, "gray"];
		return [label, color, "consent_status,=," + (doc.consent_status || "inactive")];
	},
};
