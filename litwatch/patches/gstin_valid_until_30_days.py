import frappe
from frappe.utils import add_days, add_months, getdate


def execute():
	"""Valid Until was activation + 12 months; it is now activation + 30 days (consent_valid_days).
	For GSTINs still set the old way, recover the activation date (valid_until - 12 months) and use
	+30 days. The daily job then expires those whose 30 days have passed."""
	frappe.reload_doc("litwatch", "doctype", "sync_settings")
	limit = add_days(getdate(), 31)
	for g in frappe.get_all("GSTIN", filters={"valid_until": [">", limit]}, fields=["name", "valid_until"]):
		activated = add_months(getdate(g.valid_until), -12)
		frappe.db.set_value("GSTIN", g.name, "valid_until", add_days(activated, 30), update_modified=False)
