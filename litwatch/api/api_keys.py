# apps/litwatch/litwatch/api/api_keys.py
"""Show saved secrets again on desk forms: a user's API secret (User form) and a business's GSP
Client Secret (Adaequare Settings form).

Show a user's API secret again on the User form (Frappe shows it only once, right after
Generate Keys). The secret is stored encrypted, so it can be read back. Only System Managers
and the user themselves get it."""

import frappe
from frappe.utils.password import get_decrypted_password


@frappe.whitelist(methods=["GET", "POST"])
def get_api_secret(user=None):
	user = user or frappe.session.user
	me = frappe.session.user
	if me != user and me != "Administrator" and "System Manager" not in frappe.get_roles(me):
		return {}
	api_key = frappe.db.get_value("User", user, "api_key")
	if not api_key:
		return {}
	secret = get_decrypted_password("User", user, "api_secret", raise_exception=False)
	return {"api_key": api_key, "api_secret": secret} if secret else {}


@frappe.whitelist(methods=["GET", "POST"])
def get_gsp_client_secret(name=None):
	"""Adaequare Settings Client Secret, for System Managers only (never for a scoped GST User)."""
	from litwatch import scope

	me = frappe.session.user
	if me != "Administrator" and "System Manager" not in frappe.get_roles(me):
		return {}
	if scope.get_scope() is not None:  # request names a GST User: no GSP secrets
		return {}
	if not name or not frappe.db.exists("Adaequare Settings", name):
		return {}
	secret = get_decrypted_password("Adaequare Settings", name, "client_secret", raise_exception=False)
	return {"client_secret": secret} if secret else {}
