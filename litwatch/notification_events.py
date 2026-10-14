# apps/litwatch/litwatch/notification_events.py
"""
doc_events (hooks.py) that turn changes into App Notifications (litwatch/notifications.py).

Recipients are the GST Users linked to the record's Business (and a GSTIN's own users);
the person who made the change is left out. GSTIN status changes are handled in
litwatch/gstin_status.py, deadlines and consent expiry in litwatch/notification_jobs.py.
"""

import json

import frappe
from frappe import _
from frappe.utils import fmt_money

from litwatch.notifications import (
	approvers,
	business_name,
	business_users,
	firm_profile_users,
	gstin_recipients,
	notice_business,
	notify,
)


def _before(doc):
	return doc.get_doc_before_save()


def _norm_json(value):
	if value in (None, "", "{}", "[]", "null"):
		return None
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except ValueError:
			return value.strip() or None
	if value in ({}, []):
		return None
	return json.dumps(value, sort_keys=True, default=str)


def _changed(doc, field):
	before = _before(doc)
	if not before:
		return False
	return _norm_json(before.get(field)) != _norm_json(doc.get(field))


def _ref(doc, business_id):
	return {"client": business_id, "reference_doctype": doc.doctype, "reference_name": doc.name}


# ---------------------------------------------------------------------------
# Notices
# ---------------------------------------------------------------------------
def notice_after_insert(doc, method=None):
	if doc.flags.from_sync:
		return  # a sync sends one summary notification instead (litwatch.api.gstin)
	business_id = notice_business(doc)
	notify(
		business_users(business_id),
		_("New notice {0}").format(doc.name),
		_("A notice was added for {0}{1}.").format(
			business_name(business_id), f" (GSTIN {doc.gstin})" if doc.get("gstin") else ""
		),
		kind="system",
		**_ref(doc, business_id),
	)


def notice_on_update(doc, method=None):
	before = _before(doc)
	if not before:
		return
	business_id = notice_business(doc)
	users = business_users(business_id)
	if _norm_json(doc.get("analysis")) and not _norm_json(before.get("analysis")):
		notify(
			users,
			_("AI analysis ready: {0}").format(doc.name),
			_("The AI analysis of notice {0} ({1}) is finished.").format(doc.name, business_name(business_id)),
			kind="ai",
			**_ref(doc, business_id),
		)
	if _norm_json(before.get("review")) and _changed(doc, "review"):
		notify(
			users,
			_("Review corrections saved: {0}").format(doc.name),
			_("Corrections to the extracted details of notice {0} were saved.").format(doc.name),
			kind="ai",
			**_ref(doc, business_id),
		)


def review_item_on_update(doc, method=None):
	before = _before(doc)
	if doc.status != "Confirmed" or (before and before.status == "Confirmed"):
		return
	business_id = str(doc.client) if doc.get("client") else None
	notify(
		business_users(business_id),
		_("Review confirmed: {0}").format(doc.get("notice") or doc.name),
		_("{0} confirmed the review item {1}{2}.").format(
			doc.get("confirmed_by") or _("The team"), doc.name,
			f" for notice {doc.notice}" if doc.get("notice") else "",
		),
		kind="ai",
		**_ref(doc, business_id),
	)


# ---------------------------------------------------------------------------
# Payments and documents
# ---------------------------------------------------------------------------
def payment_after_insert(doc, method=None):
	business_id = str(doc.client) if doc.get("client") else None
	amount = fmt_money(doc.get("amount_paid") or 0, currency="INR")
	notify(
		business_users(business_id),
		_("Payment recorded: {0}").format(amount),
		_("{0} ({1}) paid for {2}{3}.").format(
			doc.get("payment_type") or _("Payment"), amount, business_name(business_id),
			f", notice {doc.notice}" if doc.get("notice") else "",
		),
		kind="payment",
		**_ref(doc, business_id),
	)


def client_document_after_insert(doc, method=None):
	business_id = str(doc.client) if doc.get("client") else None
	notify(
		business_users(business_id),
		_("Document uploaded: {0}").format(doc.get("file_name") or doc.name),
		_("{0} was uploaded for {1}{2}.").format(
			doc.get("document_type") or _("A document"), business_name(business_id),
			f" ({doc.matter})" if doc.get("matter") else "",
		),
		kind="document",
		**_ref(doc, business_id),
	)


def client_document_on_update(doc, method=None):
	before = _before(doc)
	if not before:
		return
	if all((before.get(f) or None) == (doc.get(f) or None) for f in ("document_type", "role", "matter")):
		return
	business_id = str(doc.client) if doc.get("client") else None
	notify(
		business_users(business_id),
		_("Document retagged: {0}").format(doc.get("file_name") or doc.name),
		_("Now tagged {0}{1}{2}.").format(
			doc.get("document_type") or "-",
			f" / {doc.role}" if doc.get("role") else "",
			f" / {doc.matter}" if doc.get("matter") else "",
		),
		kind="document",
		**_ref(doc, business_id),
	)


# ---------------------------------------------------------------------------
# Businesses
# ---------------------------------------------------------------------------
def business_after_insert(doc, method=None):
	if doc.approval_status == "Pending":
		notify(
			approvers(),
			_("Business waiting for approval: {0}").format(doc.business_name),
			_("{0} (Business {1}) was created in LitWatch by {2}. Approve or reject it in Frappe.").format(
				doc.business_name, doc.name, doc.owner
			),
			kind="approval",
			**_ref(doc, str(doc.name)),
		)


def business_on_update(doc, method=None):
	before = _before(doc)
	if not before:
		return
	business_id = str(doc.name)
	users = business_users(business_id)
	if before.approval_status != doc.approval_status and doc.approval_status in ("Approved", "Rejected"):
		if doc.approval_status == "Approved":
			title, detail = _("Business approved: {0}").format(doc.business_name), _(
				"{0} is approved. You can now connect its GSTINs."
			).format(doc.business_name)
		else:
			title, detail = _("Business rejected: {0}").format(doc.business_name), _(
				"{0} was not approved. Reason: {1}"
			).format(doc.business_name, doc.approval_note or _("No reason given"))
		notify(users, title, detail, kind="approval", **_ref(doc, business_id))
	if (before.onboarding_stage or None) != (doc.onboarding_stage or None) and doc.onboarding_stage:
		notify(
			users,
			_("{0}: {1}").format(doc.business_name, doc.onboarding_stage),
			_("Onboarding stage of {0} changed from {1} to {2}.").format(
				doc.business_name, before.onboarding_stage or "-", doc.onboarding_stage
			),
			kind="business",
			**_ref(doc, business_id),
		)
	if not doc.flags.from_gstin_sync:
		# GSTINs added from the Business form (the GSTIN side notifies when it is the one that changed)
		old = {r.gstin for r in before.get("gstins") or []}
		for gstin in sorted({r.gstin for r in doc.get("gstins") or []} - old):
			_gstin_added(gstin, business_id)


# ---------------------------------------------------------------------------
# GSTINs (status changes: litwatch/gstin_status.py)
# ---------------------------------------------------------------------------
def _gstin_added(gstin, business_id):
	notify(
		gstin_recipients(gstin, business_id),
		_("GSTIN {0} added").format(gstin),
		_("{0} was added to {1}.").format(gstin, business_name(business_id)),
		kind="system",
		client=business_id,
		reference_doctype="GSTIN",
		reference_name=gstin,
	)


def gstin_on_update(doc, method=None):
	if doc.flags.from_business_sync:
		return
	before = _before(doc)
	new = str(doc.business_id) if doc.business_id else None
	old = str(before.business_id) if before and before.business_id else None
	if new and new != old:
		_gstin_added(doc.name, new)


# ---------------------------------------------------------------------------
# GST Users and the practice profile
# ---------------------------------------------------------------------------
def gst_user_after_insert(doc, method=None):
	names = [business_name(r.business) for r in doc.get("businesses") or [] if r.business]
	notify(
		[doc.name],
		_("Welcome to LitWatch"),
		_("Your LitWatch account is ready.{0}").format(
			_(" Businesses: {0}.").format(", ".join(names)) if names else ""
		),
		kind="account",
		reference_doctype="GST User",
		reference_name=doc.name,
		include_actor=True,  # even when the user registered themselves
	)
	from litwatch.onboarding import send_account_email

	send_account_email(doc.name)


def gst_user_on_update(doc, method=None):
	before = _before(doc)
	if not before:
		return
	old = {str(r.business) for r in before.get("businesses") or [] if r.business}
	added = [str(r.business) for r in doc.get("businesses") or [] if r.business and str(r.business) not in old]
	for business_id in added:
		notify(
			[doc.name],
			_("Business added: {0}").format(business_name(business_id)),
			_("{0} was added to your LitWatch account.").format(business_name(business_id)),
			kind="business",
			client=business_id,
			reference_doctype="Business",
			reference_name=business_id,
		)
	if (before.user_name or None) != (doc.user_name or None):
		notify(
			[doc.name],
			_("Account details updated"),
			_("Your name in LitWatch is now {0}.").format(doc.user_name or "-"),
			kind="account",
			reference_doctype="GST User",
			reference_name=doc.name,
		)


def firm_profile_on_update(doc, method=None):
	if not _before(doc):
		return
	notify(
		firm_profile_users(doc.name),
		_("Practice profile updated"),
		_("The practice profile {0} was updated.").format(doc.name),
		kind="account",
		reference_doctype="Firm Profile",
		reference_name=doc.name,
	)


def firm_profile_after_rename(doc, method=None, old=None, new=None, merge=False):
	notify(
		firm_profile_users(new or doc.name),
		_("Practice renamed"),
		_("The practice {0} is now called {1}.").format(old or "-", new or doc.name),
		kind="account",
		reference_doctype="Firm Profile",
		reference_name=new or doc.name,
	)
