# apps/litwatch/litwatch/onboarding.py
"""
How a person gets LitWatch access.

Scenario 1, website lead: LitWatch Lead (imported from Excel with Data Import, or
  typed in) -> "Convert to User" (convert_lead) -> account email.
Scenario 2, created by the team: create the User and the GST User in Frappe ->
  account email (sent when the GST User is created).
Scenario 3, self-registration: Registration Invite (token link, sent by email or
  copied into WhatsApp) -> the person fills in the form in the LitWatch app ->
  litwatch.api.registration.register -> lead + User + GST User -> account email.

The account email ("Your LitWatch account is ready") carries a set-password link
and the LitWatch app URL (Sync Settings). It is sent once per GST User, from the
GST User's after_insert (litwatch/notification_events.py), and can be resent.
"""

import frappe
from frappe import _
from frappe.utils import escape_html, now_datetime

from litwatch import settings


def _has_password(user):
	return bool(
		frappe.db.sql(
			"SELECT 1 FROM `__Auth` WHERE doctype = 'User' AND name = %s AND fieldname = 'password' LIMIT 1", user
		)
	)


def send_account_email(email, force=False):
	"""Email "Your LitWatch account is ready" with a set-password link. Returns True when queued."""
	if not frappe.db.exists("GST User", email) or not frappe.db.exists("User", email):
		return False
	if not force and (not settings.flag("send_account_email") or frappe.db.get_value("GST User", email, "account_email_sent_on")):
		return False
	if frappe.flags.in_import or frappe.flags.in_patch or frappe.flags.in_migrate:
		return False
	try:
		user = frappe.get_doc("User", email)
		app_url = settings.app_url()
		name = escape_html(user.first_name or user.full_name or email)
		if _has_password(email):
			password_line = _("Sign in with your existing password.")
		else:
			link = user.reset_password(send_email=False)
			password_line = _('First <a href="{0}">set your password</a> (the link works once and expires).').format(link)
		message = "".join(
			[
				f"<p>{_('Hi {0},').format(name)}</p>",
				f"<p>{_('Your LitWatch account is ready.')}</p>",
				f"<p>{password_line}</p>",
				f"<p>{_('Then sign in at')} <a href=\"{app_url}\">{app_url}</a> {_('with this email address:')} <b>{escape_html(email)}</b></p>",
				f"<p>{_('— The LitWatch team')}</p>",
			]
		)
		frappe.sendmail(recipients=[email], subject=_("Your LitWatch account is ready"), message=message,
		                reference_doctype="GST User", reference_name=email)
		frappe.db.set_value("GST User", email, "account_email_sent_on", now_datetime(), update_modified=False)
		return True
	except Exception:
		frappe.log_error(title="LitWatch account email failed", message=frappe.get_traceback())
		# The account itself is fine: don't let Frappe's error message reach the caller's response.
		if getattr(frappe, "clear_last_message", None):
			frappe.clear_last_message()
		return False


def create_account(email, first_name, last_name=None, mobile=None, user_type="Individual"):
	"""User (Website User, no Frappe welcome email) + GST User. The GST User's after_insert sends the
	account email and the welcome notification. Returns the email."""
	email = str(email or "").strip().lower()
	frappe.utils.validate_email_address(email, throw=True)
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": (first_name or email.split("@")[0]).strip(),
				"last_name": (last_name or "").strip() or None,
				"mobile_no": (mobile or "").strip() or None,
				"user_type": "Website User",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		)
		user.flags.ignore_permissions = True
		user.flags.ignore_password_policy = True
		user.insert()
	if not frappe.db.exists("GST User", email):
		full = " ".join(p for p in [(first_name or "").strip(), (last_name or "").strip()] if p) or None
		frappe.get_doc({"doctype": "GST User", "user_email_id": email, "user_name": full,
		                "user_type": user_type}).insert(ignore_permissions=True)
	return email


@frappe.whitelist(methods=["POST"])
def convert_lead(lead=None):
	"""Scenario 1: LitWatch Lead -> User + GST User (status Onboard). The lead is kept."""
	from litwatch.api.approvals import check_approver

	check_approver()
	lead = lead or frappe.form_dict.get("lead")
	doc = frappe.get_doc("LitWatch Lead", lead)
	if doc.user:
		frappe.throw(_("Lead {0} is already converted to User {1}").format(doc.name, doc.user))
	if not doc.email:
		frappe.throw(_("Lead {0} has no Email ID").format(doc.name))
	# leads are CA practices / firms: they manage their clients' businesses
	email = create_account(doc.email, doc.first_name, doc.last_name, doc.whatsapp_number, user_type="Consultant")
	doc.user = email
	doc.status = "Onboard"
	doc.converted_on = now_datetime()
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	sent = bool(frappe.db.get_value("GST User", email, "account_email_sent_on"))
	if not sent and settings.flag("send_account_email"):
		frappe.msgprint(
			_("The account {0} was created, but the account email could not be sent. Check Email Account "
			  "(outgoing) and the Error Log, then use Resend account email.").format(email),
			title=_("Email not sent"),
			indicator="orange",
		)
	return {"lead": doc.name, "user": email, "accountEmailSent": sent}


@frappe.whitelist(methods=["POST"])
def resend_account_email(gstUser=None):
	"""Send the acknowledgement email again (new set-password link)."""
	from litwatch.api.approvals import check_approver

	check_approver()
	email = gstUser or frappe.form_dict.get("gst_user")
	if not send_account_email(email, force=True):
		frappe.throw(_("Could not send the account email to {0}. Check the Error Log and the outgoing Email Account.").format(email))
	frappe.db.commit()
	return {"sent": True, "to": email}
