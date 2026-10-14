# apps/litwatch/litwatch/notification_jobs.py
"""
Scheduled notifications (hooks.py scheduler_events, every morning).

- Reply deadlines: "Reply due in N days" on each of the user's reminder days
  (Notification Setting > Deadline reminders, else Sync Settings > Default reply
  reminders, 7,3,1), "Reply due today", and "Reply overdue" on day 1 and then weekly.
- Short reply window (Notification Setting > Short window alerts): a notice added in
  the last day whose reply is due within 7 days.
- Consent expiring: active GSTINs whose consent ends in Sync Settings > Warn before
  consent expiry days (30), 7 or 1 days; lapsed ones are marked expired.
- Morning digest (Notification Setting > Morning digest): one summary per user.
- Consultant copies (Notification Setting > Consultant copies): deadline reminders are
  also sent to the business's default consultant (when that consultant is a User).

Each notification is sent once per user, record and day.
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate

from litwatch import settings
from litwatch.notifications import business_name, business_users, gstin_recipients, notify

SHORT_WINDOW_DAYS = 7


def run_daily():
	frappe.flags.mute_litwatch_notifications = False
	for job in (expire_and_warn_consent, deadline_reminders, morning_digest):
		try:
			job()
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"LitWatch {job.__name__} failed", message=frappe.get_traceback())


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _sent_today(user, title, reference_doctype, reference_name):
	return frappe.db.exists(
		"App Notification",
		{
			"user": user,
			"title": title[:140],
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"creation": [">=", nowdate()],
		},
	)


def _notify_once(users, title, detail, kind, client, reference_doctype, reference_name):
	fresh = [u for u in users if not _sent_today(u, title, reference_doctype, reference_name)]
	if fresh:
		notify(fresh, title, detail, kind=kind, client=client,
		       reference_doctype=reference_doctype, reference_name=reference_name)


def _user_settings(users):
	rows = frappe.get_all(
		"Notification Setting",
		filters={"user": ["in", list(users) or [""]]},
		fields=["user", "deadline_reminders", "morning_digest", "short_window_alerts", "consultant_copies"],
	)
	return {r.user: r for r in rows}


def _consultant_user(business_id):
	consultant = frappe.db.get_value("Business", business_id, "default_consultant")
	email = frappe.db.get_value("Consultant", consultant, "email") if consultant else None
	return email if email and frappe.db.exists("User", email) else None


def open_notices(today=None):
	"""Open (not resolved, not cancelled) notices with their reply due date, via the Command Hub parser."""
	from litwatch.api import dashboard

	today = today or getdate(nowdate())
	meta = frappe.get_meta("Notice")
	json_fields = [f for f in dashboard.JSON_FIELDS if meta.get_field(f)]
	rows = frappe.get_all(
		"Notice",
		filters=[["docstatus", "!=", 2]],
		fields=["name", "business_id", "gstin", "proceeding_stage", "docstatus", "creation", "modified"] + json_fields,
		limit_page_length=0,
	)
	gstin_business = {g.name: str(g.business_id) for g in frappe.get_all("GSTIN", fields=["name", "business_id"]) if g.business_id}
	out = []
	for r in rows:
		n = dashboard._prepare(dict(r), {})
		if n["resolvedOn"]:
			continue
		business_id = str(n["businessId"]) if n["businessId"] else gstin_business.get(n["gstin"] or "")
		out.append({**n, "businessId": business_id, "created": getdate(r.creation)})
	return out


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------
def deadline_reminders(today=None):
	today = getdate(today or nowdate())
	notices = [n for n in open_notices(today) if n["due"] and n["businessId"]]
	users_by_business = {b: business_users(b) for b in {n["businessId"] for n in notices}}
	prefs = _user_settings({u for us in users_by_business.values() for u in us})

	for n in notices:
		days_left = (getdate(n["due"]) - today).days
		bname = business_name(n["businessId"])
		for user in users_by_business.get(n["businessId"]) or []:
			pref = prefs.get(user) or frappe._dict()
			reminder_days = settings.reminder_days(pref.get("deadline_reminders"))
			title = None
			if days_left in reminder_days:
				title = _("Reply due in {0} day(s): {1}").format(days_left, n["id"])
			elif days_left == 0:
				title = _("Reply due today: {0}").format(n["id"])
			elif days_left < 0 and (-days_left == 1 or -days_left % 7 == 0):
				title = _("Reply overdue by {0} day(s): {1}").format(-days_left, n["id"])
			elif pref.get("short_window_alerts") and 0 < days_left <= SHORT_WINDOW_DAYS and n["created"] >= add_days(today, -1):
				title = _("Short reply window: {0}").format(n["id"])
			if not title:
				continue
			detail = _("Notice {0} ({1}{2}): reply due {3}.").format(
				n["id"], bname, f", {n['noticeType']}" if n.get("noticeType") else "", n["due"]
			)
			recipients = [user]
			if pref.get("consultant_copies"):
				consultant = _consultant_user(n["businessId"])
				if consultant:
					recipients.append(consultant)
			_notify_once(recipients, title, detail, "deadline", n["businessId"], "Notice", n["id"])


def expire_and_warn_consent(today=None):
	today = getdate(today or nowdate())
	warn = {int(settings.get("consent_expiry_days") or 30), 7, 1}
	for g in frappe.get_all("GSTIN", filters={"consent_status": "active", "valid_until": ["is", "set"]},
	                        fields=["name", "business_id", "valid_until"]):
		days_left = (getdate(g.valid_until) - today).days
		business_id = str(g.business_id) if g.business_id else None
		if days_left < 0:
			doc = frappe.get_doc("GSTIN", g.name)
			doc.consent_status = "expired"
			doc.flags.ignore_auto_status = True
			doc.save(ignore_permissions=True)  # notifies "consent expired" (litwatch/gstin_status.py)
		elif days_left in warn:
			_notify_once(
				gstin_recipients(g.name, business_id),
				_("Consent expiring: {0}").format(g.name),
				_("The GST portal consent of {0} ({1}) ends on {2}. Reconnect it with a new OTP before then.").format(
					g.name, business_name(business_id), g.valid_until
				),
				"deadline", business_id, "GSTIN", g.name,
			)


def morning_digest(today=None):
	today = getdate(today or nowdate())
	users = [r.user for r in frappe.get_all("Notification Setting", filters={"morning_digest": 1}, fields=["user"])]
	if not users:
		return
	notices = [n for n in open_notices(today) if n["businessId"]]
	from litwatch import scope

	for user in users:
		mine = set(scope._businesses_of(user)) if frappe.db.exists("GST User", user) else None
		rows = [n for n in notices if mine is None or n["businessId"] in mine]
		due = [n for n in rows if n["due"] and 0 <= (getdate(n["due"]) - today).days <= 7]
		overdue = [n for n in rows if n["due"] and getdate(n["due"]) < today]
		unread = frappe.db.count("App Notification", {"user": user, "unread": 1})
		_notify_once(
			[user],
			_("Morning digest {0}").format(today.strftime("%d %b")),
			_("{0} open notice(s), {1} due in the next 7 days, {2} overdue, {3} unread notification(s).").format(
				len(rows), len(due), len(overdue), unread
			),
			"deadline", None, "User", user,
		)
