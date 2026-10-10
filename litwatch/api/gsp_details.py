# apps/litwatch/litwatch/api/gsp_details.py
"""
Everything stored for one GSTIN's GST portal connection, in one call.

GET /api/method/litwatch.api.gsp_details.get_gstin_gsp_details?gstin=33AATCA0189J1ZD

Returns the GSP app credentials (Client ID and Secret) from the GSTIN's
Adaequare Settings record, the portal username, the current OTP, and the
expiry dates (consent, GSP token, latest OTP request).

Contains secrets: only System Manager may call it, and every call is logged.
"""

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime


def _iso(value):
	return get_datetime(value).isoformat() if value else None


def _password(doctype, name, field):
	try:
		return frappe.get_doc(doctype, name).get_password(field, raise_exception=False) or None
	except Exception:
		return None


@frappe.whitelist(methods=["GET"])
def get_gstin_gsp_details(gstin=None):
	"""
	{
	  "gstin": "33AATCA0189J1ZD",
	  "businessId": "32", "businessName": "Arsu Pvt Ltd",
	  "portalUserId": "arsupvtltd",
	  "consent": "active", "consentValidUntil": "2027-10-10", "lastChecked": "...",
	  "gsp": {"configured": true, "isActive": true, "clientId": "...", "clientSecret": "...",
	          "environment": "Live", "baseUrl": "https://gsp.adaequare.com",
	          "tokenExpiresAt": "...", "tokenValid": true},
	  "otp": {"value": "123456", "source": "adaequare_settings",
	          "latestRequestId": "OTP-...", "latestRequestStatus": "verified",
	          "requestedAt": "...", "expiresAt": "...", "expired": true}
	}
	"""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only System Manager can read GSP credentials"), frappe.PermissionError)

	gstin = str(gstin or frappe.form_dict.get("gstin") or "").strip().upper()
	if not gstin:
		frappe.throw(_("gstin is required"))
	if not frappe.db.exists("GSTIN", gstin):
		frappe.throw(_("GSTIN {0} not found").format(gstin), frappe.DoesNotExistError)

	reg = frappe.db.get_value(
		"GSTIN", gstin,
		["business_id", "portal_user_id", "consent_status", "valid_until", "last_checked", "portal_otp"],
		as_dict=True,
	)
	business_name = (
		frappe.db.get_value("Business", reg.business_id, "business_name")
		if reg.business_id and frappe.db.exists("Business", reg.business_id) else None
	)

	# GSP app (the GSTIN's own Adaequare Settings record)
	gsp = {"configured": False}
	settings_otp = None
	if frappe.db.exists("Adaequare Settings", gstin):
		s = frappe.get_doc("Adaequare Settings", gstin)
		expires = s.get("token_expires_at")
		gsp = {
			"configured": True,
			"isActive": bool(s.is_active),
			"clientId": s.client_id,
			"clientSecret": _password("Adaequare Settings", gstin, "client_secret"),
			"environment": s.get("environment"),
			"baseUrl": s.get("base_url") or "https://gsp.adaequare.com",
			"tokenExpiresAt": _iso(expires),
			"tokenValid": bool(expires and get_datetime(expires) > now_datetime()),
		}
		settings_otp = (s.get("otp") or "").strip() or None

	# OTP: Adaequare Settings "OTP" field first, else the one saved on the GSTIN at verify
	otp_value, otp_source = settings_otp, "adaequare_settings" if settings_otp else None
	if not otp_value and reg.portal_otp:
		otp_value = _password("GSTIN", gstin, "portal_otp")
		otp_source = "gstin" if otp_value else None

	latest = frappe.get_all(
		"GST OTP Request",
		filters={"gstin": gstin},
		fields=["name", "status", "requested_at", "expires_at", "otp_sent_to"],
		order_by="creation desc",
		limit=1,
	)
	latest = latest[0] if latest else None

	frappe.get_doc({
		"doctype": "Comment", "comment_type": "Info",
		"reference_doctype": "GSTIN", "reference_name": gstin,
		"content": _("GSP credentials read via API by {0}").format(frappe.session.user),
	}).insert(ignore_permissions=True)
	frappe.db.commit()  # GET requests are not committed automatically

	return {
		"gstin": gstin,
		"businessId": reg.business_id,
		"businessName": business_name,
		"portalUserId": reg.portal_user_id,
		"consent": reg.consent_status or "inactive",
		"consentValidUntil": str(reg.valid_until) if reg.valid_until else None,
		"lastChecked": _iso(reg.last_checked),
		"gsp": gsp,
		"otp": {
			"value": otp_value,
			"source": otp_source,
			"latestRequestId": latest.name if latest else None,
			"latestRequestStatus": latest.status if latest else None,
			"sentTo": latest.otp_sent_to if latest else None,
			"requestedAt": _iso(latest.requested_at) if latest else None,
			"expiresAt": _iso(latest.expires_at) if latest else None,
			"expired": bool(latest and latest.expires_at and get_datetime(latest.expires_at) < now_datetime()),
		},
	}
