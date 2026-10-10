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


def normalise_business_selects():
	"""Client data copied onto Business without validation may hold values that are no
	longer valid options (e.g. onboarding stage "Pending"). Reset those to the first option."""
	meta = frappe.get_meta("Business")
	for fieldname in ("onboarding_stage", "status"):
		df = meta.get_field(fieldname)
		if not df:
			continue
		options = [o for o in (df.options or "").split("\n") if o]
		if not options:
			continue
		bad = frappe.db.sql(
			f"""SELECT name, `{fieldname}` FROM `tabBusiness`
			WHERE IFNULL(`{fieldname}`, '') != '' AND `{fieldname}` NOT IN %(options)s""",
			{"options": options},
		)
		for name, value in bad:
			print(f"Business {name}: {fieldname} '{value}' is not a valid option, set to '{options[0]}'")
			frappe.db.set_value("Business", name, fieldname, options[0], update_modified=False)


def execute():
	if not frappe.db.table_exists("Client"):
		return
	normalise_business_selects()
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
			skip = ("name", "parent", "parenttype", "parentfield", "idx", "owner", "creation", "modified", "modified_by", "docstatus", "doctype")
			existing = [
				{k: v for k, v in r.as_dict().items() if k not in skip}
				for r in business.get(table_field) or []
			]
			for row in rows:
				data = {k: v for k, v in row.items() if k not in skip}
				if any(all(e.get(k) == v for k, v in data.items()) for e in existing):
					continue  # already copied (re-run safe)
				business.append(table_field, data)
				changed = True
		if changed:
			business.flags.from_gstin_sync = True  # no GSTIN changes here
			business.flags.ignore_validate = True  # copying data as-is
			business.flags.ignore_mandatory = True
			business.flags.ignore_links = True
			business.save(ignore_permissions=True)

	frappe.db.commit()
