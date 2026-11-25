# Run: bench --site <site> run-tests --module litwatch.tests.test_notice_files
import frappe
from frappe.tests.utils import FrappeTestCase

FNAME = "litwatch-attach-test.txt"  # not .pdf: Frappe checks real PDF content on upload


def _cleanup():
	frappe.db.delete("File", {"file_name": ["like", "litwatch-attach-test%"]})
	for n in frappe.get_all("Notice", filters={"business_id": "attach-test"}, pluck="name"):
		frappe.delete_doc("Notice", n, force=True)
	frappe.db.commit()


class TestNoticeFiles(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.flags.mute_litwatch_notifications = True
		_cleanup()

	def tearDown(self):
		_cleanup()
		frappe.flags.mute_litwatch_notifications = False

	def _upload(self):
		# like /api/method/upload_file without doctype / docname: attached to nothing
		f = frappe.get_doc({"doctype": "File", "file_name": FNAME, "is_private": 1,
		                    "content": frappe.generate_hash().encode()}).insert(ignore_permissions=True)
		self.url = f.file_url
		return f

	def _attached(self, notice):
		# by file_url, not file_name: Frappe renames a re-upload when the name already exists on disk
		return frappe.get_all("File", filters={"file_url": self.url, "attached_to_doctype": "Notice",
		                                      "attached_to_name": notice}, pluck="name")

	def test_unattached_upload_is_claimed_and_shared_file_gets_a_record(self):
		f = self._upload()
		a = frappe.get_doc({"doctype": "Notice", "client_id": "Administrator", "business_id": "attach-test",
		                    "document_files": [{"file_name": f.file_url}]}).insert()
		self.assertEqual([f.name], self._attached(a.name))  # the free record is claimed

		b = frappe.get_doc({"doctype": "Notice", "client_id": "Administrator", "business_id": "attach-test",
		                    "document_files": [{"file_name": f.file_url}]}).insert()
		self.assertEqual(1, len(self._attached(b.name)))  # same file, its own record for b
		self.assertEqual(1, len(self._attached(a.name)))  # a keeps its own

		b.save()
		self.assertEqual(1, len(self._attached(b.name)))  # idempotent

	def test_api_save_keeps_document_files(self):
		f = self._upload()
		n = frappe.get_doc({"doctype": "Notice", "client_id": "Administrator", "business_id": "attach-test",
		                    "document_files": [{"file_name": f.file_url}]}).insert()
		# like the frontend saving a document request's upload with an empty / stale document_files list
		n.reload()
		n.document_files = []
		n.analysis = frappe.as_json({"requests": [{"response": {"file_urls": [f.file_url]}}]})
		n.save()
		n.reload()
		self.assertEqual([f.file_url], [r.file_name for r in n.document_files])

		# deliberate removal
		from litwatch.api.notices import remove_notice_document

		remove_notice_document(notice=n.name, file_url=f.file_url)
		n.reload()
		self.assertEqual([], n.document_files)
