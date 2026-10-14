import frappe
from frappe.model.rename_doc import rename_doc


def execute():
	"""Adaequare Settings used to be named by GSTIN; now one record per Business.
	Move each old record to its GSTIN's Business ID."""
	if not frappe.db.has_column("Adaequare Settings", "business"):
		return
	has_gstin_col = frappe.db.has_column("Adaequare Settings", "gstin")
	# gstin is no longer in the doctype; migrate keeps the column, so read it with SQL
	cols = "name, business" + (", gstin" if has_gstin_col else "")
	for row in frappe.db.sql(f"select {cols} from `tabAdaequare Settings` order by creation", as_dict=True):
		if row.business and str(row.name) == str(row.business):
			continue
		gstin = str((row.get("gstin") if has_gstin_col else None) or row.name).strip().upper()
		business = row.business or frappe.db.get_value("GSTIN", gstin, "business_id")
		if not business or not frappe.db.exists("Business", business):
			print(f"Adaequare Settings {row.name}: GSTIN {gstin} has no Business, left as is - set Business by hand")
			continue
		business = str(business)
		if frappe.db.exists("Adaequare Settings", business):
			print(f"Adaequare Settings {row.name}: Business {business} already has a record, left as is - merge by hand")
			continue
		frappe.db.set_value("Adaequare Settings", row.name, "business", business, update_modified=False)
		rename_doc("Adaequare Settings", row.name, business, force=True, show_alert=False)
		print(f"Adaequare Settings {row.name} -> Business {business}")
	frappe.db.commit()
