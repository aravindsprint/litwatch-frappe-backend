# Run: bench --site <site> run-tests --module litwatch.tests.test_consent_validity
import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, nowdate

from litwatch import settings
from litwatch.api.gstin import consent_valid_until


class TestConsentValidity(FrappeTestCase):
	def setUp(self):
		self.saved = settings.raw("consent_valid_days")

	def tearDown(self):
		frappe.db.set_single_value("Sync Settings", "consent_valid_days", self.saved or 30)

	def test_default_is_30_days(self):
		frappe.db.set_single_value("Sync Settings", "consent_valid_days", 30)
		self.assertEqual(getdate(add_days(nowdate(), 30)), getdate(consent_valid_until()))

	def test_setting_changes_it(self):
		frappe.db.set_single_value("Sync Settings", "consent_valid_days", 15)
		self.assertEqual(getdate(add_days("2026-11-25", 15)), getdate(consent_valid_until("2026-11-25")))
