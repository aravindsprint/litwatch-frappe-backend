import frappe

from litwatch.notice_files import attach_notice_files


def execute():
	"""Attach every Notice's document_files to the Notice (AI Layer got 403 on unattached PDFs)."""
	for name in frappe.get_all("Notice", pluck="name"):
		attach_notice_files(frappe.get_doc("Notice", name))
