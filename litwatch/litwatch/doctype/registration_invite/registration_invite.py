# Copyright (c) 2026, Shahina and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, escape_html, get_datetime, now_datetime

from litwatch import settings


class RegistrationInvite(Document):
	"""Scenario 3: a one-time token link to the LitWatch registration form."""

	def before_insert(self):
		self.token = frappe.generate_hash(length=32)
		self.status = "Active"
		if not self.expires_on:
			self.expires_on = add_days(now_datetime(), int(settings.get("invite_valid_days") or 14))

	def validate(self):
		if self.email:
			self.email = self.email.strip().lower()
			frappe.utils.validate_email_address(self.email, throw=True)
		if not (self.email or self.whatsapp_number):
			frappe.throw(_("Add an Email ID or a WhatsApp number"))
		self.registration_link = registration_link(self.token)

	@property
	def is_usable(self):
		return self.status == "Active" and not (self.expires_on and get_datetime(self.expires_on) < now_datetime())


def registration_link(token):
	path = "/" + str(settings.get("registration_path") or "/register").strip().lstrip("/")
	return f"{settings.app_url()}{path}?token={token}"


def _check_staff():
	from litwatch.api.approvals import check_approver

	check_approver()


@frappe.whitelist(methods=["POST"])
def send_invite_email(invite=None):
	_check_staff()
	doc = frappe.get_doc("Registration Invite", invite or frappe.form_dict.get("invite"))
	if not doc.is_usable:
		frappe.throw(_("Invite {0} is {1}").format(doc.name, doc.status if doc.status != "Active" else _("expired")))
	if not doc.email:
		frappe.throw(_("Invite {0} has no Email ID").format(doc.name))
	name = escape_html(doc.invitee_name or doc.email)
	frappe.sendmail(
		recipients=[doc.email],
		subject=_("Your invitation to LitWatch"),
		message=(
			f"<p>{_('Hi {0},').format(name)}</p>"
			f"<p>{_('You are invited to LitWatch. Register here:')}</p>"
			f"<p><a href=\"{doc.registration_link}\">{doc.registration_link}</a></p>"
			f"<p>{_('The link works once and expires on {0}.').format(frappe.utils.format_datetime(doc.expires_on))}</p>"
			f"<p>{_('— The LitWatch team')}</p>"
		),
		reference_doctype=doc.doctype,
		reference_name=doc.name,
	)
	_mark_sent(doc, "Email")
	return {"sent": True, "to": doc.email}


@frappe.whitelist(methods=["POST"])
def mark_sent_on_whatsapp(invite=None):
	"""Record that the link was sent by WhatsApp (copied by hand until WhatsApp sending is set up)."""
	_check_staff()
	doc = frappe.get_doc("Registration Invite", invite or frappe.form_dict.get("invite"))
	_mark_sent(doc, "WhatsApp")
	return {"sentVia": doc.sent_via}


@frappe.whitelist(methods=["POST"])
def cancel_invite(invite=None):
	_check_staff()
	doc = frappe.get_doc("Registration Invite", invite or frappe.form_dict.get("invite"))
	if doc.status == "Used":
		frappe.throw(_("Invite {0} was already used").format(doc.name))
	doc.db_set("status", "Cancelled")
	return {"status": "Cancelled"}


def _mark_sent(doc, channel):
	before = doc.sent_via or ""
	via = channel if before in ("", channel) else "Email and WhatsApp"
	doc.db_set({"sent_via": via, "sent_on": now_datetime()})
