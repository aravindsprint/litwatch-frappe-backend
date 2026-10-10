import frappe


def execute():
	"""Adaequare Settings records are now named by their Default GSTIN."""
	for row in frappe.get_all("Adaequare Settings", fields=["name", "default_gstin"], limit_page_length=0):
		gstin = (row.default_gstin or "").strip().upper()
		if not gstin or row.name == gstin or frappe.db.exists("Adaequare Settings", gstin):
			continue
		frappe.rename_doc("Adaequare Settings", row.name, gstin, force=True)
	frappe.db.commit()
