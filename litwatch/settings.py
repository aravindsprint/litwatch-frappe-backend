# apps/litwatch/litwatch/settings.py
"""Reads LitWatch settings (the Sync Settings single) with defaults for values never saved."""

import frappe
from frappe.utils import cint, get_url

DEFAULTS = {
	"require_business_approval": 0,
	"require_gstin_approval": 1,
	"send_account_email": 1,
	"app_url": "",
	"registration_path": "/register",
	"invite_valid_days": 14,
	"default_reminder_days": "7,3,1",
	"consent_expiry_days": 30,
}


def raw(fieldname):
	"""The stored value, or None when it was never saved. (frappe.db.get_single_value turns a missing
	Check into 0, which would hide the default.)"""
	row = frappe.db.sql(
		"SELECT value FROM `tabSingles` WHERE doctype = 'Sync Settings' AND field = %s", fieldname
	)
	return row[0][0] if row else None


def get(fieldname):
	value = raw(fieldname)
	return DEFAULTS.get(fieldname) if value in (None, "") else value


def flag(fieldname):
	return bool(cint(get(fieldname)))


def app_url():
	return (str(get("app_url") or "").strip() or get_url()).rstrip("/")


def reminder_days(text=None):
	"""'7,3,1' -> [7, 3, 1] (positive ints, unique, descending)."""
	text = text if text not in (None, "") else get("default_reminder_days")
	days = set()
	for part in str(text or "").replace(";", ",").split(","):
		part = part.strip().lower().replace("days", "").replace("day", "").strip()
		if part.isdigit() and 0 < int(part) <= 365:
			days.add(int(part))
	return sorted(days, reverse=True)
