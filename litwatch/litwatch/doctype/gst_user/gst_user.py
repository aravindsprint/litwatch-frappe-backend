# Copyright (c) 2026, Shahina and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class GSTUser(Document):
	def has_permission(self, permtype="read", *, debug=False, user=None):
		# Per-user scoping (litwatch/scope.py); also applies to Administrator / the shared API key
		from litwatch.scope import doc_in_scope

		if not doc_in_scope(self):
			return False
		return super().has_permission(permtype, debug=debug, user=user)

	def validate(self):
		if not self.user_type:
			self.user_type = "Individual"
		self._check_scoped_change()

	def _check_scoped_change(self):
		"""A GST User acting as themselves (gstUser / own login) may not promote themselves to
		Consultant or add Businesses they cannot already see. Firm staff (unscoped) can."""
		from litwatch import scope

		if self.flags.ignore_permissions or self.is_new() or scope.get_scope() is None:
			return
		before = self.get_doc_before_save()
		if not before:
			return
		if (before.user_type or "Individual") != self.user_type:
			frappe.throw(_("Only firm staff can change the User Type"), frappe.PermissionError)
		allowed = set(scope.get_scope())
		added = {str(r.business) for r in self.businesses} - {str(r.business) for r in before.businesses}
		if added - allowed:
			frappe.throw(_("Not permitted to add Business {0}").format(", ".join(sorted(added - allowed))),
			             frappe.PermissionError)
