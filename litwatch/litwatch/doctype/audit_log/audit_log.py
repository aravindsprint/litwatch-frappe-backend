# Copyright (c) 2026, Shahina and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class AuditLog(Document):
	"""Append-only: rows can be created but never edited or deleted."""

	def has_permission(self, permtype="read", *, debug=False, user=None):
		# Per-user scoping (litwatch/scope.py); also applies to Administrator / the shared API key
		from litwatch.scope import doc_in_scope

		if not doc_in_scope(self):
			return False
		return super().has_permission(permtype, debug=debug, user=user)

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
