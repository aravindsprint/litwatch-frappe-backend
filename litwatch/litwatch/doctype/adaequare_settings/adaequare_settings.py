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
