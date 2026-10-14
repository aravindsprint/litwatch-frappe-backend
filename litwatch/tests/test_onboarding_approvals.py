# Run: bench --site <site> run-tests --module litwatch.tests.test_onboarding_approvals
# Business / GSTIN approval switches, notifications for updates and reminders,
# leads, registration invites and self-registration. Uses the mock GST portal.
# The APIs commit, so test records are deleted before and after the run.

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, nowdate

from litwatch import scope

CLIENT = "approvals-test-client@example.com"
LEAD_EMAIL = "lead-test@example.com"
REG_EMAIL = "register-test@example.com"
PREFIX = "Approvals Test"
G1, G2, G3, G4 = "33APRVA0001A1Z1", "33APRVB0002B1Z2", "33APRVC0003C1Z3", "33APRVD0004D1Z4"
SETTINGS = ("mock_portal", "require_business_approval", "require_gstin_approval", "send_account_email")


def _cleanup():
	gstins = [G1, G2, G3, G4]
	businesses = [str(b) for b in frappe.get_all("Business", filters={"business_name": ["like", PREFIX + "%"]}, pluck="name")]
	notices = frappe.get_all("Notice", filters={"business_id": ["in", businesses or ["-"]]}, pluck="name")
	emails = [CLIENT, LEAD_EMAIL, REG_EMAIL]
	frappe.db.delete("App Notification", {"user": ["in", emails]})
	frappe.db.delete("App Notification", {"reference_name": ["in", gstins + businesses + notices + ["-"]]})
	for dt in ("GST Sync Log", "GST OTP Request"):
		frappe.db.delete(dt, {"gstin": ["in", gstins]})
	frappe.db.delete("Business GSTIN", {"gstin": ["in", gstins]})
	frappe.db.delete("GSTIN", {"name": ["in", gstins]})
	if businesses:
		for dt in ("Payment", "Client Document", "Review Queue Item"):
			frappe.db.delete(dt, {"client": ["in", businesses]})
		frappe.db.delete("Notice", {"name": ["in", notices or ["-"]]})
		frappe.db.delete("Adaequare Settings", {"name": ["in", businesses]})
		frappe.db.delete("GST User Business", {"business": ["in", businesses]})
		frappe.db.delete("Business", {"name": ["in", businesses]})
	for email in emails:
		frappe.db.delete("GST User Business", {"parent": email})
		frappe.db.delete("GST User", {"name": email})
		frappe.db.delete("Notification Setting", {"name": email})
	frappe.db.delete("LitWatch Lead", {"email": ["in", emails]})
	frappe.db.delete("Registration Invite", {"email": ["in", emails]})
	for email in (LEAD_EMAIL, REG_EMAIL):
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, ignore_permissions=True, force=True)
	frappe.db.commit()


def as_staff():
	frappe.set_user("Administrator")
	frappe.local.form_dict = frappe._dict()
	frappe.local.response = frappe._dict()
	scope.reset_cache()


def as_client():
	frappe.set_user("Administrator")
	frappe.local.form_dict = frappe._dict({"gstUser": CLIENT})
	frappe.local.response = frappe._dict()
	scope.reset_cache()


def titles(user):
	return frappe.get_all("App Notification", filters={"user": user}, pluck="title", order_by="creation asc")


def has_title(user, start):
	return any(t.startswith(start) for t in titles(user))


class TestOnboardingApprovals(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		as_staff()
		from litwatch import settings

		cls.before = {f: settings.get(f) for f in SETTINGS}  # effective values, defaults included
		frappe.db.set_single_value("Sync Settings", "mock_portal", 1)
		frappe.db.set_single_value("Sync Settings", "require_gstin_approval", 1)
		frappe.db.set_single_value("Sync Settings", "send_account_email", 1)
		_cleanup()
		if not frappe.db.exists("User", CLIENT):
			frappe.get_doc({"doctype": "User", "email": CLIENT, "first_name": "Approvals Client",
			                "user_type": "Website User", "send_welcome_email": 0}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "GST User", "user_email_id": CLIENT}).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		as_staff()
		_cleanup()
		for f, v in cls.before.items():
			frappe.db.set_single_value("Sync Settings", f, v or 0)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		as_staff()

	def _settings(self, business):
		frappe.get_doc({"doctype": "Adaequare Settings", "business": business, "client_id": "appr-app",
		                "client_secret": "secret", "is_active": 1}).insert(ignore_permissions=True)

	# --- approvals ---------------------------------------------------------
	def test_business_approval(self):
		from litwatch.api.approvals import approve_business, get_pending_approvals, reject_business
		from litwatch.api.business import add_gstin, create_business
		from litwatch.api.gstin import connect_gstin

		frappe.db.set_single_value("Sync Settings", "require_business_approval", 1)

		as_client()
		res = create_business(name=PREFIX + " Pending")
		biz = res["businessId"]
		self.assertEqual("Pending", res["approval"])
		add_gstin(businessId=biz, gstin=G1, portalUserId="apprportal")
		as_staff()
		self.assertTrue(has_title("Administrator", "Business waiting for approval"))
		self.assertIn(biz, [b["businessId"] for b in get_pending_approvals()["businesses"]])

		self._settings(biz)
		self.assertEqual("inactive", frappe.db.get_value("GSTIN", G1, "consent_status"))  # business not approved yet
		as_client()
		with self.assertRaises(frappe.ValidationError):
			connect_gstin(gstin=G1, portalUserId="apprportal")
		with self.assertRaises(frappe.PermissionError):
			approve_business(businessId=biz)  # a GST User can't approve

		as_staff()
		self.assertEqual("Approved", approve_business(businessId=biz)["approval"])
		self.assertEqual("ready", frappe.db.get_value("GSTIN", G1, "consent_status"))
		self.assertTrue(has_title(CLIENT, "Business approved"))

		as_client()
		other = create_business(name=PREFIX + " Rejected")["businessId"]
		as_staff()
		res = reject_business(businessId=other, reason="Duplicate of another client")
		self.assertEqual("Rejected", res["approval"])
		self.assertTrue(has_title(CLIENT, "Business rejected"))

		# staff-created businesses are approved even with the switch on
		staff_biz = create_business(name=PREFIX + " Staff")
		self.assertEqual("Approved", staff_biz["approval"])
		frappe.db.set_single_value("Sync Settings", "require_business_approval", 0)

	def test_gstin_approval_off(self):
		from litwatch.api.gstin import connect_gstin, verify_gstin_otp

		frappe.db.set_single_value("Sync Settings", "require_gstin_approval", 0)
		try:
			biz = str(frappe.get_doc({"doctype": "Business", "business_name": PREFIX + " NoApproval"}).insert(ignore_permissions=True).name)
			gst_user = frappe.get_doc("GST User", CLIENT)
			gst_user.append("businesses", {"business": biz})
			gst_user.save(ignore_permissions=True)
			self.assertTrue(has_title(CLIENT, "Business added"))
			self._settings(biz)
			frappe.get_doc({"doctype": "GSTIN", "gstin": G2, "business_id": biz}).insert(ignore_permissions=True)
			req = connect_gstin(gstin=G2, portalUserId="noapproval")
			res = verify_gstin_otp(gstin=G2, otpRequestId=req["otpRequestId"], otp="123456")
			self.assertEqual("active", res["consent"])
			self.assertTrue(res["validUntil"])
			self.assertTrue(has_title(CLIENT, f"{G2} connected"))
		finally:
			frappe.db.set_single_value("Sync Settings", "require_gstin_approval", 1)

	# --- notifications for updates -----------------------------------------
	def _client_business(self, name):
		biz = str(frappe.get_doc({"doctype": "Business", "business_name": PREFIX + " " + name}).insert(ignore_permissions=True).name)
		gst_user = frappe.get_doc("GST User", CLIENT)
		gst_user.append("businesses", {"business": biz})
		gst_user.save(ignore_permissions=True)
		return biz

	def test_update_notifications(self):
		biz = self._client_business("Updates")

		frappe.get_doc({"doctype": "Payment", "client": biz, "amount_paid": 2500, "payment_type": "Pre-deposit"}).insert(ignore_permissions=True)
		self.assertTrue(has_title(CLIENT, "Payment recorded"))

		doc = frappe.get_doc({"doctype": "Client Document", "client": biz, "file": "/files/approvals-test.pdf",
		                      "file_name": "approvals-test.pdf", "document_type": "Notice"}).insert(ignore_permissions=True)
		self.assertTrue(has_title(CLIENT, "Document uploaded"))
		doc.document_type = "Evidence"
		doc.save(ignore_permissions=True)
		self.assertTrue(has_title(CLIENT, "Document retagged"))

		notice = frappe.get_doc({"doctype": "Notice", "naming_series": "DRC-.YYYY.-", "client_id": "Administrator",
		                         "business_id": biz}).insert(ignore_permissions=True)
		self.assertTrue(has_title(CLIENT, f"New notice {notice.name}"))
		notice.analysis = json.dumps({"summary": "ok"})
		notice.save(ignore_permissions=True)
		self.assertTrue(has_title(CLIENT, f"AI analysis ready: {notice.name}"))

		item = frappe.get_doc({"doctype": "Review Queue Item", "review_id": "APPR-TEST-1", "client": biz,
		                       "notice": notice.name, "status": "Pending"}).insert(ignore_permissions=True)
		item.status = "Confirmed"
		item.save(ignore_permissions=True)
		self.assertTrue(has_title(CLIENT, "Review confirmed"))

		b = frappe.get_doc("Business", biz)
		b.onboarding_stage = "Engagement letter sent"
		b.save(ignore_permissions=True)
		self.assertTrue(has_title(CLIENT, b.business_name + ": Engagement letter sent"))

	def test_deadline_and_consent_jobs(self):
		from litwatch import notification_jobs

		biz = self._client_business("Deadlines")
		today = getdate(nowdate())
		due = frappe.get_doc({"doctype": "Notice", "naming_series": "DRC-.YYYY.-", "client_id": "Administrator", "business_id": biz,
		                      "portal_metadata": json.dumps({"dueDateOfReplyIso": str(add_days(today, 3))})}).insert(ignore_permissions=True)
		late = frappe.get_doc({"doctype": "Notice", "naming_series": "DRC-.YYYY.-", "client_id": "Administrator", "business_id": biz,
		                       "portal_metadata": json.dumps({"dueDateOfReplyIso": str(add_days(today, -1))})}).insert(ignore_permissions=True)
		notification_jobs.deadline_reminders(today)
		notification_jobs.deadline_reminders(today)  # second run: no duplicates
		self.assertEqual(1, titles(CLIENT).count(f"Reply due in 3 day(s): {due.name}"))
		self.assertEqual(1, titles(CLIENT).count(f"Reply overdue by 1 day(s): {late.name}"))

		frappe.get_doc({"doctype": "GSTIN", "gstin": G3, "business_id": biz, "consent_status": "active",
		                "valid_until": add_days(today, 7)}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "GSTIN", "gstin": G4, "business_id": biz, "consent_status": "active",
		                "valid_until": add_days(today, -1)}).insert(ignore_permissions=True)
		notification_jobs.expire_and_warn_consent(today)
		self.assertTrue(has_title(CLIENT, f"Consent expiring: {G3}"))
		self.assertEqual("expired", frappe.db.get_value("GSTIN", G4, "consent_status"))
		self.assertTrue(has_title(CLIENT, f"{G4} consent expired"))

	# --- leads and registration --------------------------------------------
	def test_lead_conversion(self):
		from litwatch.onboarding import convert_lead

		lead = frappe.get_doc({"doctype": "LitWatch Lead", "first_name": "Lead", "last_name": "Tester", "email": LEAD_EMAIL,
		                       "whatsapp_number": "+919800000001", "practice_type": "Individual CA", "client_count": 12}).insert(ignore_permissions=True)
		self.assertEqual("New", lead.status)
		with patch("frappe.sendmail") as sendmail:  # no outgoing Email Account needed
			res = convert_lead(lead=lead.name)
		self.assertEqual(LEAD_EMAIL, res["user"])
		self.assertTrue(res["accountEmailSent"])
		sent = sendmail.call_args.kwargs
		self.assertEqual([LEAD_EMAIL], sent["recipients"])
		self.assertIn("set your password", sent["message"])
		lead.reload()
		self.assertEqual("Onboard", lead.status)
		self.assertTrue(frappe.db.exists("GST User", LEAD_EMAIL))
		self.assertTrue(frappe.db.get_value("GST User", LEAD_EMAIL, "account_email_sent_on"))
		self.assertTrue(has_title(LEAD_EMAIL, "Welcome to LitWatch"))

	def test_self_registration(self):
		from litwatch.api.registration import get_registration_invite, register

		invite = frappe.get_doc({"doctype": "Registration Invite", "invitee_name": "Reg Tester", "email": REG_EMAIL}).insert(ignore_permissions=True)
		self.assertTrue(invite.registration_link.endswith("?token=" + invite.token))

		frappe.set_user("Guest")
		self.assertEqual(REG_EMAIL, get_registration_invite(token=invite.token)["email"])
		with self.assertRaises(frappe.ValidationError):
			register(token=invite.token, firstName="Reg", whatsappNumber="+919800000002", email="someone-else@example.com",
			         practiceType="Firm", firmName="Reg & Co", clientCount=5)
		with patch("frappe.sendmail"):
			res = register(token=invite.token, firstName="Reg", lastName="Tester", whatsappNumber="+919800000002",
			               email=REG_EMAIL, practiceType="Firm", firmName="Reg & Co", clientCount=5)
		self.assertTrue(res["registered"])
		with self.assertRaises(frappe.PermissionError):
			register(token=invite.token, firstName="Reg", whatsappNumber="+919800000002", email=REG_EMAIL,
			         practiceType="Firm", firmName="Reg & Co", clientCount=5)  # used once
		with self.assertRaises(frappe.PermissionError):
			get_registration_invite(token="not-a-token")
		as_staff()

		self.assertEqual("Used", frappe.db.get_value("Registration Invite", invite.name, "status"))
		lead = frappe.get_doc("LitWatch Lead", {"email": REG_EMAIL})
		self.assertEqual(("Registration link", "Onboard", "Reg & Co", 5), (lead.source, lead.status, lead.firm_name, lead.client_count))
		self.assertTrue(frappe.db.exists("GST User", REG_EMAIL))
		self.assertTrue(has_title(REG_EMAIL, "Welcome to LitWatch"))
