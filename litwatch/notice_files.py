# apps/litwatch/litwatch/notice_files.py
"""Keep a Notice's PDFs (document_files) attached to the Notice.

A private file can be downloaded only by its owner, Administrator, or someone who can read the
document it is attached to. Files uploaded with /api/method/upload_file without doctype/docname
are attached to nothing, so the AI Layer (which reads them with its own API key) got 403
FRAPPE_FILE_DOWNLOAD_FAILED. On every Notice save, each document_files URL gets a File record
attached to that Notice: an unattached one is claimed, otherwise a new File record pointing at
the same stored file is added (no copy of the content).
"""

import frappe

DESK_SAVE = "frappe.desk.form.save.savedocs"


def attach_notice_files(notice):
	urls = {(row.file_name or "").strip() for row in notice.get("document_files") or []}
	for url in sorted(u for u in urls if u):
		_attach(notice, url)


def _attach(notice, url):
	files = frappe.get_all(
		"File",
		filters={"file_url": url},
		fields=["name", "attached_to_doctype", "attached_to_name", "is_private", "file_name", "file_size", "content_hash"],
		order_by="creation asc",
	)
	if not files:
		return  # external URL or file not uploaded: nothing to attach
	if any(f.attached_to_doctype == "Notice" and f.attached_to_name == notice.name for f in files):
		return
	free = next((f for f in files if not f.attached_to_doctype), None)
	if free:
		frappe.db.set_value(
			"File", free.name,
			{"attached_to_doctype": "Notice", "attached_to_name": notice.name, "attached_to_field": "document_files"},
			update_modified=False,
		)
		return
	src = files[0]
	frappe.get_doc({
		"doctype": "File",
		"file_url": url,
		"file_name": src.file_name,
		"is_private": src.is_private,
		"file_size": src.file_size,
		"content_hash": src.content_hash,
		"attached_to_doctype": "Notice",
		"attached_to_name": notice.name,
		"attached_to_field": "document_files",
	}).insert(ignore_permissions=True)


def removal_allowed():
	"""Rows may be removed from the desk form or through remove_notice_document, never by an API save."""
	return bool(frappe.flags.allow_document_file_removal) or (frappe.form_dict or {}).get("cmd") == DESK_SAVE


def keep_document_files(notice):
	"""An API save that sends document_files without some existing rows (e.g. saving a document request's
	upload together with a stale list) must not drop the notice's PDFs: put the missing rows back.
	Deliberate removal: litwatch.api.notices.remove_notice_document, or the desk form."""
	if notice.is_new() or removal_allowed():
		return
	before = notice.get_doc_before_save()
	if not before:
		return
	current = {(r.file_name or "").strip() for r in notice.get("document_files") or []}
	kept = []
	for row in before.get("document_files") or []:
		url = (row.file_name or "").strip()
		if url and url not in current:
			notice.append("document_files", {"file_name": url})
			current.add(url)
			kept.append(url)
	if kept:
		frappe.logger("litwatch").info({"notice": notice.name, "kept_document_files": kept})
