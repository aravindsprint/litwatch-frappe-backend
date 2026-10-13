# apps/litwatch/litwatch/api/notices.py
"""
Notices for one client (Business).

GET /api/method/litwatch.api.notices.get_client_notices?client_key=<Business ID>

A notice belongs to a client when its business_id is the Business ID, or when
its gstin is one of the Business's GSTINs (covers notices imported before the
GSTIN was moved to this Business).
"""

import json

import frappe
from frappe import _

from litwatch import scope
from frappe.utils import cint, getdate

# Shown in the list view; everything else comes with full=1
SUMMARY_FIELDS = [
	"name", "business_id", "gstin", "portal_ref_id", "client_id",
	"proceeding_stage", "proceeding_id", "originating_scn_reference",
	"portal_metadata", "docstatus", "creation", "modified",
]
JSON_FIELDS = [
	"portal_metadata", "document_identity", "taxpayer", "notice", "jurisdiction_and_authority",
	"legal_basis", "demand", "issues", "hearing", "extensions", "related_proceedings",
	"document_contents", "artifacts", "review", "validation", "risk_mapping", "analysis",
	"draft", "demand_versions", "lifecycle_events",
]
SORTS = {
	"newest": "creation desc",
	"oldest": "creation asc",
	"modified": "modified desc",
}


def _resolve_business(key):
	key = str(key or "").strip()
	if not key:
		frappe.throw(_("client_key is required"))
	if frappe.db.exists("Business", key):
		return key
	alt = frappe.db.get_value("Business", {"short_name": key.upper()}, "name")
	if alt:
		return str(alt)
	frappe.throw(_("Client {0} not found").format(key), frappe.DoesNotExistError)


def _parse(value):
	if isinstance(value, str) and value.strip()[:1] in ("{", "["):
		try:
			return json.loads(value)
		except ValueError:
			return value
	return value


def _shape(row, files):
	meta = _parse(row.get("portal_metadata")) or {}
	if not isinstance(meta, dict):
		meta = {}
	out = {
		"id": row["name"],
		"businessId": row.get("business_id"),
		"gstin": row.get("gstin") or meta.get("gstin"),
		"portalRefId": row.get("portal_ref_id") or meta.get("refId"),
		"arn": meta.get("arn"),
		"noticeType": meta.get("noticeType"),
		"dateOfIssue": meta.get("dateOfIssueIso") or meta.get("dateOfIssue"),
		"dueDateOfReply": meta.get("dueDateOfReplyIso") or meta.get("dueDateOfReply"),
		"proceedingStage": row.get("proceeding_stage"),
		"proceedingId": row.get("proceeding_id"),
		"originatingScnReference": row.get("originating_scn_reference"),
		"status": {0: "Draft", 1: "Submitted", 2: "Cancelled"}.get(row.get("docstatus"), "Draft"),
		"importedOn": str(row["creation"]) if row.get("creation") else None,
		"modified": str(row["modified"]) if row.get("modified") else None,
		"files": files.get(row["name"], []),
	}
	return out


@frappe.whitelist(methods=["GET"])
def get_client_notices(
	client_key=None, gstin=None, proceeding_stage=None, from_date=None, to_date=None,
	search=None, full=0, sort="newest", limit=50, start=0,
):
	"""
	All notices for a client (Business).

	Query params:
	  client_key        required. Business ID (an old short code like "GT" also works)
	  gstin             only this GSTIN of the business
	  proceeding_stage  e.g. "Show Cause"
	  from_date/to_date import date range, YYYY-MM-DD
	  search            matches notice id, portal ref id, proceeding id or SCN reference
	  full              1 = also return every JSON field (analysis, draft, demand, ...)
	  sort              newest (default) | oldest | modified
	  limit / start     paging (limit 0 = all)

	Returns {"total": N, "notices": [...]}
	"""
	if not frappe.has_permission("Notice", "read"):
		frappe.throw(_("Not permitted to read notices"), frappe.PermissionError)

	business_id = _resolve_business(client_key)
	scope.check_business(business_id)  # only the caller's own businesses (litwatch/scope.py)
	meta = frappe.get_meta("Notice")
	has = lambda f: bool(meta.get_field(f)) or f in ("name", "docstatus", "creation", "modified")

	business_gstins = frappe.get_all("GSTIN", filters={"business_id": business_id}, pluck="name") \
		if frappe.db.table_exists("GSTIN") else []

	if gstin:
		gstin = str(gstin).strip().upper()
		if gstin not in business_gstins:
			frappe.throw(_("GSTIN {0} does not belong to client {1}").format(gstin, business_id))

	# business_id = X  OR  gstin IN (business GSTINs)
	or_filters = [["business_id", "=", business_id]]
	if business_gstins and has("gstin"):
		or_filters.append(["gstin", "in", business_gstins])

	filters = []
	if gstin and has("gstin"):
		filters.append(["gstin", "=", gstin])
	if proceeding_stage and has("proceeding_stage"):
		filters.append(["proceeding_stage", "=", proceeding_stage])
	if from_date:
		filters.append(["creation", ">=", f"{getdate(from_date)} 00:00:00"])
	if to_date:
		filters.append(["creation", "<=", f"{getdate(to_date)} 23:59:59"])
	if search:
		like = f"%{str(search).strip()}%"
		search_or = [["name", "like", like]] + [
			[f, "like", like] for f in ("portal_ref_id", "proceeding_id", "originating_scn_reference") if has(f)
		]
		ids = frappe.get_all("Notice", or_filters=search_or, pluck="name", limit_page_length=0)
		filters.append(["name", "in", ids or ["__none__"]])

	fields = [f for f in SUMMARY_FIELDS if has(f)]
	if cint(full):
		fields += [f for f in JSON_FIELDS if has(f) and f not in fields]

	ids_all = frappe.get_all("Notice", filters=filters, or_filters=or_filters, pluck="name", limit_page_length=0)
	total = len(ids_all)

	rows = frappe.get_all(
		"Notice",
		filters=filters + [["name", "in", ids_all or ["__none__"]]],
		fields=fields,
		order_by=SORTS.get(sort, SORTS["newest"]),
		start=cint(start),
		limit_page_length=cint(limit),
	)

	files = {}
	if rows:
		for f in frappe.get_all(
			"Notice Document File",
			filters={"parenttype": "Notice", "parent": ["in", [r.name for r in rows]]},
			fields=["parent", "file_name"],
			order_by="idx asc",
		):
			files.setdefault(f.parent, []).append(f.file_name)

	notices = []
	for r in rows:
		item = _shape(r, files)
		if cint(full):
			item["data"] = {f: _parse(r.get(f)) for f in JSON_FIELDS if f in r}
		notices.append(item)

	return {"total": total, "notices": notices}
