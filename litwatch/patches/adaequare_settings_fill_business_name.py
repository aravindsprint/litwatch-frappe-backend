import frappe


def execute():
	"""Fill Business Name on Adaequare Settings records that have a Business but no name yet."""
	if not frappe.db.has_column("Adaequare Settings", "business_name"):
		return
	for row in frappe.get_all("Adaequare Settings", fields=["name", "business", "business_name"]):
		if row.business and not row.business_name:
			name = frappe.db.get_value("Business", row.business, "business_name")
			if name:
				frappe.db.set_value("Adaequare Settings", row.name, "business_name", name, update_modified=False)
				print(f"Adaequare Settings {row.name}: Business Name = {name}")
	frappe.db.commit()
