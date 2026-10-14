# Copyright (c) 2026, Shahina and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class AdaequareSettings(Document):
	# One record per Business (autoname "field:business"): the business's GSP app
	# (Client ID, Secret, cached Access Token) and its latest portal OTP.

	def validate(self):
		if self.business:
			self.business = str(self.business).strip()
			self.business_name = frappe.db.get_value("Business", self.business, "business_name")
		if self.otp:
			self.otp = str(self.otp).strip()
			if not self.otp.isdigit():
				frappe.throw(_("OTP must be a number"))
