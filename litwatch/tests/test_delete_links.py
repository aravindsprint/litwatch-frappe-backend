# Run: bench --site <site> run-tests --module litwatch.tests.test_delete_links
# Audit Log and App Notification entries must not block deleting a Notice, Payment or Business.

import frappe
from frappe.tests.utils import FrappeTestCase

NAME = "Delete Links Test Business"
TAG = "delete-links-test"


def _cleanup():
	frappe.db.delete("Audit Log", {"action": TAG})
	frappe.db.delete("App Notification", {"title": TAG})
	for biz in frappe.get_all("Business", filters={"business_name": NAME}, pluck="name"):
		for p in frappe.get_all("Payment", filters={"client": biz}, pluck="name"):
			frappe.delete_doc("Payment", p, force=True)
		for n in frappe.get_all("Notice", filters={"business_id": str(biz)}, pluck="name"):
			frappe.delete_doc("Notice", n, force=True)
		frappe.delete_doc("Business", biz, force=True)
	frappe.db.commit()


class TestDeleteLinks(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.flags.mute_litwatch_notifications = True
		_cleanup()

	def tearDown(self):
		_cleanup()
		frappe.flags.mute_litwatch_notifications = False

	def _logs(self, doc):
		frappe.get_doc({"doctype": "Audit Log", "action": TAG, "client": self.biz.name,
		                "reference_doctype": doc.doctype, "reference_name": doc.name}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "App Notification", "title": TAG, "user": "Administrator", "client": self.biz.name,
		                "reference_doctype": doc.doctype, "reference_name": doc.name}).insert(ignore_permissions=True)

	def test_delete_with_audit_log_and_notifications(self):
		self.biz = frappe.get_doc({"doctype": "Business", "business_name": NAME}).insert()
		notice = frappe.get_doc({"doctype": "Notice", "client_id": "Administrator", "business_id": str(self.biz.name)}).insert()
		payment = frappe.get_doc({"doctype": "Payment", "client": self.biz.name, "notice": notice.name, "amount_paid": 100}).insert()
		for doc in (self.biz, notice, payment):
			self._logs(doc)

		frappe.delete_doc("Payment", payment.name)
		frappe.delete_doc("Notice", notice.name)
		frappe.delete_doc("Business", self.biz.name)

		self.assertFalse(frappe.db.exists("Notice", notice.name))
		self.assertFalse(frappe.db.exists("Business", self.biz.name))
		# the history stays
		self.assertTrue(frappe.db.exists("Audit Log", {"reference_doctype": "Notice", "reference_name": notice.name}))
		self.assertEqual(3, frappe.db.count("Audit Log", {"client": self.biz.name}))
