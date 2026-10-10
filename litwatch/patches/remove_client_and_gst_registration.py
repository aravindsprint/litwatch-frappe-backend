import frappe


def execute():
	"""Client and GST Registration are replaced by Business and GSTIN (their data was
	moved by the earlier patches). Remove the two doctypes and their tables."""
	for dt in ("GST Registration", "Client"):
		if frappe.db.exists("DocType", dt):
			frappe.delete_doc("DocType", dt, force=True, ignore_permissions=True, ignore_missing=True)
		frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{dt}`")

	# Child rows that belonged to Client (already copied to Business)
	for child in ("Client Contact", "Client Address"):
		if frappe.db.table_exists(child):
			frappe.db.delete(child, {"parenttype": "Client"})
	frappe.db.commit()
