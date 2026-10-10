# Copyright (c) 2026, Shahina and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

SHARED_NAME = "LitWatch GSP"


class AdaequareSettings(Document):
	def autoname(self):
		# The shared GSP app is "LitWatch GSP"; a client-specific app is named by its GSTIN.
		if self.is_shared:
			self.name = SHARED_NAME
		else:
			self.name = (self.default_gstin or "").strip().upper()

	def validate(self):
		if self.default_gstin:
			self.default_gstin = self.default_gstin.strip().upper()
		if self.is_shared and not self.is_new() and self.name != SHARED_NAME:
			frappe.throw(_("Rename this record to \"{0}\" to make it the shared GSP app.").format(SHARED_NAME))
		if not self.is_shared and self.name == SHARED_NAME:
			frappe.throw(_("\"{0}\" is the shared GSP app; keep Shared ticked.").format(SHARED_NAME))
