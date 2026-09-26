# Copyright (c) 2026, Shahina and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class AuditLog(Document):
	"""Append-only: rows can be created but never edited or deleted."""

	def validate(self):
		if not self.is_new():
			frappe.throw(_("Audit Log entries cannot be edited"), frappe.PermissionError)
		if not self.log_time:
			self.log_time = now_datetime()
		if not self.user:
			self.user = frappe.session.user
		if not self.actor:
			self.actor = frappe.utils.get_fullname(self.user)

	def on_trash(self):
		frappe.throw(_("Audit Log entries cannot be deleted"), frappe.PermissionError)
