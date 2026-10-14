# apps/litwatch/litwatch/api/registration.py
"""
Self-registration through a token link (Registration Invite). Called by the
LitWatch app's registration page; no login needed (allow_guest), rate limited.

GET  litwatch.api.registration.get_registration_invite?token=...
POST litwatch.api.registration.register
     {token, firstName, lastName?, whatsappNumber, email, practiceType, firmName?, clientCount}

register() saves the details as a LitWatch Lead (source "Registration link",
status Onboard), creates the User and GST User, marks the invite used, and the
account email + welcome notification go out (litwatch/onboarding.py).
"""

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, get_datetime, now_datetime

PRACTICE_TYPES = ("Individual CA", "Firm")


def _invite(token):
	token = str(token or "").strip()
	name = frappe.db.get_value("Registration Invite", {"token": token}, "name") if token else None
	if not name:
		frappe.throw(_("This registration link is not valid."), frappe.PermissionError)
	doc = frappe.get_doc("Registration Invite", name)
	if doc.status == "Active" and doc.expires_on and get_datetime(doc.expires_on) < now_datetime():
		doc.db_set("status", "Expired")
		frappe.db.commit()
	if doc.status != "Active":
		msg = {
			"Used": _("This registration link was already used. Sign in instead."),
			"Expired": _("This registration link has expired. Ask the LitWatch team for a new one."),
		}.get(doc.status, _("This registration link is no longer valid."))
		frappe.throw(msg, frappe.PermissionError)
	return doc


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=60, seconds=3600)
def get_registration_invite(token=None):
	"""Check a token before showing the form; returns the details to pre-fill."""
	doc = _invite(token or frappe.form_dict.get("token"))
	first, _sep, last = (doc.invitee_name or "").partition(" ")
	return {
		"valid": True,
		"email": doc.email,
		"firstName": first or None,
		"lastName": last or None,
		"whatsappNumber": doc.whatsapp_number,
		"expiresOn": str(doc.expires_on) if doc.expires_on else None,
		"practiceTypes": list(PRACTICE_TYPES),
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=3600)
def register(token=None, firstName=None, lastName=None, whatsappNumber=None, email=None,
             practiceType=None, firmName=None, clientCount=None):
	from litwatch.onboarding import create_account

	f = frappe.form_dict
	token = token or f.get("token")
	first = str(firstName or f.get("firstName") or "").strip()
	last = str(lastName or f.get("lastName") or "").strip() or None
	phone = str(whatsappNumber or f.get("whatsappNumber") or "").strip()
	email = str(email or f.get("email") or "").strip().lower()
	practice = str(practiceType or f.get("practiceType") or "").strip()
	firm = str(firmName or f.get("firmName") or "").strip() or None
	clients = clientCount if clientCount is not None else f.get("clientCount")

	invite = _invite(token)
	missing = [label for label, value in (("firstName", first), ("whatsappNumber", phone), ("email", email),
	                                      ("practiceType", practice), ("clientCount", clients)) if value in (None, "")]
	if missing:
		frappe.throw(_("Required: {0}").format(", ".join(missing)))
	frappe.utils.validate_email_address(email, throw=True)
	if practice not in PRACTICE_TYPES:
		frappe.throw(_("practiceType must be one of: {0}").format(", ".join(PRACTICE_TYPES)))
	if practice == "Firm" and not firm:
		frappe.throw(_("firmName is required for a Firm"))
	if cint(clients) < 0:
		frappe.throw(_("clientCount can't be negative"))
	if invite.email and invite.email.lower() != email:
		frappe.throw(_("Use the email address this invitation was sent to: {0}").format(invite.email))
	if frappe.db.exists("User", email):
		frappe.throw(_("An account with this email already exists. Sign in instead."), frappe.DuplicateEntryError)

	lead = frappe.get_doc("LitWatch Lead", invite.lead) if invite.lead and frappe.db.exists("LitWatch Lead", invite.lead) else frappe.new_doc("LitWatch Lead")
	if lead.is_new():
		lead.source = "Registration link"
		lead.collected_on = frappe.utils.nowdate()
	lead.update({
		"first_name": first, "last_name": last, "email": email, "whatsapp_number": phone,
		"practice_type": practice, "firm_name": firm if practice == "Firm" else None,
		"client_count": cint(clients), "invite": invite.name,
	})
	lead.save(ignore_permissions=True) if not lead.is_new() else lead.insert(ignore_permissions=True)

	create_account(email, first, last, phone)

	lead.db_set({"user": email, "status": "Onboard", "converted_on": now_datetime()})
	invite.db_set({"status": "Used", "registered_user": email, "registered_on": now_datetime(), "lead": lead.name})
	frappe.db.commit()
	return {
		"registered": True,
		"email": email,
		"message": _("Your account is ready. Check your email to set your password, then sign in."),
	}
