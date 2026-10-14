# apps/litwatch/litwatch/gstin_status.py
"""
GSTIN connection status (GSTIN.consent_status) and its notifications.

    inactive -> ready -> pending -> verifying -> active -> expired
                  ^                     |
                  +---- rejected -------+

- inactive : the Business has no working GSP app (Adaequare Settings).
- ready    : Adaequare Settings saved, active, and its credentials got a GSP token.
- pending  : OTP sent (connect_gstin), not entered yet.
- verifying: OTP verified, waiting for approval in Frappe.
- active   : approved (approve_gstin_connection); notices sync.
- expired  : consent or portal session lapsed.

inactive <-> ready is worked out automatically (GSTIN.validate and the
Adaequare Settings hooks). Notifications are sent from GSTIN.on_update when
the status changes, so every path that changes it notifies exactly once.
"""

import frappe
from frappe import _

from litwatch.notifications import approvers, gstin_recipients, notify

AUTO = ("inactive", "ready")


def business_configured(business_id, exclude_settings=None):
	"""True when the Business has active Adaequare Settings whose credentials were verified."""
	if not business_id:
		return False
	name = str(business_id)
	if exclude_settings and name == str(exclude_settings):
		return False
	row = frappe.db.get_value(
		"Adaequare Settings", name, ["is_active", "client_id", "credentials_verified"], as_dict=True
	)
	return bool(row and row.is_active and row.client_id and row.credentials_verified)


def auto_status(doc):
	"""Called from GSTIN.validate: inactive/ready follow the Business's Adaequare Settings."""
	if doc.flags.ignore_auto_status:
		return
	current = doc.consent_status or "inactive"
	if current not in AUTO:
		return
	doc.consent_status = "ready" if business_configured(doc.business_id) else "inactive"


def move_business_gstins(business_id, from_status, to_status):
	"""Move every GSTIN of the Business that is in from_status. Saves each one, so notifications fire."""
	if not business_id:
		return []
	moved = []
	for name in frappe.get_all(
		"GSTIN", filters={"business_id": str(business_id), "consent_status": from_status}, pluck="name"
	):
		doc = frappe.get_doc("GSTIN", name)
		doc.consent_status = to_status
		doc.flags.ignore_auto_status = True
		doc.save(ignore_permissions=True)
		moved.append(name)
	return moved


# ---------------------------------------------------------------------------
# Notifications (GSTIN.on_update)
# ---------------------------------------------------------------------------
def notify_status_change(doc):
	if doc.flags.skip_notify or not doc.has_value_changed("consent_status"):
		return
	before = doc.get_doc_before_save()
	old = (before.consent_status if before else None) or None
	new = doc.consent_status
	business_id = str(doc.business_id) if doc.business_id else None
	business_name = (
		frappe.db.get_value("Business", business_id, "business_name") if business_id else None
	) or business_id or "-"
	ref = {"client": business_id, "reference_doctype": "GSTIN", "reference_name": doc.name}

	if new == "ready" and old == "verifying":
		reason = doc.rejection_reason or _("No reason given")
		notify(
			gstin_recipients(doc.name, business_id),
			_("{0} connection rejected").format(doc.name),
			_("The connection of {0} ({1}) was rejected. Reason: {2}. Connect it again with a new GST portal OTP.").format(
				doc.name, business_name, reason
			),
			**ref,
		)
	elif new == "ready":
		notify(
			gstin_recipients(doc.name, business_id),
			_("GSTIN ready to connect"),
			_("{0} ({1}) is set up. Connect it with the GST portal OTP.").format(doc.name, business_name),
			**ref,
		)
	elif new == "verifying":
		notify(
			approvers(),
			_("{0} is waiting for verification").format(doc.name),
			_("{0} ({1}) verified the GST portal OTP. Approve or reject the connection in Frappe (GSTIN {0}).").format(
				doc.name, business_name
			),
			**ref,
		)
	elif new == "active" and old == "verifying":
		notify(
			gstin_recipients(doc.name, business_id),
			_("{0} connected").format(doc.name),
			_("{0} ({1}) is connected to the GST portal. Notices will sync until {2}.").format(
				doc.name, business_name, doc.valid_until or "-"
			),
			**ref,
		)
