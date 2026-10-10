import frappe

# (doctype, field) whose link moved from Client to Business
LINKS = [
	("AI Copilot Conversation", "client"),
	("App Notification", "client"),
	("Audit Log", "client"),
	("Client Document", "client"),
	("Client Onboarding Pipeline", "converted_client"),
	("Filing", "client"),
	("Litigation Case", "client"),
	("Payment", "client"),
	("Report Request", "client"),
	("Review Queue Item", "client"),
	("Support Ticket", "client"),
]


def client_to_business_map():
	"""Client key -> Business ID, matching by name as the earlier migrations did."""
	mapping = {}
	for c in frappe.get_all("Client", fields=["name", "client_name"], limit_page_length=0):
		business_id = frappe.db.get_value("Business", {"business_name": c.client_name or c.name}, "name")
		if business_id:
			mapping[c.name] = str(business_id)
	return mapping


def execute():
	if not frappe.db.table_exists("Client"):
		return
	mapping = client_to_business_map()

	# 1. Re-point every link value from the Client key to the Business ID
	for doctype, field in LINKS:
		if not frappe.db.table_exists(doctype) or not frappe.db.has_column(doctype, field):
			continue
		for client_key, business_id in mapping.items():
			frappe.db.sql(
				f"UPDATE `tab{doctype}` SET `{field}` = %s WHERE `{field}` = %s",
				(business_id, client_key),
			)

	# 2. Move each Client's contacts and addresses onto its Business
	for client_key, business_id in mapping.items():
		business = frappe.get_doc("Business", business_id)
		changed = False
		for child_doctype, table_field in (("Client Contact", "client_contacts"), ("Client Address", "client_addresses")):
			if not frappe.db.table_exists(child_doctype):
				continue
			rows = frappe.get_all(
				child_doctype,
				filters={"parenttype": "Client", "parent": client_key},
				fields=["*"],
				order_by="idx asc",
			)
			for row in rows:
				data = {k: v for k, v in row.items() if k not in (
					"name", "parent", "parenttype", "parentfield", "idx", "owner", "creation", "modified", "modified_by", "docstatus", "doctype"
				)}
				business.append(table_field, data)
				changed = True
		if changed:
			business.flags.from_gstin_sync = True  # no GSTIN changes here
			business.save(ignore_permissions=True)

	frappe.db.commit()
