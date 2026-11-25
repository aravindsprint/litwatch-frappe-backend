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

	def validate(self):
		# An API save may not drop the notice's PDFs (document_files); see notice_files.keep_document_files
		from litwatch.notice_files import keep_document_files

		keep_document_files(self)

	def on_update(self):
		# PDFs in document_files must be attached to this Notice, or the AI Layer gets 403 on them
		from litwatch.notice_files import attach_notice_files

		attach_notice_files(self)
