import frappe


def execute():
	"""Remove only the Litigation Notice doctype and its table.
	Links to it on other doctypes were changed to plain Data fields, so their values are kept."""
	if frappe.db.exists("DocType", "Litigation Notice"):
		frappe.delete_doc("DocType", "Litigation Notice", force=True, ignore_permissions=True, ignore_missing=True)
	frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabLitigation Notice`")
	frappe.db.delete("App Notification", {"reference_doctype": "Litigation Notice"})
	frappe.db.commit()
