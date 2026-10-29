# apps/litwatch/litwatch/api/gst_portal.py
"""
Single place for every call to the GST portal through the Adaequare GSP
"enriched" notice APIs. Nothing here is whitelisted; gstin.py calls it.

Endpoints used (from the Adaequare "GST notice retrieval" collection):
  POST {base}/gsp/authenticate?grant_type=token          headers: gspappid, gspappsecret
  GET  {base}/enriched/notices?action=NOTCELIST            list of notices
  GET  {base}/enriched/notices?action=NOTCEDETAILS&refId=  details + document ids
  GET  {base}/enriched/document?action=DOCDOWNLOAD&doc_id= { ct, doc_nam, data(Base64) }
Every taxpayer call sends: username, gstin, ret_period, requestid,
Authorization: Bearer <token>, state-cd, otp (and form_typ for downloads).

Configuration: Adaequare Settings, one record per Business (named by the Business ID)
  client_id     -> gspappid
  client_secret -> gspappsecret
  base_url      -> GSP host (default https://gsp.adaequare.com)
The bearer token is cached on that record until shortly before it expires.

Sync Settings > Mock GST Portal returns the sample data from the collection
instead of calling Adaequare (OTP 123456), so the whole flow can be tested
without credentials.
"""

import base64
import json

import frappe
import requests
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, now_datetime, nowdate
from frappe.utils.password import set_encrypted_password

MOCK_OTP = "123456"
TIMEOUT = 60


class PortalNotConfigured(frappe.ValidationError):
	pass


class CallCapReached(frappe.ValidationError):
	pass


class PortalError(frappe.ValidationError):
	pass


class PortalOtpRequired(PortalError):
	"""The portal wants an OTP (none sent, a wrong one, or the session expired)."""


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
	return cint(frappe.db.get_value("API Usage Log", {"log_date": nowdate()}, "sum(calls)") or 0)


def _check_cap():
	cap = call_cap()
	if cap and calls_used_today() >= cap:
		frappe.throw(
			_("Daily GST portal API cap of {0} calls reached. Try again tomorrow.").format(cap),
			CallCapReached,
		)


def business_of(gstin):
	"""Business ID that owns the GSTIN, or None."""
	gstin = str(gstin or "").strip().upper()
	owner = frappe.db.get_value("GSTIN", gstin, "business_id") if gstin else None
	return str(owner) if owner else None


def _settings(gstin):
	"""The Adaequare Settings record of the Business that owns this GSTIN
	(the business's GSP app: Client ID, Secret, cached token). No fallback to another business."""
	gstin = str(gstin or "").strip().upper()
	business = business_of(gstin)
	if not business:
		frappe.throw(
			_("GSTIN {0} is not linked to a Business. Add it to a Business first.").format(gstin or "-"),
			PortalNotConfigured,
		)
	name = frappe.db.get_value("Adaequare Settings", {"name": business, "is_active": 1}, "name")
	if not name:
		reason = _("is not active") if frappe.db.exists("Adaequare Settings", business) else _("does not exist")
		frappe.throw(
			_("Adaequare Settings for Business {0} {1}. Add it at /app/adaequare-settings with the business's GSP Client ID and Client Secret (and tick Is Active), or enable Mock GST Portal in Sync Settings for testing.").format(business, reason),
			PortalNotConfigured,
		)
	return frappe.get_doc("Adaequare Settings", name)


# ---------------------------------------------------------------------------
# OTP stored on the Business's Adaequare Settings record (field "OTP")
# ---------------------------------------------------------------------------
def _own_record(gstin):
	business = business_of(gstin)
	return business if business and frappe.db.exists("Adaequare Settings", business) else None


def saved_otp(gstin):
	"""OTP in the Adaequare Settings record of the GSTIN's Business, if any."""
	name = _own_record(gstin)
	otp = frappe.db.get_value("Adaequare Settings", name, "otp") if name else None
	return str(otp).strip() if otp else None


def store_otp(gstin, otp):
	"""Save (or clear, with otp=None) the OTP on the Adaequare Settings record of the GSTIN's Business."""
	name = _own_record(gstin)
	if name:
		frappe.db.set_value("Adaequare Settings", name, "otp", str(otp).strip() if otp else None, update_modified=False)


def _base_url(settings):
	return (settings.get("base_url") or "https://gsp.adaequare.com").rstrip("/")


# ---------------------------------------------------------------------------
# Usage logging
# ---------------------------------------------------------------------------
def log_api_call(endpoint, calls=1, token_valid_until=None):
	"""One API Usage Log row per endpoint per day; calls is incremented."""
	today = nowdate()
	name = frappe.db.get_value("API Usage Log", {"endpoint_name": endpoint, "log_date": today}, "name")
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
# HTTP helpers (real portal)
# ---------------------------------------------------------------------------
def _json(resp):
	try:
		data = resp.json()
		return data if isinstance(data, dict) else {"_list": data}
	except ValueError:
		return {}


def _error_message(resp, data):
	"""Pull a readable message out of the error shapes GSPs return."""
	err = data.get("error") if isinstance(data, dict) else None
	if isinstance(err, dict):
		msg = err.get("message") or err.get("error_cd") or json.dumps(err)
	else:
		msg = (
			data.get("message")
			or data.get("errorMessage")
			or data.get("error_description")
			or (err if isinstance(err, str) else None)
		)
	return msg or f"HTTP {resp.status_code}: {resp.text[:300]}"


NO_RECORDS_CODES = ("NOTC_010",)


def _no_records(data):
	"""The portal's "No Records Found." (errorCode NOTC_010) comes with success false, but it means the
	taxpayer session is active and the list is empty, not a failure."""
	if not isinstance(data, dict):
		return False
	code = str(data.get("errorCode") or data.get("error_cd") or "").upper()
	msg = str(data.get("message") or "").strip().lower()
	return code in NO_RECORDS_CODES or msg.startswith("no records found")


def _is_error(resp, data):
	if resp.status_code != 200:
		return True
	if data.get("error"):
		return True
	if data.get("success") is False:
		return True
	if str(data.get("status_cd", "1")) == "0":
		return True
	return False


def _get_token(settings, force=False):
	"""GSP bearer token, cached on Adaequare Settings until 5 minutes before expiry."""
	if not force and settings.get("token_expires_at"):
		if get_datetime(settings.token_expires_at) > add_to_date(now_datetime(), minutes=5):
			token = settings.get_password("access_token", raise_exception=False)
			if token:
				return token

	_check_cap()
	resp = requests.post(
		f"{_base_url(settings)}/gsp/authenticate",
		params={"grant_type": "token"},
		headers={
			"gspappid": settings.client_id,
			"gspappsecret": settings.get_password("client_secret"),
		},
		timeout=TIMEOUT,
	)
	data = _json(resp)
	token = data.get("access_token")
	if resp.status_code != 200 or not token:
		msg = _error_message(resp, data)
		frappe.log_error(
			title=f"GSP authentication failed: Adaequare Settings {settings.name}",
			message=f"HTTP {resp.status_code}\nclient_id: {settings.client_id}\n{msg}\n\n{(resp.text or '')[:2000]}",
		)
		frappe.db.commit()
		frappe.throw(_("Adaequare authentication failed for Business {0}: {1}. Check the Client ID and Client Secret "
		               "on its Adaequare Settings.").format(settings.name, msg), PortalError)

	expires_at = add_to_date(now_datetime(), seconds=cint(data.get("expires_in")) or 3600)
	# Cache without a full save (no validation of the other settings fields).
	set_encrypted_password("Adaequare Settings", settings.name, token, "access_token")
	settings.db_set({"access_token": "*" * 8, "token_expires_at": expires_at}, update_modified=False)
	frappe.db.commit()
	log_api_call("authenticate", token_valid_until=expires_at)
	return token


def _ret_period():
	"""MMYYYY of the current month."""
	d = get_datetime(now_datetime())
	return f"{d.month:02d}{d.year}"


def _call(settings, path, params, gstin, username, otp=None, form_typ=None, endpoint="", retry_auth=True):
	_check_cap()
	headers = {
		"Content-Type": "application/json",
		"username": username or "",
		"gstin": gstin,
		"ret_period": _ret_period(),
		"requestid": f"gst-notice-{frappe.generate_hash(length=12)}",
		"Authorization": f"Bearer {_get_token(settings)}",
		"state-cd": gstin[:2],
	}
	if otp:
		headers["otp"] = otp
	if form_typ:
		headers["form_typ"] = form_typ

	resp = requests.get(f"{_base_url(settings)}{path}", params=params, headers=headers, timeout=TIMEOUT)
	log_api_call(endpoint)
	data = _json(resp)

	if resp.status_code == 401 and retry_auth:
		# GSP bearer token rejected: refresh it once and retry.
		_get_token(settings, force=True)
		return _call(settings, path, params, gstin, username, otp, form_typ, endpoint, retry_auth=False)

	if _no_records(data):
		# The call went through (portal session active): there is just nothing to list.
		return {"notices": []}

	if _is_error(resp, data):
		msg = _error_message(resp, data)
		if "otp" in msg.lower():
			raise PortalOtpRequired(msg)
		# Keep a trace: the request is rolled back after this error, which would also undo the usage count.
		frappe.log_error(
			title=f"GST portal error: {endpoint or path} {gstin}",
			message=f"HTTP {resp.status_code}\nusername: {username}\n{msg}\n\n{(resp.text or '')[:2000]}",
		)
		frappe.db.commit()
		raise PortalError(_("GST portal: {0}").format(msg))
	return data


# ---------------------------------------------------------------------------
# Mock data (the sample responses from the Adaequare collection)
# ---------------------------------------------------------------------------
_MOCK_LIST = [
	{"dateOfRespond": "NA", "alertCd": "AMYDT_NOTCE_MREMND", "moduleCd": "AMYDT", "refId": "ZD330726228205I", "arn": "AD3306260044469", "dateOfIssue": "27/07/2026"},
	{"dateOfRespond": "NA", "alertCd": "AMYDT_NOTCE_MREMND", "moduleCd": "AMYDT", "refId": "ZD330826183260E", "arn": "AD3306260044469", "dateOfIssue": "20/08/2026"},
	{"dateOfRespond": "NA", "alertCd": "AMYDT_NOTCE_MREMND", "moduleCd": "AMYDT", "refId": "ZD330926012396B", "arn": "AD3306260044469", "dateOfIssue": "02/09/2026"},
]


def _mock_details(ref_id):
	item = next((n for n in _MOCK_LIST if n["refId"] == ref_id), _MOCK_LIST[0])
	return {
		"maindocs": [{"dcupdtls": {"ct": "application/pdf", "docName": f"DOT_REMINDER_{ref_id}.pdf", "ty": "ADJN", "id": f"DOC{ref_id}", "hash": ""}}],
		"taxPeriod": {},
		"dueDateOfReply": "10/10/2026",
		"suppdocs": [],
		"noticeType": "REMINDER",
		"arn": item["arn"],
		"dateOfIssue": item["dateOfIssue"],
	}


def _mock_pdf(text):
	body = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
	pdf = (
		b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
		b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
		b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R"
		b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
		b"4 0 obj<</Length " + str(len(body)).encode() + b">>stream\n" + body + b"\nendstream endobj\n"
		b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
		b"trailer<</Root 1 0 R>>\n%%EOF"
	)
	return base64.b64encode(pdf).decode()


# ---------------------------------------------------------------------------
# Portal operations used by gstin.py
# ---------------------------------------------------------------------------
def request_otp(gstin, portal_user_id):
	"""Start the taxpayer session.

	Returns {"sent_to": <where the OTP went>, "session_active": bool}.

	The enriched APIs have no separate "send OTP" call: a taxpayer API called
	without an active session makes the portal send an OTP to the registered
	mobile / email and answer with an OTP-required error. So a notice list
	call without the otp header is used to trigger it. If that call succeeds,
	the portal session is already active and no OTP is needed."""
	if is_mock():
		_check_cap()
		log_api_call("otp/request")
		return {"sent_to": "•• 42", "session_active": False}

	settings = _settings(gstin)
	try:
		_call(settings, "/enriched/notices", {"action": "NOTCELIST"}, gstin, portal_user_id, endpoint="otp/request")
	except PortalOtpRequired:
		return {"sent_to": _("registered mobile / email"), "session_active": False}
	return {"sent_to": _("not needed (portal session already active)"), "session_active": True}


def verify_otp(gstin, portal_user_id, otp):
	"""True if the portal accepts the OTP (a notice list call succeeds with it)."""
	if is_mock():
		_check_cap()
		log_api_call("otp/verify")
		return str(otp).strip() == MOCK_OTP

	try:
		_call(
			_settings(gstin), "/enriched/notices", {"action": "NOTCELIST"},
			gstin, portal_user_id, otp=str(otp).strip(), endpoint="otp/verify",
		)
	except PortalOtpRequired:
		return False
	return True


def list_notices(gstin, portal_user_id, otp=None):
	"""[{refId, arn, alertCd, moduleCd, dateOfIssue, dateOfRespond}, ...]"""
	if is_mock():
		_check_cap()
		log_api_call("notices/list")
		return [dict(n) for n in _MOCK_LIST]

	data = _call(
		_settings(gstin), "/enriched/notices", {"action": "NOTCELIST"},
		gstin, portal_user_id, otp=otp, endpoint="notices/list",
	)
	return data.get("notices") or []


def get_notice_details(gstin, portal_user_id, ref_id, otp=None):
	"""{maindocs:[{dcupdtls:{ct, docName, ty, id, hash}}], suppdocs, noticeType,
	dueDateOfReply, arn, dateOfIssue, taxPeriod}"""
	if is_mock():
		_check_cap()
		log_api_call("notices/details")
		return _mock_details(ref_id)

	return _call(
		_settings(gstin), "/enriched/notices", {"action": "NOTCEDETAILS", "refId": ref_id},
		gstin, portal_user_id, otp=otp, endpoint="notices/details",
	)


def download_document(gstin, portal_user_id, doc_id, otp=None):
	"""{ct, doc_nam, data} where data is Base64 PDF content."""
	if is_mock():
		_check_cap()
		log_api_call("document/download")
		return {"ct": "application/pdf", "doc_nam": f"{doc_id}.pdf", "data": _mock_pdf(f"Mock GST notice document {doc_id}")}

	return _call(
		_settings(gstin), "/enriched/document", {"action": "DOCDOWNLOAD", "doc_id": doc_id},
		gstin, portal_user_id, otp=otp, form_typ="s", endpoint="document/download",
	)
