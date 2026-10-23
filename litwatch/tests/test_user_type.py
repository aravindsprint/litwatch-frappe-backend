# Run: bench --site <site> run-tests --module litwatch.tests.test_user_type
# GST User Type: a Consultant sees every Business in their table and all its GSTINs; an Individual
# sees only the GSTINs whose Users table lists them (plus their Businesses, and own Businesses
# that have no GSTIN yet).

import frappe
from frappe.tests.utils import FrappeTestCase

from litwatch import scope
from litwatch.notifications import business_users

G1, G2, G3, G4 = "33UTYPA0001A1Z1", "33UTYPB0002B1Z2", "33UTYPC0003C1Z3", "33UTYPD0004D1Z4"
GSTINS = (G1, G2, G3, G4)
IND = "utype-individual@example.com"
CON = "utype-consultant@example.com"


def _cleanup():
	businesses = [str(b) for b in frappe.get_all("Business", filters={"business_name": ["like", "UType Test%"]}, pluck="name")]
	if businesses:
		frappe.db.delete("Payment", {"client": ["in", businesses]})
		frappe.db.delete("Notice", {"business_id": ["in", businesses]})
		frappe.db.delete("Business GSTIN", {"parent": ["in", businesses]})
		frappe.db.delete("Business", {"name": ["in", businesses]})
	frappe.db.delete("Notice", {"gstin": ["in", GSTINS]})
	frappe.db.delete("GSTIN User", {"parenttype": "GSTIN", "parent": ["in", GSTINS]})
	frappe.db.delete("GSTIN", {"name": ["in", GSTINS]})
	for u in (IND, CON):
		frappe.db.delete("GST User Business", {"parent": u})
		frappe.db.delete("GST User", {"name": u})
	frappe.db.commit()


def as_gst_user(email=None):
	frappe.set_user("Administrator")
	frappe.local.form_dict = frappe._dict({"gstUser": email} if email else {})
	scope.reset_cache()


class TestUserType(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		frappe.local.response = frappe._dict()
		frappe.flags.mute_litwatch_notifications = True
		_cleanup()
		new = lambda d: frappe.get_doc(d).insert(ignore_permissions=True)
		cls.b1 = str(new({"doctype": "Business", "business_name": "UType Test 1"}).name)  # G1 (individual's), G2
		cls.b2 = str(new({"doctype": "Business", "business_name": "UType Test 2"}).name)  # G3
		cls.b3 = str(new({"doctype": "Business", "business_name": "UType Test 3"}).name)  # no GSTIN yet
		for u, name in ((IND, "UType Individual"), (CON, "UType Consultant")):
			if not frappe.db.exists("User", u):
				new({"doctype": "User", "email": u, "first_name": name, "user_type": "Website User", "send_welcome_email": 0})
		new({"doctype": "GST User", "user_email_id": IND, "user_type": "Individual",
		     "businesses": [{"business": b} for b in (cls.b1, cls.b2, cls.b3)]})
		new({"doctype": "GST User", "user_email_id": CON, "user_type": "Consultant",
		     "businesses": [{"business": b} for b in (cls.b1, cls.b2)]})
		new({"doctype": "GSTIN", "gstin": G1, "business_id": cls.b1, "users": [{"user": IND}]})
		new({"doctype": "GSTIN", "gstin": G2, "business_id": cls.b1})
		new({"doctype": "GSTIN", "gstin": G3, "business_id": cls.b2})
		notice = lambda gstin, biz: new({"doctype": "Notice", "client_id": "Administrator", "business_id": biz, "gstin": gstin}).name
		cls.n1, cls.n2, cls.n3, cls.n4 = notice(G1, cls.b1), notice(G2, cls.b1), notice(None, cls.b1), notice(G3, cls.b2)
		pay = lambda gstin: new({"doctype": "Payment", "client": cls.b1, "gstin": gstin, "amount_paid": 1}).name
		cls.p1, cls.p2, cls.p3 = pay(G1), pay(G2), pay(None)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		as_gst_user(None)
		_cleanup()
		frappe.flags.mute_litwatch_notifications = False
		super().tearDownClass()

	def tearDown(self):
		as_gst_user(None)

	def names(self, doctype):
		return {str(n) for n in frappe.get_list(doctype, pluck="name", limit_page_length=0)}

	def test_consultant_sees_all_of_their_businesses(self):
		as_gst_user(CON)
		self.assertEqual({self.b1, self.b2}, set(scope.get_scope()))
		self.assertIsNone(scope.get_gstin_scope())
		self.assertEqual({G1, G2, G3}, self.names("GSTIN") & set(GSTINS))
		self.assertEqual({self.n1, self.n2, self.n3, self.n4}, self.names("Notice") & {self.n1, self.n2, self.n3, self.n4})

	def test_individual_sees_only_own_gstins(self):
		as_gst_user(IND)
		self.assertEqual({self.b1, self.b3}, set(scope.get_scope()))  # b2: only someone else's GSTIN
		self.assertEqual([G1], scope.get_gstin_scope())
		self.assertEqual({G1}, self.names("GSTIN") & set(GSTINS))
		self.assertEqual({self.n1, self.n3}, self.names("Notice") & {self.n1, self.n2, self.n3, self.n4})
		self.assertEqual({self.p1, self.p3}, self.names("Payment") & {self.p1, self.p2, self.p3})
		self.assertTrue(frappe.has_permission("Notice", "read", self.n1))
		self.assertFalse(frappe.has_permission("Notice", "read", self.n2))
		self.assertFalse(frappe.has_permission("GSTIN", "read", G2))
		self.assertFalse(frappe.has_permission("Payment", "read", self.p2))

	def test_individual_apis(self):
		from litwatch.api.business import add_gstin, get_businesses
		from litwatch.api.gstin import get_gstin_connections
		from litwatch.api.notices import get_client_notices

		as_gst_user(IND)
		got = {b["businessId"]: [g["gstin"] for g in b["gstins"]] for b in get_businesses()}
		self.assertEqual({self.b1: [G1], self.b3: []}, {k: v for k, v in got.items() if k in (self.b1, self.b2, self.b3)})
		self.assertEqual({G1}, {g["gstin"] for g in get_gstin_connections()} & set(GSTINS))
		self.assertEqual({self.n1, self.n3}, {n["id"] if "id" in n else n["name"] for n in get_client_notices(client_key=self.b1)["notices"]})

		# an Individual cannot claim a GSTIN of their business that is not theirs
		as_gst_user(IND)
		with self.assertRaises(frappe.PermissionError):
			add_gstin(businessId=self.b1, gstin=G2)
		# a GSTIN they add is theirs
		as_gst_user(IND)
		add_gstin(businessId=self.b3, gstin=G4)
		self.assertIn(IND, [r.user for r in frappe.get_doc("GSTIN", G4).users])
		as_gst_user(IND)
		self.assertIn(G4, scope.get_gstin_scope())

	def test_no_self_promotion(self):
		as_gst_user(IND)
		doc = frappe.get_doc("GST User", IND)
		doc.user_type = "Consultant"
		with self.assertRaises(frappe.PermissionError):
			doc.save()
		as_gst_user(None)  # firm staff can
		frappe.db.set_value("GST User", IND, "user_type", "Individual")

	def test_notification_recipients(self):
		self.assertEqual({CON, IND}, set(business_users(self.b1, G1)) & {CON, IND})
		self.assertEqual({CON}, set(business_users(self.b1, G2)) & {CON, IND})
		self.assertEqual({CON, IND}, set(business_users(self.b1)) & {CON, IND})  # business-level
		self.assertEqual({CON}, set(business_users(self.b2)) & {CON, IND})
