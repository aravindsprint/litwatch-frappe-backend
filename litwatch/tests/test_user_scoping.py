# Run: bench --site <site> set-config allow_tests true
#      bench --site <site> run-tests --module litwatch.tests.test_user_scoping
# The APIs under test commit (create_business, run_all_gstin_sync...), so a rollback
# is not enough: test records are deleted before and after the run.

import frappe
from frappe.tests.utils import FrappeTestCase

from litwatch import scope

GSTIN_A = "33SCOPA0001A1Z1"
GSTIN_B = "33SCOPB0002B1Z2"
CLIENT_EMAIL = "scope-test-client@example.com"


def _cleanup():
	"""Delete everything this test creates (left over from an earlier run too)."""
	gstins = [GSTIN_A, GSTIN_B, "33SCOPC0003C1Z3"]
	businesses = frappe.get_all("Business", filters={"business_name": ["like", "Scope Test%"]}, pluck="name")
	businesses = [str(b) for b in businesses]
	if businesses:
		frappe.db.delete("Adaequare Settings", {"name": ["in", businesses]})
		frappe.db.delete("Notice", {"business_id": ["in", businesses]})
		frappe.db.delete("GST User Business", {"business": ["in", businesses]})
		frappe.db.delete("Business GSTIN", {"parent": ["in", businesses]})
		frappe.db.delete("Business", {"name": ["in", businesses]})
	frappe.db.delete("Notice", {"gstin": ["in", gstins]})
	for dt in ("GST Sync Log", "GST OTP Request"):
		frappe.db.delete(dt, {"gstin": ["in", gstins]})
	frappe.db.delete("Business GSTIN", {"gstin": ["in", gstins]})
	frappe.db.delete("GSTIN User", {"parenttype": "GSTIN", "parent": ["in", gstins]})
	frappe.db.delete("GSTIN", {"name": ["in", gstins]})
	frappe.db.delete("GST User Business", {"parent": CLIENT_EMAIL})
	frappe.db.delete("GST User", {"name": CLIENT_EMAIL})
	frappe.db.commit()


def as_gst_user(email=None):
	"""Act like the frontend: shared key (Administrator) + gstUser."""
	frappe.set_user("Administrator")
	frappe.local.form_dict = frappe._dict({"gstUser": email} if email else {})
	scope.reset_cache()


class TestUserScoping(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		frappe.local.response = frappe._dict()
		# Mock portal: saving Adaequare Settings below must not call the real GSP to check credentials
		cls.mock_before = frappe.db.get_single_value("Sync Settings", "mock_portal")
		frappe.db.set_single_value("Sync Settings", "mock_portal", 1)
		_cleanup()
		cls.biz_a = frappe.get_doc({"doctype": "Business", "business_name": "Scope Test A"}).insert(ignore_permissions=True).name
		cls.biz_b = frappe.get_doc({"doctype": "Business", "business_name": "Scope Test B"}).insert(ignore_permissions=True).name
		for gstin, biz in ((GSTIN_A, cls.biz_a), (GSTIN_B, cls.biz_b)):
			frappe.get_doc({"doctype": "GSTIN", "gstin": gstin, "business_id": str(biz), "consent_status": "active"}).insert(ignore_permissions=True)
		cls.notice_a = frappe.get_doc({"doctype": "Notice", "client_id": "Administrator", "business_id": str(cls.biz_a)}).insert(ignore_permissions=True).name
		cls.notice_b = frappe.get_doc({"doctype": "Notice", "client_id": "Administrator", "business_id": str(cls.biz_b)}).insert(ignore_permissions=True).name
		cls.notice_gstin_a = frappe.get_doc({"doctype": "Notice", "client_id": "Administrator", "gstin": GSTIN_A}).insert(ignore_permissions=True).name
		for biz in (cls.biz_a, cls.biz_b):
			frappe.get_doc({"doctype": "Adaequare Settings", "business": str(biz), "client_id": f"scope-{biz}",
			                "client_secret": "x", "is_active": 1}).insert(ignore_permissions=True)
		if not frappe.db.exists("User", CLIENT_EMAIL):
			frappe.get_doc({"doctype": "User", "email": CLIENT_EMAIL, "first_name": "Scope Client",
			                "user_type": "Website User", "send_welcome_email": 0}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "GST User", "user_email_id": CLIENT_EMAIL, "user_name": "Scope Client", "user_type": "Consultant",
		                "businesses": [{"business": str(cls.biz_a)}]}).insert(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		as_gst_user(None)
		_cleanup()
		frappe.db.set_single_value("Sync Settings", "mock_portal", cls.mock_before or 0)
		frappe.db.commit()
		super().tearDownClass()

	def tearDown(self):
		as_gst_user(None)

	def names(self, doctype, **kw):
		return {str(n) for n in frappe.get_list(doctype, pluck="name", limit_page_length=0, **kw)}

	# --- unscoped (firm staff) -------------------------------------------
	def test_unscoped_sees_everything(self):
		as_gst_user(None)
		self.assertIsNone(scope.get_scope())
		self.assertTrue({str(self.biz_a), str(self.biz_b)} <= self.names("Business"))
		self.assertTrue({str(self.biz_a), str(self.biz_b)} <= self.names("Adaequare Settings"))

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
		self.assertEqual({str(self.biz_a)}, self.names("Adaequare Settings"))

	# --- single records (Resource API read/update/delete) ----------------
	def test_single_records_are_checked(self):
		as_gst_user(CLIENT_EMAIL)
		self.assertTrue(frappe.get_doc("Notice", self.notice_a).has_permission("read"))
		self.assertFalse(frappe.get_doc("Notice", self.notice_b).has_permission("read"))
		self.assertFalse(frappe.get_doc("Business", self.biz_b).has_permission("write"))
		self.assertFalse(frappe.get_doc("GSTIN", GSTIN_B).has_permission("read"))
		self.assertTrue(frappe.get_doc("Adaequare Settings", str(self.biz_a)).has_permission("read"))
		self.assertFalse(frappe.get_doc("Adaequare Settings", str(self.biz_b)).has_permission("read"))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Adaequare Settings", str(self.biz_b)).check_permission("write")
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

	def test_get_businesses_gstin_details(self):
		from litwatch.api.business import get_businesses

		as_gst_user(None)
		reg = frappe.get_doc("GSTIN", GSTIN_A)
		reg.address = "1 Test Street, Tiruppur"
		reg.portal_user_id = "scopeportal"
		reg.set("users", [{"user": CLIENT_EMAIL}])
		reg.save(ignore_permissions=True)

		as_gst_user(CLIENT_EMAIL)
		frappe.local.response = frappe._dict()
		biz = [b for b in get_businesses() if b["businessId"] == str(self.biz_a)][0]
		for key in ("businessId", "name", "pan", "sector", "status", "notices", "gstins"):
			self.assertIn(key, biz)
		g = [x for x in biz["gstins"] if x["gstin"] == GSTIN_A][0]
		self.assertEqual("1 Test Street, Tiruppur", g["address"])
		self.assertEqual("scopeportal", g["portalUserId"])
		self.assertEqual([{"email": CLIENT_EMAIL, "name": "Scope Client"}], g["users"])
		for key in ("gstin", "state", "consent"):
			self.assertIn(key, g)

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
