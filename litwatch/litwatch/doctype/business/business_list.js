// Business list: approval status colours; filter Approval Status = Pending to see what waits.
frappe.listview_settings["Business"] = {
	add_fields: ["approval_status", "status"],
	get_indicator(doc) {
		const s = doc.approval_status || "Approved";
		if (s === "Pending") return [__("Pending approval"), "orange", "approval_status,=,Pending"];
		if (s === "Rejected") return [__("Rejected"), "red", "approval_status,=,Rejected"];
		return [__(doc.status || "Approved"), doc.status === "Inactive" ? "gray" : "green", "status,=," + (doc.status || "")];
	},
};
