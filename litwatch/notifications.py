# apps/litwatch/litwatch/notifications.py
"""
App Notifications for the LitWatch UI (header bell, pop-up, Notifications page).

notify() inserts one App Notification per recipient. The UI reads the
logged-in user's records (field "user"), so a recipient must be an existing
User; unknown emails are skipped. A failure to notify never breaks the action
that triggered it: it is written to the Error Log instead.
"""

import frappe
from frappe.utils import now_datetime

KINDS = ("deadline", "sync", "ai", "system")


def notify(users, title, detail=None, kind="system", client=None, reference_doctype=None, reference_name=None):
	"""Create an App Notification for each user (duplicates removed). Returns the number created."""
	recipients = []
	for u in users or []:
		u = str(u or "").strip()
		if u and u != "Guest" and u not in recipients:
			recipients.append(u)
	if not recipients:
		return 0

	kind = kind if kind in KINDS else "system"
	client = str(client) if client and frappe.db.exists("Business", str(client)) else None
	created = 0
	try:
		existing = set(frappe.get_all("User", filters={"name": ["in", recipients], "enabled": 1}, pluck="name"))
		for user in recipients:
			if user not in existing:
				continue
			frappe.get_doc(
				{
					"doctype": "App Notification",
					"user": user,
					"title": (title or "")[:140],
					"detail": detail,
					"notification_time": now_datetime(),
					"kind": kind,
					"unread": 1,
					"client": client,
					"reference_doctype": reference_doctype if reference_name else None,
					"reference_name": reference_name,
				}
			).insert(ignore_permissions=True)
			created += 1
	except Exception:
		frappe.log_error(title="LitWatch notify failed", message=frappe.get_traceback())
	return created


# ---------------------------------------------------------------------------
# Recipients
# ---------------------------------------------------------------------------
def business_users(business_id):
	"""GST Users (emails) linked to the Business in their Business ID table."""
	if not business_id:
		return []
	return sorted(
		set(
			frappe.get_all(
				"GST User Business",
				filters={"parenttype": "GST User", "business": str(business_id)},
				pluck="parent",
			)
		)
	)


def gstin_users(gstin):
	"""GST Users (emails) in the GSTIN's own Users table."""
	if not gstin:
		return []
	return [
		u
		for u in frappe.get_all(
			"GSTIN User",
			filters={"parenttype": "GSTIN", "parentfield": "users", "parent": gstin},
			pluck="user",
			order_by="idx asc",
		)
		if u
	]


def gstin_recipients(gstin, business_id=None):
	"""The Business's GST Users plus the GSTIN's own users, without duplicates."""
	out = []
	for u in business_users(business_id) + gstin_users(gstin):
		if u not in out:
			out.append(u)
	return out


def approvers():
	"""Firm staff who approve GSTIN connections: enabled System Manager users, plus Administrator."""
	users = frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "role": "System Manager"},
		pluck="parent",
	)
	users = set(users) | {"Administrator"}
	enabled = set(frappe.get_all("User", filters={"name": ["in", list(users)], "enabled": 1}, pluck="name"))
	return sorted(u for u in users if u in enabled and u != "Guest")
