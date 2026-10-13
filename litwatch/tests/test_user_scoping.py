# Run: bench --site <site> set-config allow_tests true
#      bench --site <site> run-tests --module litwatch.tests.test_user_scoping
# Everything is created inside the test and rolled back afterwards.

import frappe
from frappe.tests.utils import FrappeTestCase

from litwatch import scope

GSTIN_A = "33SCOPA0001A1Z1"
GSTIN_B = "33SCOPB0002B1Z2"
CLIENT_EMAIL = "scope-test-client@example.com"


def as_gst_user(email=None):
	"""Act like the frontend: shared key (Administrator) + gstUser."""
	frappe.set_user("Administrator")
	frappe.local.form_dict = frappe._dict({"gstUser": email} if email else {})
	frappe.local.__dict__.pop(scope._CACHE, None)


class TestUserScoping(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		frappe.local.response = frappe._dict()
		cls.biz_a = frappe.get_doc({"doctype": "Business", "business_name": "Scope Test A"}).insert(ignore_permissions=True).name
		cls.biz_b = frappe.get_doc({"doctype": "Business", "business_name": "Scope Test B"}).insert(ignore_permissions=True).name
		for gstin, biz in ((GSTIN_A, cls.biz_a), (GSTIN_B, cls.biz_b)):
			frappe.get_doc({"doctype": "GSTIN", "gstin": gstin, "business_id": str(biz), "consent_status": "active"}).insert(ignore_permissions=True)
		cls.notice_a = frappe.get_doc({"doctype": "Notice", "client_id": "Administrator", "business_id": str(cls.biz_a)}).insert(ignore_permissions=True).name
		cls.notice_b = frappe.get_doc({"doctype": "Notice", "client_id": "Administrator", "business_id": str(cls.biz_b)}).insert(ignore_permissions=True).name
		cls.notice_gstin_a = frappe.get_doc({"doctype": "Notice", "client_id": "Administrator", "gstin": GSTIN_A}).insert(ignore_permissions=True).name
		if not frappe.db.exists("User", CLIENT_EMAIL):
			frappe.get_doc({"doctype": "User", "email": CLIENT_EMAIL, "first_name": "Scope Client",
			                "user_type": "Website User", "send_welcome_email": 0}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "GST User", "user_email_id": CLIENT_EMAIL, "user_name": "Scope Client",
		                "businesses": [{"business": str(cls.biz_a)}]}).insert(ignore_permissions=True)

	def tearDown(self):
		as_gst_user(None)

	def names(self, doctype, **kw):
		return {str(n) for n in frappe.get_list(doctype, pluck="name", limit_page_length=0, **kw)}

	# --- unscoped (firm staff) -------------------------------------------
	def test_unscoped_sees_everything(self):
		as_gst_user(None)
		self.assertIsNone(scope.get_scope())
		self.assertTrue({str(self.biz_a), str(self.biz_b)} <= self.names("Business"))

	# --- lists (Resource API uses get_list) ------------------------------
	def test_lists_are_filtered(self):
		as_gst_user(CLIENT_EMAIL)
		self.assertEqual(scope.get_scope(), [str(self.biz_a)])
		self.assertIn(str(self.biz_a), self.names("Business"))
		self.assertNotIn(str(self.biz_b), self.names("Business"))
		self.assertEqual({GSTIN_A}, self.names("GSTIN", filters={"name": ["in", [GSTIN_A, GSTIN_B]]}))
		notices = self.names("Notice", filters={"name": ["in", [self.notice_a, self.notice_b, self.notice_gstin_a]]})
		self.assertEqual({self.notice_a, self.notice_gstin_a}, notices)
		self.assertEqual({CLIENT_EMAIL}, self.names("GST User"))

	# --- single records (Resource API read/update/delete) ----------------
	def test_single_records_are_checked(self):
		as_gst_user(CLIENT_EMAIL)
		self.assertTrue(frappe.get_doc("Notice", self.notice_a).has_permission("read"))
		self.assertFalse(frappe.get_doc("Notice", self.notice_b).has_permission("read"))
		self.assertFalse(frappe.get_doc("Business", self.biz_b).has_permission("write"))
		self.assertFalse(frappe.get_doc("GSTIN", GSTIN_B).has_permission("read"))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Notice", self.notice_b).check_permission("read")
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({"doctype": "Notice", "client_id": "Administrator", "business_id": str(self.biz_b)}).insert()

	# --- custom methods --------------------------------------------------
	def test_custom_methods(self):
		from litwatch.api.business import add_gstin, get_businesses
		from litwatch.api.clients import get_clients
		from litwatch.api.dashboard import get_command_hub
		from litwatch.api.gstin import connect_gstin, get_gstin_connections, run_all_gstin_sync
		from litwatch.api.notices import get_client_notices

		as_gst_user(CLIENT_EMAIL)
		frappe.local.response = frappe._dict()
		self.assertEqual([str(self.biz_a)], [c["key"] for c in get_clients()])
		self.assertEqual([str(self.biz_a)], [b["businessId"] for b in get_businesses()])
		self.assertEqual({GSTIN_A}, {g["gstin"] for g in get_gstin_connections()})
		self.assertGreaterEqual(get_client_notices(client_key=str(self.biz_a))["total"], 2)
		for call in (
			lambda: get_client_notices(client_key=str(self.biz_b)),
			lambda: get_command_hub(client_key=str(self.biz_b)),
			lambda: connect_gstin(gstin=GSTIN_B, portalUserId="x"),
			lambda: add_gstin(businessId=str(self.biz_b), gstin="33SCOPC0003C1Z3"),
		):
			with self.assertRaises(frappe.PermissionError):
				call()
		self.assertEqual(1, run_all_gstin_sync()["gstinsQueued"])  # only GSTIN_A
		hub = get_command_hub()
		ids = {r["id"] for r in hub["activeNotices"]["rows"]}
		self.assertNotIn(self.notice_b, ids)

	def test_new_business_is_linked_to_creator(self):
		from litwatch.api.business import create_business

		as_gst_user(CLIENT_EMAIL)
		frappe.local.response = frappe._dict()
		new_id = create_business(name="Scope Test New")["businessId"]
		self.assertIn(new_id, scope.get_scope())
		businesses = {r.business for r in frappe.get_doc("GST User", CLIENT_EMAIL).businesses}
		self.assertIn(new_id, {str(b) for b in businesses})

	def test_unknown_gst_user(self):
		as_gst_user("nobody-at-all@example.com")
		with self.assertRaises(frappe.DoesNotExistError):
			scope.get_scope()
