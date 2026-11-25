# Run: bench --site <site> run-tests --module litwatch.tests.test_gst_portal
# The portal is mocked: no network calls.
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from litwatch.api import gst_portal

NO_RECORDS = {"success": False, "message": "No Records Found.", "status": 500, "errorCode": "NOTC_010"}


def resp(body, status=200):
	r = MagicMock()
	r.status_code = status
	r.json.return_value = body
	r.text = frappe.as_json(body)
	return r


class TestGstPortal(FrappeTestCase):
	def _call(self, body):
		settings = frappe._dict(name="x", base_url="https://gsp.example", environment="Live")
		with patch.object(gst_portal, "_get_token", return_value="t"), \
			patch.object(gst_portal, "_check_cap"), patch.object(gst_portal, "log_api_call"), \
			patch.object(gst_portal, "_base_url", return_value="https://gsp.example"), \
			patch.object(gst_portal.requests, "get", return_value=resp(body)):
			return gst_portal._call(settings, "/enriched/notices", {"action": "NOTCELIST"}, "33AAHCV1119K1ZE", "u")

	def test_no_records_is_an_empty_list(self):
		self.assertEqual({"notices": []}, self._call(NO_RECORDS))

	def test_other_errors_still_raise(self):
		with patch.object(gst_portal.frappe, "log_error"), patch.object(gst_portal.frappe.db, "commit"):
			with self.assertRaises(gst_portal.PortalError):
				self._call({"success": False, "message": "Invalid GSTIN", "errorCode": "GSTN_001"})
			with self.assertRaises(gst_portal.PortalOtpRequired):
				self._call({"success": False, "message": "OTP is required"})

	def test_api_access_disabled(self):
		body = {"success": False, "status": 500, "errorCode": "AUTH002",
		        "message": "GSTIN/UIN/Temporary ID: 33AALCT1012H1ZR has disabled API access, or your GSP/ASP name has "
		                   "not been allowed access. The taxpayer may login to the GST Common Portal and update the "
		                   "'Manage API Access' settings"}
		with patch.object(gst_portal.frappe, "log_error") as log:
			with self.assertRaises(gst_portal.PortalApiAccessDisabled) as e:
				self._call(body)
			log.assert_not_called()  # a known taxpayer setting, not an error to log
		self.assertIn("Manage API Access", str(e.exception))
