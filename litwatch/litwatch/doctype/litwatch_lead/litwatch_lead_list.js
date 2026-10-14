frappe.listview_settings["LitWatch Lead"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const colours = { New: "blue", Hold: "yellow", Rejected: "red", Onboard: "green" };
		return [__(doc.status), colours[doc.status] || "gray", "status,=," + doc.status];
	},
};
