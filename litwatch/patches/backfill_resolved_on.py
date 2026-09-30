import frappe


def execute():
	"""Existing Resolved notices have no resolved_on, so trend charts show 0 resolved.
	Use the last modified time as the best available approximation."""
	if frappe.db.table_exists("Litigation Notice"):  # removed later
		frappe.db.sql(
			"""
			UPDATE `tabLitigation Notice`
			SET resolved_on = modified
			WHERE status = 'Resolved' AND resolved_on IS NULL
			"""
		)
	frappe.db.sql(
		"""
		UPDATE `tabGST Registration`
		SET consent_status = 'inactive'
		WHERE consent_status IS NULL OR consent_status = ''
		"""
	)

	# Seed Sync Settings defaults (Single doctype defaults are not stored until first save).
	settings = frappe.get_single("Sync Settings")
	if not settings.daily_call_cap:
		settings.daily_call_cap = 2000
	if not settings.otp_validity_minutes:
		settings.otp_validity_minutes = 10
	settings.save(ignore_permissions=True)
