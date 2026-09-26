# Copyright (c) 2026, Shahina and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class OnboardingProgress(Document):
	def validate(self):
		self.ensure_unique()
		self.set_timestamps()

	def ensure_unique(self):
		# One progress row per user per checklist item.
		existing = frappe.db.get_value(
			"Onboarding Progress",
			{"user": self.user, "checklist_item": self.checklist_item, "name": ["!=", self.name]},
			"name",
		)
		if existing:
			frappe.throw(
				_("Progress for {0} / {1} already exists ({2})").format(self.user, self.checklist_item, existing)
			)

	def set_timestamps(self):
		if self.status in ("In progress", "Done") and not self.started_on:
			self.started_on = now_datetime()
		if self.status == "Done":
			if not self.completed_on:
				self.completed_on = now_datetime()
		else:
			self.completed_on = None
