# Copyright (c) 2026, Shahina and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class Business(Document):
	def has_permission(self, permtype="read", *, debug=False, user=None):
		# Per-user scoping (litwatch/scope.py); also applies to Administrator / the shared API key
		from litwatch.scope import doc_in_scope

		if not doc_in_scope(self):
			return False
		return super().has_permission(permtype, debug=debug, user=user)
	def validate(self):
		seen = set()
		rows = []
		for row in self.get("gstins") or []:
			if not row.gstin or row.gstin in seen:
				continue  # drop blanks and duplicates
			seen.add(row.gstin)
			owner = frappe.db.get_value("GSTIN", row.gstin, "business_id")
			if owner and str(owner) != str(self.name):
				frappe.throw(_("GSTIN {0} already belongs to Business {1}").format(row.gstin, owner))
			rows.append(row)
		if len(rows) != len(self.get("gstins") or []):
			self.set("gstins", rows)

	def after_insert(self):
		# A client (or the frontend acting for one) creating a business keeps seeing it.
		from litwatch.scope import link_business_to_scope_user

		link_business_to_scope_user(self.name)

	def on_update(self):
		# Keep GSTIN.business_id in step with this table (skip when GSTIN is the one syncing us).
		if self.flags.from_gstin_sync:
			return
		before = self.get_doc_before_save()
		old = {row.gstin for row in (before.get("gstins") if before else []) or []}
		new = {row.gstin for row in self.get("gstins") or []}
		me = str(self.name)
		for gstin in new:
			if str(frappe.db.get_value("GSTIN", gstin, "business_id") or "") != me:
				frappe.db.set_value("GSTIN", gstin, "business_id", me)
		for gstin in old - new:
			if str(frappe.db.get_value("GSTIN", gstin, "business_id") or "") == me:
				frappe.db.set_value("GSTIN", gstin, "business_id", None)

	def on_trash(self):
		me = str(self.name)
		for row in self.get("gstins") or []:
			if str(frappe.db.get_value("GSTIN", row.gstin, "business_id") or "") == me:
				frappe.db.set_value("GSTIN", row.gstin, "business_id", None)
