# Copyright (c) 2026, Shahina and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class AdaequareSettings(Document):
	# One record per Business (autoname "field:business"): the business's GSP app
	# (Client ID, Secret, cached Access Token) and its latest portal OTP.

	def has_permission(self, permtype="read", *, debug=False, user=None):
		# Per-user scoping: a GST User sees only their own Businesses' records
		# (hooks are skipped for Administrator, the frontend's shared key).
		from litwatch.scope import doc_in_scope

		if not doc_in_scope(self):
			return False
		return super().has_permission(permtype, debug=debug, user=user)

	def validate(self):
		if self.business:
			self.business = str(self.business).strip()
			self.business_name = frappe.db.get_value("Business", self.business, "business_name")
		if self.otp:
			self.otp = str(self.otp).strip()
			if not self.otp.isdigit():
				frappe.throw(_("OTP must be a number"))
		# Before the password is stored, a changed secret holds the typed value (else only asterisks).
		secret = str(self.client_secret or "")
		self.flags.credentials_changed = (
			self.is_new()
			or self.has_value_changed("client_id")
			or self.has_value_changed("base_url")
			or self.has_value_changed("environment")
			or bool(secret and set(secret) != {"*"})
		)

	def on_update(self):
		"""Check the credentials, then move the Business's GSTINs inactive -> ready (or back).
		GSTINs of a business that is not approved stay inactive (litwatch/gstin_status.py)."""
		from litwatch.gstin_status import business_configured, refresh_business_gstins

		if self.flags.credentials_changed:
			self._clear_token()
		ok, error = self._verify_credentials()
		self.db_set("credentials_verified", 1 if ok else 0, update_modified=False)

		moved = refresh_business_gstins(self.business)
		if ok and moved and business_configured(self.business):
			frappe.msgprint(
				_("{0} GSTIN(s) of this business are now Ready to connect: {1}").format(len(moved), ", ".join(moved)),
				indicator="green",
			)
		elif ok and frappe.db.get_value("Business", self.business, "approval_status") in ("Pending", "Rejected"):
			frappe.msgprint(
				_("Credentials verified. The business is not approved yet, so its GSTINs stay Not set up until it is."),
				indicator="orange",
			)
		elif error:
			frappe.msgprint(
				_("The GSP credentials did not work, so the GSTINs stay Not set up: {0}").format(error),
				title=_("Credentials not verified"),
				indicator="orange",
			)

	def on_trash(self):
		from litwatch.gstin_status import move_business_gstins

		move_business_gstins(self.business, "ready", "inactive")

	def _clear_token(self):
		from frappe.utils.password import remove_encrypted_password

		remove_encrypted_password("Adaequare Settings", self.name, "access_token")
		self.db_set({"access_token": None, "token_expires_at": None}, update_modified=False)

	def _verify_credentials(self):
		"""(ok, error). Fetches a GSP token with these credentials; mock mode needs only the fields."""
		from litwatch.api import gst_portal

		if not (self.is_active and self.client_id and self.get_password("client_secret", raise_exception=False)):
			return False, None
		if gst_portal.is_mock():
			return True, None
		try:
			gst_portal._get_token(self, force=bool(self.flags.credentials_changed))
			return True, None
		except Exception as e:
			if getattr(frappe, "clear_last_message", None):
				frappe.clear_last_message()  # the error is shown once, by on_update
			return False, str(e) or e.__class__.__name__
