# apps/litwatch/litwatch/api/clients.py
"""
Client APIs used by the frontend (roster, create, active client, onboarding
pipeline). They now run on the Business doctype: a "client" is a Business and
its "key" is the Business ID. GST registrations come from the GSTIN doctype.
Endpoint paths and response shapes are unchanged.
"""

import frappe
from frappe import _
from frappe.utils import add_months, get_first_day, get_last_day, getdate, nowdate

from litwatch.api.business import new_business, onboarding_stages


def _request_params():
	"""JSON body + form_dict + query string (first non-empty wins in that order)."""
	body = {}
	if frappe.request and frappe.request.data:
		try:
			body = frappe.request.get_json(silent=True) or {}
		except Exception:
			body = {}
	fd = dict(frappe.form_dict or {})
	qs = dict(frappe.request.args or {}) if frappe.request else {}
	return [s for s in (body, fd, qs) if isinstance(s, dict)]


def _pick(sources, *keys):
	for src in sources:
		for k in keys:
			v = src.get(k)
			if v not in (None, ""):
				return v
	return None


def _resolve_business(key):
	"""Business ID from a key; also accepts a short name (e.g. old client codes like 'GT')."""
	key = str(key).strip()
	if frappe.db.exists("Business", key):
		return key
	alt = frappe.db.get_value("Business", {"short_name": key.upper()}, "name")
	if alt:
		return str(alt)
	frappe.throw(_("Client {0} not found").format(key), frappe.DoesNotExistError)


# ---------------------------------------------------------------------------
# GET litwatch.api.clients.get_clients
# ---------------------------------------------------------------------------
def _allowed_business_ids(gst_user=None):
	"""Business IDs the caller may see, or None for "all".

	- gst_user given: that GST User's businesses (System Manager only, unless it is
	  the caller's own GST User).
	- otherwise the caller's own GST User (GST User is named by the User's email):
	  only the businesses in its Business ID table.
	- a System Manager without a GST User record: all businesses (firm staff).
	- anyone else without a GST User record: none.
	"""
	user = frappe.session.user
	is_admin = "System Manager" in frappe.get_roles(user)
	if gst_user:
		gst_user = str(gst_user).strip()
		if not frappe.db.exists("GST User", gst_user):
			frappe.throw(_("GST User {0} not found").format(gst_user), frappe.DoesNotExistError)
		if not is_admin and gst_user.lower() != user.lower():
			frappe.throw(_("Not permitted to view another GST User's businesses"), frappe.PermissionError)
	elif frappe.db.exists("GST User", user):
		gst_user = user
	elif is_admin:
		return None
	else:
		return []

	return [
		str(b) for b in frappe.get_all(
			"GST User Business",
			filters={"parenttype": "GST User", "parent": gst_user},
			pluck="business",
			order_by="idx asc",
		) if b
	]


@frappe.whitelist(methods=["GET"])
def get_clients(gstUser=None):
	"""
	Client roster with summary metrics: only the Businesses that belong to the
	GST User (see _allowed_business_ids). Optional query param gstUser=<email>
	(System Manager only) returns that GST User's businesses.

	  [{ "key": "1", "name": "...", "shortName": "...", "pan": "...", "sector": "...",
	     "notices": 2, "demand": 0, "overdue": 0,
	     "registrations": [{"gstin": "...", "state": null, "consent": "active"}],
	     "trendData": [12 monthly counts of notices received], "resolvedData": [12 zeros] }]

	notices / trendData count Notice records with this Business ID (trendData by
	the month the notice was imported). demand, overdue and resolvedData are 0:
	Notice has no structured demand, due-date or resolved fields yet.
	"""
	gstUser = gstUser or _pick(_request_params(), "gstUser", "gst_user")
	allowed = _allowed_business_ids(gstUser)
	if allowed is not None and not allowed:
		return []

	businesses = frappe.get_all(
		"Business",
		filters={"name": ["in", allowed]} if allowed is not None else None,
		fields=["name", "business_name", "short_name", "pan", "sector"],
		order_by="name asc",
		limit_page_length=0,
	)
	if not businesses:
		return []

	gstins = frappe.get_all(
		"GSTIN", fields=["name", "business_id", "state", "consent_status"], limit_page_length=0
	)
	regs_by_business = {}
	for g in gstins:
		regs_by_business.setdefault(str(g.business_id), []).append(
			{"gstin": g.name, "state": g.state, "consent": g.consent_status or "inactive"}
		)

	today = getdate(nowdate())
	months = [add_months(today, -i) for i in range(11, -1, -1)]
	window_start = get_first_day(months[0])
	window_end = get_last_day(months[-1])

	counts = dict(
		frappe.db.sql(
			"""SELECT business_id, COUNT(*) FROM `tabNotice`
			WHERE IFNULL(business_id, '') != '' GROUP BY business_id"""
		)
	)
	monthly = {}
	for business_id, ym, n in frappe.db.sql(
		"""SELECT business_id, DATE_FORMAT(creation, '%%Y-%%m'), COUNT(*) FROM `tabNotice`
		WHERE IFNULL(business_id, '') != '' AND creation BETWEEN %s AND %s
		GROUP BY business_id, DATE_FORMAT(creation, '%%Y-%%m')""",
		(f"{window_start} 00:00:00", f"{window_end} 23:59:59"),
	):
		monthly[(str(business_id), ym)] = n

	result = []
	for b in businesses:
		key = str(b.name)
		result.append(
			{
				"key": key,
				"name": b.business_name,
				"shortName": b.short_name,
				"pan": b.pan,
				"sector": b.sector,
				"notices": counts.get(key, 0),
				"demand": 0,
				"overdue": 0,
				"registrations": regs_by_business.get(key, []),
				"trendData": [monthly.get((key, m.strftime("%Y-%m")), 0) for m in months],
				"resolvedData": [0] * len(months),
			}
		)
	return result


# ---------------------------------------------------------------------------
# POST litwatch.api.clients.create_client
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["POST"])
def create_client(name=None, pan=None, sector=None, firstGstin=None):
	"""Creates a Business (and its first GSTIN). Same as business.create_business,
	in the client response shape. Returns HTTP 201."""
	sources = _request_params()
	name = name or _pick(sources, "name")
	pan = pan or _pick(sources, "pan")
	sector = sector or _pick(sources, "sector")
	firstGstin = firstGstin or _pick(sources, "firstGstin", "gstin")
	portal_user_id = _pick(sources, "portalUserId")

	business, gstins = new_business(name, pan, sector, firstGstin, portal_user_id=portal_user_id)
	frappe.db.commit()

	frappe.local.response.http_status_code = 201
	return {
		"key": str(business.name),
		"name": business.business_name,
		"notices": 0,
		"registrations": gstins,
	}


# ---------------------------------------------------------------------------
# PATCH litwatch.api.clients.set_active_client   (raw JSON response)
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["PATCH", "POST"])
def set_active_client(clientKey=None):
	"""Stores the caller's active Business. Returns { "clientKey": "<Business ID>" }."""
	client_key = clientKey or _pick(_request_params(), "clientKey", "client_key", "key", "businessId")
	if not client_key:
		frappe.throw(_("clientKey is required"))

	business_id = _resolve_business(client_key)
	frappe.defaults.set_user_default("active_client", business_id)

	frappe.local.response.update({"clientKey": business_id})
	frappe.local.response.http_status_code = 200
	return


# ---------------------------------------------------------------------------
# GET litwatch.api.clients.get_active_client   (raw JSON response)
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["GET"])
def get_active_client():
	"""Returns { "clientKey": "<Business ID>" } or { "clientKey": null }."""
	client_key = frappe.defaults.get_user_default("active_client") or None
	if client_key and not frappe.db.exists("Business", client_key):
		client_key = None  # stale value (e.g. an old Client code)

	frappe.local.response.update({"clientKey": client_key})
	frappe.local.response.http_status_code = 200
	return


# ---------------------------------------------------------------------------
# GET litwatch.api.clients.get_client_pipeline   (response wrapped in "data")
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["GET"])
def get_client_pipeline():
	"""Businesses still onboarding (stage not Complete), sorted by stage then date."""
	businesses = frappe.get_all(
		"Business",
		filters={"onboarding_stage": ["!=", "Complete"]},
		fields=["name", "business_name", "sector", "onboarding_stage", "onboarding_date"],
		limit_page_length=0,
	)
	gstin_counts = dict(
		frappe.db.sql(
			"""SELECT business_id, COUNT(*) FROM `tabGSTIN`
			WHERE IFNULL(business_id, '') != '' GROUP BY business_id"""
		)
	)

	result = []
	for b in businesses:
		when = b.get("onboarding_date")
		result.append(
			{
				"id": str(b.name),
				"name": b.business_name,
				"sector": b.sector,
				"stage": b.onboarding_stage,
				"gstins": gstin_counts.get(str(b.name), 0),
				"when": str(getdate(when)) if when else None,
			}
		)

	stage_order = {stage: i for i, stage in enumerate(onboarding_stages(), start=1)}
	result.sort(key=lambda r: (stage_order.get(r["stage"], 99), r.get("when") or ""))

	frappe.local.response.update({"data": result})
	frappe.local.response.http_status_code = 200
	return


# ---------------------------------------------------------------------------
# PATCH litwatch.api.clients.update_client_pipeline_stage   (raw JSON response)
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["PATCH", "POST"])
def update_client_pipeline_stage(id=None, stage=None):
	"""Moves a Business to another onboarding stage. Returns { "name": ..., "stage": ... }."""
	sources = _request_params()
	id = id or _pick(sources, "id", "clientKey", "client_key", "key", "businessId")
	stage = stage or _pick(sources, "stage", "onboarding_stage")

	if not id:
		frappe.throw(_("id is required"))
	if not stage:
		frappe.throw(_("stage is required"))

	valid_stages = onboarding_stages()
	if stage not in valid_stages:
		frappe.throw(_("Invalid stage: {0}. Must be one of {1}").format(stage, valid_stages))

	business_id = _resolve_business(id)
	frappe.db.set_value("Business", business_id, "onboarding_stage", stage)
	frappe.db.commit()

	frappe.local.response.update({"name": frappe.db.get_value("Business", business_id, "business_name"), "stage": stage})
	frappe.local.response.http_status_code = 200
	return
