# Copyright (c) 2026, Litwatch and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class Notice(Document):
	def has_permission(self, permtype="read", *, debug=False, user=None):
		# Per-user scoping (litwatch/scope.py); also applies to Administrator / the shared API key
		from litwatch.scope import doc_in_scope

		if not doc_in_scope(self):
			return False
		return super().has_permission(permtype, debug=debug, user=user)
