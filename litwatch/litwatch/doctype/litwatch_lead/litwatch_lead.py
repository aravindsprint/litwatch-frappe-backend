# Copyright (c) 2026, Shahina and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class LitWatchLead(Document):
	# Kept after conversion (status Onboard, user set), so the leads can feed a CRM later.

	def validate(self):
		self.first_name = (self.first_name or "").strip()
		self.last_name = (self.last_name or "").strip() or None
		self.full_name = " ".join(p for p in [self.first_name, self.last_name] if p)
		if self.email:
			self.email = self.email.strip().lower()
			frappe.utils.validate_email_address(self.email, throw=True)
		if self.practice_type != "Firm":
			self.firm_name = None
		if self.client_count and self.client_count < 0:
			frappe.throw(_("How Many Clients can't be negative"))
		if frappe.flags.in_import and not self.source:
			self.source = "Excel import"
