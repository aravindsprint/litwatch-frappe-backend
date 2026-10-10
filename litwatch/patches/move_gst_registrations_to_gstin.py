import frappe
from frappe.utils.password import get_decrypted_password, set_encrypted_password


def execute():
	"""Move GST Registration records (and their Clients) into GSTIN and Business,
	which the GST notice flow now uses. GST Registration and Client are left as they are."""
	if not frappe.db.table_exists("GST Registration"):
		return

	business_for_client = {}
	for reg in frappe.get_all("GST Registration", fields=["*"], limit_page_length=0):
		client_name = frappe.db.get_value("Client", reg.client, "client_name") or reg.client
		business_id = business_for_client.get(reg.client)
		if not business_id:
			business_id = frappe.db.get_value("Business", {"business_name": client_name}, "name")
		if not business_id:
			client = frappe.db.get_value("Client", reg.client, ["pan", "sector"], as_dict=True) or {}
			business_id = frappe.get_doc(
				{
					"doctype": "Business",
					"business_name": client_name,
					"pan": client.get("pan"),
					"sector": client.get("sector"),
					"status": "Active",
				}
			).insert(ignore_permissions=True).name
		business_for_client[reg.client] = business_id

		values = {
			"business_id": str(business_id),
			"state": reg.state,
			"city": reg.city,
			"consent_status": reg.consent_status or "inactive",
			"valid_until": reg.valid_until,
			"last_checked": reg.last_checked,
			"portal_user_id": reg.portal_user_id,
		}
		if frappe.db.exists("GSTIN", reg.name):
			existing_owner = frappe.db.get_value("GSTIN", reg.name, "business_id")
			if existing_owner and str(existing_owner) != str(business_id):
				continue  # already set up under another business; leave it
			frappe.db.set_value("GSTIN", reg.name, values, update_modified=False)
		else:
			frappe.get_doc({"doctype": "GSTIN", "gstin": reg.name, **values}).insert(ignore_permissions=True)

		otp = get_decrypted_password("GST Registration", reg.name, "portal_otp", raise_exception=False)
		if otp:
			set_encrypted_password("GSTIN", reg.name, otp, "portal_otp")
			frappe.db.set_value("GSTIN", reg.name, "portal_otp", "*" * 8, update_modified=False)

		business = frappe.get_doc("Business", business_id)
		if not any(row.gstin == reg.name for row in business.get("gstins") or []):
			business.append("gstins", {"gstin": reg.name})
			business.save(ignore_permissions=True)

	# Notices imported earlier carry the Client key as business_id; point them at the Business.
	for client, business_id in business_for_client.items():
		frappe.db.sql(
			"UPDATE `tabNotice` SET business_id = %s WHERE business_id = %s AND IFNULL(portal_ref_id, '') != ''",
			(str(business_id), client),
		)

	frappe.db.commit()
