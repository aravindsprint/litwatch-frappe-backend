# apps/litwatch/litwatch/api/gst_portal.py
"""
Single place for every call to the GST portal (via Adaequare).

Nothing here is whitelisted. gstin.py calls these helpers, so when the real
Adaequare integration is written only this file changes.

Behaviour today:
  - Sync Settings > Mock GST Portal ON  -> mock responses (OTP 123456 only).
  - Mock OFF                            -> clear error until the real calls are written.
Every successful call is counted in API Usage Log, which feeds get_sync_usage.
"""

import frappe
from frappe import _
from frappe.utils import cint, nowdate

MOCK_OTP = "123456"
MOCK_SENT_TO = "•• 42"


class PortalNotConfigured(frappe.ValidationError):
	pass


class CallCapReached(frappe.ValidationError):
	pass


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------
def is_mock():
	return bool(cint(frappe.db.get_single_value("Sync Settings", "mock_portal")))


def call_cap():
	return cint(frappe.db.get_single_value("Sync Settings", "daily_call_cap"))


def otp_validity_minutes():
	return cint(frappe.db.get_single_value("Sync Settings", "otp_validity_minutes")) or 10


def calls_used_today():
	return cint(
		frappe.db.get_value("API Usage Log", {"log_date": nowdate()}, "sum(calls)") or 0
	)


def _check_cap():
	cap = call_cap()
	if cap and calls_used_today() >= cap:
		frappe.throw(
			_("Daily GST portal API cap of {0} calls reached. Try again tomorrow.").format(cap),
			CallCapReached,
		)


def _adaequare_settings():
	name = frappe.db.get_value("Adaequare Settings", {"is_active": 1}, "name")
	if not name:
		frappe.throw(
			_("No active Adaequare Settings found. Configure one, or enable Mock GST Portal in Sync Settings for testing."),
			PortalNotConfigured,
		)
	return frappe.get_doc("Adaequare Settings", name)


def _not_implemented(what):
	frappe.throw(
		_("GST portal call '{0}' is not implemented yet. Enable Mock GST Portal in Sync Settings for testing.").format(what),
		PortalNotConfigured,
	)


# ---------------------------------------------------------------------------
# Usage logging
# ---------------------------------------------------------------------------
def log_api_call(endpoint, calls=1, token_valid_until=None):
	"""One API Usage Log row per endpoint per day; calls is incremented."""
	today = nowdate()
	name = frappe.db.get_value(
		"API Usage Log", {"endpoint_name": endpoint, "log_date": today}, "name"
	)
	if name:
		frappe.db.sql(
			"UPDATE `tabAPI Usage Log` SET calls = IFNULL(calls, 0) + %s WHERE name = %s",
			(calls, name),
		)
		if token_valid_until:
			frappe.db.set_value("API Usage Log", name, "token_valid_until", token_valid_until)
	else:
		frappe.get_doc(
			{
				"doctype": "API Usage Log",
				"endpoint_name": endpoint,
				"log_date": today,
				"calls": calls,
				"token_valid_until": token_valid_until,
			}
		).insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Portal operations
# ---------------------------------------------------------------------------
def request_otp(gstin, portal_user_id):
	"""Ask the portal to send an OTP. Returns the masked destination, e.g. '•• 42'."""
	_check_cap()
	if is_mock():
		log_api_call("otp/request")
		return MOCK_SENT_TO

	_adaequare_settings()
	# TODO: real Adaequare OTP request using settings.client_id / client_secret.
	_not_implemented("otp/request")


def verify_otp(gstin, portal_user_id, otp):
	"""Returns True if the portal accepts the OTP, False otherwise."""
	_check_cap()
	if is_mock():
		log_api_call("otp/verify")
		return str(otp).strip() == MOCK_OTP

	_adaequare_settings()
	# TODO: real Adaequare OTP verification. Store the returned auth token
	# expiry via log_api_call(..., token_valid_until=...).
	_not_implemented("otp/verify")


def fetch_notices(gstin):
	"""
	Returns a list of notice dicts from the portal. Expected keys:
	  portal_ref (required, unique), section, label, notice_type, fy, amount,
	  filed_date, due_date, city, notice_data (optional dict)
	"""
	_check_cap()
	if is_mock():
		log_api_call("notices/list")
		return []

	_adaequare_settings()
	# TODO: real Adaequare notices API; map the response to the keys above.
	_not_implemented("notices/list")
