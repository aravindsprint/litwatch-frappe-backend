import frappe


def execute():
	"""Client APIs now run on Business. Make sure every Client has a Business
	(matched by name, as the GSTIN migration did), copy the client fields, and
	re-point active-client user defaults and imported notices to the Business ID."""
	if not frappe.db.table_exists("Client"):
		return

	fields = ["name", "client_name", "short_name", "pan", "sector", "status",
		"onboarding_stage", "onboarding_date", "firm_profile", "default_consultant", "notes"]
	for c in frappe.get_all("Client", fields=fields, limit_page_length=0):
		business_name = c.client_name or c.name
		business_id = frappe.db.get_value("Business", {"business_name": business_name}, "name")
		if not business_id:
			business_id = frappe.get_doc({"doctype": "Business", "business_name": business_name}).insert(
				ignore_permissions=True
			).name
		business_id = str(business_id)

		current = frappe.db.get_value(
			"Business", business_id,
			["short_name", "pan", "sector", "status", "onboarding_stage", "onboarding_date",
				"firm_profile", "default_consultant", "notes"],
			as_dict=True,
		)
		values = {}
		for field, value in (
			("short_name", c.short_name or c.name),
			("pan", c.pan), ("sector", c.sector), ("status", c.status),
			("onboarding_stage", c.onboarding_stage), ("onboarding_date", c.onboarding_date),
			("firm_profile", c.firm_profile), ("default_consultant", c.default_consultant),
			("notes", c.notes),
		):
			if value and (not current.get(field) or field in ("onboarding_stage", "status")):
				values[field] = value
		if values:
			frappe.db.set_value("Business", business_id, values, update_modified=False)

		# Active client stored per user as the Client key -> Business ID
		frappe.db.sql(
			"UPDATE `tabDefaultValue` SET defvalue = %s WHERE defkey = 'active_client' AND defvalue = %s",
			(business_id, c.name),
		)
		# Notices imported before the move carried the Client key as business_id
		frappe.db.sql(
			"UPDATE `tabNotice` SET business_id = %s WHERE business_id = %s",
			(business_id, c.name),
		)

	frappe.db.commit()
	frappe.clear_cache()
