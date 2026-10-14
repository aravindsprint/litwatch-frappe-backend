# apps/litwatch/litwatch/scope.py
"""
Per-user scoping: which Businesses (clients) the current request may see.

Who is asking
-------------
- A user who is not System Manager (a client logging in as themselves): their
  own GST User record decides.
- System Manager / Administrator (the frontend's shared API key): the GST User
  passed with the request decides, via the header ``X-LitWatch-GST-User`` or the
  ``gstUser`` parameter (query string, form or JSON body). Without one, the
  request is not scoped (firm staff see everything).

What they see
-------------
- GST User found: only the Businesses in its ``businesses`` table, and the
  GSTINs, Notices, Payments, Review Queue Items, Client Documents, Audit Log
  entries, sync logs, OTP requests and Adaequare Settings that belong to those
  Businesses.
- No GST User record, but the user is System Manager (firm staff): everything.
- Anyone else without a GST User record: "GST User ... not found" (HTTP 404),
  the same answer get_clients has always given, so the frontend's existing
  fallback keeps working.

get_scope() returns None for "everything", otherwise a list of Business IDs
(possibly empty). Background jobs and system code (no request, or
ignore_permissions) are never scoped.
"""

import frappe
from frappe import _

HEADER = "X-LitWatch-GST-User"
PARAMS = ("gstUser", "gst_user")
STAFF_ROLE = "System Manager"
_CACHE = "litwatch_scope_cache"


def _cache():
	"""Per-request cache. frappe.local is a werkzeug Local, so only get/setattr work on it."""
	cache = getattr(frappe.local, _CACHE, None)
	if cache is None:
		cache = {}
		setattr(frappe.local, _CACHE, cache)
	return cache


def reset_cache():
	setattr(frappe.local, _CACHE, {})


# ---------------------------------------------------------------------------
# Who / what
# ---------------------------------------------------------------------------
def _is_staff(user):
	return user == "Administrator" or STAFF_ROLE in frappe.get_roles(user)


def requested_gst_user():
	"""GST User named by the request (header or gstUser param), or None."""
	value = None
	try:
		if getattr(frappe.local, "request", None):
			value = frappe.get_request_header(HEADER)
	except Exception:
		value = None
	if not value:
		fd = frappe.local.form_dict if getattr(frappe.local, "form_dict", None) else {}
		for key in PARAMS:
			if fd.get(key):
				value = fd.get(key)
				break
	value = str(value or "").strip()
	return value or None


def scope_user():
	"""The GST User email the current request is scoped to, or None when unscoped."""
	user = frappe.session.user if getattr(frappe.local, "session", None) else "Guest"
	if _is_staff(user):
		return requested_gst_user()
	return user


def _businesses_of(gst_user):
	return sorted(
		{
			str(b)
			for b in frappe.get_all(
				"GST User Business",
				filters={"parenttype": "GST User", "parent": gst_user},
				pluck="business",
			)
			if b
		},
		key=lambda x: (len(x), x),
	)


def get_scope():
	"""None = everything; otherwise the list of Business IDs the request may see."""
	cache = _cache()
	user = frappe.session.user if getattr(frappe.local, "session", None) else "Guest"
	key = (user, requested_gst_user())
	if key in cache:
		return cache[key]

	gst_user = scope_user()
	if user == "Guest":
		scope = []  # not logged in: nothing
	elif not gst_user:
		scope = None
	elif frappe.db.exists("GST User", gst_user):
		scope = _businesses_of(gst_user)
	elif frappe.db.exists("User", gst_user) and _is_staff(gst_user):
		scope = None  # firm staff: everything
	else:
		frappe.throw(_("GST User {0} not found").format(gst_user), frappe.DoesNotExistError)

	cache[key] = scope
	return scope


def add_to_scope(business_id):
	"""Make a just-created Business visible for the rest of this request."""
	cache = getattr(frappe.local, _CACHE, None) or {}
	for scope in cache.values():
		if scope is not None and str(business_id) not in scope:
			scope.append(str(business_id))


def scope_gstins(scope=None):
	scope = get_scope() if scope is None else scope
	if not scope:
		return []
	return frappe.get_all("GSTIN", filters={"business_id": ["in", scope]}, pluck="name")


# ---------------------------------------------------------------------------
# Checks used by the API methods
# ---------------------------------------------------------------------------
def business_allowed(business_id):
	scope = get_scope()
	return scope is None or str(business_id or "") in scope


def check_business(business_id):
	if not business_allowed(business_id):
		frappe.throw(_("Not permitted to access client {0}").format(business_id), frappe.PermissionError)


def gstin_allowed(gstin):
	scope = get_scope()
	if scope is None:
		return True
	owner = frappe.db.get_value("GSTIN", str(gstin or "").strip().upper(), "business_id")
	return bool(owner) and str(owner) in scope


def check_gstin(gstin):
	if not gstin_allowed(gstin):
		frappe.throw(_("Not permitted to access GSTIN {0}").format(gstin), frappe.PermissionError)


def notice_allowed(business_id=None, gstin=None, scope=None, gstins=None):
	scope = get_scope() if scope is None else scope
	if scope is None:
		return True
	if business_id and str(business_id) in scope:
		return True
	if gstin:
		gstins = scope_gstins(scope) if gstins is None else gstins
		return str(gstin).upper() in gstins
	return False


def link_business_to_scope_user(business_id):
	"""Add a newly created Business to the creator's GST User, so it stays in their list."""
	gst_user = scope_user()
	if not gst_user or not frappe.db.exists("GST User", gst_user):
		return
	if str(business_id) in _businesses_of(gst_user):
		return
	doc = frappe.get_doc("GST User", gst_user)
	doc.append("businesses", {"business": str(business_id)})
	doc.save(ignore_permissions=True)
	add_to_scope(business_id)


# ---------------------------------------------------------------------------
# Document-level check (called from the controllers' has_permission)
# ---------------------------------------------------------------------------
def doc_in_scope(doc):
	if doc.flags.ignore_permissions:
		return True
	scope = get_scope()
	if scope is None:
		return True
	dt = doc.doctype
	if dt == "Business":
		return doc.is_new() or str(doc.name) in scope
	if dt == "GSTIN":
		return str(doc.business_id or "") in scope
	if dt == "Notice":
		return notice_allowed(doc.get("business_id"), doc.get("gstin"), scope)
	if dt in ("Payment", "Review Queue Item", "Client Document", "Audit Log"):
		return str(doc.get("client") or "") in scope
	if dt == "GST User":
		return (doc.name or "").lower() == (scope_user() or "").lower()
	if dt == "Adaequare Settings":
		return str(doc.get("business") or doc.name or "") in scope
	return True


def has_permission(doc, ptype=None, user=None, debug=False):
	"""has_permission hook: deny records outside the scope, otherwise defer (None)."""
	if isinstance(doc, str):
		return None
	return False if not doc_in_scope(doc) else None


# ---------------------------------------------------------------------------
# List conditions (permission_query_conditions hooks; applied to get_list and
# the Resource API, also for Administrator)
# ---------------------------------------------------------------------------
def _in(column, values):
	if not values:
		return "1=0"
	return "{} in ({})".format(column, ", ".join(frappe.db.escape(str(v)) for v in values))


def _cond(builder):
	scope = get_scope()
	if scope is None:
		return ""
	return builder(scope)


def business_query(user=None, doctype=None):
	return _cond(lambda s: _in("`tabBusiness`.`name`", s))


def gstin_query(user=None, doctype=None):
	return _cond(lambda s: _in("`tabGSTIN`.`business_id`", s))


def notice_query(user=None, doctype=None):
	def build(s):
		parts = [_in("`tabNotice`.`business_id`", s)]
		g = scope_gstins(s)
		if g:
			parts.append(_in("`tabNotice`.`gstin`", g))
		return "(" + " or ".join(parts) + ")"
	return _cond(build)


def _client_query(table):
	return lambda user=None, doctype=None: _cond(lambda s: _in(f"`tab{table}`.`client`", s))


payment_query = _client_query("Payment")
review_queue_item_query = _client_query("Review Queue Item")
client_document_query = _client_query("Client Document")
audit_log_query = _client_query("Audit Log")


def gst_user_query(user=None, doctype=None):
	if get_scope() is None:
		return ""
	return "`tabGST User`.`name` = {}".format(frappe.db.escape(scope_user() or ""))


def gst_sync_log_query(user=None, doctype=None):
	return _cond(lambda s: _in("`tabGST Sync Log`.`gstin`", scope_gstins(s)))


def gst_otp_request_query(user=None, doctype=None):
	return _cond(lambda s: _in("`tabGST OTP Request`.`gstin`", scope_gstins(s)))


def adaequare_settings_query(user=None, doctype=None):
	# one record per Business, named by the Business ID
	return _cond(lambda s: _in("`tabAdaequare Settings`.`name`", s))
