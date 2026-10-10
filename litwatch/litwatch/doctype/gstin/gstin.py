# Copyright (c) 2026, Shahina and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document

GSTIN_RE = re.compile(r"[0-9]{2}[A-Z0-9]{13}")


class GSTIN(Document):
	def before_insert(self):
		# Upper-case before the record is named after it.
		self.gstin = (self.gstin or "").strip().upper()

	def validate(self):
		if not GSTIN_RE.fullmatch(self.gstin or ""):
			frappe.throw(_("Invalid GSTIN: {0}").format(self.gstin))
		if self.business_id:
			self.business_id = str(self.business_id).strip()
			if not frappe.db.exists("Business", self.business_id):
				frappe.throw(_("Business {0} not found").format(self.business_id))

	def on_update(self):
		# Keep Business.gstins in step with business_id (skip when Business is the one syncing us).
		if self.flags.from_business_sync:
			return
		before = self.get_doc_before_save()
		old = str(before.business_id) if before and before.business_id else None
		new = str(self.business_id) if self.business_id else None
		if old and old != new:
			remove_from_business(old, self.name)
		if new:
			add_to_business(new, self.name)

	def on_trash(self):
		if self.business_id:
			remove_from_business(str(self.business_id), self.name)


def add_to_business(business_id, gstin):
	if not frappe.db.exists("Business", business_id):
		return
	business = frappe.get_doc("Business", business_id)
	if any(row.gstin == gstin for row in business.get("gstins") or []):
		return
	business.append("gstins", {"gstin": gstin})
	business.flags.from_gstin_sync = True
	business.save(ignore_permissions=True)


def remove_from_business(business_id, gstin):
	if not frappe.db.exists("Business", business_id):
		return
	business = frappe.get_doc("Business", business_id)
	rows = [row for row in business.get("gstins") or [] if row.gstin != gstin]
	if len(rows) == len(business.get("gstins") or []):
		return
	business.set("gstins", rows)
	business.flags.from_gstin_sync = True
	business.save(ignore_permissions=True)
