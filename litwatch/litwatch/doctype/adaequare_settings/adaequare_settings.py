# Copyright (c) 2026, Shahina and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class AdaequareSettings(Document):
	# Named by the GSTIN field (autoname "field:gstin")

	def validate(self):
		if self.gstin:
			self.gstin = self.gstin.strip().upper()
		if self.otp:
			self.otp = str(self.otp).strip()
			if not self.otp.isdigit():
				frappe.throw(_("OTP must be a number"))
