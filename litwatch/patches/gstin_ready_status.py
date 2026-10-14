import frappe


def execute():
	"""New GSTIN status "ready". Existing active Adaequare Settings with a Client ID are treated as
	verified (they were already in use), and their businesses' inactive GSTINs become ready.
	Plain SQL: no notifications are sent for this backfill."""
	if not frappe.db.has_column("Adaequare Settings", "credentials_verified"):
		return
	businesses = frappe.get_all(
		"Adaequare Settings",
		filters={"is_active": 1, "client_id": ["is", "set"]},
		pluck="name",
	)
	if not businesses:
		return
	frappe.db.sql(
		"UPDATE `tabAdaequare Settings` SET credentials_verified = 1 WHERE name IN %(b)s",
		{"b": businesses},
	)
	gstins = frappe.db.sql_list(
		"""SELECT name FROM `tabGSTIN`
		WHERE business_id IN %(b)s AND IFNULL(consent_status, '') IN ('', 'inactive')""",
		{"b": businesses},
	)
	if gstins:
		frappe.db.sql("UPDATE `tabGSTIN` SET consent_status = 'ready' WHERE name IN %(g)s", {"g": gstins})
	frappe.db.commit()
	print(f"GSTIN ready status: {len(businesses)} Adaequare Settings marked verified, {len(gstins)} GSTIN(s) inactive -> ready {gstins}")
