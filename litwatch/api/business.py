# apps/litwatch/litwatch/api/business.py
"""Businesses and their GSTINs: the taxpayer side of the GST notice flow.

A Business (auto-increment ID) owns GSTINs. Each GSTIN is linked both ways:
  GSTIN.business_id = <Business ID>   and   Business.gstins[] -> GSTIN
"""

import re

import frappe
from frappe import _

from litwatch import scope

GSTIN_RE = re.compile(r"[0-9]{2}[A-Z0-9]{13}")


def _params():
	"""Body, query string and form_dict merged."""
	params = dict(frappe.form_dict or {})
	params.pop("cmd", None)
	req = frappe.request
	if req and req.data:
		try:
			body = req.get_json(silent=True) or {}
			if isinstance(body, dict):
				params.update(body)
		except Exception:
			pass
	return params


def _clean_gstin(value):
	gstin = str(value or "").strip().upper()
	if not GSTIN_RE.fullmatch(gstin):
		frappe.throw(_("Invalid GSTIN: {0}").format(value or ""))
	return gstin


def _attach_gstin(business, gstin, address=None, portal_user_id=None):
	"""Create the GSTIN (or reuse it if it belongs to this business) with business_id set.
	The GSTIN controller adds it to the Business's GSTIN table."""
	business_id = str(business.name)
	if frappe.db.exists("GSTIN", gstin):
		owner = frappe.db.get_value("GSTIN", gstin, "business_id")
		if owner and str(owner) != business_id:
			frappe.throw(_("GSTIN {0} already belongs to Business {1}").format(gstin, owner))
		if scope.is_individual() and not scope.gstin_allowed(gstin):
			# an Individual cannot claim a GSTIN someone else holds; firm staff add them to its Users table
			frappe.throw(_("GSTIN {0} is already registered. Ask the firm to add you to its users.").format(gstin),
			             frappe.PermissionError)
		doc = frappe.get_doc("GSTIN", gstin)
		doc.business_id = business_id
		if address:
			doc.address = address
		if portal_user_id:
			doc.portal_user_id = portal_user_id
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "GSTIN",
				"gstin": gstin,
				"business_id": business_id,
				"address": address,
				"portal_user_id": portal_user_id,
				"consent_status": "inactive",
			}
		).insert(ignore_permissions=True)
	scope.link_gstin_to_scope_user(doc.name)  # an Individual owns the GSTINs they add
	return doc


def _gstin_row(doc):
	return {"gstin": doc.name, "state": doc.state, "consent": doc.consent_status or "inactive"}


def _initials(name):
	return "".join(w[0].upper() for w in name.split() if w and w[0].isalnum()) or "BIZ"


def resolve_firm_profile():
	"""User default, else one already used by a business, else the first Firm Profile (or None)."""
	firm_profile = frappe.defaults.get_user_default("firm_profile")
	if firm_profile and frappe.db.exists("Firm Profile", firm_profile):
		return firm_profile
	existing = frappe.db.get_value("Business", {"firm_profile": ["is", "set"]}, "firm_profile")
	if existing and frappe.db.exists("Firm Profile", existing):
		return existing
	return frappe.db.get_value("Firm Profile", {}, "name", order_by="creation asc")


def onboarding_stages():
	options = frappe.get_meta("Business").get_field("onboarding_stage").options or ""
	return [o for o in options.split("\n") if o]


def new_business(name, pan=None, sector=None, first_gstin=None, address=None, portal_user_id=None):
	"""Create a Business (with onboarding defaults) and optionally its first GSTIN.
	Returns (business, [gstin rows])."""
	from frappe.utils import nowdate

	name = str(name or "").strip()
	if not name:
		frappe.throw(_("name is required"))

	gstin = _clean_gstin(first_gstin) if first_gstin else None
	if gstin:
		owner = frappe.db.get_value("GSTIN", gstin, "business_id")
		if owner:
			frappe.throw(_("GSTIN {0} already belongs to Business {1}").format(gstin, owner))

	stages = onboarding_stages()
	business = frappe.get_doc(
		{
			"doctype": "Business",
			"business_name": name,
			"short_name": _initials(name),
			"pan": str(pan).strip().upper() if pan else None,
			"sector": str(sector).strip() if sector else None,
			"status": "Active",
			"firm_profile": resolve_firm_profile(),
			"onboarding_stage": stages[0] if stages else None,
			"onboarding_date": nowdate(),
		}
	).insert(ignore_permissions=True)

	rows = []
	if gstin:
		rows.append(_gstin_row(_attach_gstin(business, gstin, address, portal_user_id)))
	return business, rows


# ---------------------------------------------------------------------------
# POST litwatch.api.business.create_business
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["POST"])
def create_business(name=None, pan=None, sector=None, firstGstin=None, address=None, portalUserId=None):
	"""Create a Business and, optionally, its first GSTIN. Returns HTTP 201."""
	p = _params()
	name = str(name or p.get("name") or p.get("businessName") or "").strip()
	pan = pan or p.get("pan")
	sector = sector or p.get("sector")
	firstGstin = firstGstin or p.get("firstGstin") or p.get("gstin")
	address = address or p.get("address")
	portalUserId = portalUserId or p.get("portalUserId")

	business, gstins = new_business(name, pan, sector, firstGstin, address, portalUserId)

	frappe.db.commit()
	frappe.local.response.http_status_code = 201
	return {
		"businessId": str(business.name),
		"name": business.business_name,
		"approval": business.approval_status or "Approved",
		"notices": 0,
		"gstins": gstins,
	}


# ---------------------------------------------------------------------------
# POST litwatch.api.business.add_gstin
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["POST"])
def add_gstin(businessId=None, gstin=None, address=None, portalUserId=None):
	"""Add another GSTIN to an existing Business."""
	p = _params()
	businessId = businessId or p.get("businessId") or p.get("business_id")
	gstin = _clean_gstin(gstin or p.get("gstin"))
	address = address or p.get("address")
	portalUserId = portalUserId or p.get("portalUserId")

	if not businessId or not frappe.db.exists("Business", businessId):
		frappe.throw(_("Business {0} not found").format(businessId or ""), frappe.DoesNotExistError)
	scope.check_business(businessId)  # only the caller's own businesses

	business = frappe.get_doc("Business", businessId)
	business.check_permission("write")
	doc = _attach_gstin(business, gstin, address, portalUserId)
	frappe.db.commit()
	return {"businessId": str(business.name), "gstin": _gstin_row(doc)}


# ---------------------------------------------------------------------------
# GET litwatch.api.business.get_businesses
# ---------------------------------------------------------------------------
def _gstin_users(gstin_names):
	"""{gstin: [{"email", "name"}]} from each GSTIN's Users table (GSTIN User -> GST User), in table order."""
	if not gstin_names:
		return {}
	rows = frappe.get_all(
		"GSTIN User",
		filters={"parenttype": "GSTIN", "parentfield": "users", "parent": ["in", gstin_names]},
		fields=["parent", "user"],
		order_by="parent asc, idx asc",
		limit_page_length=0,
	)
	emails = {r.user for r in rows if r.user}
	names = (
		dict(frappe.get_all("GST User", filters={"name": ["in", list(emails)]}, fields=["name", "user_name"], as_list=True))
		if emails else {}
	)
	out = {}
	for r in rows:
		if r.user:
			out.setdefault(r.parent, []).append({"email": r.user, "name": names.get(r.user) or None})
	return out


@frappe.whitelist(methods=["GET"])
def get_businesses():
	"""Every Business the caller may see (litwatch/scope.py) with its GSTINs and their consent status."""
	allowed = scope.get_scope()
	if allowed is not None and not allowed:
		return []
	businesses = frappe.get_all(
		"Business",
		filters={"name": ["in", allowed]} if allowed is not None else None,
		fields=["name", "business_name", "pan", "sector", "status", "approval_status", "approval_note"],
		order_by="name asc",
		limit_page_length=0,
	)
	gstin_filters = {"business_id": ["in", allowed]} if allowed is not None else {}
	if scope.gstin_filter():
		gstin_filters["name"] = scope.gstin_filter()  # Individual: only their own GSTINs
	gstins = frappe.get_all(
		"GSTIN",
		filters=gstin_filters or None,
		fields=["name", "business_id", "state", "consent_status", "address", "portal_user_id"],
		limit_page_length=0,
	)
	users_by_gstin = _gstin_users([g.name for g in gstins])
	by_business = {}
	for g in gstins:
		by_business.setdefault(str(g.business_id), []).append(
			{
				"gstin": g.name,
				"state": g.state,
				"consent": g.consent_status or "inactive",
				"address": g.address or None,
				"portalUserId": g.portal_user_id or None,
				"users": users_by_gstin.get(g.name, []),
			}
		)
	notice_counts = scope.notice_counts()
	if notice_counts is None:
		notice_counts = dict(
			frappe.db.sql(
				"""SELECT business_id, COUNT(*) FROM `tabNotice`
				WHERE IFNULL(business_id, '') != '' GROUP BY business_id"""
			)
		)
	return [
		{
			"businessId": str(b.name),
			"name": b.business_name,
			"pan": b.pan,
			"sector": b.sector,
			"status": b.status,
			"approval": b.approval_status or "Approved",
			"approvalNote": b.approval_note or None,
			"gstins": by_business.get(str(b.name), []),
			"notices": notice_counts.get(str(b.name), 0),
		}
		for b in businesses
	]
