# apps/litwatch/litwatch/api/business.py
"""Businesses and their GSTINs: the taxpayer side of the GST notice flow.

A Business (auto-increment ID) owns GSTINs. Each GSTIN is linked both ways:
  GSTIN.business_id = <Business ID>   and   Business.gstins[] -> GSTIN
"""

import re

import frappe
from frappe import _

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
	"""Create the GSTIN record (or reuse it if it belongs to this business) and add it to the business."""
	business_id = str(business.name)
	if frappe.db.exists("GSTIN", gstin):
		owner = frappe.db.get_value("GSTIN", gstin, "business_id")
		if owner and str(owner) != business_id:
			frappe.throw(_("GSTIN {0} already belongs to Business {1}").format(gstin, owner))
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

	if not any(row.gstin == gstin for row in business.get("gstins") or []):
		business.append("gstins", {"gstin": gstin})
		business.save(ignore_permissions=True)
	return doc


def _gstin_row(doc):
	return {"gstin": doc.name, "state": doc.state, "consent": doc.consent_status or "inactive"}


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

	if not name:
		frappe.throw(_("name is required"))

	gstin = _clean_gstin(firstGstin) if firstGstin else None
	if gstin and frappe.db.get_value("GSTIN", gstin, "business_id"):
		frappe.throw(
			_("GSTIN {0} already belongs to Business {1}").format(gstin, frappe.db.get_value("GSTIN", gstin, "business_id"))
		)

	business = frappe.get_doc(
		{
			"doctype": "Business",
			"business_name": name,
			"pan": str(pan).strip().upper() if pan else None,
			"sector": str(sector).strip() if sector else None,
			"status": "Active",
		}
	).insert(ignore_permissions=True)

	gstins = []
	if gstin:
		gstins.append(_gstin_row(_attach_gstin(business, gstin, address, portalUserId)))

	frappe.db.commit()
	frappe.local.response.http_status_code = 201
	return {"businessId": str(business.name), "name": business.business_name, "notices": 0, "gstins": gstins}


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

	business = frappe.get_doc("Business", businessId)
	business.check_permission("write")
	doc = _attach_gstin(business, gstin, address, portalUserId)
	frappe.db.commit()
	return {"businessId": str(business.name), "gstin": _gstin_row(doc)}


# ---------------------------------------------------------------------------
# GET litwatch.api.business.get_businesses
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["GET"])
def get_businesses():
	"""Every Business with its GSTINs and their consent status."""
	businesses = frappe.get_all(
		"Business", fields=["name", "business_name", "pan", "sector", "status"], order_by="name asc", limit_page_length=0
	)
	gstins = frappe.get_all(
		"GSTIN", fields=["name", "business_id", "state", "consent_status"], limit_page_length=0
	)
	by_business = {}
	for g in gstins:
		by_business.setdefault(str(g.business_id), []).append(
			{"gstin": g.name, "state": g.state, "consent": g.consent_status or "inactive"}
		)
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
			"gstins": by_business.get(str(b.name), []),
			"notices": notice_counts.get(str(b.name), 0),
		}
		for b in businesses
	]
