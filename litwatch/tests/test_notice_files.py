# Run: bench --site <site> run-tests --module litwatch.tests.test_notice_files
import frappe
from frappe.tests.utils import FrappeTestCase

FNAME = "litwatch-attach-test.txt"  # not .pdf: Frappe checks real PDF content on upload


def _cleanup():
	frappe.db.delete("File", {"file_name": FNAME})
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
		return frappe.get_doc({"doctype": "File", "file_name": FNAME, "is_private": 1,
		                       "content": b"attach test"}).insert(ignore_permissions=True)

	def _attached(self, notice):
		return frappe.get_all("File", filters={"file_name": FNAME, "attached_to_doctype": "Notice",
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
