import frappe


def _old_default_gstin(name):
	# default_gstin was removed from the doctype; migrate keeps the column, so read it with SQL
	if not frappe.db.has_column("Adaequare Settings", "default_gstin"):
		return None
	value = frappe.db.sql("select default_gstin from `tabAdaequare Settings` where name=%s", name)
	return (value[0][0] or "").strip().upper() if value and value[0][0] else None


def execute():
	"""Adaequare Settings is now named by its GSTIN field (Link to GSTIN).
	Fill the new gstin field and rename each record to its GSTIN. A record whose
	GSTIN can't be worked out (e.g. the old shared "LitWatch GSP") is left as is
	and listed, so it can be fixed by hand."""
	for name in frappe.get_all("Adaequare Settings", pluck="name", order_by="creation asc", limit_page_length=0):
		current = frappe.db.get_value("Adaequare Settings", name, "gstin")
		candidates = [current, name.strip().upper(), _old_default_gstin(name)]
		gstin = next((g for g in candidates if g and frappe.db.exists("GSTIN", g)), None)

		if not gstin:
			print(f"Adaequare Settings \"{name}\": no GSTIN found - open it, set GSTIN and rename it to that GSTIN")
			continue
		if name != gstin and frappe.db.exists("Adaequare Settings", gstin):
			print(f"Adaequare Settings \"{name}\": a record for {gstin} already exists - left as is")
			continue

		frappe.db.set_value("Adaequare Settings", name, "gstin", gstin, update_modified=False)
		if name != gstin:
			frappe.rename_doc("Adaequare Settings", name, gstin, force=True)
			print(f"Adaequare Settings \"{name}\" renamed to {gstin}")
	frappe.db.commit()
