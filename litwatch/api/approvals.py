# apps/litwatch/litwatch/api/approvals.py
"""
Approvals done by the LitWatch team in Frappe.

- Business approval (Sync Settings > Require business approval): a business created
  by a GST User waits as Pending until approved here.
- GSTIN connection approval (Require GSTIN approval): approve_gstin_connection /
  reject_gstin_connection in litwatch.api.gstin.

Only System Manager, and never on behalf of a GST User (frontend shared key + gstUser).
"""

import frappe
from frappe import _

from litwatch import scope


def check_approver():
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only System Manager can approve or reject"), frappe.PermissionError)
	if scope.get_scope() is not None:
		# The frontend's shared key acting for a GST User must not approve its own items.
		frappe.throw(_("Approvals are done by firm staff, not by a GST User"), frappe.PermissionError)


def _business(business_id):
	business_id = str(business_id or frappe.form_dict.get("businessId") or frappe.form_dict.get("business_id") or "").strip()
	if not business_id:
		frappe.throw(_("businessId is required"))
	if not frappe.db.exists("Business", business_id):
		frappe.throw(_("Business {0} not found").format(business_id), frappe.DoesNotExistError)
	return frappe.get_doc("Business", business_id)


def _result(doc):
	return {"businessId": str(doc.name), "approval": doc.approval_status, "reason": doc.approval_note or None}


@frappe.whitelist(methods=["POST"])
def approve_business(businessId=None):
	"""Pending (or Rejected) -> Approved. Its GSTINs can connect; its users are notified."""
	check_approver()
	doc = _business(businessId)
	if doc.approval_status == "Approved":
		frappe.throw(_("Business {0} is already approved").format(doc.name))
	doc.approval_status = "Approved"
	doc.approval_note = None
	doc.flags.keep_approval_status = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return _result(doc)


@frappe.whitelist(methods=["POST"])
def reject_business(businessId=None, reason=None):
	"""Pending -> Rejected with a reason. Its users are notified."""
	check_approver()
	doc = _business(businessId)
	reason = str(reason or frappe.form_dict.get("reason") or "").strip()
	if not reason:
		frappe.throw(_("reason is required"))
	if doc.approval_status == "Rejected":
		frappe.throw(_("Business {0} is already rejected").format(doc.name))
	doc.approval_status = "Rejected"
	doc.approval_note = reason[:1000]
	doc.flags.keep_approval_status = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return _result(doc)


@frappe.whitelist(methods=["GET"])
def get_pending_approvals():
	"""Everything waiting for the team: pending businesses and GSTINs awaiting verification."""
	check_approver()
	businesses = frappe.get_all(
		"Business",
		filters={"approval_status": "Pending"},
		fields=["name", "business_name", "owner", "creation"],
		order_by="creation asc",
		limit_page_length=0,
	)
	gstins = frappe.get_all(
		"GSTIN",
		filters={"consent_status": "verifying"},
		fields=["name", "business_id", "portal_user_id", "last_checked"],
		order_by="last_checked asc",
		limit_page_length=0,
	)
	names = {str(k): v for k, v in frappe.get_all("Business", fields=["name", "business_name"], as_list=True)}
	return {
		"businesses": [
			{"businessId": str(b.name), "name": b.business_name, "createdBy": b.owner, "createdOn": str(b.creation)}
			for b in businesses
		],
		"gstins": [
			{
				"gstin": g.name,
				"businessId": str(g.business_id) if g.business_id else None,
				"businessName": names.get(str(g.business_id)) if g.business_id else None,
				"portalUserId": g.portal_user_id,
				"verifiedAt": str(g.last_checked) if g.last_checked else None,
			}
			for g in gstins
		],
	}
