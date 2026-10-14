import frappe


def execute():
	"""Existing businesses are approved; approval switches keep today's behaviour
	(business approval off, GSTIN approval on); account emails on for new GST Users.
	Existing GST Users are marked as already emailed so nobody gets a surprise email."""
	if frappe.db.has_column("Business", "approval_status"):
		frappe.db.sql(
			"UPDATE `tabBusiness` SET approval_status = 'Approved' WHERE IFNULL(approval_status, '') = ''"
		)
	defaults = {
		"require_business_approval": 0,
		"require_gstin_approval": 1,
		"send_account_email": 1,
		"registration_path": "/register",
		"invite_valid_days": 14,
		"default_reminder_days": "7,3,1",
		"consent_expiry_days": 30,
	}
	for field, value in defaults.items():
		if frappe.db.get_single_value("Sync Settings", field) in (None, ""):
			frappe.db.set_single_value("Sync Settings", field, value)
	if frappe.db.has_column("GST User", "account_email_sent_on"):
		frappe.db.sql(
			"UPDATE `tabGST User` SET account_email_sent_on = creation WHERE account_email_sent_on IS NULL"
		)
	frappe.db.commit()
