# apps/litwatch/litwatch/api/gstin.py

import frappe
from frappe import _
from frappe.utils import add_months, add_to_date, get_datetime, getdate, now_datetime, nowdate

from litwatch.api import gst_portal

VALID_CONSENT = ("inactive", "pending", "active", "expired")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _request_params():
	"""JSON body + query string + form_dict merged (body wins).
	The Next.js proxy sends some params in the body and some in the query."""
	params = {}
	req = frappe.request
	if req:
		params.update({k: v for k, v in (req.args or {}).items() if v not in (None, "")})
		if req.data:
			try:
				body = req.get_json(silent=True) or {}
				if isinstance(body, dict):
					params.update({k: v for k, v in body.items() if v not in (None, "")})
			except Exception:
				pass
	for k, v in (frappe.form_dict or {}).items():
		if k != "cmd" and v not in (None, "") and k not in params:
			params[k] = v
	return params


def _pick(params, *keys):
	for k in keys:
		if params.get(k) not in (None, ""):
			return params[k]
	return None


def _get_registration(gstin, ptype="write"):
	if not gstin:
		frappe.throw(_("gstin is required"))
	if not frappe.db.exists("GST Registration", gstin):
		frappe.throw(_("GST Registration {0} not found").format(gstin), frappe.DoesNotExistError)
	reg = frappe.get_doc("GST Registration", gstin)
	if ptype:
		reg.check_permission(ptype)
	return reg


def _iso(dt):
	return get_datetime(dt).isoformat() + "Z" if dt else None


def _new_otp_request(gstin, otp_sent_to):
	# Only one live OTP request per GSTIN.
	frappe.db.sql(
		"""UPDATE `tabGST OTP Request` SET status = 'expired'
		WHERE gstin = %s AND status = 'pending'""",
		gstin,
	)
	otp_request_id = f"OTP-{frappe.generate_hash(length=8).upper()}"
	frappe.get_doc(
		{
			"doctype": "GST OTP Request",
			"gstin": gstin,
			"otp_request_id": otp_request_id,
			"otp_sent_to": otp_sent_to,
			"status": "pending",
			"requested_at": now_datetime(),
			"expires_at": add_to_date(now_datetime(), minutes=gst_portal.otp_validity_minutes()),
		}
	).insert(ignore_permissions=True)
	return otp_request_id


# ---------------------------------------------------------------------------
# 3.1 GET get_gstin_connections
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["GET"])
def get_gstin_connections():
	registrations = frappe.get_all(
		"GST Registration",
		fields=["name", "city", "state", "client", "consent_status", "valid_until", "last_checked"],
		order_by="modified desc",
		limit_page_length=0,
	)
	if not registrations:
		return []

	state_codes = dict(frappe.get_all("State", fields=["name", "state_code"], as_list=True))
	client_codes = dict(frappe.get_all("Client", fields=["name", "client_code"], as_list=True))
	notice_counts = dict(
		frappe.db.sql(
			"""SELECT gstin, COUNT(*) FROM `tabLitigation Notice`
			WHERE gstin IS NOT NULL GROUP BY gstin"""
		)
	)

	today = getdate(nowdate())
	result = []
	for reg in registrations:
		if reg.client not in client_codes:
			# Orphaned link: log it and skip the row instead of failing the whole list.
			frappe.log_error(
				title="GST Registration with missing Client",
				message=f"GST Registration {reg.name} points to missing Client {reg.client}",
			)
			continue

		consent = reg.consent_status or "inactive"
		# Consent past its validity date is shown as expired even before a job updates it.
		if consent == "active" and reg.valid_until and getdate(reg.valid_until) < today:
			consent = "expired"

		state = reg.state
		result.append(
			{
				"gstin": reg.name,
				"code": state_codes.get(state) or (state[:2].upper() if state else ""),
				"city": reg.city,
				"state": state,
				"client": client_codes.get(reg.client),
				"clientKey": reg.client,
				"consent": consent,
				"validUntil": str(reg.valid_until) if reg.valid_until else None,
				"lastChecked": _iso(reg.last_checked),
				"notices": notice_counts.get(reg.name, 0),
			}
		)
	return result


# ---------------------------------------------------------------------------
# 3.2 POST connect_gstin   body: gstin, portalUserId
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["POST"])
def connect_gstin(gstin=None, portalUserId=None):
	p = _request_params()
	gstin = gstin or _pick(p, "gstin")
	portalUserId = portalUserId or _pick(p, "portalUserId", "portal_user_id")

	if not portalUserId:
		frappe.throw(_("portalUserId is required"))

	reg = _get_registration(gstin)

	otp_sent_to = gst_portal.request_otp(gstin, portalUserId)

	reg.portal_user_id = portalUserId
	if reg.consent_status != "active":
		reg.consent_status = "pending"
	reg.save(ignore_permissions=True)

	otp_request_id = _new_otp_request(gstin, otp_sent_to)
	frappe.db.commit()

	return {"otpSentTo": otp_sent_to, "otpRequestId": otp_request_id}


# ---------------------------------------------------------------------------
# 3.3 POST verify_gstin_otp   body: gstin, otpRequestId, otp
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["POST"])
def verify_gstin_otp(gstin=None, otpRequestId=None, otp=None):
	p = _request_params()
	gstin = gstin or _pick(p, "gstin", "GSTIN")
	otpRequestId = otpRequestId or _pick(p, "otpRequestId", "otp_request_id")
	otp = otp or _pick(p, "otp", "OTP")

	if not otpRequestId:
		frappe.throw(_("otpRequestId is required"))
	if not otp:
		frappe.throw(_("otp is required"))

	reg = _get_registration(gstin)

	if not frappe.db.exists("GST OTP Request", otpRequestId):
		frappe.throw(_("OTP request {0} not found").format(otpRequestId), frappe.DoesNotExistError)
	otp_req = frappe.get_doc("GST OTP Request", otpRequestId)

	if otp_req.gstin != gstin:
		frappe.throw(_("OTP request {0} does not belong to GSTIN {1}").format(otpRequestId, gstin))
	if otp_req.status == "verified":
		frappe.throw(_("OTP request {0} has already been verified").format(otpRequestId))
	if otp_req.status == "expired" or (
		otp_req.expires_at and get_datetime(otp_req.expires_at) < now_datetime()
	):
		if otp_req.status != "expired":
			otp_req.db_set("status", "expired")
			frappe.db.commit()
		frappe.throw(_("OTP request {0} has expired. Please resend the OTP.").format(otpRequestId))

	if not gst_portal.verify_otp(gstin, reg.portal_user_id, otp):
		frappe.db.commit()  # keep the API usage count for the failed attempt
		frappe.throw(_("Invalid OTP"))

	reg.consent_status = "active"
	reg.valid_until = add_months(nowdate(), 12)
	reg.last_checked = now_datetime()
	reg.save(ignore_permissions=True)

	otp_req.status = "verified"
	otp_req.save(ignore_permissions=True)
	frappe.db.commit()

	return {"consent": reg.consent_status, "validUntil": str(reg.valid_until)}


# ---------------------------------------------------------------------------
# 3.4 POST resend_gstin_otp?gstin=
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["POST"])
def resend_gstin_otp(gstin=None):
	gstin = gstin or _pick(_request_params(), "gstin")
	reg = _get_registration(gstin)

	if not reg.portal_user_id:
		frappe.throw(_("GSTIN {0} has no portal user id. Call connect first.").format(gstin))

	otp_sent_to = gst_portal.request_otp(gstin, reg.portal_user_id)
	otp_request_id = _new_otp_request(gstin, otp_sent_to)
	frappe.db.commit()

	return {"otpRequestId": otp_request_id}


# ---------------------------------------------------------------------------
# Sync core (shared by "Sync now" and "Run all")
# ---------------------------------------------------------------------------
def _write_sync_log(gstin, seen, found, status, sync_run=None, error=None):
	frappe.get_doc(
		{
			"doctype": "GST Sync Log",
			"gstin": gstin,
			"sync_time": now_datetime(),
			"seen": seen,
			"found": found,
			"status": status,
			"sync_run": sync_run,
			"error": error,
		}
	).insert(ignore_permissions=True)


def _insert_portal_notice(reg, n):
	notice_type = n.get("notice_type")
	if notice_type and not frappe.db.exists("Notice Type", notice_type):
		notice_type = None

	doc = frappe.get_doc(
		{
			"doctype": "Litigation Notice",
			"notice_id": f"N-{frappe.generate_hash(length=6).upper()}",
			"client": reg.client,
			"gstin": reg.name,
			"portal_ref": n["portal_ref"],
			"state": reg.state,
			"city": n.get("city") or reg.city,
			"section": n.get("section"),
			"label": n.get("label"),
			"notice_type": notice_type,
			"fy": n.get("fy"),
			"amount": n.get("amount"),
			"filed_date": n.get("filed_date"),
			"due_date": n.get("due_date"),
			"status": "Under review",
			"extracted_by_ai": 0,
			"notice_data": n.get("notice_data") or {},
		}
	)
	doc.append("timeline", {"at": now_datetime(), "event": "Imported from GST portal"})
	doc.insert(ignore_permissions=True)


def _sync_one(reg, sync_run=None):
	"""Pull notices for one registration, insert new ones, write GST Sync Log.
	Returns {seen, found, status}."""
	portal_notices = gst_portal.fetch_notices(reg.name) or []
	seen = len(portal_notices)
	found = 0

	for n in portal_notices:
		ref = n.get("portal_ref")
		if not ref:
			continue
		if frappe.db.exists("Litigation Notice", {"portal_ref": ref}):
			continue
		_insert_portal_notice(reg, n)
		found += 1

	reg.db_set("last_checked", now_datetime(), update_modified=False)
	_write_sync_log(reg.name, seen, found, "ok", sync_run=sync_run)
	return {"seen": seen, "found": found, "status": "ok"}


# ---------------------------------------------------------------------------
# 3.5 POST sync_gstin_notices?gstin=
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["POST"])
def sync_gstin_notices(gstin=None):
	gstin = gstin or _pick(_request_params(), "gstin")
	reg = _get_registration(gstin)

	if reg.consent_status != "active":
		frappe.throw(_("GST Registration {0} has no active consent. Connect it first.").format(gstin))

	try:
		result = _sync_one(reg)
		frappe.db.commit()
		return result
	except Exception as e:
		frappe.db.rollback()
		_write_sync_log(gstin, 0, 0, "failed", error=str(e)[:1000])
		frappe.db.commit()
		raise


def run_sync_job(gstin, run_id=None):
	"""Background job queued by run_all_gstin_sync. Not whitelisted."""
	if run_id:
		frappe.db.sql(
			"UPDATE `tabSync Run` SET status = 'running' WHERE name = %s AND status = 'queued'",
			run_id,
		)
		frappe.db.commit()

	try:
		reg = frappe.get_doc("GST Registration", gstin)
		if reg.consent_status != "active":
			_write_sync_log(gstin, 0, 0, "skipped", sync_run=run_id, error="Consent not active")
		else:
			_sync_one(reg, sync_run=run_id)
		frappe.db.commit()
	except Exception as e:
		frappe.db.rollback()
		_write_sync_log(gstin, 0, 0, "failed", sync_run=run_id, error=str(e)[:1000])
		frappe.db.commit()
		frappe.log_error(title=f"GST sync failed for {gstin}", message=frappe.get_traceback())
	finally:
		if run_id:
			_mark_run_progress(run_id)


def _mark_run_progress(run_id):
	frappe.db.sql(
		"UPDATE `tabSync Run` SET gstins_done = IFNULL(gstins_done, 0) + 1 WHERE name = %s",
		run_id,
	)
	queued, done = frappe.db.get_value("Sync Run", run_id, ["gstins_queued", "gstins_done"])
	if (done or 0) >= (queued or 0):
		failed = frappe.db.count("GST Sync Log", {"sync_run": run_id, "status": "failed"})
		frappe.db.set_value(
			"Sync Run",
			run_id,
			{"status": "failed" if failed and failed >= queued else "done", "finished_at": now_datetime()},
		)
	frappe.db.commit()


# ---------------------------------------------------------------------------
# 3.6 POST run_all_gstin_sync
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["POST"])
def run_all_gstin_sync():
	gstins = [
		g
		for g in frappe.get_all(
			"GST Registration", filters={"consent_status": "active"}, pluck="name", limit_page_length=0
		)
		if frappe.has_permission("GST Registration", "write", g)
	]

	run_id = f"RUN-{frappe.generate_hash(length=8).upper()}"
	frappe.get_doc(
		{
			"doctype": "Sync Run",
			"run_id": run_id,
			"gstins_queued": len(gstins),
			"gstins_done": 0,
			"started_at": now_datetime(),
			"status": "queued" if gstins else "done",
			"finished_at": None if gstins else now_datetime(),
		}
	).insert(ignore_permissions=True)

	for gstin in gstins:
		frappe.enqueue(
			"litwatch.api.gstin.run_sync_job",
			queue="long",
			timeout=600,
			gstin=gstin,
			run_id=run_id,
			enqueue_after_commit=True,
		)

	frappe.db.commit()
	frappe.local.response.http_status_code = 202
	return {"runId": run_id, "gstinsQueued": len(gstins)}


# ---------------------------------------------------------------------------
# 3.7 GET get_sync_usage
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["GET"])
def get_sync_usage():
	today = nowdate()
	today_d = getdate(today)

	token_valid_until = frappe.db.get_value(
		"API Usage Log",
		{"token_valid_until": ["is", "set"]},
		"token_valid_until",
		order_by="log_date desc, modified desc",
	)

	week_start = frappe.utils.add_days(today_d, -today_d.weekday())
	week_end = frappe.utils.add_days(week_start, 6)
	notices_this_week = frappe.db.count(
		"Litigation Notice",
		filters={"creation": ["between", [f"{week_start} 00:00:00", f"{week_end} 23:59:59"]]},
	)

	skipped_runs = frappe.db.count("GST Sync Log", filters={"status": "skipped"})

	by_endpoint = frappe.db.sql(
		"""
		SELECT endpoint_name AS name, CAST(SUM(calls) AS SIGNED) AS calls, 'today' AS `when`
		FROM `tabAPI Usage Log`
		WHERE log_date = %(today)s
		GROUP BY endpoint_name
		ORDER BY calls DESC
		""",
		{"today": today},
		as_dict=True,
	)

	return {
		"callsUsed": gst_portal.calls_used_today(),
		"callsCap": gst_portal.call_cap(),
		"tokenValidUntil": str(token_valid_until) if token_valid_until else None,
		"noticesThisWeek": notices_this_week,
		"skippedRuns": skipped_runs,
		"byEndpoint": by_endpoint,
	}


# ---------------------------------------------------------------------------
# 3.8 GET get_sync_log?gstin=
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["GET"])
def get_sync_log(gstin=None):
	filters = {}
	if gstin:
		if not frappe.db.exists("GST Registration", gstin):
			frappe.throw(_("GST Registration {0} not found").format(gstin), frappe.DoesNotExistError)
		filters["gstin"] = gstin

	rows = frappe.get_all(
		"GST Sync Log",
		filters=filters,
		fields=["sync_time as time", "gstin", "seen", "found", "status"],
		order_by="sync_time desc",
		limit_page_length=100,
	)
	for r in rows:
		r["time"] = _iso(r.get("time"))
	return rows
