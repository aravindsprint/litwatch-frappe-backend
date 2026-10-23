# Run: bench --site <site> run-tests --module litwatch.tests.test_gstin_status
# GSTIN statuses inactive -> ready -> pending -> verifying -> active (and reject),
# plus the App Notifications they send. Uses the mock GST portal (OTP 123456).
# The APIs commit, so test records are deleted before and after the run.

import frappe
from frappe.tests.utils import FrappeTestCase

from litwatch import scope

G1 = "33STATA0001A1Z1"
G2 = "33STATB0002B1Z2"
G3 = "33STATC0003C1Z3"
G4 = "33STATD0004D1Z4"
CLIENT = "status-test-client@example.com"
PREFIX = "Status Test"


def _cleanup():
	gstins = [G1, G2, G3, G4]
	businesses = [str(b) for b in frappe.get_all("Business", filters={"business_name": ["like", PREFIX + "%"]}, pluck="name")]
	frappe.db.delete("App Notification", {"reference_doctype": "GSTIN", "reference_name": ["in", gstins]})
	for dt in ("GST Sync Log", "GST OTP Request"):
		frappe.db.delete(dt, {"gstin": ["in", gstins]})
	frappe.db.delete("GSTIN User", {"parenttype": "GSTIN", "parent": ["in", gstins]})
	frappe.db.delete("Business GSTIN", {"gstin": ["in", gstins]})
	frappe.db.delete("GSTIN", {"name": ["in", gstins]})
	if businesses:
		frappe.db.delete("Adaequare Settings", {"name": ["in", businesses]})
		frappe.db.delete("GST User Business", {"business": ["in", businesses]})
		frappe.db.delete("Business", {"name": ["in", businesses]})
	frappe.db.delete("GST User Business", {"parent": CLIENT})
	frappe.db.delete("GST User", {"name": CLIENT})
	frappe.db.commit()


def as_staff():
	frappe.set_user("Administrator")
	frappe.local.form_dict = frappe._dict()
	frappe.local.response = frappe._dict()
	scope.reset_cache()


def notes(user, gstin):
	return frappe.get_all(
		"App Notification",
		filters={"user": user, "reference_doctype": "GSTIN", "reference_name": gstin},
		pluck="title",
		order_by="creation asc",
	)


class TestGstinStatus(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		as_staff()
		cls.mock_before = frappe.db.get_single_value("Sync Settings", "mock_portal")
		frappe.db.set_single_value("Sync Settings", "mock_portal", 1)
		from litwatch import settings

		cls.approval_before = settings.get("require_gstin_approval")
		frappe.db.set_single_value("Sync Settings", "require_gstin_approval", 1)  # this test checks the approval flow
		_cleanup()
		cls.biz = str(frappe.get_doc({"doctype": "Business", "business_name": PREFIX + " Co"}).insert(ignore_permissions=True).name)
		if not frappe.db.exists("User", CLIENT):
			frappe.get_doc({"doctype": "User", "email": CLIENT, "first_name": "Status Client",
			                "user_type": "Website User", "send_welcome_email": 0}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "GST User", "user_email_id": CLIENT, "user_type": "Consultant", "businesses": [{"business": cls.biz}]}).insert(
			ignore_permissions=True
		)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		as_staff()
		_cleanup()
		frappe.db.set_single_value("Sync Settings", "mock_portal", cls.mock_before or 0)
		frappe.db.set_single_value("Sync Settings", "require_gstin_approval", cls.approval_before or 0)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		as_staff()

	def status(self, gstin):
		return frappe.db.get_value("GSTIN", gstin, "consent_status")

	def test_full_flow(self):
		from litwatch.api.gstin import (
			approve_gstin_connection,
			connect_gstin,
			reject_gstin_connection,
			verify_gstin_otp,
		)

		# 1. no GSP app yet: inactive
		frappe.get_doc({"doctype": "GSTIN", "gstin": G1, "business_id": self.biz}).insert(ignore_permissions=True)
		self.assertEqual("inactive", self.status(G1))

		# 2. Adaequare Settings saved: inactive -> ready, users told
		settings = frappe.get_doc({"doctype": "Adaequare Settings", "business": self.biz, "client_id": "status-app",
		                           "client_secret": "secret", "is_active": 1}).insert(ignore_permissions=True)
		self.assertEqual(1, frappe.db.get_value("Adaequare Settings", self.biz, "credentials_verified"))
		self.assertEqual("ready", self.status(G1))
		self.assertEqual(1, notes(CLIENT, G1).count("GSTIN ready to connect"))

		# saving again does not notify again
		settings.reload()
		settings.save(ignore_permissions=True)
		self.assertEqual(1, notes(CLIENT, G1).count("GSTIN ready to connect"))

		# 3. a GSTIN added later starts as ready
		frappe.get_doc({"doctype": "GSTIN", "gstin": G2, "business_id": self.biz}).insert(ignore_permissions=True)
		self.assertEqual("ready", self.status(G2))
		self.assertEqual(1, notes(CLIENT, G2).count("GSTIN ready to connect"))

		# 4. OTP sent -> pending; verified -> verifying, approvers told
		req = connect_gstin(gstin=G1, portalUserId="statususer")
		self.assertEqual("pending", req["consent"])
		res = verify_gstin_otp(gstin=G1, otpRequestId=req["otpRequestId"], otp="123456")
		self.assertEqual("verifying", res["consent"])
		self.assertIsNone(frappe.db.get_value("GSTIN", G1, "valid_until"))
		self.assertEqual("123456", frappe.db.get_value("Adaequare Settings", self.biz, "otp"))
		self.assertIn(f"{G1} is waiting for verification", notes("Administrator", G1))

		# no new OTP while waiting
		with self.assertRaises(frappe.ValidationError):
			connect_gstin(gstin=G1, portalUserId="statususer")

		# a GST User (shared key + gstUser) can't approve
		frappe.local.form_dict = frappe._dict({"gstUser": CLIENT})
		scope.reset_cache()
		with self.assertRaises(frappe.PermissionError):
			approve_gstin_connection(gstin=G1)
		as_staff()

		# 5. approved -> active for 12 months, users told
		res = approve_gstin_connection(gstin=G1)
		self.assertEqual("active", res["consent"])
		self.assertTrue(res["validUntil"])
		self.assertEqual("123456", frappe.db.get_value("Adaequare Settings", self.biz, "otp"))  # OTP kept
		self.assertIn(f"{G1} connected", notes(CLIENT, G1))

		# 6. rejected -> back to ready with the reason, OTP cleared, users told
		req = connect_gstin(gstin=G2, portalUserId="statususer2")
		verify_gstin_otp(gstin=G2, otpRequestId=req["otpRequestId"], otp="123456")
		res = reject_gstin_connection(gstin=G2, reason="Wrong taxpayer")
		self.assertEqual("ready", res["consent"])
		self.assertEqual("Wrong taxpayer", frappe.db.get_value("GSTIN", G2, "rejection_reason"))
		self.assertFalse(frappe.db.get_value("GSTIN", G2, "portal_otp"))
		self.assertIn(f"{G2} connection rejected", notes(CLIENT, G2))

		# 7. settings turned off: ready -> inactive, a live connection is left alone
		settings.reload()
		settings.is_active = 0
		settings.save(ignore_permissions=True)
		self.assertEqual("inactive", self.status(G2))
		self.assertEqual("active", self.status(G1))

		# 8. outside mock mode an inactive GSTIN can't request an OTP
		frappe.db.set_single_value("Sync Settings", "mock_portal", 0)
		try:
			with self.assertRaises(frappe.ValidationError):
				connect_gstin(gstin=G2, portalUserId="statususer2")
		finally:
			frappe.db.set_single_value("Sync Settings", "mock_portal", 1)

		# 9. settings deleted: nothing ready is left
		settings.reload()
		settings.is_active = 1
		settings.save(ignore_permissions=True)
		self.assertEqual("ready", self.status(G2))
		frappe.delete_doc("Adaequare Settings", self.biz, ignore_permissions=True)
		self.assertEqual("inactive", self.status(G2))
		frappe.get_doc({"doctype": "GSTIN", "gstin": G3, "business_id": self.biz}).insert(ignore_permissions=True)
		self.assertEqual("inactive", self.status(G3))

	def test_otp_expiry(self):
		from frappe.utils import add_to_date, now_datetime

		from litwatch.api.gstin import connect_gstin, expire_otp_requests, get_gstin_otp_status, resend_gstin_otp

		frappe.get_doc({"doctype": "GSTIN", "gstin": G4, "business_id": self.biz}).insert(ignore_permissions=True)
		req = connect_gstin(gstin=G4, portalUserId="expiryuser")  # mock mode: allowed even when not set up
		self.assertEqual("pending", self.status(G4))
		self.assertTrue(req["expiresAt"])
		self.assertTrue(500 < req["expiresInSeconds"] <= 600)
		st = get_gstin_otp_status(gstin=G4)
		self.assertEqual(("pending", "pending", True), (st["consent"], st["otpStatus"], st["canVerify"]))

		# still within 10 minutes: nothing changes
		expire_otp_requests()
		self.assertEqual("pending", self.status(G4))

		frappe.db.set_value("GST OTP Request", req["otpRequestId"], "expires_at", add_to_date(now_datetime(), minutes=-1))
		st = get_gstin_otp_status(gstin=G4)  # reading it also expires it
		self.assertEqual(("expired", "expired", False, 0), (st["consent"], st["otpStatus"], st["canVerify"], st["expiresInSeconds"]))
		expire_otp_requests()
		self.assertEqual("expired", frappe.db.get_value("GST OTP Request", req["otpRequestId"], "status"))
		self.assertEqual("expired", self.status(G4))
		self.assertIn(f"OTP expired: {G4}", notes(CLIENT, G4))

		# a new OTP puts it back to pending
		resend_gstin_otp(gstin=G4)
		self.assertEqual("pending", self.status(G4))
