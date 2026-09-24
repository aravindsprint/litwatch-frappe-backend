# Copyright (c) 2026, Shahina and contributors
# For license information, please see license.txt

from frappe.model.document import Document
from frappe.utils import now_datetime


class LitigationNotice(Document):
	def validate(self):
		self.set_resolved_on()
		self.track_status_change()

	def set_resolved_on(self):
		# resolved_on drives the "resolved" series in trend charts,
		# so keep it in step with status.
		if self.status == "Resolved":
			if not self.resolved_on:
				self.resolved_on = now_datetime()
		else:
			self.resolved_on = None

	def track_status_change(self):
		if self.is_new():
			return
		before = self.get_doc_before_save()
		if before and before.status != self.status:
			self.append(
				"timeline",
				{
					"at": now_datetime(),
					"event": f"Status changed from {before.status or '-'} to {self.status}",
				},
			)
